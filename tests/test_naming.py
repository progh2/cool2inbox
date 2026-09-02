"""파일명 규칙과 Windows 안전 정규화 (#10)."""
from __future__ import annotations

from datetime import datetime

import pytest

from src.sources.coolm import Message
from src.writer.naming import (DEFAULT_FORMAT, MAX_PATH, attachment_dirname, attachment_filename,
                               avoid_reserved, format_is_unique, note_filename, sanitize,
                               title_for, unique_path)


def msg(**kw) -> Message:
    base = dict(key=1234, received=datetime(2026, 9, 2, 17, 4), sender="홍길동(hong)",
                title="2학기 교육과정 협의회", body="본문")
    return Message(**{**base, **kw})


# ---------------------------------------------------------------- 기본

def test_PRD_예시_그대로():
    assert note_filename(msg()) == "2026-09-02_1704_홍길동_2학기_교육과정_협의회_#1234.md"


def test_첨부_폴더명():
    assert attachment_dirname(msg()) == "2026-09-02_1704_홍길동_#1234"


def test_보낸사람은_괄호_없이():
    assert "hong" not in note_filename(msg())


# ---------------------------------------------------------------- 제목 폴백 (FR-3.4)

def test_제목이_없으면_본문_첫_줄():
    assert title_for(msg(title="", body="\n\n첫 줄입니다\n둘째 줄")) == "첫 줄입니다"


def test_본문_첫_줄은_30자까지():
    assert len(title_for(msg(title="", body="가" * 100))) == 30


def test_제목도_본문도_없으면_무제():
    assert title_for(msg(title="", body="")) == "무제"
    assert note_filename(msg(title="", body="")).endswith("_무제_#1234.md")


def test_공백뿐인_제목도_없는_것으로():
    assert title_for(msg(title="   ", body="본문")) == "본문"


# ---------------------------------------------------------------- 정규화 (FR-3.5)

@pytest.mark.parametrize("bad", list('\\/:*?"<>|'))
def test_금지문자는_밑줄로(bad):
    got = note_filename(msg(title=f"제목{bad}뒤"))
    assert bad not in got
    assert "제목_뒤" in got


def test_제어문자와_개행도_제거():
    got = note_filename(msg(title="제목\n둘째\t줄\x00"))
    assert "\n" not in got and "\t" not in got and "\x00" not in got


def test_연속_공백과_밑줄은_하나로():
    assert sanitize("가   나___다") == "가_나_다"


def test_앞뒤_공백과_마침표_제거():
    assert sanitize("  .제목.  ") == "제목"


def test_전부_금지문자면_대체값():
    assert sanitize("///", fallback="무제") == "무제"


@pytest.mark.parametrize("name", ["CON", "con", "PRN", "AUX", "NUL", "COM1", "LPT9"])
def test_예약어_회피(name):
    assert avoid_reserved(name) == name + "_"


def test_예약어가_아니면_그대로():
    assert avoid_reserved("COM10") == "COM10"
    assert avoid_reserved("협의회") == "협의회"


def test_예약어_제목도_안전하다():
    got = note_filename(msg(title="CON", key=1, ), fmt="{title}")
    assert got == "CON_.md"


def test_이모지와_한자도_통과():
    got = note_filename(msg(title="회의 📅 漢字"))
    assert "📅" in got and "漢字" in got


# ---------------------------------------------------------------- 길이 제한 (FR-3.5)

def test_긴_제목은_제목부터_줄인다(tmp_path):
    got = note_filename(msg(title="가" * 300), base_dir=tmp_path)
    assert len(str(tmp_path / got)) <= MAX_PATH
    assert got.startswith("2026-09-02_1704_홍길동_")
    assert got.endswith("_#1234.md")          # 식별에 필요한 부분은 남는다


def test_경로가_깊어도_상한을_지킨다(tmp_path):
    deep = tmp_path / ("가" * 60) / ("나" * 60)
    got = note_filename(msg(title="다" * 200), base_dir=deep)
    assert len(str(deep / got)) <= MAX_PATH


def test_base_dir이_없으면_자르지_않는다():
    assert len(note_filename(msg(title="가" * 300))) > MAX_PATH


# ---------------------------------------------------------------- 서식

def test_서식_토큰():
    assert note_filename(msg(), fmt="{date}_{sender}") == "2026-09-02_홍길동.md"
    assert note_filename(msg(), fmt="{title}") == "2학기_교육과정_협의회.md"
    assert note_filename(msg(), fmt="#{key}") == "#1234.md"


def test_키가_있으면_이름이_겹치지_않는다():
    assert format_is_unique(DEFAULT_FORMAT)
    assert not format_is_unique("{date}_{sender}")


def test_모르는_토큰은_그대로_둔다():
    assert note_filename(msg(), fmt="{date}_{없는토큰}") == "2026-09-02_{없는토큰}.md"


# ---------------------------------------------------------------- 이름 충돌

def test_같은_이름이_있으면_번호를_붙인다(tmp_path):
    (tmp_path / "a.md").touch()
    assert unique_path(tmp_path, "a.md").name == "a (2).md"
    (tmp_path / "a (2).md").touch()
    assert unique_path(tmp_path, "a.md").name == "a (3).md"


def test_없으면_그대로(tmp_path):
    assert unique_path(tmp_path, "a.md") == tmp_path / "a.md"


# ---------------------------------------------------------------- 첨부 파일명

def test_첨부_파일명_정규화():
    assert attachment_filename("보고서: 최종본*.hwp") == "보고서_최종본.hwp"
    assert attachment_filename("CON.txt") == "CON_.txt"


def test_첨부_확장자는_지킨다():
    assert attachment_filename("가" * 300 + ".hwpx").endswith(".hwpx")


def test_이름이_비어도_대체값():
    assert attachment_filename("") == "첨부파일"
