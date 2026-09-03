"""아카이브 폴더 — 옮겨둔 쪽지를 '이미 가져온 것'으로 인식 (FR-4.6, #26)."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta

import pytest

from src.config import Config
from src.sources.fake_udb import create_fake_udb
from src.state import StateDB
from src.sources.coolm import CoolmReader
from src.writer.importer import Importer


def _md(path, key, chash="h", direction="received"):
    path.write_text(f"---\nmessage_key: {key}\ncontent_hash: {chash}\n"
                    f"direction: {direction}\nimported_at: 2026-09-01 10:00:00\n---\n본문\n",
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------- 이력 복구

def test_아카이브를_재귀로_훑어_이력을_채운다(tmp_path):
    arch = tmp_path / "쪽지아카이브"
    (arch / "2026" / "첨부").mkdir(parents=True)
    _md(arch / "a.md", 10)
    _md(arch / "2026" / "b.md", 11)                      # 하위 폴더까지
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_archives([str(arch)]) == 2
        assert db.keys() == {10, 11}


def test_direction_으로_받은_보낸을_가른다(tmp_path):
    arch = tmp_path / "arch"
    arch.mkdir()
    _md(arch / "r.md", 5, direction="received")
    _md(arch / "s.md", 5, direction="sent")             # 같은 키, 다른 방향
    with StateDB(tmp_path / "s.db") as db:
        db.rebuild_from_archives([str(arch)])
        assert db.seen(5, kind="recv")
        assert db.seen(5, kind="send")


def test_여러_아카이브_폴더(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(); b.mkdir()
    _md(a / "x.md", 1); _md(b / "y.md", 2)
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_archives([str(a), str(b)]) == 2


def test_없는_폴더는_건너뛴다(tmp_path):
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_archives([str(tmp_path / "없음"), ""]) == 0


def test_기존_이력을_덮지_않는다(tmp_path):
    arch = tmp_path / "arch"; arch.mkdir()
    _md(arch / "a.md", 7, chash="아카이브해시")
    with StateDB(tmp_path / "s.db") as db:
        db.record(7, "원래해시", "/원래/경로.md")
        db.rebuild_from_archives([str(arch)])
        assert db.get(7).content_hash == "원래해시"


# ---------------------------------------------------------------- 사용자 시나리오 (통짜)

def test_옮겨둔_쪽지는_다시_만들어지지_않는다(tmp_path, qapp):
    """사용자가 인박스의 md·첨부를 아카이브 폴더로 옮긴 뒤, 상태 DB 까지 잃은 최악의 경우."""
    from src.app import AppController

    memo = tmp_path / "Memo"
    base = datetime(2026, 1, 1, 9, 0)
    create_fake_udb(memo, [{"title": f"쪽지 {i}", "body": f"본문 {i}",
                            "received": base + timedelta(hours=i)} for i in range(5)],
                    members=[{"key": 1, "id": "ham", "name": "함기훈"}])
    inbox = tmp_path / "Inbox"
    archive = tmp_path / "아카이브"
    archive.mkdir()

    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(inbox)

    # 1) 처음 가져온다
    with StateDB(tmp_path / "s.db") as st:
        imp = Importer(c, st)
        with CoolmReader(memo) as r:
            imp.import_many(r.messages_page(0, 100))
        assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 5

    # 2) 사용자가 md 를 몽땅 아카이브로 옮기고 상태 DB 도 사라졌다
    for f in c.inbox.coolm_dir().glob("*.md"):
        shutil.move(str(f), archive / f.name)
    (tmp_path / "s.db").unlink()
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 0

    # 3) 아카이브를 등록하고 다시 켠다
    c.inbox.archive_dirs = [str(archive)]
    ctl = AppController(qapp, config=c, state=StateDB(tmp_path / "s.db"))
    # 시작 시 absorb_archives 로 이력이 복구됐다
    assert ctl.state.keys() == {1, 2, 3, 4, 5}

    # 4) 폴링해도 다시 만들지 않는다
    with CoolmReader(memo) as r:
        summary = ctl.watcher.importer.import_many(r.messages_page(0, 100))
    assert summary.saved == 0
    assert len(list(c.inbox.coolm_dir().glob("*.md"))) == 0    # 새로 안 만든다
    ctl.tray.hide()


def test_아카이브_등록_후_새_쪽지는_기존_폴더로(tmp_path, qapp):
    from src.app import AppController

    memo = tmp_path / "Memo"
    p = create_fake_udb(memo, [{"title": "옛날 쪽지", "body": "1",
                                "received": datetime(2026, 1, 1, 9, 0)}])
    inbox = tmp_path / "Inbox"
    archive = tmp_path / "아카이브"
    archive.mkdir()
    _md(archive / "옛날.md", 1, chash="x")               # 1번은 아카이브에 있다

    c = Config()
    c.coolm.memo_dir = str(memo)
    c.inbox.root_dir = str(inbox)
    c.inbox.archive_dirs = [str(archive)]
    ctl = AppController(qapp, config=c, state=StateDB(tmp_path / "s.db"))
    assert ctl.state.seen(1)                              # 아카이브에서 인식됨

    # 새 쪽지 도착
    from src.sources.fake_udb import append_fake_message
    append_fake_message(p, {"title": "새 쪽지", "body": "2", "received": datetime(2026, 9, 3, 9, 0)})
    with CoolmReader(memo) as r:
        s = ctl.watcher.importer.import_many(r.messages_after(0, 100))
    # 1번은 건너뛰고 2번만 기존 폴더에 저장
    assert s.saved == 1
    saved = list(c.inbox.coolm_dir().glob("*.md"))
    assert len(saved) == 1 and "새" in saved[0].read_text(encoding="utf-8")
    ctl.tray.hide()


# ---------------------------------------------------------------- 첨부 재시도

def test_md가_옮겨졌으면_재시도를_멈춘다(tmp_path):
    from src.sources.coolm import Attachment, Message
    from src.sources.attachments import AttachmentFinder

    c = Config()
    c.inbox.root_dir = str(tmp_path / "Inbox")
    with StateDB(tmp_path / "s.db") as st:
        imp = Importer(c, st)
        m = Message(key=1, received=datetime(2026, 9, 2, 17, 0), sender="홍(h)", title="t",
                    attachments=[Attachment("a.hwp", 100)])
        saved = imp.import_one(m)
        assert st.pending_attachments()               # 첨부 못 찾아 미완료

        saved.md_path.unlink()                        # 사용자가 md 를 옮겼다(여기선 삭제로 흉내)
        r = imp.retry_attachments(m, st.get(1))
        assert "옮겨졌습니다" in r.reason
        assert st.pending_attachments() == []         # 무한 재시도 안 함
