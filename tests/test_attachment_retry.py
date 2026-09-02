"""첨부 재시도 (FR-2.7).

쿨메신저는 사용자가 눌러서 받기 전까지 첨부를 PC 에 내려받지 않는다.
쪽지가 도착한 시점에는 원본이 없다가 나중에 생기는 것이 오히려 보통이다.
"""
from __future__ import annotations

import time
from datetime import datetime

import pytest

from src.config import Config
from src.sources.attachments import AttachmentFinder
from src.sources.coolm import Attachment, Message
from src.sources.fake_udb import create_fake_udb
from src.sources.watcher import Watcher
from src.state import StateDB
from src.writer.importer import SAVED, SKIPPED, Importer, md_sha


def msg(**kw) -> Message:
    base = dict(key=1, received=datetime(2026, 9, 2, 17, 0), sender="홍길동(hong)",
                title="협의회", body="자료 확인 바랍니다",
                attachments=[Attachment("계획서.hwp", 500)])
    return Message(**{**base, **kw})


@pytest.fixture
def env(tmp_path):
    recv = tmp_path / "Received Files"
    recv.mkdir()
    c = Config()
    c.inbox.root_dir = str(tmp_path / "Inbox")
    c.coolm.recv_file_dir = str(recv)
    c.coolm.attach_match_minutes = 0
    state = StateDB(tmp_path / "state.db")
    imp = Importer(c, state)
    yield imp, state, recv, c
    state.close()


def test_처음엔_못_찾고_이력에_미완료로_남는다(env):
    imp, state, recv, c = env
    r = imp.import_one(msg())
    assert r.status == SAVED and r.attach_ok == 0
    assert [x.message_key for x in state.pending_attachments()] == [1]
    assert "찾지 못했습니다" in r.md_path.read_text(encoding="utf-8")


def test_나중에_파일이_생기면_재시도로_붙는다(env):
    imp, state, recv, c = env
    saved = imp.import_one(msg())

    (recv / "계획서.hwp").write_bytes(b"x" * 500)      # 사용자가 뒤늦게 내려받았다
    imp.finder = AttachmentFinder(recv, 0)

    r = imp.retry_attachments(msg(), state.get(1))
    assert r.status == SAVED and r.attach_ok == 1
    text = saved.md_path.read_text(encoding="utf-8")
    assert "찾지 못했습니다" not in text
    assert "첨부파일/2026-09-02_1700_홍길동_#1/계획서.hwp" in text
    assert state.pending_attachments() == []


def test_파일이_복사된다(env):
    imp, state, recv, c = env
    imp.import_one(msg())
    (recv / "계획서.hwp").write_bytes(b"x" * 500)
    imp.finder = AttachmentFinder(recv, 0)
    imp.retry_attachments(msg(), state.get(1))
    copied = c.inbox.attach_dir() / "2026-09-02_1700_홍길동_#1" / "계획서.hwp"
    assert copied.read_bytes() == b"x" * 500


def test_여전히_없으면_아무것도_하지_않는다(env):
    imp, state, recv, c = env
    saved = imp.import_one(msg())
    before = saved.md_path.read_text(encoding="utf-8")
    r = imp.retry_attachments(msg(), state.get(1))
    assert r.status == SKIPPED
    assert saved.md_path.read_text(encoding="utf-8") == before


def test_사용자가_md를_고쳤으면_파일만_복사하고_md는_그대로_둔다(env):
    """인박스는 사용자의 것이다. 메모를 덧붙였다면 덮어쓰지 않는다."""
    imp, state, recv, c = env
    saved = imp.import_one(msg())
    edited = saved.md_path.read_text(encoding="utf-8") + "\n\n내가 적은 메모\n"
    saved.md_path.write_text(edited, encoding="utf-8")

    (recv / "계획서.hwp").write_bytes(b"x" * 500)
    imp.finder = AttachmentFinder(recv, 0)
    r = imp.retry_attachments(msg(), state.get(1))

    assert r.status == SAVED and r.attach_ok == 1
    assert saved.md_path.read_text(encoding="utf-8") == edited      # 손대지 않았다
    assert (c.inbox.attach_dir() / "2026-09-02_1700_홍길동_#1" / "계획서.hwp").exists()
    assert state.pending_attachments() == []                       # 재시도는 끝난 것으로 본다


def test_md가_사라졌으면_건너뛴다(env):
    imp, state, recv, c = env
    saved = imp.import_one(msg())
    saved.md_path.unlink()
    assert imp.retry_attachments(msg(), state.get(1)).status == SKIPPED


def test_md_지문이_저장된다(env):
    imp, state, recv, c = env
    saved = imp.import_one(msg())
    row = state.get(1)
    assert row.md_sha == md_sha(saved.md_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 폴링 연동

def test_폴링이_알아서_재시도한다(tmp_path, qapp):
    memo = tmp_path / "Memo"
    create_fake_udb(memo, [{"title": "협의회", "body": "자료 확인",
                            "received": datetime(2026, 9, 2, 17, 0),
                            "files": [("계획서.hwp", 500)]}])
    recv = tmp_path / "Received Files"
    recv.mkdir()
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.coolm.recv_file_dir = str(recv)
    c.coolm.attach_match_minutes = 0
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)

    def poll():
        done = []
        w.poll_finished.connect(done.append)
        w.poll_now()
        deadline = time.monotonic() + 5
        while not done and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        qapp.processEvents()
        return done[0] if done else None

    first = poll()
    assert first.saved == 1
    md = next(c.inbox.coolm_dir().glob("*.md"))
    assert "찾지 못했습니다" in md.read_text(encoding="utf-8")

    (recv / "계획서.hwp").write_bytes(b"x" * 500)      # 사용자가 쿨메신저에서 내려받았다
    second = poll()
    assert second.saved == 1                          # 새 쪽지는 없지만 첨부를 붙였다
    assert "찾지 못했습니다" not in md.read_text(encoding="utf-8")
    assert state.pending_attachments() == []
    state.close()
