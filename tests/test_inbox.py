"""인박스 쓰기 (#12)."""
from __future__ import annotations

import os
import stat

import pytest

from src.config import InboxSettings
from src.writer.inbox import PART_SUFFIX, TMP_SUFFIX, InboxError, InboxWriter


@pytest.fixture
def writer(tmp_path):
    s = InboxSettings(root_dir=str(tmp_path / "Inbox"))
    return InboxWriter(s)


def test_경로_조립(writer, tmp_path):
    assert writer.coolm_dir() == tmp_path / "Inbox" / "쿨메신저"
    assert writer.attach_dir() == tmp_path / "Inbox" / "쿨메신저" / "첨부파일"


def test_폴더를_자동으로_만든다(writer):
    writer.ensure_dirs(attachments=True)
    assert writer.coolm_dir().is_dir()
    assert writer.attach_dir().is_dir()


def test_md_쓰기(writer):
    p = writer.write_note("a.md", "내용\n")
    assert p.read_text(encoding="utf-8") == "내용\n"
    assert p.name == "a.md"


def test_UTF8이고_BOM이_없다(writer):
    p = writer.write_note("a.md", "한글\n")
    raw = p.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw == "한글\n".encode("utf-8")


def test_개행은_LF로_저장된다(writer):
    p = writer.write_note("a.md", "첫 줄\n둘째 줄\n")
    assert b"\r\n" not in p.read_bytes()


def test_임시_파일을_남기지_않는다(writer):
    writer.write_note("a.md", "x")
    assert [p.name for p in writer.coolm_dir().iterdir()] == ["a.md"]


def test_쓰기가_실패하면_임시_파일도_치운다(writer, monkeypatch):
    writer.ensure_dirs()
    monkeypatch.setattr(os, "replace", lambda *a: (_ for _ in ()).throw(OSError(13, "권한 없음")))
    with pytest.raises(InboxError, match="권한이 없습니다"):
        writer.write_note("a.md", "x")
    assert list(writer.coolm_dir().iterdir()) == []


def test_디스크가_가득_차면_사람이_읽을_안내(writer, monkeypatch):
    import errno
    writer.ensure_dirs()
    monkeypatch.setattr(os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError(errno.ENOSPC, "no space")))
    with pytest.raises(InboxError, match="디스크 공간이 부족합니다"):
        writer.write_note("a.md", "x")


def test_첨부_복사(writer, tmp_path):
    src = tmp_path / "원본.hwp"
    src.write_bytes(b"\x00\x01" * 100)
    dest = writer.attach_dir() / "쪽지폴더"
    p = writer.copy_attachment(src, dest, "원본.hwp")
    assert p.read_bytes() == src.read_bytes()
    assert p.parent == dest


def test_첨부_복사는_원본을_건드리지_않는다(writer, tmp_path):
    src = tmp_path / "원본.hwp"
    src.write_bytes(b"data")
    before = (src.stat().st_size, src.read_bytes())
    writer.copy_attachment(src, writer.attach_dir() / "x", "원본.hwp")
    assert (src.stat().st_size, src.read_bytes()) == before
    assert src.exists()


def test_첨부_복사도_임시_파일을_남기지_않는다(writer, tmp_path):
    src = tmp_path / "a.bin"
    src.write_bytes(b"x")
    dest = writer.attach_dir() / "쪽지"
    writer.copy_attachment(src, dest, "a.bin")
    assert [p.name for p in dest.iterdir()] == ["a.bin"]


def test_없는_원본을_복사하면_오류(writer, tmp_path):
    with pytest.raises(InboxError):
        writer.copy_attachment(tmp_path / "없음.hwp", writer.attach_dir() / "x", "없음.hwp")


def test_남은_임시_파일_청소(writer):
    writer.ensure_dirs(attachments=True)
    (writer.coolm_dir() / f"죽다만것.md{TMP_SUFFIX}").write_text("x")
    (writer.attach_dir() / f"a.hwp{PART_SUFFIX}").write_text("x")
    (writer.coolm_dir() / "정상.md").write_text("x")
    assert writer.cleanup_temp() == 2
    assert (writer.coolm_dir() / "정상.md").exists()


def test_폴더를_못_만들면_안내(tmp_path):
    """읽기 전용 위치에 쓰려 하면 사람이 읽을 오류가 난다."""
    blocked = tmp_path / "잠김"
    blocked.mkdir()
    blocked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        w = InboxWriter(InboxSettings(root_dir=str(blocked / "Inbox")))
        with pytest.raises(InboxError):
            w.ensure_dirs()
    finally:
        blocked.chmod(stat.S_IRWXU)
