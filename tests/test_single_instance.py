"""중복 실행 방지 (#4).

두 번째 프로세스가 뜨면 쪽지를 두 번 저장할 수 있으므로 반드시 막아야 한다.
"""
from __future__ import annotations

import json
import os

import pytest

from src import single_instance as si


@pytest.fixture(autouse=True)
def _unique_server(request, monkeypatch):
    """테스트마다 다른 소켓 이름을 쓴다 (병렬/잔여 소켓 간섭 방지)."""
    name = f"cool2inbox-test-{os.getpid()}-{abs(hash(request.node.nodeid)) % 100000}"
    monkeypatch.setattr(si, "SERVER_NAME", name)
    return name


# ---------------------------------------------------------------- 잠금 파일

def test_잠금은_설정_디렉터리에(isolated_dirs):
    assert si.lock_path() == isolated_dirs / "instance.json"


def test_쓰고_읽기():
    si.write_lock()
    ex = si.read_lock()
    assert ex.pid == os.getpid()
    assert ex.version


def test_없으면_None():
    assert si.read_lock() is None


def test_깨진_잠금은_None():
    si.lock_path().write_text("{ 깨짐", encoding="utf-8")
    assert si.read_lock() is None


def test_pid가_없는_잠금은_None():
    si.lock_path().write_text(json.dumps({"version": "1"}), encoding="utf-8")
    assert si.read_lock() is None


def test_clear는_내_잠금만_지운다():
    si.write_lock()
    si.clear_lock()
    assert si.read_lock() is None


def test_clear는_남의_잠금을_건드리지_않는다():
    si.lock_path().write_text(json.dumps({"pid": 999999, "version": "9"}), encoding="utf-8")
    si.clear_lock()
    assert si.read_lock().pid == 999999


# ---------------------------------------------------------------- pid 확인

def test_내_pid는_살아있다():
    assert si.pid_alive(os.getpid()) is True


def test_말도_안_되는_pid():
    assert si.pid_alive(0) is False
    assert si.pid_alive(-1) is False


def test_죽은_pid():
    import subprocess

    p = subprocess.Popen(["true"])
    p.wait()
    # 좀비가 수거된 뒤에는 죽은 것으로 보여야 한다
    assert si.pid_alive(p.pid) is False


# ---------------------------------------------------------------- acquire 판정

def test_잠금이_없으면_실행권을_잡는다(qapp):
    server = si.acquire()
    assert server is not None
    assert si.read_lock().pid == os.getpid()
    server.close()


def test_살아있는_인스턴스가_응답하면_None(qapp, monkeypatch):
    si.lock_path().write_text(json.dumps(
        {"pid": 424242, "version": "0.1.0", "server": si.SERVER_NAME}), encoding="utf-8")
    monkeypatch.setattr(si, "pid_alive", lambda pid: True)
    monkeypatch.setattr(si, "ping_show", lambda server=None, wait_ms=800: True)
    assert si.acquire() is None


def test_pid는_살아있지만_응답이_없으면_이어받는다(qapp, monkeypatch):
    """다른 프로그램이 그 pid 를 물려받은 경우 — 우리 앱이 아니므로 실행권을 가져온다."""
    si.lock_path().write_text(json.dumps(
        {"pid": 424242, "version": "0.1.0", "server": si.SERVER_NAME}), encoding="utf-8")
    monkeypatch.setattr(si, "pid_alive", lambda pid: True)
    monkeypatch.setattr(si, "ping_show", lambda server=None, wait_ms=800: False)
    server = si.acquire()
    assert server is not None
    assert si.read_lock().pid == os.getpid()
    server.close()


def test_죽은_인스턴스의_잠금은_이어받는다(qapp):
    si.lock_path().write_text(json.dumps(
        {"pid": 999999, "version": "0.1.0", "server": si.SERVER_NAME}), encoding="utf-8")
    server = si.acquire()
    assert server is not None
    assert si.read_lock().pid == os.getpid()
    server.close()


# ---------------------------------------------------------------- 소켓 왕복

def test_두_번째_실행이_기존_인스턴스를_깨운다(qapp):
    called = []
    server = si.acquire(on_show=lambda: called.append(1))
    assert server is not None and server.ok

    assert si.ping_show(si.SERVER_NAME) is True
    for _ in range(50):
        qapp.processEvents()
        if called:
            break
    assert called == [1]
    server.close()


def test_서버가_없으면_ping은_실패한다(qapp):
    assert si.ping_show("cool2inbox-존재하지-않는-서버", wait_ms=200) is False


def test_close하면_잠금이_사라진다(qapp):
    server = si.acquire()
    server.close()
    assert si.read_lock() is None
