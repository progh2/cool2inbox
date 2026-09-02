"""중복 방지 이력 (state.sqlite3).

같은 쪽지를 두 번 저장하지 않기 위한 유일한 진실의 원천 — 은 아니다.
진짜 원천은 **인박스 폴더 그 자체**다 (FR-4.3). 이 DB 를 잃어버려도 인박스의 md 머리말을 다시
읽어 이력을 복구할 수 있어야 한다. 그래서 md 에 `message_key` 와 `content_hash` 를 적어 둔다.

판정 순서 (FR-4.2):
  1) message_key — udb 안에서 고유
  2) content_hash — udb 가 재생성돼 키가 초기화된 경우 대비
"""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
FRONT_MATTER_SCAN_LINES = 60      # md 머리말은 이 안에서 끝난다고 본다


@dataclass(frozen=True)
class ImportedRow:
    message_key: int
    content_hash: str
    md_path: str
    imported_at: str
    attach_total: int
    attach_ok: int

    @property
    def attachments_pending(self) -> bool:
        """첨부 일부가 아직 복사되지 않았다 → 다음 폴링에서 재시도 대상 (FR-2.7)."""
        return self.attach_ok < self.attach_total


class StateDB:
    """with 문으로 쓰거나 close() 를 직접 부른다."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(str(self.path))
        self._con.row_factory = sqlite3.Row
        self._migrate()

    def __enter__(self) -> "StateDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if self._con is not None:
            self._con.close()
            self._con = None  # type: ignore[assignment]

    def _migrate(self) -> None:
        cur = self._con.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS imported (
            message_key  INTEGER PRIMARY KEY,
            content_hash TEXT NOT NULL,
            md_path      TEXT NOT NULL,
            imported_at  TEXT NOT NULL,
            attach_total INTEGER NOT NULL DEFAULT 0,
            attach_ok    INTEGER NOT NULL DEFAULT 0
        )""")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_hash ON imported(content_hash)")
        cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._con.commit()

    # ---- 조회

    def seen(self, message_key: int, content_hash: str = "") -> bool:
        """이미 처리한 쪽지인가. 키 1차, 해시 2차."""
        row = self._con.execute("SELECT 1 FROM imported WHERE message_key=?", (int(message_key),)).fetchone()
        if row:
            return True
        if content_hash:
            row = self._con.execute("SELECT 1 FROM imported WHERE content_hash=?", (content_hash,)).fetchone()
            return row is not None
        return False

    def get(self, message_key: int) -> ImportedRow | None:
        row = self._con.execute("SELECT * FROM imported WHERE message_key=?", (int(message_key),)).fetchone()
        return _row(row) if row else None

    def keys(self) -> set[int]:
        """처리한 MessageKey 전부. 백필 미리보기용 (FR-7.6)."""
        return {r[0] for r in self._con.execute("SELECT message_key FROM imported")}

    def max_key(self) -> int:
        return int(self._con.execute("SELECT COALESCE(MAX(message_key), 0) FROM imported").fetchone()[0])

    def pending_attachments(self) -> list[ImportedRow]:
        """첨부를 다 못 가져온 쪽지들 (FR-2.7 재시도 대상)."""
        rows = self._con.execute(
            "SELECT * FROM imported WHERE attach_ok < attach_total ORDER BY message_key").fetchall()
        return [_row(r) for r in rows]

    def stats(self) -> dict:
        """설정 창 '가져오기' 탭에 보여줄 요약 (FR-6.5)."""
        r = self._con.execute("""SELECT COUNT(*) AS n,
                                        COALESCE(SUM(attach_total), 0) AS at,
                                        COALESCE(SUM(attach_ok), 0) AS ao,
                                        MIN(imported_at) AS first,
                                        MAX(imported_at) AS last,
                                        COALESCE(MAX(message_key), 0) AS maxkey
                                 FROM imported""").fetchone()
        pending = self._con.execute("SELECT COUNT(*) FROM imported WHERE attach_ok < attach_total").fetchone()[0]
        return {"notes": r["n"], "attachments": r["at"], "attachments_ok": r["ao"],
                "attachments_pending_notes": pending, "first_imported_at": r["first"],
                "last_imported_at": r["last"], "max_message_key": r["maxkey"]}

    # ---- 기록

    def record(self, message_key: int, content_hash: str, md_path: str | Path,
               attach_total: int = 0, attach_ok: int = 0, imported_at: str = "") -> None:
        """저장이 **성공한 뒤에만** 부른다 (FR-4.4). 같은 키를 다시 기록하면 갱신된다."""
        self._con.execute(
            "INSERT OR REPLACE INTO imported "
            "(message_key, content_hash, md_path, imported_at, attach_total, attach_ok) "
            "VALUES (?,?,?,?,?,?)",
            (int(message_key), content_hash, str(md_path),
             imported_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             int(attach_total), int(attach_ok)))
        self._con.commit()

    def update_attachments(self, message_key: int, attach_ok: int) -> None:
        """첨부 재시도 결과 반영."""
        self._con.execute("UPDATE imported SET attach_ok=? WHERE message_key=?",
                          (int(attach_ok), int(message_key)))
        self._con.commit()

    def forget(self, message_key: int) -> None:
        """한 건만 이력에서 지운다 (다시 가져오게 만든다)."""
        self._con.execute("DELETE FROM imported WHERE message_key=?", (int(message_key),))
        self._con.commit()

    def clear(self) -> int:
        """이력 전체 초기화 (FR-4.5). 인박스 파일은 건드리지 않는다."""
        n = self._con.execute("SELECT COUNT(*) FROM imported").fetchone()[0]
        self._con.execute("DELETE FROM imported")
        self._con.commit()
        return int(n)

    # ---- 복구

    def rebuild_from_inbox(self, coolm_dir: str | Path) -> int:
        """인박스의 md 머리말을 읽어 이력을 되살린다 (FR-4.3).

        기존 행은 건드리지 않고 없는 것만 채운다. 반환값은 새로 채운 건수.
        """
        d = Path(coolm_dir)
        if not d.is_dir():
            return 0
        added = 0
        for md in sorted(d.glob("*.md")):
            meta = read_front_matter(md)
            key = meta.get("message_key")
            if key is None:
                continue
            cur = self._con.execute(
                "INSERT OR IGNORE INTO imported "
                "(message_key, content_hash, md_path, imported_at, attach_total, attach_ok) "
                "VALUES (?,?,?,?,?,?)",
                (key, meta.get("content_hash", ""), str(md),
                 meta.get("imported_at", "") or _mtime(md), 0, 0))
            added += cur.rowcount
        self._con.commit()
        if added:
            log.info("인박스에서 이력 %d건을 복구했습니다: %s", added, d)
        return added


# ---------------------------------------------------------------- 도구

def _row(r: sqlite3.Row) -> ImportedRow:
    return ImportedRow(message_key=r["message_key"], content_hash=r["content_hash"],
                       md_path=r["md_path"], imported_at=r["imported_at"],
                       attach_total=r["attach_total"], attach_ok=r["attach_ok"])


def _mtime(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def read_front_matter(md_path: str | Path) -> dict:
    """md 머리말에서 우리가 쓰는 값만 뽑는다.

    YAML 파서를 쓰지 않는다 — 필요한 건 `message_key`(int)와 `content_hash`, `imported_at`
    세 개뿐이고, 의존성을 늘리지 않는 편이 낫다. 머리말이 없으면 빈 dict.
    """
    out: dict = {}
    try:
        with open(md_path, encoding="utf-8") as f:
            first = f.readline()
            if first.strip() != "---":
                return out
            for _ in range(FRONT_MATTER_SCAN_LINES):
                line = f.readline()
                if not line or line.strip() == "---":
                    break
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k == "message_key":
                    try:
                        out["message_key"] = int(v)
                    except ValueError:
                        pass
                elif k in ("content_hash", "imported_at"):
                    out[k] = v
    except OSError as e:
        log.warning("md 머리말을 읽지 못했습니다 (%s): %s", md_path, e)
    return out
