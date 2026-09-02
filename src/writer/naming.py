"""파일명 생성과 Windows 안전 정규화 (#10, FR-3.3~3.6).

인박스는 드롭박스로 동기화되고 결국 Windows 탐색기에서 열린다. 리눅스에서는 통과하지만
Windows 에서 만들 수 없는 이름이 얼마든지 나온다 — 금지문자, 예약어, 260자 제한, 끝의 마침표.
여기서 다 걸러 낸다.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

# Windows 금지문자 + 제어문자
_FORBIDDEN_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_SPACE_RE = re.compile(r"\s+")
_UNDERSCORE_RE = re.compile(r"_{2,}")
# Windows 예약 장치 이름 (확장자가 붙어도 예약이다)
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

MAX_PATH = 250          # 전체 경로 상한 (Windows 260 에서 여유를 둔다)
MIN_TITLE = 4           # 제목을 잘라도 이만큼은 남긴다
TITLE_FROM_BODY = 30    # 제목이 없을 때 본문에서 가져올 글자 수
NO_TITLE = "무제"

DEFAULT_FORMAT = "{date}_{time}_{sender}_{title}_#{key}"
TOKENS = ("date", "time", "sender", "title", "key")


def sanitize(part: str, *, fallback: str = "_") -> str:
    """파일명 한 조각을 안전하게. 폴더 구분자가 되지 않도록 경로 조각 단위로 부른다."""
    s = unicodedata.normalize("NFC", part or "")
    s = _FORBIDDEN_RE.sub("_", s)
    s = _SPACE_RE.sub("_", s)
    s = _UNDERSCORE_RE.sub("_", s)
    s = s.strip(" ._")
    return s or fallback


def avoid_reserved(stem: str) -> str:
    """CON, COM1 같은 Windows 예약 이름이면 밑줄을 붙인다."""
    return f"{stem}_" if stem.upper() in _RESERVED else stem


def title_for(message) -> str:
    """제목. 없으면 본문 첫 줄, 그것도 없으면 '무제' (FR-3.4)."""
    if message.title.strip():
        return message.title.strip()
    for line in (message.body or "").replace("\r", "").split("\n"):
        if line.strip():
            return line.strip()[:TITLE_FROM_BODY]
    return NO_TITLE


def _tokens(message) -> dict[str, str]:
    return {
        "date": f"{message.received:%Y-%m-%d}",
        "time": f"{message.received:%H%M}",
        "sender": sanitize(message.sender_name or message.sender, fallback="보낸이없음"),
        "title": sanitize(title_for(message), fallback=NO_TITLE),
        "key": str(message.key),
    }


def _render(fmt: str, tokens: dict[str, str]) -> str:
    out = fmt
    for k in TOKENS:
        out = out.replace("{" + k + "}", tokens.get(k, ""))
    return out


def note_filename(message, fmt: str = DEFAULT_FORMAT, *, base_dir: str | Path | None = None,
                  suffix: str = ".md") -> str:
    """쪽지 md 파일 이름.

    경로가 너무 길면 **제목 부분부터** 줄인다 (날짜·보낸이·키는 식별에 필요하다).
    """
    tokens = _tokens(message)
    name = avoid_reserved(sanitize(_render(fmt, tokens), fallback=NO_TITLE)) + suffix
    if base_dir is None:
        return name

    room = MAX_PATH - len(str(Path(base_dir))) - 1
    if len(name) <= room:
        return name
    # 제목을 줄여 가며 다시 만든다
    title = tokens["title"]
    over = len(name) - room
    shortened = title[:max(MIN_TITLE, len(title) - over)]
    tokens = {**tokens, "title": shortened}
    name = avoid_reserved(sanitize(_render(fmt, tokens), fallback=NO_TITLE)) + suffix
    if len(name) > room:                    # 제목을 다 줄여도 길면 통째로 자른다
        keep = max(1, room - len(suffix))
        name = sanitize(name[:keep], fallback=NO_TITLE) + suffix
    return name


def attachment_dirname(message) -> str:
    """쪽지별 첨부 폴더 이름 — `2026-09-02_1704_홍길동_#1234` (FR-2.4, PRD 4.2)."""
    t = _tokens(message)
    return avoid_reserved(sanitize(f"{t['date']}_{t['time']}_{t['sender']}_#{t['key']}"))


def attachment_filename(name: str) -> str:
    """첨부 원본 파일명을 안전하게. 확장자는 지킨다."""
    p = Path(unicodedata.normalize("NFC", name or ""))
    stem = avoid_reserved(sanitize(p.stem, fallback="첨부파일"))
    ext = _FORBIDDEN_RE.sub("_", p.suffix)[:20]
    return stem + ext


def unique_path(directory: str | Path, filename: str) -> Path:
    """같은 이름이 있으면 `이름 (2).ext` 로 피한다 (FR-3.6, FR-2.6)."""
    d = Path(directory)
    p = d / filename
    if not p.exists():
        return p
    stem, ext = Path(filename).stem, Path(filename).suffix
    for i in range(2, 1000):
        cand = d / f"{stem} ({i}){ext}"
        if not cand.exists():
            return cand
    raise FileExistsError(f"이름을 정할 수 없습니다: {p}")


def format_is_unique(fmt: str) -> bool:
    """서식에 `{key}` 가 있으면 이름이 원천적으로 겹치지 않는다."""
    return "{key}" in (fmt or "")
