"""보낸 쪽지 수집 (#25).

받은 쪽지와 키가 겹쳐도(recv#5 / send#5) 섞이지 않는 것이 핵심이다.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import pytest

from src.config import Config
from src.sources.coolm import CoolmReader, Message
from src.sources.fake_udb import append_fake_message, create_fake_udb
from src.state import StateDB
from src.writer.importer import Importer


def add_sent(path, **m):
    """tbl_send 에 보낸 쪽지 한 건."""
    import sqlite3
    from src.sources.fake_udb import format_receive_date, key_list, file_list
    con = sqlite3.connect(path)
    received = m.get("sent", datetime(2026, 9, 2, 14, 0))
    con.execute(
        "INSERT INTO tbl_send (MessageKey, MessageBody, Title, Receiver, ReceiverKey, ReferenceList, "
        "CCList, MessageType, SendDate, FilePath, FileHost, MessageText, MemoID, MessageCategory) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (m.get("key"), "", m.get("title", ""), m.get("receiver", "김철수(kim);"),
         key_list(m.get("recipients", [2])), key_list(m.get("recipients", [2])), None,
         5, format_receive_date(received), file_list(m.get("files", [])),
         "coolmsgrfilea.coolmessenger.com:46001" if m.get("files") else "",
         m.get("body", ""), 50000000 + (m.get("key") or 0), 0))
    con.commit()
    con.close()


@pytest.fixture
def memo(tmp_path):
    p = create_fake_udb(tmp_path / "Memo", [
        {"title": "받은 것", "body": "받은 본문", "received": datetime(2026, 9, 1, 10, 0),
         "recipients": [1]},
    ], members=[{"key": 1, "id": "ham", "name": "함기훈"},
                {"key": 2, "id": "kim", "name": "김철수"},
                {"key": 3, "id": "lee", "name": "이영희"}])
    add_sent(p, key=1, title="보낸 것", body="보낸 본문", recipients=[2, 3],
             sent=datetime(2026, 9, 2, 14, 0))
    add_sent(p, key=2, title="자료 전달", body="첨부 확인", recipients=[2],
             files=[("보고서.hwp", 500)], sent=datetime(2026, 9, 2, 15, 0))
    return tmp_path / "Memo"


# ---------------------------------------------------------------- 리더

def test_보낸_쪽지를_읽는다(memo):
    with CoolmReader(memo) as r:
        assert r.has_sent
        assert r.latest_sent_key() == 2
        assert r.all_sent_keys() == [1, 2]
        sent = r.sent_page(0, 10)
    assert [m.title for m in sent] == ["보낸 것", "자료 전달"]
    assert all(m.is_sent for m in sent)


def test_보낸_쪽지의_받는_사람(memo):
    with CoolmReader(memo) as r:
        m = r.sent_by_keys([1])[0]
    assert m.kind == "send"
    assert m.recipients == ["김철수", "이영희"]
    assert m.sender == ""                       # 보낸 사람은 나 자신
    assert m.party == "김철수 외 1"


def test_보낸_쪽지_첨부(memo):
    with CoolmReader(memo) as r:
        m = r.sent_by_keys([2])[0]
    assert m.attachment_names == ["보고서.hwp"]


def test_보낸_쪽지가_없는_DB도_안전(tmp_path):
    import sqlite3
    p = create_fake_udb(tmp_path / "Memo", [{"title": "x"}])
    con = sqlite3.connect(p); con.execute("DROP TABLE tbl_send"); con.commit(); con.close()
    with CoolmReader(tmp_path / "Memo") as r:
        assert r.has_sent is False
        assert r.sent_after(0) == []
        assert r.latest_sent_key() == 0


# ---------------------------------------------------------------- 저장

@pytest.fixture
def imp(tmp_path, memo):
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.coolm.include_sent = True
    c.inbox.root_dir = str(tmp_path / "Inbox")
    state = StateDB(tmp_path / "state.db")
    yield Importer(c, state), c, state
    state.close()


def test_보낸_쪽지는_보낸쪽지_폴더에(imp, memo):
    importer, c, state = imp
    with CoolmReader(memo) as r:
        sent = r.sent_page(0, 10)
    importer.import_many(sent)
    sent_dir = c.inbox.coolm_dir(sent=True)
    assert sent_dir.name == "보낸쪽지"
    assert len(list(sent_dir.glob("*.md"))) == 2


def test_받은_쪽지_폴더와_안_섞인다(imp, memo):
    importer, c, state = imp
    with CoolmReader(memo) as r:
        importer.import_many(r.messages_page(0, 10))
        importer.import_many(r.sent_page(0, 10))
    recv_top = list(c.inbox.coolm_dir().glob("*.md"))       # 재귀 안 함
    sent_top = list(c.inbox.coolm_dir(sent=True).glob("*.md"))
    assert len(recv_top) == 1                                # 받은 것 1건만
    assert len(sent_top) == 2                                # 보낸 것 2건


def test_받은_쪽지와_보낸_쪽지의_같은_키가_공존한다(imp, memo):
    """recv#1 과 send#1 이 둘 다 저장돼야 한다 (복합 키)."""
    importer, c, state = imp
    with CoolmReader(memo) as r:
        importer.import_many(r.messages_page(0, 10))         # recv#1
        importer.import_many(r.sent_page(0, 10))             # send#1, send#2
    assert state.seen(1, kind="recv")
    assert state.seen(1, kind="send")
    assert state.get(1, kind="recv").md_path != state.get(1, kind="send").md_path
    assert state.keys(kind="recv") == {1}
    assert state.keys(kind="send") == {1, 2}


def test_보낸_쪽지_재실행_중복_없음(imp, memo):
    importer, c, state = imp
    with CoolmReader(memo) as r:
        sent = r.sent_page(0, 10)
    importer.import_many(sent)
    s2 = importer.import_many(sent)
    assert s2.saved == 0
    assert len(list(c.inbox.coolm_dir(sent=True).glob("*.md"))) == 2


# ---------------------------------------------------------------- 폴링

def _poll(qapp, w):
    done = []
    w.poll_finished.connect(done.append)
    w.poll_now()
    deadline = time.monotonic() + 5
    while not done and time.monotonic() < deadline:
        qapp.processEvents(); time.sleep(0.01)
    qapp.processEvents()
    return done[0] if done else None


def test_설정을_켜야_보낸_쪽지를_가져온다(tmp_path, memo, qapp):
    from src.sources.watcher import Watcher
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    state = StateDB(tmp_path / "s.db")

    c.coolm.include_sent = False               # 꺼져 있으면
    w = Watcher(c, state)
    _poll(qapp, w)
    assert not c.inbox.coolm_dir(sent=True).exists() or \
        not list(c.inbox.coolm_dir(sent=True).glob("*.md"))

    c.coolm.include_sent = True                # 켜면
    _poll(qapp, w)
    assert len(list(c.inbox.coolm_dir(sent=True).glob("*.md"))) == 2
    assert c.coolm.last_sent_key == 2
    state.close()


def test_보낸_쪽지_키는_따로_전진한다(tmp_path, memo, qapp):
    from src.sources.watcher import Watcher
    c = Config()
    c.coolm.memo_dir = str(memo)
    c.coolm.include_sent = True
    c.inbox.root_dir = str(tmp_path / "Inbox")
    (tmp_path / "Inbox").mkdir()
    state = StateDB(tmp_path / "s.db")
    w = Watcher(c, state)
    _poll(qapp, w)
    assert c.coolm.last_message_key == 1       # 받은 것
    assert c.coolm.last_sent_key == 2          # 보낸 것 — 서로 독립
    state.close()
