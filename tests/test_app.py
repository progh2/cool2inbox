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


def test_로그_보기는_로그_창을_연다(ctl, opened, isolated_dirs):
    """창 안의 [폴더 열기] 를 눌러야 탐색기가 뜬다 — 바로 폴더를 열지 않는다."""
    ctl.open_logs()
    assert ctl._logs is not None
    assert opened == []
    ctl._logs.btn_folder.click()
    assert opened == [str(isolated_dirs)]
    ctl._logs.close()


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


# ---------------------------------------------------------------- 폴링 연동 (#14)

def test_지금_확인은_워처를_부른다(ctl, monkeypatch):
    called = []
    monkeypatch.setattr(ctl.watcher, "poll_now", lambda: called.append(1))
    ctl.check_now()
    assert called == [1]


def test_설정_전에_지금_확인하면_설정으로_안내한다(qapp, monkeypatch):
    from src.config import Config
    ctl = AppController(qapp, config=Config())
    called = []
    monkeypatch.setattr(ctl.watcher, "poll_now", lambda: called.append(1))
    ctl.check_now()
    assert called == []
    ctl.tray.hide()


def test_일시정지하면_워처도_멈춘다(ctl):
    ctl.set_paused(True)
    assert not ctl.watcher.active
    ctl.set_paused(False)
    assert ctl.watcher.active


def test_폴링_시작하면_배달중_아이콘(ctl):
    ctl.on_poll_started()
    assert ctl.tray.state is AppState.WORKING


def test_일시정지_중에는_배달중으로_바뀌지_않는다(ctl):
    ctl.set_paused(True)
    ctl.on_poll_started()
    assert ctl.tray.state is AppState.PAUSED


def test_배달_결과를_알린다(ctl, monkeypatch):
    from src.writer.importer import ImportResult, Summary, SAVED

    notices = []
    monkeypatch.setattr(ctl.tray, "notify", lambda t, m, error=False: notices.append((m, error)))
    s = Summary([ImportResult(1, SAVED), ImportResult(2, SAVED)])
    ctl.on_poll_finished(s)
    assert notices == [("쪽지 2건을 인박스로 배달했어요.", False)]
    assert ctl.tray.state is AppState.IDLE


def test_알림을_끄면_조용하다(ctl, monkeypatch):
    from src.writer.importer import ImportResult, Summary, SAVED

    ctl.config.schedule.notify = False
    notices = []
    monkeypatch.setattr(ctl.tray, "notify", lambda t, m, error=False: notices.append(m))
    ctl.on_poll_finished(Summary([ImportResult(1, SAVED)]))
    assert notices == []


def test_가져온_쪽지가_없으면_알리지_않는다(ctl, monkeypatch):
    from src.writer.importer import Summary

    notices = []
    monkeypatch.setattr(ctl.tray, "notify", lambda t, m, error=False: notices.append(m))
    ctl.on_poll_finished(Summary())
    assert notices == []


def test_오류는_알림을_꺼도_알린다(ctl, monkeypatch):
    ctl.config.schedule.notify = False
    notices = []
    monkeypatch.setattr(ctl.tray, "notify", lambda t, m, error=False: notices.append((m, error)))
    ctl.on_poll_error("쿨메신저 쪽지 폴더가 없습니다: C:\\없음")
    assert notices[0][1] is True
    assert ctl.tray.state is AppState.ERROR


def test_설정이_없으면_마법사를_띄운다(qapp, monkeypatch):
    from src.config import Config

    ctl = AppController(qapp, config=Config())
    opened = []
    monkeypatch.setattr(ctl, "open_wizard", lambda: opened.append(1))
    assert ctl.prompt_setup_if_needed() is True
    assert opened == [1]
    ctl.tray.hide()


def test_설정이_있으면_띄우지_않는다(ctl, monkeypatch):
    opened = []
    monkeypatch.setattr(ctl, "open_settings", lambda: opened.append(1))
    assert ctl.prompt_setup_if_needed() is False
    assert opened == []
