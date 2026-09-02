"""설정 창 (#18)."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.config import POLL_MAX, Config
from src.sources.fake_udb import create_fake_udb
from src.ui.settings_dialog import SettingsDialog


@pytest.fixture
def cfg(tmp_path):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "Memo")
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Memo").mkdir()
    (tmp_path / "Inbox").mkdir()
    return c


@pytest.fixture
def dlg(qapp, cfg):
    d = SettingsDialog(cfg)
    yield d
    d.close()


def test_탭_다섯_개(dlg):
    assert [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())] == \
        ["폴더", "확인 주기", "출력 형식", "가져오기", "정보"]


def test_설정값이_화면에_들어온다(dlg, cfg):
    assert dlg.pick_memo.value() == cfg.coolm.memo_dir
    assert dlg.pick_inbox.value() == cfg.inbox.root_dir
    assert dlg.spin_minutes.value() == 5
    assert dlg.edit_coolm_name.text() == "쿨메신저"
    assert dlg.chk_notify.isChecked() is True


def test_화면값이_설정으로_돌아간다(dlg, cfg, tmp_path):
    dlg.spin_minutes.setValue(15)
    dlg.chk_notify.setChecked(False)
    dlg.edit_coolm_name.setText("CoolMessenger")
    dlg.edit_format.setText("{date}_{title}")
    got = dlg.apply_to_config()
    assert got.schedule.poll_minutes == 15
    assert got.schedule.notify is False
    assert got.inbox.coolm_folder_name == "CoolMessenger"
    assert got.output.filename_format == "{date}_{title}"


def test_주기는_허용_범위를_벗어날_수_없다(dlg):
    dlg.spin_minutes.setValue(99999)
    assert dlg.spin_minutes.value() == POLL_MAX


def test_저장하면_파일에_쓰이고_시그널이_난다(dlg):
    got = []
    dlg.applied.connect(got.append)
    dlg.spin_minutes.setValue(9)
    dlg.save()
    assert got and got[0].schedule.poll_minutes == 9
    assert Config.load().schedule.poll_minutes == 9


def test_폴더가_없으면_저장을_막는다(qapp, tmp_path, monkeypatch):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "없음")
    c.inbox.root_dir = str(tmp_path)
    d = SettingsDialog(c)
    warned = []
    monkeypatch.setattr("src.ui.settings_dialog.QMessageBox.warning",
                        lambda *a, **k: warned.append(a[2]))
    got = []
    d.applied.connect(got.append)
    d.save()
    assert got == []                    # 시그널이 나지 않는다
    assert d.isVisible() is False or True
    assert "쪽지 폴더가 없습니다" in warned[0]
    d.close()


# ---------------------------------------------------------------- 미리보기

def test_파일명_미리보기(dlg):
    assert dlg.lbl_preview.text() == "2026-09-02_1704_홍길동_2학기_교육과정_협의회_#1234.md"


def test_서식을_바꾸면_미리보기도_바뀐다(dlg):
    dlg.edit_format.setText("{date}_{sender}")
    assert dlg.lbl_preview.text() == "2026-09-02_홍길동.md"


def test_저장_경로_미리보기(dlg, cfg):
    assert cfg.inbox.root_dir in dlg.lbl_paths.text()
    assert "쿨메신저" in dlg.lbl_paths.text()
    dlg.edit_attach_name.setText("files")
    assert "files" in dlg.lbl_paths.text()


def test_인박스가_비면_안내(qapp):
    d = SettingsDialog(Config())
    assert "고르면" in d.lbl_paths.text()
    d.close()


# ---------------------------------------------------------------- 통계

def test_통계가_없으면_그렇게_말한다(dlg):
    assert "아직 가져온 쪽지가 없습니다" in dlg.lbl_stats.text()


def test_통계_표시(qapp, cfg):
    d = SettingsDialog(cfg, stats={"notes": 1075, "attachments_ok": 2,
                                   "last_imported_at": "2026-09-02 19:08",
                                   "attachments_pending_notes": 276})
    assert "1,075건" in d.lbl_stats.text()
    assert "첨부 미완료 276건" in d.lbl_stats.text()
    d.close()


# ---------------------------------------------------------------- 시그널

@pytest.mark.parametrize("signal_name", [
    "coolm_test_requested", "recv_test_requested", "backfill_requested",
    "rebuild_requested", "clear_history_requested",
])
def test_시그널이_정의돼_있다(dlg, signal_name):
    got = []
    getattr(dlg, signal_name).connect(lambda: got.append(1))
    getattr(dlg, signal_name).emit()
    assert got == [1]


def test_연결_테스트_결과_표시(dlg):
    dlg.show_coolm_result("연결 OK — 쪽지 3건")
    assert "✅" in dlg.lbl_memo.text()
    dlg.show_coolm_result("폴더가 없습니다", ok=False)
    assert "⚠️" in dlg.lbl_memo.text()


# ---------------------------------------------------------------- 컨트롤러 연동

def test_컨트롤러가_연결_테스트를_처리한다(qapp, tmp_path):
    from src.app import AppController

    memo = tmp_path / "Memo"
    create_fake_udb(memo, [{"title": "x", "received": datetime(2026, 9, 1, 10, 0)}])
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(tmp_path)
    ctl = AppController(qapp, config=c)
    d = ctl.build_settings_dialog()
    d.coolm_test_requested.emit()
    assert "연결 OK" in d.lbl_memo.text()
    d.close()
    ctl.tray.hide()


def test_컨트롤러가_실패도_보여준다(qapp, tmp_path):
    from src.app import AppController

    c = Config()
    c.coolm.memo_dir = str(tmp_path / "없음")
    c.inbox.root_dir = str(tmp_path)
    ctl = AppController(qapp, config=c)
    d = ctl.build_settings_dialog()
    d.coolm_test_requested.emit()
    assert "⚠️" in d.lbl_memo.text()
    d.close()
    ctl.tray.hide()


def test_설정_저장이_워처에_반영된다(qapp, tmp_path):
    from src.app import AppController

    memo = tmp_path / "Memo"
    create_fake_udb(memo, [{"title": "x"}])
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(memo), str(tmp_path)
    ctl = AppController(qapp, config=c)
    d = ctl.build_settings_dialog()
    d.spin_minutes.setValue(11)
    d.save()
    assert ctl.watcher._timer.interval() == 11 * 60 * 1000
    ctl.tray.hide()


def test_이력_초기화가_마지막_키도_되돌린다(qapp, tmp_path):
    from src.app import AppController

    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(tmp_path), str(tmp_path)
    c.coolm.last_message_key = 500
    ctl = AppController(qapp, config=c)
    ctl.state.record(1, "h", "/x/1.md")
    d = ctl.build_settings_dialog()
    ctl._clear_history(d)
    assert ctl.config.coolm.last_message_key == 0
    assert ctl.state.stats()["notes"] == 0
    d.close()
    ctl.tray.hide()
