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
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3
FRONT_MATTER_SCAN_LINES = 60      # md 머리말은 이 안에서 끝난다고 본다


@dataclass(frozen=True)
class ImportedRow:
    message_key: int
    content_hash: str
    md_path: str
    imported_at: str
    attach_total: int
    attach_ok: int
    md_sha: str = ""             # 우리가 쓴 md 본문의 sha256 — 사용자가 손댔는지 판별용
    kind: str = "recv"           # recv | send

    @property
    def attachments_pending(self) -> bool:
        """첨부 일부가 아직 복사되지 않았다 → 다음 폴링에서 재시도 대상 (FR-2.7)."""
        return self.attach_ok < self.attach_total


class StateDB:
    """with 문으로 쓰거나 close() 를 직접 부른다.

    **스레드를 넘나든다.** 폴링 워커(별도 스레드)가 쓰고, 설정 창(메인 스레드)이 통계를 읽는다.
    sqlite3 연결은 기본적으로 만든 스레드에서만 쓸 수 있으므로 `check_same_thread=False` 로 열고
    모든 접근을 락으로 감싼다. 접근 빈도가 낮아(수 분에 한 번) 락 경합은 문제가 되지 않는다.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._con = sqlite3.connect(str(self.path), check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._migrate()

    def __enter__(self) -> "StateDB":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._con is not None:
                self._con.close()
                self._con = None  # type: ignore[assignment]

    def _migrate(self) -> None:
        with self._lock:
            cur = self._con.cursor()
            cur.execute("""CREATE TABLE IF NOT EXISTS imported (
                kind         TEXT NOT NULL DEFAULT 'recv',
                message_key  INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                md_path      TEXT NOT NULL,
                imported_at  TEXT NOT NULL,
                attach_total INTEGER NOT NULL DEFAULT 0,
                attach_ok    INTEGER NOT NULL DEFAULT 0,
                md_sha       TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (kind, message_key)
            )""")
            cols = {r[1] for r in cur.execute("PRAGMA table_info(imported)")}
            if cols and "md_sha" not in cols:            # v1 → v2
                cur.execute("ALTER TABLE imported ADD COLUMN md_sha TEXT NOT NULL DEFAULT ''")
                cols.add("md_sha")
            if cols and "kind" not in cols:              # v2 → v3: PK 를 (kind, key) 로 바꾼다
                cur.execute("ALTER TABLE imported RENAME TO imported_old")
                cur.execute("""CREATE TABLE imported (
                    kind TEXT NOT NULL DEFAULT 'recv', message_key INTEGER NOT NULL,
                    content_hash TEXT NOT NULL, md_path TEXT NOT NULL, imported_at TEXT NOT NULL,
                    attach_total INTEGER NOT NULL DEFAULT 0, attach_ok INTEGER NOT NULL DEFAULT 0,
                    md_sha TEXT NOT NULL DEFAULT '', PRIMARY KEY (kind, message_key))""")
                cur.execute("""INSERT INTO imported
                    (kind, message_key, content_hash, md_path, imported_at, attach_total, attach_ok, md_sha)
                    SELECT 'recv', message_key, content_hash, md_path, imported_at, attach_total, attach_ok, md_sha
                    FROM imported_old""")
                cur.execute("DROP TABLE imported_old")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_hash ON imported(content_hash)")
            cur.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            self._con.commit()

    # ---- 조회

    def seen(self, message_key: int, content_hash: str = "", kind: str = "recv") -> bool:
        """이미 처리한 쪽지인가. (kind, 키) 1차, 해시 2차."""
        with self._lock:
            row = self._con.execute("SELECT 1 FROM imported WHERE kind=? AND message_key=?",
                                    (kind, int(message_key))).fetchone()
            if row:
                return True
            if content_hash:
                row = self._con.execute("SELECT 1 FROM imported WHERE content_hash=?",
                                        (content_hash,)).fetchone()
                return row is not None
            return False

    def get(self, message_key: int, kind: str = "recv") -> ImportedRow | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM imported WHERE kind=? AND message_key=?",
                                    (kind, int(message_key))).fetchone()
            return _row(row) if row else None

    def keys(self, kind: str = "recv") -> set[int]:
        """처리한 MessageKey 전부. 백필 미리보기용 (FR-7.6)."""
        with self._lock:
            return {r[0] for r in self._con.execute(
                "SELECT message_key FROM imported WHERE kind=?", (kind,))}

    def max_key(self, kind: str = "recv") -> int:
        with self._lock:
            return int(self._con.execute(
                "SELECT COALESCE(MAX(message_key), 0) FROM imported WHERE kind=?", (kind,)).fetchone()[0])

    def pending_attachments(self) -> list[ImportedRow]:
        """첨부를 다 못 가져온 쪽지들 (FR-2.7 재시도 대상)."""
        with self._lock:
            rows = self._con.execute(
                "SELECT * FROM imported WHERE attach_ok < attach_total ORDER BY kind, message_key").fetchall()
            return [_row(r) for r in rows]

    def stats(self) -> dict:
        """설정 창 '가져오기' 탭에 보여줄 요약 (FR-6.5)."""
        with self._lock:
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
               attach_total: int = 0, attach_ok: int = 0, imported_at: str = "",
               md_sha: str = "", kind: str = "recv") -> None:
        """저장이 **성공한 뒤에만** 부른다 (FR-4.4). 같은 (kind, 키)를 다시 기록하면 갱신된다."""
        with self._lock:
            self._con.execute(
                "INSERT OR REPLACE INTO imported "
                "(kind, message_key, content_hash, md_path, imported_at, attach_total, attach_ok, md_sha) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (kind, int(message_key), content_hash, str(md_path),
                 imported_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                 int(attach_total), int(attach_ok), md_sha))
            self._con.commit()

    def update_attachments(self, message_key: int, attach_ok: int, md_sha: str = "",
                           kind: str = "recv") -> None:
        """첨부 재시도 결과 반영. md 를 다시 썼으면 새 지문도 함께 남긴다."""
        with self._lock:
            if md_sha:
                self._con.execute("UPDATE imported SET attach_ok=?, md_sha=? WHERE kind=? AND message_key=?",
                                  (int(attach_ok), md_sha, kind, int(message_key)))
            else:
                self._con.execute("UPDATE imported SET attach_ok=? WHERE kind=? AND message_key=?",
                                  (int(attach_ok), kind, int(message_key)))
            self._con.commit()

    def forget(self, message_key: int, kind: str = "recv") -> None:
        """한 건만 이력에서 지운다 (다시 가져오게 만든다)."""
        with self._lock:
            self._con.execute("DELETE FROM imported WHERE kind=? AND message_key=?",
                              (kind, int(message_key)))
            self._con.commit()

    def clear(self) -> int:
        """이력 전체 초기화 (FR-4.5). 인박스 파일은 건드리지 않는다."""
        with self._lock:
            n = self._con.execute("SELECT COUNT(*) FROM imported").fetchone()[0]
            self._con.execute("DELETE FROM imported")
            self._con.commit()
            return int(n)

    # ---- 복구

    def rebuild_from_inbox(self, coolm_dir: str | Path, kind: str = "recv",
                           recursive: bool = False) -> int:
        """한 폴더의 md 머리말을 읽어 이력을 되살린다 (FR-4.3). 기존 행은 건드리지 않는다.

        recursive=False 면 직속 md 만 본다(받은쪽지 폴더가 보낸쪽지 하위 폴더를 삼키지 않게).
        recursive=True 면 하위까지 훑고 각 md 의 direction 머리말로 kind 를 정한다(아카이브용).
        """
        d = Path(coolm_dir)
        if not d.is_dir():
            return 0
        files = sorted(d.rglob("*.md") if recursive else d.glob("*.md"))
        with self._lock:
            added = 0
            for md in files:
                meta = read_front_matter(md)
                key = meta.get("message_key")
                if key is None:
                    continue
                row_kind = kind
                if recursive:                    # 아카이브: 파일이 스스로 방향을 말한다
                    row_kind = "send" if meta.get("direction") == "sent" else "recv"
                cur = self._con.execute(
                    "INSERT OR IGNORE INTO imported "
                    "(kind, message_key, content_hash, md_path, imported_at, attach_total, attach_ok) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (row_kind, key, meta.get("content_hash", ""), str(md),
                     meta.get("imported_at", "") or _mtime(md), 0, 0))
                added += cur.rowcount
            self._con.commit()
            if added:
                log.info("이력 %d건을 복구했습니다: %s", added, d)
            return added

    def rebuild_from_archives(self, archive_dirs) -> int:
        """아카이브 폴더들을 재귀로 훑어 이력을 채운다. 반환: 새로 채운 건수 (FR-4.6).

        아카이브의 쪽지는 '이미 처리됨' 으로만 기록한다(첨부 미완료로 남기지 않는다).
        """
        total = 0
        for d in archive_dirs or []:
            if str(d).strip():
                total += self.rebuild_from_inbox(d, recursive=True)
        return total


# ---------------------------------------------------------------- 도구

def _row(r: sqlite3.Row) -> ImportedRow:
    keys = r.keys()
    return ImportedRow(message_key=r["message_key"], content_hash=r["content_hash"],
                       md_path=r["md_path"], imported_at=r["imported_at"],
                       attach_total=r["attach_total"], attach_ok=r["attach_ok"],
                       md_sha=r["md_sha"] if "md_sha" in keys else "",
                       kind=r["kind"] if "kind" in keys else "recv")


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
                elif k in ("content_hash", "imported_at", "direction"):
                    out[k] = v
    except OSError as e:
        log.warning("md 머리말을 읽지 못했습니다 (%s): %s", md_path, e)
    return out
