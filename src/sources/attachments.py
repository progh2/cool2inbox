"""쿨메신저 수신 파일 찾기 (#15, #16, FR-2.2~2.4).

실물 확인 경로:

    %USERPROFILE%\\Documents\\CoolMessenger Files\\Received Files\\

하위 폴더 없이 **원본 파일명 그대로** 평평하게 쌓인다. 쪽지 키도 날짜 접두사도 붙지 않는다.
그래서 DB 의 `FilePath` 가 알려 주는 **이름 + 바이트 크기**로 맞춘다 — 실물 대조에서 이름과
크기가 정확히 일치했다.

찾지 못하는 것이 정상인 경우가 많다. 사용자가 수신 파일을 주기적으로 다른 곳으로 옮기기 때문에
(확인한 PC 에는 397개 중 5개만 남아 있었다) 오래된 쪽지의 첨부는 대부분 없다. 실패가 아니다.
"""
from __future__ import annotations

import logging
import os
import unicodedata
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

RECV_DIR_CANDIDATES = (
    ("USERPROFILE", ("Documents", "CoolMessenger Files", "Received Files")),
    ("USERPROFILE", ("Documents", "CoolMessenger", "Received Files")),
    ("USERPROFILE", ("OneDrive", "Documents", "CoolMessenger Files", "Received Files")),
    ("USERPROFILE", ("Documents", "CoolMessenger Files")),
    ("LOCALAPPDATA", ("CoolMessenger", "Received Files")),
)


def norm(name: str) -> str:
    """파일명 비교용 정규화. macOS/Linux 를 거치면 NFD 로 분해돼 한글 이름이 안 맞는다."""
    return unicodedata.normalize("NFC", name or "")


def default_recv_dir() -> str:
    """수신 파일 폴더 자동 탐지. 못 찾으면 빈 문자열."""
    for var, sub in RECV_DIR_CANDIDATES:
        base = os.environ.get(var, "")
        if not base:
            continue
        d = Path(base).joinpath(*sub)
        try:
            if d.is_dir():
                return str(d)
        except OSError:
            continue
    return ""


class AttachmentFinder:
    """수신 파일 폴더에서 쪽지의 첨부 원본을 찾는다. 읽기만 한다."""

    def __init__(self, recv_dir: str | Path | None, match_minutes: int = 30):
        self.recv_dir = Path(recv_dir) if recv_dir else None
        self.match_minutes = int(match_minutes)
        self._index: dict[str, list[Path]] = {}
        self._index_key: tuple | None = None

    # ---- 색인

    def _dir_signature(self) -> tuple | None:
        try:
            st = self.recv_dir.stat()
        except (OSError, AttributeError):
            return None
        return (st.st_mtime_ns, st.st_size)

    def refresh(self, force: bool = False) -> int:
        """폴더를 훑어 이름 → 경로 색인을 만든다. 폴더가 그대로면 다시 훑지 않는다."""
        if self.recv_dir is None or not self.recv_dir.is_dir():
            self._index, self._index_key = {}, None
            return 0
        sig = self._dir_signature()
        if not force and sig is not None and sig == self._index_key and self._index:
            return sum(len(v) for v in self._index.values())
        index: dict[str, list[Path]] = {}
        try:
            for p in self.recv_dir.iterdir():
                if p.is_file():
                    index.setdefault(norm(p.name).casefold(), []).append(p)
        except OSError as e:
            log.warning("수신 파일 폴더를 읽지 못했습니다 (%s): %s", self.recv_dir, e)
            self._index, self._index_key = {}, None
            return 0
        self._index, self._index_key = index, sig
        return sum(len(v) for v in index.values())

    # ---- 찾기

    def find(self, message) -> list[tuple[object, Path | None]]:
        """[(첨부, 실제 경로 또는 None)]. 순서는 쪽지의 첨부 순서 그대로."""
        if not message.attachments:
            return []
        self.refresh()
        used: set[Path] = set()
        out = []
        for att in message.attachments:
            p = self._match(att, message.received, used)
            if p is not None:
                used.add(p)
            out.append((att, p))
        return out

    def _match(self, att, received: datetime, used: set[Path]) -> Path | None:
        cands = [p for p in self._index.get(norm(att.name).casefold(), []) if p not in used]
        if not cands:
            return None

        # ① 이름 + 바이트 크기 일치 (가장 확실하다)
        if att.size:
            exact = [p for p in cands if _size(p) == att.size]
            if exact:
                return _closest(exact, received)

        # ② 이름만 일치 — 수신 시각에 가까운 것. 너무 멀면 남의 파일일 수 있어 거른다
        best = _closest(cands, received)
        if self.match_minutes:
            gap = abs(_mtime(best) - received.timestamp())
            if gap > self.match_minutes * 60:
                log.debug("이름은 맞지만 시각이 %.0f분 떨어져 건너뜁니다: %s", gap / 60, att.name)
                return None
        return best

    # ---- 상태

    def summary(self) -> str:
        """'연결 테스트' 버튼용 한 줄 (FR-6.2)."""
        if self.recv_dir is None or not str(self.recv_dir).strip():
            return "수신 파일 폴더가 지정되지 않았습니다 — 첨부는 이름만 기록됩니다."
        if not self.recv_dir.is_dir():
            return f"수신 파일 폴더가 없습니다: {self.recv_dir}"
        n = self.refresh(force=True)
        if not n:
            return f"폴더는 있지만 파일이 없습니다: {self.recv_dir}"
        newest = max((p for ps in self._index.values() for p in ps), key=_mtime)
        return f"연결 OK — 파일 {n:,}개, 최근 {datetime.fromtimestamp(_mtime(newest)):%Y-%m-%d}"


def _size(p: Path) -> int:
    try:
        return p.stat().st_size
    except OSError:
        return -1


def _mtime(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def _closest(paths: list[Path], received: datetime) -> Path:
    target = received.timestamp()
    return min(paths, key=lambda p: abs(_mtime(p) - target))
