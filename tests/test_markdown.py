"""마크다운 렌더링 (#11, PRD 4.3)."""
from __future__ import annotations

from datetime import datetime

from src.sources.coolm import Attachment, Message
from src.state import read_front_matter
from src.writer.markdown import AttachmentLink, RenderOptions, render, yaml_scalar

WHEN = datetime(2026, 9, 2, 17, 4, 52)
IMPORTED = datetime(2026, 9, 2, 17, 10, 3)


def msg(**kw) -> Message:
    base = dict(key=1234, received=WHEN, sender="홍길동(hong)", title="2학기 교육과정 협의회",
                body="내일 오후 3시 시청각실입니다.")
    return Message(**{**base, **kw})


def head(text: str) -> dict:
    """머리말을 아주 단순하게 key -> 첫 값으로 읽는다 (테스트용)."""
    out, lines = {}, text.split("\n")
    assert lines[0] == "---"
    for line in lines[1:]:
        if line == "---":
            break
        if line.startswith("  - "):
            out.setdefault(_last_key[0] + "[]", []).append(line[4:].strip())
        elif ":" in line:
            k, _, v = line.partition(":")
            _last_key[0] = k.strip()
            out[k.strip()] = v.strip()
    return out


_last_key = [""]


# ---------------------------------------------------------------- 머리말

def test_기본_머리말():
    h = head(render(msg(), imported_at=IMPORTED))
    assert h["source"] == "coolmessenger"
    assert h["message_key"] == "1234"
    assert h["title"] == "2학기 교육과정 협의회"
    assert h["sender"] == "홍길동"
    assert h["sender_login"] == "hong"
    assert h["received"] == "2026-09-02 17:04:52"
    assert h["received_weekday"] == "수"
    assert h["imported_at"] == "2026-09-02 17:10:03"
    assert len(h["content_hash"]) == 64


def test_값이_없는_항목은_키_자체가_없다():
    h = head(render(msg(title="", sender="")))
    assert "title" not in h
    assert "sender" not in h
    assert "recipients" not in h
    assert "attachments" not in h
    assert "unread" not in h


def test_수신자와_참조():
    h = head(render(msg(recipients=["김철수", "이영희"], recipient_count=27, cc=["박지훈"])))
    assert h["recipients[]"] == ["김철수", "이영희"]
    assert h["recipient_count"] == "27"
    assert h["cc[]"] == ["박지훈"]


def test_읽지_않음_표시():
    assert head(render(msg(is_unread=True)))["unread"] == "true"


def test_상태DB가_머리말을_읽을_수_있다(tmp_path):
    """FR-4.3 이력 복구가 이 형식에 의존한다."""
    p = tmp_path / "a.md"
    p.write_text(render(msg(), imported_at=IMPORTED), encoding="utf-8")
    got = read_front_matter(p)
    assert got["message_key"] == 1234
    assert got["content_hash"] == msg().content_hash()
    assert got["imported_at"] == "2026-09-02 17:10:03"


# ---------------------------------------------------------------- YAML 안전성

def test_콜론이_든_제목은_따옴표로():
    h = head(render(msg(title="공지: 협의회")))
    assert h["title"] == '"공지: 협의회"'


def test_따옴표와_역슬래시_이스케이프():
    out = yaml_scalar('그는 "안녕" 이라고\\ 말했다')
    assert out.startswith('"') and '\\"안녕\\"' in out and "\\\\" in out


def test_개행은_공백으로():
    assert "\n" not in yaml_scalar("첫 줄\n둘째 줄")


def test_YAML_특수문자로_시작하면_따옴표():
    for t in ("- 목록", "#주석", "*별표", "@골뱅이"):
        assert yaml_scalar(t).startswith('"'), t


def test_평범한_한글은_따옴표_없이():
    assert yaml_scalar("협의회 안내") == "협의회 안내"


# ---------------------------------------------------------------- 본문

def test_제목이_있으면_본문_위에_H1():
    assert "\n# 2학기 교육과정 협의회\n" in render(msg())


def test_제목이_없으면_H1도_없다():
    assert "\n# " not in render(msg(title=""))


def test_본문을_가공하지_않는다():
    body = "첫 줄\n\n\n   들여쓴 줄\n- 목록\n**굵게**"
    assert body in render(msg(body=body))


def test_본문이_비면_표시를_남긴다():
    assert "(본문 없음)" in render(msg(body=""))


def test_CRLF는_LF로():
    out = render(msg(body="첫 줄\r\n둘째 줄"))
    assert "\r" not in out


def test_파일은_개행으로_끝난다():
    assert render(msg()).endswith("\n")
    assert not render(msg()).endswith("\n\n")


def test_본문이_구분선으로_시작해도_머리말과_안_섞인다():
    out = render(msg(title="", body="---\n표 같은 것"))
    assert out.count("---") >= 3
    assert read_front_matter_ok(out)


def read_front_matter_ok(text: str) -> bool:
    lines = text.split("\n")
    return lines[0] == "---" and "---" in lines[1:]


# ---------------------------------------------------------------- 첨부

def test_첨부_링크():
    out = render(msg(attachments=[Attachment("협의회 자료.hwp", 717824)]),
                 attachments=[AttachmentLink("협의회 자료.hwp", 717824, "첨부파일/폴더/협의회 자료.hwp")])
    assert "## 첨부파일" in out
    assert "[협의회 자료.hwp](<첨부파일/폴더/협의회 자료.hwp>)" in out
    assert "717,824 bytes" in out


def test_원본을_못_찾으면_이유를_적는다():
    out = render(msg(), attachments=[AttachmentLink("사라진.hwp", 100, None)])
    assert "⚠️" in out
    assert "원본을 찾지 못했습니다" in out
    assert head(out)["attachments_missing[]"] == ["사라진.hwp"]


def test_못_찾은_이유를_직접_줄_수도_있다():
    out = render(msg(), attachments=[AttachmentLink("큰파일.zip", 999, None, note="용량 제한 초과")])
    assert "용량 제한 초과" in out


def test_첨부를_끄면_안_나온다():
    out = render(msg(attachments=[Attachment("a.hwp")]),
                 options=RenderOptions(include_attachments=False))
    assert "## 첨부파일" not in out
    assert "attachments:" not in out


# ---------------------------------------------------------------- 인용 분리

def test_인용된_대화는_따로_인용문으로():
    out = render(msg(body="확인 바랍니다\n\n김철수님이 보낸글 >>\n원래 내용"))
    assert "## 인용된 이전 대화" in out
    assert "> 김철수님이 보낸글 >>" in out
    assert out.index("확인 바랍니다") < out.index("## 인용된 이전 대화")


def test_인용_분리를_끄면_본문에_그대로():
    body = "확인 바랍니다\n\n김철수님이 보낸글 >>\n원래 내용"
    out = render(msg(body=body), options=RenderOptions(split_quoted=False))
    assert "## 인용된 이전 대화" not in out
    assert body in out


def test_수신자를_끄면_머리말에서_빠진다():
    out = render(msg(recipients=["김철수"]), options=RenderOptions(include_recipients=False))
    assert "recipients" not in head(out)
