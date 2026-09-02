"""중복 방지 이력 (#3).

수용 기준 2번 — "프로그램을 10번 재시작하고 백필을 3번 눌러도 중복 0건" 을 여기서 지킨다.
"""
from __future__ import annotations

import pytest

from src.state import StateDB, read_front_matter


@pytest.fixture
def db(tmp_path):
    with StateDB(tmp_path / "state.sqlite3") as s:
        yield s


def _md(path, key=None, chash=None, imported_at=None, body="본문"):
    lines = ["---"]
    if key is not None:
        lines.append(f"message_key: {key}")
    if chash is not None:
        lines.append(f"content_hash: {chash}")
    if imported_at is not None:
        lines.append(f"imported_at: {imported_at}")
    lines += ["---", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# ---------------------------------------------------------------- 판정

def test_처음_보는_쪽지(db):
    assert db.seen(1) is False
    assert db.seen(1, "해시") is False


def test_키로_판정(db):
    db.record(1, "해시A", "/x/a.md")
    assert db.seen(1)
    assert db.seen(1, "완전히_다른_해시")       # 키가 이미 있으면 해시와 무관하게 중복


def test_해시로_판정_udb가_재생성된_경우(db):
    """udb 가 초기화돼 같은 쪽지가 다른 키로 다시 나타나도 잡아낸다."""
    db.record(1, "해시A", "/x/a.md")
    assert db.seen(9999, "해시A")
    assert not db.seen(9999, "해시B")


def test_해시가_비면_키만_본다(db):
    db.record(1, "해시A", "/x/a.md")
    assert db.seen(1, "")
    assert not db.seen(2, "")


# ---------------------------------------------------------------- 중복 방지 (수용 기준 2)

def test_같은_쪽지를_열_번_기록해도_한_행(db):
    for _ in range(10):
        if not db.seen(42, "해시"):
            db.record(42, "해시", "/x/42.md")
    assert db.stats()["notes"] == 1


def test_record는_같은_키를_갱신한다(db):
    db.record(7, "h", "/x/old.md", attach_total=2, attach_ok=0)
    db.record(7, "h", "/x/new.md", attach_total=2, attach_ok=2)
    row = db.get(7)
    assert row.md_path == "/x/new.md"
    assert row.attach_ok == 2
    assert db.stats()["notes"] == 1


# ---------------------------------------------------------------- 조회

def test_get과_keys와_max_key(db):
    assert db.get(1) is None
    assert db.keys() == set()
    assert db.max_key() == 0
    db.record(3, "h3", "/x/3.md")
    db.record(10, "h10", "/x/10.md")
    assert db.keys() == {3, 10}
    assert db.max_key() == 10
    assert db.get(3).content_hash == "h3"


def test_첨부_미완료는_재시도_대상(db):
    db.record(1, "h", "/x/1.md", attach_total=3, attach_ok=3)
    db.record(2, "h2", "/x/2.md", attach_total=3, attach_ok=1)
    db.record(3, "h3", "/x/3.md", attach_total=0, attach_ok=0)
    pending = db.pending_attachments()
    assert [r.message_key for r in pending] == [2]
    assert pending[0].attachments_pending is True
    assert db.get(1).attachments_pending is False


def test_첨부_재시도_결과_반영(db):
    db.record(2, "h", "/x/2.md", attach_total=3, attach_ok=1)
    db.update_attachments(2, 3)
    assert db.pending_attachments() == []


def test_stats(db):
    assert db.stats()["notes"] == 0
    db.record(1, "h", "/x/1.md", attach_total=2, attach_ok=1, imported_at="2026-01-01 00:00:00")
    db.record(2, "h2", "/x/2.md", imported_at="2026-02-02 00:00:00")
    s = db.stats()
    assert s == {"notes": 2, "attachments": 2, "attachments_ok": 1, "attachments_pending_notes": 1,
                 "first_imported_at": "2026-01-01 00:00:00", "last_imported_at": "2026-02-02 00:00:00",
                 "max_message_key": 2}


# ---------------------------------------------------------------- 삭제

def test_forget은_다시_가져오게_만든다(db):
    db.record(1, "h", "/x/1.md")
    db.forget(1)
    assert not db.seen(1, "h")


def test_clear(db):
    db.record(1, "h", "/x/1.md")
    db.record(2, "h2", "/x/2.md")
    assert db.clear() == 2
    assert db.stats()["notes"] == 0


# ---------------------------------------------------------------- 인박스에서 복구 (FR-4.3)

def test_인박스에서_이력_복구(tmp_path):
    inbox = tmp_path / "쿨메신저"
    inbox.mkdir()
    _md(inbox / "a.md", key=11, chash="해시11", imported_at="2026-09-01 10:00:00")
    _md(inbox / "b.md", key=12, chash="해시12")
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_inbox(inbox) == 2
        assert db.keys() == {11, 12}
        assert db.get(11).imported_at == "2026-09-01 10:00:00"
        assert db.seen(99, "해시12")


def test_복구는_기존_행을_덮지_않는다(tmp_path):
    inbox = tmp_path / "쿨메신저"
    inbox.mkdir()
    _md(inbox / "a.md", key=11, chash="파일쪽해시")
    with StateDB(tmp_path / "s.db") as db:
        db.record(11, "원래해시", "/원래/경로.md")
        assert db.rebuild_from_inbox(inbox) == 0
        assert db.get(11).content_hash == "원래해시"


def test_머리말_없는_md는_건너뛴다(tmp_path):
    inbox = tmp_path / "쿨메신저"
    inbox.mkdir()
    (inbox / "손으로_쓴_메모.md").write_text("그냥 메모입니다", encoding="utf-8")
    _md(inbox / "키없음.md", chash="해시만있음")
    _md(inbox / "정상.md", key=5, chash="h5")
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_inbox(inbox) == 1
        assert db.keys() == {5}


def test_폴더가_없으면_0(tmp_path):
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_inbox(tmp_path / "없는폴더") == 0


def test_복구는_첨부파일_폴더를_뒤지지_않는다(tmp_path):
    """첨부 하위 폴더에 md 가 들어 있어도 재귀하지 않는다."""
    inbox = tmp_path / "쿨메신저"
    (inbox / "첨부파일" / "어떤쪽지").mkdir(parents=True)
    _md(inbox / "정상.md", key=1, chash="h")
    _md(inbox / "첨부파일" / "어떤쪽지" / "받은문서.md", key=777, chash="h777")
    with StateDB(tmp_path / "s.db") as db:
        assert db.rebuild_from_inbox(inbox) == 1
        assert db.keys() == {1}


# ---------------------------------------------------------------- 머리말 읽기

def test_머리말_파싱(tmp_path):
    p = _md(tmp_path / "a.md", key=3, chash="abc", imported_at="2026-09-02 17:04:03")
    assert read_front_matter(p) == {"message_key": 3, "content_hash": "abc",
                                    "imported_at": "2026-09-02 17:04:03"}


def test_따옴표와_공백을_허용한다(tmp_path):
    p = tmp_path / "a.md"
    p.write_text('---\nmessage_key:   42  \ncontent_hash: "해시값"\n---\n본문\n', encoding="utf-8")
    got = read_front_matter(p)
    assert got["message_key"] == 42
    assert got["content_hash"] == "해시값"


def test_숫자가_아닌_키는_무시(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("---\nmessage_key: 안녕\ncontent_hash: h\n---\n", encoding="utf-8")
    assert read_front_matter(p) == {"content_hash": "h"}


def test_머리말이_없으면_빈_dict(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("# 제목\nmessage_key: 3\n", encoding="utf-8")
    assert read_front_matter(p) == {}


def test_없는_파일은_빈_dict(tmp_path):
    assert read_front_matter(tmp_path / "없음.md") == {}


# ---------------------------------------------------------------- 재시작

def test_닫았다_열어도_이력이_남는다(tmp_path):
    p = tmp_path / "s.db"
    with StateDB(p) as db:
        db.record(1, "h", "/x/1.md")
    for _ in range(10):                       # 10번 재시작해도
        with StateDB(p) as db:
            assert db.seen(1)
    assert StateDB(p).stats()["notes"] == 1


def test_상위_폴더가_없으면_만든다(tmp_path):
    db = StateDB(tmp_path / "깊은" / "경로" / "s.db")
    db.record(1, "h", "/x")
    assert (tmp_path / "깊은" / "경로" / "s.db").exists()
    db.close()
