"""첫 실행 마법사 (#17)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from src import osutil
from src.config import Config
from src.sources.fake_udb import create_fake_udb
from src.ui.setup_wizard import ALL, FUTURE_ONLY, RECENT, SetupWizard


@pytest.fixture
def wiz(qapp):
    w = SetupWizard(Config())
    yield w
    w.close()


# ---------------------------------------------------------------- 드롭박스 탐지

def test_info_json에서_드롭박스_경로를_읽는다(tmp_path, monkeypatch):
    root = tmp_path / "내드롭박스"
    root.mkdir()
    info = tmp_path / "Dropbox" / "info.json"
    info.parent.mkdir()
    info.write_text(json.dumps({"personal": {"path": str(root)}}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert osutil.dropbox_root() == str(root)


def test_이미_있는_인박스_폴더를_추천한다(tmp_path, monkeypatch):
    root = tmp_path / "Dropbox"
    (root / "학교" / "00_INBOX").mkdir(parents=True)
    info = tmp_path / "conf" / "Dropbox" / "info.json"
    info.parent.mkdir(parents=True)
    info.write_text(json.dumps({"personal": {"path": str(root)}}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "conf"))
    assert osutil.suggest_inbox_dir() == str(root / "학교" / "00_INBOX")


def test_인박스가_없으면_Inbox를_제안(tmp_path, monkeypatch):
    root = tmp_path / "Dropbox"
    (root / "문서").mkdir(parents=True)
    info = tmp_path / "conf" / "Dropbox" / "info.json"
    info.parent.mkdir(parents=True)
    info.write_text(json.dumps({"personal": {"path": str(root)}}), encoding="utf-8")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "conf"))
    assert osutil.suggest_inbox_dir() == str(root / "Inbox")


def test_드롭박스가_없으면_빈_문자열(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(osutil.Path, "home", staticmethod(lambda: tmp_path))
    assert osutil.dropbox_root() == ""
    assert osutil.suggest_inbox_dir() == ""


# ---------------------------------------------------------------- 화면

def test_다섯_단계(wiz):
    assert wiz.stack.count() == 5
    assert wiz.step_label.text() == "1 / 5"


def test_앞뒤로_이동(wiz):
    assert wiz.btn_back.isEnabled() is False
    wiz.go_next()
    assert wiz.step_label.text() == "2 / 5"
    assert wiz.btn_back.isEnabled() is True
    wiz.go_back()
    assert wiz.step_label.text() == "1 / 5"


def test_마지막_단계에서_버튼이_시작하기로(wiz):
    for _ in range(4):
        wiz.go_next()
    assert wiz.btn_next.text() == "시작하기"


def test_쪽지_폴더를_비우면_다음으로_못_간다(wiz):
    wiz.go_next()
    wiz.pick_memo.set_value("")
    assert wiz.btn_next.isEnabled() is False
    wiz.pick_memo.set_value("/어딘가")
    assert wiz.btn_next.isEnabled() is True


def test_인박스를_비우면_다음으로_못_간다(wiz):
    wiz.go_next()
    wiz.pick_memo.set_value("/어딘가")
    wiz.go_next()
    wiz.pick_inbox.set_value("")
    assert wiz.btn_next.isEnabled() is False


def test_기존_설정이_있으면_그것을_먼저_쓴다(qapp, tmp_path):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "내가정한폴더")
    c.inbox.root_dir = str(tmp_path / "내인박스")
    w = SetupWizard(c)
    assert w.pick_memo.value() == str(tmp_path / "내가정한폴더")
    assert w.pick_inbox.value() == str(tmp_path / "내인박스")
    w.close()


def test_저장_위치_미리보기(wiz, tmp_path):
    wiz.pick_inbox.set_value(str(tmp_path))
    assert "쿨메신저" in wiz.lbl_preview.text()


def test_연결_테스트_성공(qapp, tmp_path):
    memo = tmp_path / "Memo"
    create_fake_udb(memo, [{"title": "x", "received": datetime(2026, 9, 1, 10, 0)}])
    w = SetupWizard(Config())
    w.pick_memo.set_value(str(memo))
    w.test_coolm()
    assert "✅" in w.lbl_memo.text()
    w.close()


def test_연결_테스트_실패(qapp, tmp_path):
    w = SetupWizard(Config())
    w.pick_memo.set_value(str(tmp_path / "없음"))
    w.test_coolm()
    assert "⚠️" in w.lbl_memo.text()
    w.close()


# ---------------------------------------------------------------- 결과

def test_기본_선택은_앞으로_오는_것만(wiz):
    assert wiz.past_choice() == FUTURE_ONLY
    assert wiz.spin_recent.isEnabled() is False


def test_최근_N건을_고르면_숫자를_켠다(wiz):
    wiz.rb_recent.setChecked(True)
    assert wiz.past_choice() == RECENT
    assert wiz.spin_recent.isEnabled() is True


def test_완료하면_설정과_선택을_함께_내보낸다(wiz, tmp_path):
    got = []
    wiz.completed.connect(lambda c, p, n: got.append((c, p, n)))
    wiz.pick_memo.set_value(str(tmp_path / "Memo"))
    wiz.pick_inbox.set_value(str(tmp_path / "Inbox"))
    wiz.spin_minutes.setValue(10)
    wiz.rb_all.setChecked(True)
    wiz.finish()
    c, past, n = got[0]
    assert c.coolm.memo_dir == str(tmp_path / "Memo")
    assert c.schedule.poll_minutes == 10
    assert c.schedule.paused is False
    assert c.ui.first_run_done is True
    assert past == ALL


# ---------------------------------------------------------------- 컨트롤러 연동

def _controller(qapp, tmp_path, count=30):
    from src.app import AppController

    memo = tmp_path / "Memo"
    base = datetime(2026, 1, 1, 9, 0)
    create_fake_udb(memo, [{"title": f"쪽지 {i}", "body": f"본문 {i}",
                            "received": base + timedelta(hours=i)} for i in range(count)])
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    return AppController(qapp, config=c), c


def test_앞으로_오는_것만이면_최신_키에서_시작한다(qapp, tmp_path):
    ctl, c = _controller(qapp, tmp_path)
    assert ctl._start_key(FUTURE_ONLY, 20) == 30
    ctl.tray.hide()


def test_최근_N건이면_그만큼_남긴다(qapp, tmp_path):
    ctl, c = _controller(qapp, tmp_path)
    assert ctl._start_key(RECENT, 5) == 25          # 26~30 다섯 건이 남는다
    ctl.tray.hide()


def test_쪽지가_N건보다_적으면_처음부터(qapp, tmp_path):
    ctl, c = _controller(qapp, tmp_path, count=3)
    assert ctl._start_key(RECENT, 20) == 0
    ctl.tray.hide()


def test_전부면_0(qapp, tmp_path):
    ctl, c = _controller(qapp, tmp_path)
    assert ctl._start_key(ALL, 20) == 0
    ctl.tray.hide()


def test_마법사_취소해도_프로그램은_남는다(qapp):
    from src.app import AppController
    from src.ui.tray import AppState

    ctl = AppController(qapp, config=Config())
    w = ctl.open_wizard()
    w.reject()
    assert ctl.tray.state is AppState.SETUP        # 종료하지 않는다
    ctl.tray.hide()


def test_마법사_완료가_설정에_반영된다(qapp, tmp_path, monkeypatch):
    ctl, c = _controller(qapp, tmp_path)
    monkeypatch.setattr(ctl.watcher, "poll_now", lambda: None)
    w = ctl.open_wizard()
    w.spin_minutes.setValue(12)
    w.finish()
    assert ctl.config.schedule.poll_minutes == 12
    assert ctl.config.coolm.last_message_key == 30   # 앞으로 오는 것만
    assert Config.load().schedule.poll_minutes == 12
    ctl.tray.hide()
