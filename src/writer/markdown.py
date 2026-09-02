"""쪽지 → 마크다운 (#11, PRD 4.3).

원칙 하나: **본문을 가공하지 않는다.** 요약도, 마스킹도, 줄바꿈 재배치도 없다.
인박스는 원본 아카이브다. 해석은 하류 도구가 한다.

머리말은 YAML 이지만 PyYAML 을 쓰지 않는다 — 내보내기만 하면 되고, 읽을 때 필요한 키는
세 개뿐이라(`state.read_front_matter`) 의존성을 늘릴 이유가 없다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

FRONT = "---"
# YAML 평문 스칼라로 두면 위험하거나, 우리 쪽 단순 파서(state.read_front_matter)가
# 헷갈릴 수 있는 값. 따옴표·역슬래시는 YAML 상 평문에 둬도 되지만 감싸는 편이 안전하다.
_NEEDS_QUOTE = re.compile(r'^\s|\s$|^$|^[-?:,\[\]{}#&*!|>%@`]|:(\s|$)|\s#|[\n\r\t"\\]')


@dataclass
class AttachmentLink:
    """첨부 하나. `rel_path` 가 없으면 원본을 못 찾았다는 뜻이다."""

    name: str
    size: int | None = None
    rel_path: str | None = None
    note: str = ""              # 못 찾은 이유 등


@dataclass
class RenderOptions:
    split_quoted: bool = True
    include_recipients: bool = True
    include_cc: bool = True
    include_attachments: bool = True


def yaml_scalar(v) -> str:
    """YAML 스칼라 한 개를 안전하게 적는다."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    s = str(v).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    if _NEEDS_QUOTE.search(s):
        return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return s


def _line(key: str, value) -> str:
    return f"{key}: {yaml_scalar(value)}"


def _list_block(key: str, values: list[str]) -> list[str]:
    return [f"{key}:", *[f"  - {yaml_scalar(v)}" for v in values]]


def _md_link(text: str, path: str) -> str:
    """공백이 있어도 깨지지 않는 마크다운 링크 (CommonMark 의 <> 형식)."""
    return f"[{text}](<{path}>)"


def front_matter(message, *, attachments: list[AttachmentLink] | None = None,
                 options: RenderOptions | None = None, imported_at: datetime | None = None) -> str:
    """YAML 머리말. **값이 없는 항목은 키 자체를 넣지 않는다.**"""
    o = options or RenderOptions()
    at = attachments if attachments is not None else [
        AttachmentLink(a.name, a.size) for a in message.attachments]

    lines = [FRONT, _line("source", "coolmessenger"), _line("message_key", message.key)]
    if message.title.strip():
        lines.append(_line("title", message.title.strip()))
    if message.sender.strip():
        lines.append(_line("sender", message.sender_name or message.sender))
        if message.sender_login:
            lines.append(_line("sender_login", message.sender_login))
    lines.append(_line("received", f"{message.received:%Y-%m-%d %H:%M:%S}"))
    lines.append(_line("received_weekday", message.weekday))

    if o.include_recipients and message.recipients:
        lines += _list_block("recipients", message.recipients)
        lines.append(_line("recipient_count", message.recipient_count or len(message.recipients)))
    if o.include_cc and message.cc:
        lines += _list_block("cc", message.cc)
    if o.include_attachments and at:
        lines += _list_block("attachments", [a.name for a in at])
        missing = [a.name for a in at if not a.rel_path]
        if missing and attachments is not None:
            lines += _list_block("attachments_missing", missing)
    if message.is_unread:
        lines.append(_line("unread", True))
    lines.append(_line("imported_at", f"{imported_at or datetime.now():%Y-%m-%d %H:%M:%S}"))
    lines.append(_line("content_hash", message.content_hash()))
    lines.append(FRONT)
    return "\n".join(lines)


def render(message, *, attachments: list[AttachmentLink] | None = None,
           options: RenderOptions | None = None, imported_at: datetime | None = None) -> str:
    """쪽지 1건 → md 파일 전체 내용."""
    o = options or RenderOptions()
    at = attachments if attachments is not None else [
        AttachmentLink(a.name, a.size) for a in message.attachments]

    parts = [front_matter(message, attachments=attachments, options=options, imported_at=imported_at), ""]

    if message.title.strip():
        parts += [f"# {message.title.strip()}", ""]

    body, quoted = message.split_body() if o.split_quoted else (message.body.strip(), "")
    body = body.replace("\r\n", "\n").replace("\r", "\n")
    if body.lstrip().startswith(FRONT):
        parts.append("")            # 머리말과 헷갈리지 않게 한 줄 띄운다
    parts.append(body if body else "(본문 없음)")

    if o.include_attachments and at:
        parts += ["", "## 첨부파일", ""]
        for a in at:
            size = f" — {a.size:,} bytes" if a.size else ""
            if a.rel_path:
                parts.append(f"- {_md_link(a.name, a.rel_path)}{size}")
            else:
                why = a.note or "원본을 찾지 못했습니다"
                parts.append(f"- {a.name}{size} — ⚠️ {why}")

    if quoted:
        parts += ["", "## 인용된 이전 대화", ""]
        parts += [f"> {line}" if line.strip() else ">" for line in quoted.split("\n")]

    return "\n".join(parts).rstrip() + "\n"
