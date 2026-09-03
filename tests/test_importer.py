"""쪽지 1건 처리와 중복 판정 (#13). PRD 6.4 액티비티 다이어그램."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from src.config import Config
from src.sources.coolm import Attachment, Message
from src.state import StateDB
from src.writer.importer import FAILED, SAVED, SKIPPED, Importer
from src.writer.inbox import InboxError


class FakeFinder:
    """이름 → 실제 경로. 없는 이름은 못 찾은 것."""

    def __init__(self, mapping=None):
        self.mapping = mapping or {}

    def find(self, message):
        return [(a, self.mapping.get(a.name)) for a in message.attachments]


def msg(**kw) -> Message:
    base = dict(key=1234, received=datetime(2026, 9, 2, 17, 4, 52), sender="홍길동(hong)",
                title="협의회", body="내일 3시")
    return Message(**{**base, **kw})


def msgs(*keys) -> list[Message]:
    """키마다 내용이 다른 쪽지들 — 내용이 같으면 해시 판정으로 중복 처리되기 때문이다."""
    return [msg(key=k, body=f"본문 {k}") for k in keys]


@pytest.fixture
def imp(tmp_path):
    c = Config()
    c.inbox.root_dir = str(tmp_path / "Inbox")
    state = StateDB(tmp_path / "state.db")
    yield Importer(c, state)
    state.close()


# ---------------------------------------------------------------- 기본 흐름

def test_저장(imp):
    r = imp.import_one(msg())
    assert r.status == SAVED
    assert r.md_path.name == "2026-09-02_1704_홍길동_협의회_#1234.md"
    assert "내일 3시" in r.md_path.read_text(encoding="utf-8")


def test_이력에_기록된다(imp):
    imp.import_one(msg())
    assert imp.state.seen(1234)
    assert imp.state.get(1234).md_path.endswith(".md")


def test_내용이_없으면_건너뛴다(imp):
    r = imp.import_one(msg(title="", body=""))
    assert r.status == SKIPPED
    assert "내용이 없는" in r.reason
    assert not imp.state.seen(1234)          # 이력에 남기지 않는다


# ---------------------------------------------------------------- 중복 (수용 기준 2)

def test_같은_쪽지를_열_번_넣어도_파일은_하나(imp):
    for _ in range(10):
        imp.import_one(msg())
    assert len(list(imp.writer.coolm_dir().glob("*.md"))) == 1
    assert imp.state.stats()["notes"] == 1


def test_키가_달라도_내용이_같으면_건너뛴다(imp):
    """udb 가 재생성돼 키가 초기화된 경우."""
    imp.import_one(msg())
    r = imp.import_one(msg(key=1))
    assert r.status == SKIPPED
    assert "이미 가져온" in r.reason


def test_사용자가_md를_지워도_다시_만들지_않는다(imp):
    """FR-4.5 — 이력이 남아 있으므로 되살리지 않는다."""
    r = imp.import_one(msg())
    r.md_path.unlink()
    assert imp.import_one(msg()).status == SKIPPED


# ---------------------------------------------------------------- 실패 처리

def test_저장에_실패하면_이력에_남지_않는다(imp, monkeypatch):
    monkeypatch.setattr(imp.writer, "write_note",
                        lambda *a, **k: (_ for _ in ()).throw(InboxError("디스크 공간이 부족합니다.")))
    r = imp.import_one(msg())
    assert r.status == FAILED
    assert "디스크" in r.reason
    assert not imp.state.seen(1234)          # 다음 폴링에서 재시도된다


def test_한_건이_실패해도_나머지는_계속(imp, monkeypatch):
    calls = []
    real = imp.writer.write_note

    def flaky(filename, text, **k):
        calls.append(filename)
        if len(calls) == 2:
            raise InboxError("일시적 실패")
        return real(filename, text, **k)

    monkeypatch.setattr(imp.writer, "write_note", flaky)
    s = imp.import_many(msgs(1, 2, 3))
    assert (s.saved, s.failed) == (2, 1)


# ---------------------------------------------------------------- 첨부

def test_첨부_복사(tmp_path, imp):
    src = tmp_path / "자료.hwp"
    src.write_bytes(b"x" * 500)
    imp.finder = FakeFinder({"자료.hwp": src})
    r = imp.import_one(msg(attachments=[Attachment("자료.hwp", 500)]))
    assert (r.attach_total, r.attach_ok) == (1, 1)
    copied = imp.writer.attach_dir() / "2026-09-02_1704_홍길동_#1234" / "자료.hwp"
    assert copied.read_bytes() == b"x" * 500
    assert "첨부파일/2026-09-02_1704_홍길동_#1234/자료.hwp" in r.md_path.read_text(encoding="utf-8")


def test_원본을_못_찾아도_저장은_성공한다(imp):
    r = imp.import_one(msg(attachments=[Attachment("사라진.hwp", 100)]))
    assert r.status == SAVED
    assert (r.attach_total, r.attach_ok) == (1, 0)
    text = r.md_path.read_text(encoding="utf-8")
    assert "사라진.hwp" in text and "찾지 못했습니다" in text


def test_첨부_미완료는_재시도_대상으로_남는다(imp):
    imp.import_one(msg(attachments=[Attachment("a.hwp", 1), Attachment("b.hwp", 1)]))
    pending = imp.state.pending_attachments()
    assert [p.message_key for p in pending] == [1234]


def test_용량_제한을_넘으면_건너뛴다(tmp_path, imp):
    src = tmp_path / "큰파일.zip"
    src.write_bytes(b"x")
    imp.config.inbox.max_attach_mb = 1
    imp.finder = FakeFinder({"큰파일.zip": src})
    r = imp.import_one(msg(attachments=[Attachment("큰파일.zip", 5 * 1024 * 1024)]))
    assert r.attach_ok == 0
    assert "용량 제한" in r.md_path.read_text(encoding="utf-8")


def test_용량_제한_0은_무제한(tmp_path, imp):
    src = tmp_path / "큰파일.zip"
    src.write_bytes(b"x")
    imp.config.inbox.max_attach_mb = 0
    imp.finder = FakeFinder({"큰파일.zip": src})
    r = imp.import_one(msg(attachments=[Attachment("큰파일.zip", 999 * 1024 * 1024)]))
    assert r.attach_ok == 1


def test_첨부_복사_실패는_쪽지_저장_실패가_아니다(tmp_path, imp, monkeypatch):
    src = tmp_path / "a.hwp"
    src.write_bytes(b"x")
    imp.finder = FakeFinder({"a.hwp": src})
    monkeypatch.setattr(imp.writer, "copy_attachment",
                        lambda *a: (_ for _ in ()).throw(InboxError("파일이 잠겨 있습니다")))
    r = imp.import_one(msg(attachments=[Attachment("a.hwp", 1)]))
    assert r.status == SAVED
    assert "잠겨 있습니다" in r.md_path.read_text(encoding="utf-8")


def test_같은_이름_첨부는_번호를_붙인다(tmp_path, imp):
    a, b = tmp_path / "1" / "같은이름.hwp", tmp_path / "2" / "같은이름.hwp"
    for p, data in ((a, b"aaa"), (b, b"bbb")):
        p.parent.mkdir()
        p.write_bytes(data)

    class TwoFinder:
        def find(self, message):
            return [(message.attachments[0], a), (message.attachments[1], b)]

    imp.finder = TwoFinder()
    r = imp.import_one(msg(attachments=[Attachment("같은이름.hwp", 3), Attachment("같은이름.hwp", 3)]))
    names = sorted(p.name for p in (imp.writer.attach_dir() / "2026-09-02_1704_홍길동_#1234").iterdir())
    assert names == ["같은이름 (2).hwp", "같은이름.hwp"]
    assert r.attach_ok == 2


# ---------------------------------------------------------------- 여러 건

def test_요약(imp):
    a, b = msgs(1, 2)
    s = imp.import_many([a, b, a, msg(key=3, title="", body="")])
    assert (s.saved, s.skipped, s.failed) == (2, 2, 0)
    assert s.saved_keys == [1, 2]
    assert "저장 2" in s.describe()


def test_진행률_콜백(imp):
    seen = []
    imp.import_many(msgs(1, 2), on_progress=lambda i, n, r: seen.append((i, n)))
    assert seen == [(1, 2), (2, 2)]


def test_취소하면_거기서_멈춘다(imp):
    state = {"n": 0}

    def cancel():
        state["n"] += 1
        return state["n"] > 2

    s = imp.import_many(msgs(*range(1, 10)), should_cancel=cancel)
    assert s.saved == 2                       # 취소 전까지 저장분은 유지
    assert imp.state.stats()["notes"] == 2


# ---------------------------------------------------------------- 파일명 서식

def test_키가_없는_서식은_이름_충돌을_피한다(imp):
    imp.config.output.filename_format = "{date}_{sender}"
    imp.import_one(msg(key=1))
    imp.import_one(msg(key=2, body="다른 내용"))
    # 두 쪽지는 내용이 달라 각각 저장되고, 이름이 같으므로 (2) 가 붙는다
    names = sorted(p.name for p in imp.writer.coolm_dir().glob("*.md"))
    assert names == ["2026-09-02_홍길동 (2).md", "2026-09-02_홍길동.md"]


def test_내용까지_같은_두_쪽지는_한_번만_저장된다(imp):
    """키가 달라도 sender·시각·제목·본문이 같으면 같은 쪽지로 본다 (FR-4.2)."""
    s = imp.import_many([msg(key=1), msg(key=2)])
    assert (s.saved, s.skipped) == (1, 1)
