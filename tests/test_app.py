"""앱 컨트롤러 (#5)."""
from __future__ import annotations

import pytest

from src import osutil
from src.app import AppController
from src.config import Config
from src.ui.tray import AppState


@pytest.fixture
def opened(monkeypatch):
    """열린 폴더를 기록한다 (실제로 탐색기를 띄우지 않는다)."""
    calls = []
    monkeypatch.setattr(osutil, "open_folder", lambda p: (calls.append(str(p)), True)[1])
    return calls


@pytest.fixture
def ctl(qapp, tmp_path):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "memo")
    c.inbox.root_dir = str(tmp_path / "inbox")
    (tmp_path / "memo").mkdir()
    (tmp_path / "inbox").mkdir()
    controller = AppController(qapp, config=c)
    yield controller
    controller.tray.hide()


def test_설정이_없으면_설정필요_상태(qapp):
    c = AppController(qapp, config=Config())
    assert c.tray.state is AppState.SETUP
    c.tray.hide()


def test_설정이_있으면_대기_상태(ctl):
    assert ctl.tray.state is AppState.IDLE


def test_설정에_저장된_일시정지를_이어받는다(qapp, tmp_path):
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(tmp_path), str(tmp_path)
    c.schedule.paused = True
    ctl = AppController(qapp, config=c)
    assert ctl.tray.state is AppState.PAUSED
    assert ctl.tray.act_pause.text() == "재개"
    ctl.tray.hide()


def test_일시정지는_설정에_저장된다(ctl):
    ctl.set_paused(True)
    assert Config.load().schedule.paused is True
    ctl.set_paused(False)
    assert Config.load().schedule.paused is False


def test_인박스_열기는_폴더를_만들고_연다(ctl, opened):
    ctl.open_inbox()
    d = ctl.config.inbox.coolm_dir()
    assert d.is_dir()
    assert opened == [str(d)]


def test_설정_전에_인박스를_열면_설정으로_안내한다(qapp, opened):
    ctl = AppController(qapp, config=Config())
    ctl.open_inbox()
    assert opened == []               # 폴더를 열지 않는다
    ctl.tray.hide()


def test_로그_보기는_로그_폴더를_연다(ctl, opened, isolated_dirs):
    ctl.open_logs()
    assert opened == [str(isolated_dirs)]


def test_트레이_시그널이_컨트롤러에_연결돼_있다(ctl, opened):
    ctl.tray.open_inbox_requested.emit()
    assert opened            # 컨트롤러가 실제로 반응했다


def test_종료하면_잠금_서버를_닫는다(ctl):
    closed = []

    class FakeServer:
        def close(self):
            closed.append(1)

    ctl.instance_server = FakeServer()
    ctl.quit()
    assert closed == [1]
