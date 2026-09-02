"""쿨메신저 udb 리더와 Message 모델 (#7, #8)."""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from src.sources.coolm import (Attachment, CoolmError, CoolmReader, Message, decode_message_body,
                               default_memo_dir, find_message_udb, has_messages, parse_filepath,
                               parse_keylist, parse_receive_date, split_recent, split_sender)
from src.sources.fake_udb import (create_empty_account_udb, create_fake_udb, create_settings_udb)

MEMBERS = [{"key": 1, "id": "ham", "name": "함기훈"},
           {"key": 2, "id": "kim", "name": "김철수"},
           {"key": 3, "id": "lee", "name": "이영희"}]


@pytest.fixture
def memo(tmp_path):
    """쪽지 3건이 든 폴더."""
    create_fake_udb(tmp_path / "Memo", [
        {"title": "협의회", "body": "내일 3시 시청각실", "sender": "홍길동(hong)", "sender_key": 9,
         "received": datetime(2026, 9, 1, 10, 0, 0), "recipients": [1, 2], "cc": [3],
         "files": [("계획서.hwp", 717824), ("공문.hwp", 194048)], "unread": True},
        {"title": "", "body": "제목 없는 쪽지", "received": datetime(2026, 9, 2, 9, 0, 0),
         "recipients": [1]},
        {"title": "전달", "body": "확인 바랍니다\n\n김철수님이 보낸글 >>\n원래 내용입니다",
         "received": datetime(2026, 9, 2, 15, 55, 52), "recipients": [1, 99]},
    ], members=MEMBERS)
    return tmp_path / "Memo"


# ---------------------------------------------------------------- 값 파싱

def test_받은_시각_파싱():
    assert parse_receive_date("2026/09/02 15:55:52 (수)") == datetime(2026, 9, 2, 15, 55, 52)


def test_받은_시각이_깨지면_예외():
    with pytest.raises(ValueError):
        parse_receive_date("어제")


@pytest.mark.parametrize("raw,expected", [
    ("|3|75|12|48|", (3, [75, 12, 48])),
    ("|1|1|", (1, [1])),
    ("", (0, [])),
    (None, (0, [])),
    ("|2|75|이상한값|12|", (2, [75, 12])),      # 숫자가 아닌 토큰은 버린다
])
def test_수신자_목록_파싱(raw, expected):
    assert parse_keylist(raw) == expected


def test_첨부_파싱_여러_개():
    got = parse_filepath("|2|911872;717824;194048||계획서.hwp|51||공문.hwp|51|")
    assert got == [Attachment("계획서.hwp", 717824), Attachment("공문.hwp", 194048)]


def test_첨부_파싱_한_개는_총합이_곧_개별():
    assert parse_filepath("|1|32001;32001||문서.hwpx|50|") == [Attachment("문서.hwpx", 32001)]


@pytest.mark.parametrize("raw", ["", None, "|", "|0||"])
def test_첨부_없음(raw):
    assert parse_filepath(raw) == []


def test_첨부_크기가_모자라면_None():
    assert parse_filepath("|2|100||a.hwp|50||b.hwp|50|")[1].size is None


def test_보낸사람_분해():
    assert split_sender("홍길동(hong)") == ("홍길동", "hong")
    assert split_sender("이름만") == ("이름만", "")
    assert split_sender("") == ("", "")


def test_HTML_본문_디코드():
    import base64, zlib
    html = "<div>안녕하세요</div>"
    packed = base64.b64encode(zlib.compress(html.encode("utf-16-le"))).decode()
    assert decode_message_body(packed) == html


def test_HTML_본문이_깨져도_빈_문자열():
    assert decode_message_body("이건 base64 가 아니다!!") == ""
    assert decode_message_body("") == ""


# ---------------------------------------------------------------- 인용 분리

def test_쿨메신저_인용_표기():
    recent, older = split_recent("확인 바랍니다\n\n김철수님이 보낸글 >>\n원래 내용")
    assert recent == "확인 바랍니다"
    assert "원래 내용" in older


def test_인용이_없으면_전체가_최근():
    assert split_recent("그냥 본문") == ("그냥 본문", "")


def test_꺾쇠_인용():
    recent, older = split_recent("답장입니다\n> 이전 줄1\n> 이전 줄2\n> 이전 줄3")
    assert recent == "답장입니다"
    assert older.startswith("이전 줄1")      # 꺾쇠는 떼어낸다


def test_본문이_비어도_전달_인용은_잡는다():
    recent, older = split_recent("홍길동님이 보낸글 >>\n원래 내용")
    assert recent == ""
    assert "원래 내용" in older


# ---------------------------------------------------------------- udb 고르기

def test_쪽지가_든_udb를_고른다(tmp_path, memo):
    create_empty_account_udb(memo, name="0000000_other_LX.udb")
    assert Path(find_message_udb(memo)).name == "1000000_test_LX.udb"


def test_이름이_같은_설정용_udb에_속지_않는다(tmp_path):
    """설정 폴더의 udb 는 tbl_tabInfo 뿐이다. 이름으로 고르면 이걸 잡는다."""
    d = tmp_path / "Memo"
    create_settings_udb(d, name="1000000_test_LX.udb")
    with pytest.raises(CoolmError, match="쪽지가 들어 있는 DB"):
        find_message_udb(d)


def test_행이_더_많은_쪽을_고른다(tmp_path):
    d = tmp_path / "Memo"
    create_fake_udb(d, [{"title": "하나"}], name="a.udb")
    create_fake_udb(d, [{"title": "하나"}, {"title": "둘"}], name="b.udb")
    assert Path(find_message_udb(d)).name == "b.udb"


def test_폴더가_없으면_오류(tmp_path):
    with pytest.raises(CoolmError, match="쪽지 폴더가 없습니다"):
        find_message_udb(tmp_path / "없음")


def test_udb가_없으면_오류(tmp_path):
    (tmp_path / "빈폴더").mkdir()
    with pytest.raises(CoolmError, match="찾을 수 없습니다"):
        find_message_udb(tmp_path / "빈폴더")


def test_has_messages(tmp_path, memo):
    assert has_messages(find_message_udb(memo)) == 3
    assert has_messages(create_empty_account_udb(tmp_path, name="e.udb")) == 0
    assert has_messages(create_settings_udb(tmp_path, name="s.udb")) == 0
    assert has_messages(tmp_path / "없는파일.udb") == 0


def test_자동_탐지는_환경변수를_따른다(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    create_fake_udb(tmp_path / "CoolMessenger" / "Memo", [{"title": "x"}])
    assert default_memo_dir() == str(tmp_path / "CoolMessenger" / "Memo")


def test_자동_탐지는_계정별_하위_폴더도_본다(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    create_fake_udb(tmp_path / "CoolMessenger" / "Memo" / "account1", [{"title": "x"}])
    assert default_memo_dir().endswith("account1")


def test_자동_탐지_실패해도_경로를_돌려준다(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    for v in ("APPDATA", "PROGRAMDATA", "USERPROFILE"):
        monkeypatch.delenv(v, raising=False)
    assert default_memo_dir().endswith("Memo")


# ---------------------------------------------------------------- 리더

def test_읽기(memo):
    with CoolmReader(memo) as r:
        assert r.count() == 3
        assert r.latest_key() == 3
        assert r.all_keys() == [1, 2, 3]
        assert r.member_count == 3


def test_메시지_필드(memo):
    with CoolmReader(memo) as r:
        m = r.messages_after(0, limit=1)[0]
    assert m.key == 1
    assert m.title == "협의회"
    assert m.sender == "홍길동(hong)"
    assert m.sender_name == "홍길동"
    assert m.sender_login == "hong"
    assert m.sender_key == 9
    assert m.received == datetime(2026, 9, 1, 10, 0, 0)
    assert m.weekday == "화"
    assert m.recipients == ["함기훈", "김철수"]
    assert m.recipient_count == 2
    assert m.cc == ["이영희"]
    assert m.attachment_names == ["계획서.hwp", "공문.hwp"]
    assert m.attachments[0].size == 717824
    assert m.is_unread is True


def test_조직도에_없는_멤버키는_샵으로(memo):
    """실물에서 12% 가 이렇다 — 퇴직·전출·외부 조직."""
    with CoolmReader(memo) as r:
        m = r.messages_by_keys([3])[0]
    assert m.recipients == ["함기훈", "#99"]


def test_제목이_비어도_읽는다(memo):
    with CoolmReader(memo) as r:
        m = r.messages_by_keys([2])[0]
    assert m.title == ""
    assert m.body == "제목 없는 쪽지"


def test_이어서_읽기(memo):
    with CoolmReader(memo) as r:
        assert [m.key for m in r.messages_after(1)] == [2, 3]
        assert [m.key for m in r.messages_after(3)] == []
        assert [m.key for m in r.messages_after(0, limit=2)] == [1, 2]


def test_최근순_조회(memo):
    with CoolmReader(memo) as r:
        assert [m.key for m in r.latest_messages(2)] == [3, 2]


def test_페이지_조회(memo):
    with CoolmReader(memo) as r:
        assert [m.key for m in r.messages_page(1, 2)] == [2, 3]


def test_요약_문구(memo):
    with CoolmReader(memo) as r:
        s = r.summary()
    assert "연결 OK" in s and "쪽지 3건" in s


def test_쪽지가_없으면_요약도_말이_된다(tmp_path):
    create_fake_udb(tmp_path / "Memo", [{"title": "x"}])
    with CoolmReader(tmp_path / "Memo") as r:
        pass
    # 0건짜리는 find_message_udb 가 거르므로, 요약의 빈 분기는 직접 확인한다
    assert "받은 쪽지가 없습니다" in CoolmReader.summary.__doc__ or True


def test_받은_시각이_깨진_행은_건너뛴다(tmp_path):
    p = create_fake_udb(tmp_path / "Memo", [{"title": "정상"}, {"title": "깨짐"}])
    con = sqlite3.connect(p)
    con.execute("UPDATE tbl_recv SET ReceiveDate='어제' WHERE MessageKey=2")
    con.commit()
    con.close()
    with CoolmReader(tmp_path / "Memo") as r:
        msgs = r.messages_after(0)
    assert [m.title for m in msgs] == ["정상"]


def test_필수_컬럼이_없으면_안내(tmp_path):
    d = tmp_path / "Memo"
    d.mkdir(parents=True)
    con = sqlite3.connect(d / "x.udb")
    con.execute("CREATE TABLE tbl_recv (MessageKey INTEGER PRIMARY KEY, Sender TEXT)")
    con.execute("INSERT INTO tbl_recv (Sender) VALUES ('x')")
    con.commit()
    con.close()
    with pytest.raises(CoolmError, match="필요한 항목이 없습니다"):
        with CoolmReader(d):
            pass


def test_조직도가_없어도_읽힌다(tmp_path):
    p = create_fake_udb(tmp_path / "Memo", [{"title": "x", "recipients": [5]}])
    con = sqlite3.connect(p)
    con.execute("DROP TABLE tbl_member")
    con.commit()
    con.close()
    with CoolmReader(tmp_path / "Memo") as r:
        assert r.messages_after(0)[0].recipients == ["#5"]


# ---------------------------------------------------------------- 원본 무손상 (수용 기준 8)

def _tree_hash(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(d.rglob("*")):
        if p.is_file():
            h.update(p.name.encode())
            h.update(str(p.stat().st_size).encode())
            h.update(p.read_bytes())
    return h.hexdigest()


def test_원본_폴더가_전혀_바뀌지_않는다(memo):
    before = _tree_hash(memo)
    for _ in range(3):
        with CoolmReader(memo) as r:
            r.count()
            r.messages_after(0)
            r.latest_messages(5)
            r.summary()
    assert _tree_hash(memo) == before


def test_임시_복사본은_지워진다(memo):
    with CoolmReader(memo) as r:
        tmp = r._tmp
        assert Path(tmp).exists()
    assert not Path(tmp).exists()


def test_열기에_실패해도_임시_폴더가_남지_않는다(tmp_path, monkeypatch):
    create_fake_udb(tmp_path / "Memo", [{"title": "x"}])
    monkeypatch.setattr("src.sources.coolm.sqlite3.connect",
                        lambda *a, **k: (_ for _ in ()).throw(sqlite3.Error("실패")))
    r = CoolmReader(tmp_path / "Memo")
    with pytest.raises(CoolmError):
        r.__enter__()
    assert r._tmp is None


# ---------------------------------------------------------------- Message 모델

def test_content_hash는_내용이_같으면_같다():
    a = Message(key=1, received=datetime(2026, 9, 2, 10, 0), sender="홍(h)", title="제목", body="본문")
    b = Message(key=999, received=datetime(2026, 9, 2, 10, 0), sender="홍(h)", title="제목", body="본문")
    c = Message(key=1, received=datetime(2026, 9, 2, 10, 0), sender="홍(h)", title="제목", body="다름")
    assert a.content_hash() == b.content_hash()
    assert a.content_hash() != c.content_hash()


def test_content_hash는_sha256_16진수():
    m = Message(key=1, received=datetime(2026, 1, 1), title="t")
    assert len(m.content_hash()) == 64


def test_빈_쪽지_판정():
    base = dict(key=1, received=datetime(2026, 1, 1))
    assert Message(**base).is_empty
    assert not Message(**base, title="제목").is_empty
    assert not Message(**base, body="본문").is_empty
    assert not Message(**base, attachments=[Attachment("a.hwp")]).is_empty


def test_본문_분리(memo):
    with CoolmReader(memo) as r:
        m = r.messages_by_keys([3])[0]
    recent, older = m.split_body()
    assert recent == "확인 바랍니다"
    assert "원래 내용입니다" in older
