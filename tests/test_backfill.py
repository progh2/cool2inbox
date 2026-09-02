"""이전 쪽지 모두 가져오기 (#19)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from src.config import Config
from src.sources.fake_udb import create_fake_udb
from src.state import StateDB
from src.ui.progress_dialog import BackfillProgressDialog
from src.writer.backfill import Backfill
from src.writer.importer import Importer


def make_messages(n: int) -> list[dict]:
    base = datetime(2026, 1, 1, 9, 0, 0)
    return [{"title": f"쪽지 {i}", "body": f"본문 {i}", "received": base + timedelta(hours=i),
             "recipients": [1]} for i in range(n)]


@pytest.fixture
def setup(tmp_path, qapp):
    memo = tmp_path / "Memo"
    create_fake_udb(memo, make_messages(25), members=[{"key": 1, "id": "ham", "name": "함기훈"}])
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    state = StateDB(tmp_path / "state.db")
    b = Backfill(c, state, Importer(c, state))
    yield b, c, state, str(memo)
    state.close()


def run(qapp, backfill, memo, timeout=10.0):
    done, failed = [], []
    backfill.finished.connect(done.append)
    backfill.failed.connect(failed.append)
    backfill.start(memo)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not done and not failed:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    return (done[0] if done else None), failed


# ---------------------------------------------------------------- 미리보기

def test_미리보기(setup):
    b, c, state, memo = setup
    p = b.preview(memo)
    assert (p.total, p.already, p.to_import) == (25, 0, 25)
    assert "가져올 쪽지 25건" in p.describe()


def test_이미_가져온_것은_빼고_센다(setup, qapp):
    b, c, state, memo = setup
    run(qapp, b, memo)
    p = b.preview(memo)
    assert (p.total, p.already, p.to_import) == (25, 25, 0)
    assert "모두 이미 인박스에 있습니다" in p.describe()


def test_첨부_개수도_센다(tmp_path, qapp):
    memo = tmp_path / "Memo"
    create_fake_udb(memo, [{"title": "a", "body": "1", "files": [("x.hwp", 1), ("y.hwp", 2)]},
                           {"title": "b", "body": "2", "files": [("z.hwp", 3)]}])
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(memo), str(tmp_path)
    state = StateDB(tmp_path / "s.db")
    b = Backfill(c, state, Importer(c, state))
    assert b.preview(str(memo)).attachments == 3
    state.close()


# ---------------------------------------------------------------- 실행

def test_전부_가져온다(setup, qapp):
    b, c, state, memo = setup
    summary, failed = run(qapp, b, memo)
    assert failed == []
    assert summary.saved == 25
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 25


def test_배치_경계를_넘어도_전부_처리한다(tmp_path, qapp):
    """BATCH(200) 보다 많은 쪽지."""
    memo = tmp_path / "Memo"
    create_fake_udb(memo, make_messages(450))
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(memo), str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    state = StateDB(tmp_path / "s.db")
    b = Backfill(c, state, Importer(c, state))
    summary, _ = run(qapp, b, memo, timeout=30)
    assert summary.saved == 450
    state.close()


def test_두_번_돌려도_중복이_없다(setup, qapp):
    b, c, state, memo = setup
    run(qapp, b, memo)
    summary, _ = run(qapp, b, memo)
    assert summary.saved == 0
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 25


def test_진행률이_올라온다(setup, qapp):
    b, c, state, memo = setup
    seen = []
    b.progress.connect(lambda d, t, n: seen.append((d, t)))
    run(qapp, b, memo)
    assert seen[0] == (1, 25)
    assert seen[-1] == (25, 25)


def test_백필은_마지막_처리_키를_건드리지_않는다(setup, qapp):
    """백필은 과거를 채우는 일이다. 여기서 키를 옮기면 폴링이 최신 쪽지를 건너뛴다."""
    b, c, state, memo = setup
    c.coolm.last_message_key = 0
    run(qapp, b, memo)
    assert c.coolm.last_message_key == 0


def test_취소하면_거기까지만_저장하고_유지한다(setup, qapp):
    b, c, state, memo = setup
    b.progress.connect(lambda d, t, n: b.cancel() if d >= 5 else None)
    summary, _ = run(qapp, b, memo)
    assert b.cancelled is True
    assert 0 < summary.saved <= 25
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == summary.saved


def test_취소한_뒤_다시_돌리면_이어서_한다(setup, qapp):
    b, c, state, memo = setup
    b.progress.connect(lambda d, t, n: b.cancel() if d >= 5 else None)
    first, _ = run(qapp, b, memo)
    b2 = Backfill(c, state, b.importer)
    second, _ = run(qapp, b2, memo)
    assert first.saved + second.saved == 25


def test_폴더가_없으면_실패를_알린다(tmp_path, qapp):
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(tmp_path / "없음"), str(tmp_path)
    state = StateDB(tmp_path / "s.db")
    b = Backfill(c, state, Importer(c, state))
    summary, failed = run(qapp, b, str(tmp_path / "없음"))
    assert summary is None
    assert "쪽지 폴더가 없습니다" in failed[0]
    state.close()


def test_돌고_있으면_다시_시작하지_않는다(setup, qapp):
    b, c, state, memo = setup
    b.pace_seconds = 0.02
    b.start(memo)
    b.start(memo)                       # 두 번째 호출은 무시된다
    deadline = time.monotonic() + 10
    while b.running and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 25


# ---------------------------------------------------------------- 진행률 창

def test_진행률_창_표시(qapp):
    d = BackfillProgressDialog(1187)
    d.set_progress(47, 1187, "a.md")
    assert d.bar.value() == 47 and d.bar.maximum() == 1187
    assert "47" in d.label.text()
    assert d.detail.text() == "a.md"
    d.close()


def test_취소를_누르면_시그널이_나고_안내가_바뀐다(qapp):
    d = BackfillProgressDialog(10)
    got = []
    d.cancel_requested.connect(lambda: got.append(1))
    d.buttons.rejected.emit()
    assert got == [1]
    assert "취소하는 중" in d.label.text()
    assert d.buttons.isEnabled() is False
    d.close()


# ---------------------------------------------------------------- 컨트롤러 연동

def test_컨트롤러가_가져올_것이_없으면_알리고_끝낸다(qapp, tmp_path, monkeypatch):
    from src.app import AppController

    memo = tmp_path / "Memo"
    create_fake_udb(memo, make_messages(2))
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(memo), str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    ctl = AppController(qapp, config=c)
    for k in (1, 2):
        ctl.state.record(k, f"h{k}", "/x.md")

    shown = []
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.information",
                        lambda *a, **k: shown.append(a[2]))
    ctl.start_backfill()
    assert "모두 이미 인박스에 있습니다" in shown[0]
    ctl.tray.hide()


def test_컨트롤러가_확인을_받고_시작한다(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from src.app import AppController

    memo = tmp_path / "Memo"
    create_fake_udb(memo, make_messages(3))
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(memo), str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    ctl = AppController(qapp, config=c)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    ctl.start_backfill()
    deadline = time.monotonic() + 10
    while (ctl._backfill is None or ctl._backfill.running) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 3
    ctl.tray.hide()


def test_확인을_거절하면_아무것도_하지_않는다(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from src.app import AppController

    memo = tmp_path / "Memo"
    create_fake_udb(memo, make_messages(3))
    c = Config()
    c.coolm.memo_dir, c.inbox.root_dir = str(memo), str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    ctl = AppController(qapp, config=c)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    ctl.start_backfill()
    assert ctl._progress is None
    assert not list(c.inbox.coolm_dir().glob("*.md")) if c.inbox.coolm_dir().exists() else True
    ctl.tray.hide()
