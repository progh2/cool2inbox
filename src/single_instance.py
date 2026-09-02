"""중복 실행 방지 (FR-5.7).

트레이 앱이라 창이 없다. 두 번째 프로세스가 뜨면 쪽지를 두 번 저장하려 들 수 있으므로 반드시 막는다.

두 가지를 함께 쓴다.
1. 잠금 파일(`instance.json`, 설정 폴더) — pid 를 적어 두고 살아 있는지 확인한다
2. QLocalServer — 살아 있는 인스턴스에 "네가 떠 있다고 사용자에게 알려줘"를 전달하는 통로

잠금 파일만으로는 pid 재사용을 구별할 수 없고(다른 프로그램이 그 pid 를 물려받았을 수 있다),
소켓만으로는 비정상 종료 후 남은 껍데기를 정리할 수 없어 둘 다 필요하다.
**소켓 응답이 있어야만** 기존 인스턴스가 살아 있다고 인정한다.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from src import __version__
from src import config as cfg

log = logging.getLogger(__name__)

LOCK_NAME = "instance.json"
SERVER_NAME = "cool2inbox-single-instance"
MSG_SHOW = b"show\n"


def lock_path() -> Path:
    return cfg.config_dir() / LOCK_NAME


@dataclass
class Existing:
    pid: int
    version: str = "0"
    server: str = SERVER_NAME


# ---------------------------------------------------------------- 프로세스 확인

def pid_alive(pid: int) -> bool:
    """살아 있는 프로세스인가.

    Windows 의 `os.kill(pid, 0)` 은 시그널 0 도 강제 종료로 동작하므로 절대 쓰면 안 된다.
    """
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":  # pragma: no cover - Windows 전용
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:      # 다른 사용자 소유 = 살아는 있다
        return True
    return True


# ---------------------------------------------------------------- 잠금 파일

def read_lock() -> Existing | None:
    try:
        d = json.loads(lock_path().read_text(encoding="utf-8"))
        return Existing(pid=int(d["pid"]), version=str(d.get("version", "0")),
                        server=str(d.get("server", SERVER_NAME)))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def write_lock(version: str = __version__, server: str | None = None) -> None:
    try:
        lock_path().write_text(json.dumps(
            {"pid": os.getpid(), "version": version, "server": server or SERVER_NAME, "started": time.time()},
            ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        log.warning("실행 잠금 파일을 쓸 수 없습니다: %s", e)


def clear_lock() -> None:
    """내가 쓴 잠금만 지운다 (다른 인스턴스가 이어받았으면 건드리지 않는다)."""
    ex = read_lock()
    if ex is not None and ex.pid != os.getpid():
        return
    try:
        lock_path().unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- 로컬 소켓

def ping_show(server: str | None = None, wait_ms: int = 800) -> bool:
    """살아 있는 인스턴스에 '사용자에게 네 존재를 알려라'를 전달. 응답 가능 여부가 곧 생존 증명."""
    from PySide6.QtNetwork import QLocalSocket

    s = QLocalSocket()
    s.connectToServer(server or SERVER_NAME)
    if not s.waitForConnected(wait_ms):
        return False
    s.write(MSG_SHOW)
    s.flush()
    s.waitForBytesWritten(wait_ms)
    s.disconnectFromServer()
    return True


class InstanceServer:
    """살아 있는 인스턴스 쪽. 두 번째 실행이 붙으면 `on_show` 를 부른다."""

    def __init__(self, on_show=None, name: str | None = None):
        from PySide6.QtNetwork import QLocalServer

        name = name or SERVER_NAME
        self.name = name
        self._on_show = on_show
        self._conns: list = []
        self.server = QLocalServer()
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        QLocalServer.removeServer(name)      # 비정상 종료로 남은 소켓 정리
        self.ok = bool(self.server.listen(name))
        if self.ok:
            self.server.newConnection.connect(self._accept)
        else:
            log.warning("단일 인스턴스 서버를 열지 못했습니다: %s", self.server.errorString())

    def _accept(self) -> None:
        conn = self.server.nextPendingConnection()
        if conn is None:
            return
        self._conns.append(conn)
        conn.readyRead.connect(lambda c=conn: self._read(c))
        conn.disconnected.connect(lambda c=conn: c in self._conns and self._conns.remove(c))

    def _read(self, conn) -> None:
        if MSG_SHOW.strip() in bytes(conn.readAll().data()):
            log.info("이미 실행 중 — 두 번째 실행이 들어왔습니다.")
            if self._on_show:
                self._on_show()

    def close(self) -> None:
        for c in list(self._conns):
            c.close()
        self._conns.clear()
        self.server.close()
        clear_lock()


# ---------------------------------------------------------------- 공개 API

def acquire(on_show=None, name: str | None = None) -> InstanceServer | None:
    """실행권을 잡는다.

    이미 살아 있는 인스턴스가 있으면 그쪽을 깨우고 **None** 을 돌려준다 (호출자는 조용히 종료).
    아니면 잠금과 서버를 잡고 InstanceServer 를 돌려준다.
    """
    ex = read_lock()
    if ex is not None and ex.pid != os.getpid() and pid_alive(ex.pid):
        if ping_show(ex.server):
            log.info("이미 실행 중입니다 (pid %s). 이 프로세스는 종료합니다.", ex.pid)
            return None
        # pid 는 살아 있지만 우리 앱이 아니다 (pid 재사용) → 이어받는다
        log.info("잠금 파일의 pid %s 가 응답하지 않아 실행권을 이어받습니다.", ex.pid)
    server = InstanceServer(on_show=on_show, name=name)
    write_lock(server=server.name)
    return server
