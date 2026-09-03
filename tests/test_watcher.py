"""폴링 워처 (#14)."""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from src.config import Config
from src.sources.coolm import CoolmError
from src.sources.fake_udb import append_fake_message, create_fake_udb
from src.sources.watcher import Watcher
from src.state import StateDB
from src.writer.importer import FAILED, Importer
from src.writer.inbox import InboxError


@pytest.fixture
def setup(tmp_path, qapp):
    memo = tmp_path / "Memo"
    create_fake_udb(memo, [
        {"title": "첫째", "body": "본문 1", "received": datetime(2026, 9, 1, 10, 0)},
        {"title": "둘째", "body": "본문 2", "received": datetime(2026, 9, 2, 10, 0)},
    ], members=[{"key": 1, "id": "ham", "name": "함기훈"}])
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    state = StateDB(tmp_path / "state.db")
    w = Watcher(c, state)
    yield w, c, state, memo
    state.close()


def run_poll(qapp, watcher, timeout=5.0):
    """폴링을 돌리고 워커가 끝날 때까지 이벤트를 돌린다."""
    done = []
    watcher.poll_finished.connect(done.append)
    errors = []
    watcher.poll_error.connect(errors.append)
    watcher.poll_now()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not done and not errors:
        qapp.processEvents()
        time.sleep(0.01)
    return (done[0] if done else None), errors


# ---------------------------------------------------------------- 폴링

def test_새_쪽지를_배달한다(setup, qapp):
    w, c, state, _ = setup
    summary, errors = run_poll(qapp, w)
    assert errors == []
    assert summary.saved == 2
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 2


def test_두_번째_폴링은_아무것도_하지_않는다(setup, qapp):
    w, c, state, _ = setup
    run_poll(qapp, w)
    summary, _ = run_poll(qapp, w)
    assert summary.saved == 0
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 2


def test_마지막_키가_저장된다(setup, qapp):
    w, c, state, _ = setup
    run_poll(qapp, w)
    assert c.coolm.last_message_key == 2
    assert Config.load().coolm.last_message_key == 2


def test_새로_온_쪽지만_가져온다(setup, qapp):
    w, c, state, memo = setup
    run_poll(qapp, w)
    append_fake_message(next(memo.glob("*.udb")),
                        {"title": "셋째", "body": "본문 3", "received": datetime(2026, 9, 3, 9, 0)})
    summary, _ = run_poll(qapp, w)
    assert summary.saved == 1
    assert c.coolm.last_message_key == 3


def test_1회_처리_건수_제한(setup, qapp):
    w, c, state, _ = setup
    c.schedule.max_per_poll = 1
    summary, _ = run_poll(qapp, w)
    assert summary.saved == 1
    assert c.coolm.last_message_key == 1
    summary, _ = run_poll(qapp, w)              # 남은 것은 다음 주기에
    assert summary.saved == 1


def test_실패한_쪽지_앞에서_키가_멈춘다(setup, qapp, monkeypatch):
    """실패한 건을 지나쳐 버리면 영영 다시 시도되지 않는다."""
    w, c, state, _ = setup
    real = w.importer.writer.write_note

    def fail_first(filename, text, **k):
        if "첫째" in filename:
            raise InboxError("일시적 실패")
        return real(filename, text, **k)

    monkeypatch.setattr(w.importer.writer, "write_note", fail_first)
    summary, _ = run_poll(qapp, w)
    assert summary.failed == 1 and summary.saved == 1
    assert c.coolm.last_message_key == 0         # 실패한 1번을 넘지 않았다

    monkeypatch.setattr(w.importer.writer, "write_note", real)
    summary, _ = run_poll(qapp, w)
    assert summary.saved == 1                    # 다시 시도해서 성공
    assert c.coolm.last_message_key == 2


def test_오늘_배달_건수(setup, qapp):
    w, c, state, _ = setup
    assert w.delivered_today == 0
    run_poll(qapp, w)
    assert w.delivered_today == 2


def test_마지막_확인_시각이_기록된다(setup, qapp):
    w, c, state, _ = setup
    run_poll(qapp, w)
    assert len(c.ui.last_check_at) == 5           # 'HH:MM'


# ---------------------------------------------------------------- 오류

def test_폴더가_없으면_오류_시그널(tmp_path, qapp):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "없는폴더")
    c.inbox.root_dir = str(tmp_path)
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)
    summary, errors = run_poll(qapp, w)
    assert summary is None
    assert "쪽지 폴더가 없습니다" in errors[0]
    state.close()


def test_같은_오류는_한_번만_알린다(tmp_path, qapp):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "없는폴더")
    c.inbox.root_dir = str(tmp_path)
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)
    seen = []
    w.poll_error.connect(seen.append)
    for _ in range(3):
        w.poll_now()
        deadline = time.monotonic() + 2
        while w.busy and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()
    assert len(seen) == 1
    state.close()


def test_설정_전에는_안내를_낸다(tmp_path, qapp):
    c = Config()
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)
    seen = []
    w.poll_error.connect(seen.append)
    w.poll_now()
    assert "먼저 지정해" in seen[0]
    state.close()


def test_예상하지_못한_오류에도_죽지_않는다(setup, qapp, monkeypatch):
    w, c, state, _ = setup
    monkeypatch.setattr(w, "_collect", lambda: (_ for _ in ()).throw(RuntimeError("이상한 오류")))
    summary, errors = run_poll(qapp, w)
    assert summary is None
    assert "오류가 났습니다" in errors[0]
    assert w.busy is False                       # 다음 폴링을 막지 않는다


# ---------------------------------------------------------------- 타이머 제어

def test_주기_설정이_반영된다(setup):
    w, c, state, _ = setup
    c.schedule.poll_minutes = 7
    w.apply_config()
    assert w.active
    assert w._timer.interval() == 7 * 60 * 1000


def test_일시정지하면_타이머가_멈춘다(setup):
    w, c, state, _ = setup
    w.apply_config()
    assert w.active
    c.schedule.paused = True
    w.apply_config()
    assert not w.active


def test_설정이_안_됐으면_타이머를_돌리지_않는다(tmp_path, qapp):
    c = Config()
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)
    w.apply_config()
    assert not w.active
    state.close()


def test_이미_확인_중이면_다시_시작하지_않는다(setup, qapp, monkeypatch):
    w, c, state, _ = setup
    w._busy = True
    started = []
    w.poll_started.connect(lambda: started.append(1))
    w.poll_now()
    assert started == []


def test_연결_테스트_문구(setup):
    w, c, state, _ = setup
    assert "연결 OK" in w.check_connection()


def test_연결_테스트_실패는_예외(tmp_path, qapp):
    c = Config()
    c.coolm.memo_dir = str(tmp_path / "없음")
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)
    with pytest.raises(CoolmError):
        w.check_connection()
    state.close()
