"""쿨메신저 udb 스키마 덤프 (#6) — 다른 조직·다른 버전 대응용 진단 도구.

우리 환경의 스키마는 이미 확정돼 있다 (PRD 4.1). 이 도구는 **다른 사람이 썼을 때
동작하지 않을 경우** 원인을 알아내기 위한 것이다.

    python tools/dump_coolm_schema.py                 # 자동 탐지
    python tools/dump_coolm_schema.py "C:\\경로\\Memo"   # 폴더 직접 지정
    python tools/dump_coolm_schema.py --out dump.txt

**개인정보를 출력하지 않는다.** 값은 길이·형태(숫자/한글/영문/구분자)만 보여주고 내용은 가린다.
그래도 결과를 공개 저장소에 붙이기 전에 한 번 읽어 보기를 권한다.
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.sources.coolm import has_messages, memo_dir_candidates  # noqa: E402

INTERESTING = re.compile(r"recv|send|to|member|group|file|attach|ref|cc|msg|memo", re.I)
RECV_FILE_CANDIDATES = (
    ("USERPROFILE", ("Documents", "CoolMessenger Files", "Received Files")),
    ("USERPROFILE", ("Documents", "CoolMessenger", "Received Files")),
    ("USERPROFILE", ("Documents", "CoolMessenger Files")),
    ("USERPROFILE", ("Downloads",)),
)


def shape(v) -> str:
    """값의 형태만. 실제 내용은 남기지 않는다."""
    if v is None:
        return "NULL"
    if isinstance(v, (int, float)):
        return f"수 {v}" if abs(v) < 1000 else f"수({len(str(v))}자리)"
    if isinstance(v, bytes):
        return f"BLOB {len(v)}바이트 앞 8: {v[:8].hex(' ')}"
    s = str(v)
    if not s:
        return "빈 문자열"
    masked = re.sub(r"[가-힣]", "가", re.sub(r"[0-9]", "9", re.sub(r"[A-Za-z]", "a", s)))
    return f"{len(s)}자 [{masked[:60]}{'…' if len(masked) > 60 else ''}]"


def dump_db(path: Path, out) -> None:
    p = lambda *a: print(*a, file=out)
    p(f"\n{'=' * 72}\n파일: {path.name}  ({path.stat().st_size:,} bytes)\n{'=' * 72}")
    con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)   # 부작용 없이 연다
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        p(f"테이블 {len(tables)}개: {', '.join(tables)}")
        for t in tables:
            try:
                n = con.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            except sqlite3.Error as e:
                p(f"\n--- {t}: 읽기 실패 {e}")
                continue
            cols = con.execute(f"PRAGMA table_info([{t}])").fetchall()
            mark = " ★" if INTERESTING.search(t) else ""
            p(f"\n--- {t} ({n:,}행, {len(cols)}컬럼){mark}")
            for c in cols:
                p(f"      {c[1]:<24} {c[2] or '?':<16}{' PK' if c[5] else ''}")
            if n == 0:
                continue
            row = con.execute(f"SELECT * FROM [{t}] LIMIT 1").fetchone()
            names = [c[1] for c in cols]
            p("    [값의 형태 — 내용은 가림]")
            for name, v in zip(names, row):
                p(f"      {name:<24} {shape(v)}")
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="쿨메신저 udb 스키마 덤프 (개인정보 제외)")
    ap.add_argument("memo_dir", nargs="?", help="쪽지 폴더 (생략하면 자동 탐지)")
    ap.add_argument("--out", help="결과를 파일로 저장")
    args = ap.parse_args()

    out = open(args.out, "w", encoding="utf-8") if args.out else sys.stdout
    try:
        p = lambda *a: print(*a, file=out)
        p("쿨메신저 udb 스키마 덤프 — 값의 내용은 포함하지 않습니다")

        dirs = [Path(args.memo_dir)] if args.memo_dir else []
        if not dirs:
            p("\n[쪽지 폴더 후보 탐색]")
            for d in memo_dir_candidates():
                udbs = sorted(d.glob("*.udb")) if d.is_dir() else []
                if not udbs:
                    continue
                p(f"  {d}  — udb {len(udbs)}개")
                for u in udbs:
                    p(f"      {u.name}: 쪽지 {has_messages(u):,}행")
                dirs.append(d)
            if not dirs:
                p("  후보 경로에서 udb 를 찾지 못했습니다. 폴더를 직접 지정해 주세요.")

        p("\n[수신 파일 폴더 후보]")
        for var, sub in RECV_FILE_CANDIDATES:
            base = os.environ.get(var, "")
            if not base:
                continue
            d = Path(base).joinpath(*sub)
            if d.is_dir():
                files = [x for x in d.iterdir() if x.is_file()]
                p(f"  {d}  — 파일 {len(files)}개")

        for d in dirs:
            if not d.is_dir():
                p(f"\n폴더가 없습니다: {d}")
                continue
            for u in sorted(d.glob("*.udb")):
                dump_db(u, out)
        p("\n덤프 끝. 공개된 곳에 붙이기 전에 한 번 훑어봐 주세요.")
    finally:
        if args.out:
            out.close()
            print(f"저장했습니다: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
