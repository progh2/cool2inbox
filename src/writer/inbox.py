"""인박스 쓰기 (#12, FR-3.1·3.7).

드롭박스가 지켜보는 폴더에 쓴다. 반쯤 쓰인 파일이 동기화되면 다른 기기에 깨진 파일이
올라가므로 **모든 쓰기는 원자적으로** 한다 — 같은 폴더의 임시 파일에 쓴 뒤 `os.replace`.
(다른 파일시스템으로는 rename 이 원자적이지 않으므로 반드시 같은 폴더에 임시 파일을 만든다.)
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

TMP_SUFFIX = ".tmp"
PART_SUFFIX = ".part"


class InboxError(Exception):
    """사용자에게 그대로 보여줄 쓰기 오류."""


def _friendly(e: OSError, path: Path) -> InboxError:
    """OSError 를 사람이 읽을 한국어로 (FR-9.3)."""
    import errno

    if e.errno == errno.EACCES or e.errno == errno.EPERM:
        return InboxError(f"파일을 쓸 권한이 없습니다: {path}")
    if e.errno == errno.ENOSPC:
        return InboxError("디스크 공간이 부족합니다.")
    if e.errno == errno.ENAMETOOLONG:
        return InboxError(f"경로가 너무 깁니다: {path}")
    if e.errno == errno.EROFS:
        return InboxError(f"읽기 전용 위치입니다: {path}")
    return InboxError(f"파일을 쓰지 못했습니다 ({path}): {e}")


class InboxWriter:
    """인박스 폴더에 md 와 첨부를 쓴다. 경로 계산은 InboxSettings 가 한다."""

    def __init__(self, settings):
        self.settings = settings

    # ---- 경로

    @property
    def coolm_dir(self) -> Path:
        return self.settings.coolm_dir()

    @property
    def attach_dir(self) -> Path:
        return self.settings.attach_dir()

    def ensure_dirs(self, attachments: bool = False) -> None:
        """필요한 폴더를 만든다 (FR-3.1)."""
        try:
            self.coolm_dir.mkdir(parents=True, exist_ok=True)
            if attachments:
                self.attach_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise _friendly(e, self.coolm_dir) from e

    # ---- 쓰기

    def write_note(self, filename: str, text: str) -> Path:
        """md 를 원자적으로 쓴다. 이미 있으면 덮어쓴다 (중복 판정은 Importer 가 먼저 한다)."""
        self.ensure_dirs()
        target = self.coolm_dir / filename
        tmp = target.with_name(target.name + TMP_SUFFIX)
        try:
            tmp.write_text(text, encoding="utf-8", newline="\n")
            os.replace(tmp, target)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise _friendly(e, target) from e
        return target

    def copy_attachment(self, src: str | Path, dest_dir: str | Path, filename: str) -> Path:
        """첨부를 원자적으로 복사한다. **원본은 건드리지 않는다.**"""
        src, dest_dir = Path(src), Path(dest_dir)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise _friendly(e, dest_dir) from e
        target = dest_dir / filename
        tmp = target.with_name(target.name + PART_SUFFIX)
        try:
            with open(src, "rb") as fin, open(tmp, "wb") as fout:
                shutil.copyfileobj(fin, fout, 1024 * 1024)
            os.replace(tmp, target)
        except OSError as e:
            tmp.unlink(missing_ok=True)
            raise _friendly(e, target) from e
        return target

    def cleanup_temp(self) -> int:
        """중간에 죽어서 남은 임시 파일을 치운다. 반환값은 지운 개수."""
        n = 0
        for d in (self.coolm_dir, self.attach_dir):
            if not d.is_dir():
                continue
            for p in list(d.rglob(f"*{TMP_SUFFIX}")) + list(d.rglob(f"*{PART_SUFFIX}")):
                try:
                    p.unlink()
                    n += 1
                except OSError:
                    pass
        return n
