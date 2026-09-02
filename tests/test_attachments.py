"""수신 파일 폴더 탐지와 첨부 매칭 (#15, #16)."""
from __future__ import annotations

import os
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.sources.attachments import AttachmentFinder, default_recv_dir, norm
from src.sources.coolm import Attachment, Message

WHEN = datetime(2026, 9, 2, 17, 0, 0)


def msg(*attachments, received=WHEN) -> Message:
    return Message(key=1, received=received, sender="홍길동(hong)", title="제목",
                   attachments=list(attachments))


@pytest.fixture
def recv(tmp_path):
    d = tmp_path / "Received Files"
    d.mkdir()
    return d


def put(d: Path, name: str, data: bytes = b"x", when: datetime | None = None) -> Path:
    p = d / name
    p.write_bytes(data)
    if when:
        ts = when.timestamp()
        os.utime(p, (ts, ts))
    return p


# ---------------------------------------------------------------- 폴더 탐지 (#15)

def test_자동_탐지(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    target = tmp_path / "Documents" / "CoolMessenger Files" / "Received Files"
    target.mkdir(parents=True)
    assert default_recv_dir() == str(target)


def test_없으면_빈_문자열(tmp_path, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    assert default_recv_dir() == ""


def test_요약_문구(recv):
    put(recv, "a.hwp", when=datetime(2026, 9, 1, 12, 0))
    assert "연결 OK" in AttachmentFinder(recv).summary()
    assert "파일 1개" in AttachmentFinder(recv).summary()


def test_폴더가_없으면_요약이_이유를_말한다(tmp_path):
    assert "없습니다" in AttachmentFinder(tmp_path / "없음").summary()


def test_지정하지_않았으면_안내(tmp_path):
    assert "지정되지 않았습니다" in AttachmentFinder(None).summary()
    assert "지정되지 않았습니다" in AttachmentFinder("   ").summary()


def test_파일이_없으면_그렇게_말한다(recv):
    assert "파일이 없습니다" in AttachmentFinder(recv).summary()


# ---------------------------------------------------------------- 매칭 (#16)

def test_이름과_크기가_맞으면_찾는다(recv):
    p = put(recv, "계획서.hwp", b"x" * 500)
    got = AttachmentFinder(recv).find(msg(Attachment("계획서.hwp", 500)))
    assert got == [(Attachment("계획서.hwp", 500), p)]


def test_이름이_없으면_None(recv):
    put(recv, "다른파일.hwp")
    got = AttachmentFinder(recv).find(msg(Attachment("계획서.hwp", 500)))
    assert got[0][1] is None


def test_크기가_다르면_이름만_일치로_처리한다(recv):
    """이름은 맞는데 크기가 다르다 — 같은 이름의 다른 파일일 수 있으므로 시각으로 판단한다."""
    p = put(recv, "계획서.hwp", b"x" * 10, when=WHEN)
    got = AttachmentFinder(recv, match_minutes=30).find(msg(Attachment("계획서.hwp", 500)))
    assert got[0][1] == p


def test_이름만_맞고_시각이_멀면_거른다(recv):
    put(recv, "계획서.hwp", b"x" * 10, when=WHEN - timedelta(days=200))
    got = AttachmentFinder(recv, match_minutes=30).find(msg(Attachment("계획서.hwp", 500)))
    assert got[0][1] is None


def test_시각_제한_0이면_거르지_않는다(recv):
    p = put(recv, "계획서.hwp", b"x" * 10, when=WHEN - timedelta(days=200))
    got = AttachmentFinder(recv, match_minutes=0).find(msg(Attachment("계획서.hwp", 500)))
    assert got[0][1] == p


def test_크기가_맞으면_시각이_멀어도_찾는다(recv):
    """크기까지 같으면 같은 파일로 본다 — 실물 대조에서 이 조합이 정확했다."""
    p = put(recv, "계획서.hwp", b"x" * 500, when=WHEN - timedelta(days=500))
    got = AttachmentFinder(recv, match_minutes=30).find(msg(Attachment("계획서.hwp", 500)))
    assert got[0][1] == p


def test_이름이_같은_후보_중_크기가_맞는_것을_고른다(recv, tmp_path):
    """평평한 폴더라 같은 이름은 하나뿐이지만, 대소문자 차이로 둘이 될 수 있다."""
    put(recv, "계획서.hwp", b"x" * 10, when=WHEN)
    p2 = put(recv, "계획서.HWP", b"x" * 500, when=WHEN - timedelta(days=1))
    got = AttachmentFinder(recv).find(msg(Attachment("계획서.hwp", 500)))
    assert got[0][1] == p2


def test_한_파일이_두_첨부에_동시에_쓰이지_않는다(recv):
    p = put(recv, "같은이름.hwp", b"x" * 500, when=WHEN)
    got = AttachmentFinder(recv).find(msg(Attachment("같은이름.hwp", 500),
                                          Attachment("같은이름.hwp", 500)))
    assert got[0][1] == p
    assert got[1][1] is None


def test_유니코드_정규화_차이를_넘는다(recv):
    """macOS/Linux 를 거치면 한글 파일명이 NFD 로 분해된다."""
    nfd = unicodedata.normalize("NFD", "한글파일.hwp")
    p = put(recv, nfd, b"x" * 100)
    got = AttachmentFinder(recv).find(msg(Attachment("한글파일.hwp", 100)))
    assert got[0][1] == p


def test_norm은_NFC로_모은다():
    assert norm(unicodedata.normalize("NFD", "한글")) == "한글"


def test_첨부가_없으면_빈_목록(recv):
    assert AttachmentFinder(recv).find(msg()) == []


def test_폴더가_없어도_예외가_없다(tmp_path):
    got = AttachmentFinder(tmp_path / "없는폴더").find(msg(Attachment("a.hwp", 1)))
    assert got[0][1] is None


def test_폴더_미지정도_예외가_없다():
    assert AttachmentFinder(None).find(msg(Attachment("a.hwp", 1)))[0][1] is None


# ---------------------------------------------------------------- 색인

def test_색인은_폴더가_그대로면_다시_훑지_않는다(recv, monkeypatch):
    put(recv, "a.hwp")
    f = AttachmentFinder(recv)
    assert f.refresh() == 1
    calls = []
    real = Path.iterdir
    monkeypatch.setattr(Path, "iterdir", lambda self: (calls.append(1), real(self))[1])
    f.refresh()
    assert calls == []


def test_파일이_늘면_색인도_따라간다(recv):
    f = AttachmentFinder(recv)
    assert f.refresh() == 0
    put(recv, "새파일.hwp")
    assert f.refresh(force=True) == 1


def test_하위_폴더는_무시한다(recv):
    """실물은 평평하다 — 하위 폴더를 뒤지면 엉뚱한 파일을 잡는다."""
    (recv / "하위").mkdir()
    put(recv / "하위", "숨은파일.hwp")
    assert AttachmentFinder(recv).refresh() == 0


# ---------------------------------------------------------------- Importer 연동

def test_설정에_폴더가_있으면_실제_탐색기를_쓴다(tmp_path):
    from src.config import Config
    from src.state import StateDB
    from src.writer.importer import Importer, NullAttachmentFinder

    c = Config()
    c.inbox.root_dir = str(tmp_path)
    state = StateDB(tmp_path / "s.db")
    assert isinstance(Importer(c, state).finder, NullAttachmentFinder)

    c.coolm.recv_file_dir = str(tmp_path)
    assert isinstance(Importer(c, state).finder, AttachmentFinder)
    state.close()


def test_설정이_바뀌면_탐색기도_바뀐다(tmp_path):
    from src.config import Config
    from src.state import StateDB
    from src.writer.importer import Importer, NullAttachmentFinder

    c = Config()
    c.inbox.root_dir = str(tmp_path)
    state = StateDB(tmp_path / "s.db")
    imp = Importer(c, state)
    assert isinstance(imp.finder, NullAttachmentFinder)
    c.coolm.recv_file_dir = str(tmp_path)
    imp.apply_config(c)
    assert isinstance(imp.finder, AttachmentFinder)
    state.close()
