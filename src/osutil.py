"""OS 별 잡일. 얇게 유지한다 — Windows 전용 코드가 여기 말고 다른 데 퍼지지 않게."""
from __future__ import annotations

import json
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


# ---------------------------------------------------------------- 드롭박스 찾기

DROPBOX_INFO = (
    ("LOCALAPPDATA", ("Dropbox", "info.json")),      # Windows
    ("APPDATA", ("Dropbox", "info.json")),
)
# 인박스로 쓰일 법한 폴더 이름 (사람마다 다르다)
INBOX_NAMES = ("inbox", "인박스", "00_inbox", "0_inbox", "_inbox")


def dropbox_root() -> str:
    """드롭박스 동기화 폴더. 못 찾으면 빈 문자열.

    드롭박스는 로컬 폴더 위치를 info.json 에 적어 둔다. 계정이 여러 개면 개인 계정을 먼저 본다.
    """
    candidates = [Path(os.environ[v]).joinpath(*sub)
                  for v, sub in DROPBOX_INFO if os.environ.get(v)]
    candidates.append(Path.home() / ".dropbox" / "info.json")     # macOS/Linux
    for info in candidates:
        try:
            data = json.loads(info.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for account in ("personal", "business"):
            path = (data.get(account) or {}).get("path")
            if path and Path(path).is_dir():
                return str(path)
    fallback = Path.home() / "Dropbox"
    return str(fallback) if fallback.is_dir() else ""


def suggest_inbox_dir() -> str:
    """인박스로 제안할 폴더.

    드롭박스 안에 이미 인박스처럼 쓰는 폴더가 있으면 그것을 고른다 (사람마다 이름이 다르고
    한 단계 아래에 두는 경우도 많다). 없으면 `<Dropbox>/Inbox` 를 제안한다.
    """
    root = dropbox_root()
    if not root:
        return ""
    base = Path(root)
    for depth in (base.iterdir(), *(d.iterdir() for d in _dirs(base))):
        try:
            for p in depth:
                if p.is_dir() and p.name.lower() in INBOX_NAMES:
                    return str(p)
        except OSError:
            continue
    return str(base / "Inbox")


def _dirs(base: Path) -> list[Path]:
    try:
        return [p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return []
