"""OS 별 잡일. 얇게 유지한다 — Windows 전용 코드가 여기 말고 다른 데 퍼지지 않게."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def open_folder(path: str | Path) -> bool:
    """탐색기/파인더로 폴더를 연다. 성공 여부를 돌려준다 (실패해도 예외를 던지지 않는다)."""
    p = Path(path)
    if not p.exists():
        log.warning("열 폴더가 없습니다: %s", p)
        return False
    try:
        if sys.platform == "win32":          # pragma: no cover - Windows 전용
            os.startfile(str(p))             # type: ignore[attr-defined]
        elif sys.platform == "darwin":       # pragma: no cover - macOS 전용
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError as e:
        log.warning("폴더를 열지 못했습니다 (%s): %s", p, e)
        return False
