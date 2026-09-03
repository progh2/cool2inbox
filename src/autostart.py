"""운영체제 시작 시 자동 실행 등록/해제 (FR-5.8).

- Windows: HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run\\cool2inbox
- Linux  : ~/.config/autostart/cool2inbox.desktop (XDG) — 개발 환경 편의
- macOS  : ~/Library/LaunchAgents/kr.cool2inbox.app.plist — 개발 환경 편의

frozen(배포 빌드)이면 실행 파일 경로를, 소스 실행이면 `python main.py` 를 등록한다.
테스트는 환경변수 `COOL2INBOX_HOME` 으로 홈 디렉터리를 갈아끼운다.
"""
from __future__ import annotations

import os
import platform
import plistlib
import sys
from pathlib import Path

APP_ID = "kr.cool2inbox.app"
APP_KEY = "cool2inbox"
ENV_HOME = "COOL2INBOX_HOME"
_WIN_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


class AutostartError(Exception):
    """사용자에게 보여줄 실패 사유."""


def _home() -> Path:
    return Path(os.environ.get(ENV_HOME) or Path.home())


def launch_command() -> list[str]:
    """등록할 실행 명령. frozen 이면 실행 파일 하나, 아니면 python + main.py."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        if platform.system() == "Darwin":
            for p in exe.parents:
                if p.suffix == ".app":
                    return ["/usr/bin/open", "-a", str(p)]
        return [str(exe)]
    root = Path(__file__).resolve().parent.parent
    exe = sys.executable
    if platform.system() == "Windows":          # pragma: no cover - Windows 전용
        # python.exe 는 콘솔 창을 띄운다. 같은 폴더의 pythonw.exe 가 있으면 그걸 쓴다.
        w = Path(exe).with_name("pythonw.exe")
        if w.exists():
            exe = str(w)
    return [exe, str(root / "main.py")]


def _quoted(cmd: list[str]) -> str:
    return " ".join(f'"{c}"' if " " in c else c for c in cmd)


def _plist_path() -> Path:
    return _home() / "Library" / "LaunchAgents" / f"{APP_ID}.plist"


def _desktop_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config")
    return base / "autostart" / f"{APP_KEY}.desktop"


# ---------------------------------------------------------------- 공개 API

def is_enabled() -> bool:
    s = platform.system()
    try:
        if s == "Windows":  # pragma: no cover - Windows 전용
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY) as k:
                try:
                    winreg.QueryValueEx(k, APP_KEY)
                    return True
                except FileNotFoundError:
                    return False
        if s == "Darwin":
            return _plist_path().exists()
        return _desktop_path().exists()
    except OSError:
        return False


def enable() -> None:
    s = platform.system()
    cmd = launch_command()
    try:
        if s == "Windows":  # pragma: no cover - Windows 전용
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                winreg.SetValueEx(k, APP_KEY, 0, winreg.REG_SZ, _quoted(cmd))
        elif s == "Darwin":
            p = _plist_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "wb") as f:
                plistlib.dump({"Label": APP_ID, "ProgramArguments": cmd,
                               "RunAtLoad": True, "ProcessType": "Interactive"}, f)
        else:
            p = _desktop_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(
                "[Desktop Entry]\nType=Application\nName=cool2inbox\n"
                "Comment=쿨메신저 쪽지를 인박스로 배달합니다\n"
                f"Exec={_quoted(cmd)}\nTerminal=false\nX-GNOME-Autostart-enabled=true\n",
                encoding="utf-8")
    except OSError as e:
        raise AutostartError(f"자동 실행 등록에 실패했습니다: {e}") from e


def disable() -> None:
    s = platform.system()
    try:
        if s == "Windows":  # pragma: no cover - Windows 전용
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _WIN_RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
                try:
                    winreg.DeleteValue(k, APP_KEY)
                except FileNotFoundError:
                    pass
        elif s == "Darwin":
            _plist_path().unlink(missing_ok=True)
        else:
            _desktop_path().unlink(missing_ok=True)
    except OSError as e:
        raise AutostartError(f"자동 실행 해제에 실패했습니다: {e}") from e


def set_enabled(on: bool) -> None:
    (enable if on else disable)()
