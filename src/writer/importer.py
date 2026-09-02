"""쪽지 1건 처리 (#13). PRD 6.4 액티비티 다이어그램을 그대로 옮긴 것이다.

삭제 판정 → 키 판정 → 해시 판정 → 파일명 → 본문 조립 → 첨부 → 원자적 쓰기 → 이력 기록.

**저장에 성공한 뒤에만 이력을 남긴다.** 실패한 건은 이력에 없으므로 다음 폴링에서 다시 시도된다.
한 건이 실패해도 나머지는 계속 처리한다.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.sources.attachments import AttachmentFinder
from src.writer import naming
from src.writer.inbox import InboxError, InboxWriter
from src.writer.markdown import AttachmentLink, RenderOptions, render


def _parse_time(text: str):
    from datetime import datetime

    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None

log = logging.getLogger(__name__)

SAVED, SKIPPED, FAILED = "saved", "skipped", "failed"


def md_sha(text: str) -> str:
    """우리가 쓴 md 본문의 지문. 사용자가 파일을 손댔는지 판별하는 데 쓴다."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ImportResult:
    message_key: int
    status: str                  # saved | skipped | failed
    reason: str = ""
    md_path: Path | None = None
    attach_total: int = 0
    attach_ok: int = 0

    @property
    def ok(self) -> bool:
        return self.status == SAVED


@dataclass
class Summary:
    results: list[ImportResult] = field(default_factory=list)

    @property
    def saved(self) -> int:
        return sum(1 for r in self.results if r.status == SAVED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == SKIPPED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == FAILED)

    @property
    def attachments_copied(self) -> int:
        return sum(r.attach_ok for r in self.results)

    @property
    def saved_keys(self) -> list[int]:
        return [r.message_key for r in self.results if r.status == SAVED]

    def add(self, r: ImportResult) -> ImportResult:
        self.results.append(r)
        return r

    def describe(self) -> str:
        return f"저장 {self.saved} · 건너뜀 {self.skipped} · 실패 {self.failed}"


class NullAttachmentFinder:
    """첨부 원본을 찾지 않는 기본 구현 (#15/#16 에서 실제 구현으로 교체).

    이름과 크기는 md 에 남고, 원본은 '못 찾음' 으로 표기된다 — 실패가 아니다.
    """

    def find(self, message) -> list[tuple[object, Path | None]]:
        return [(a, None) for a in message.attachments]


def _finder_for(config):
    """수신 파일 폴더가 지정돼 있으면 실제 탐색기, 아니면 이름만 기록하는 기본 구현."""
    d = (config.coolm.recv_file_dir or "").strip()
    if not d:
        return NullAttachmentFinder()
    return AttachmentFinder(d, config.coolm.attach_match_minutes)


class Importer:
    def __init__(self, config, state, finder=None, writer: InboxWriter | None = None):
        self.config = config
        self.state = state
        self._explicit_finder = finder
        self.finder = finder if finder is not None else _finder_for(config)
        self.writer = writer if writer is not None else InboxWriter(config.inbox)

    def apply_config(self, config) -> None:
        """설정이 바뀌면 호출한다. 수신 파일 폴더가 바뀌면 탐색기도 새로 만든다 (FR-6.6)."""
        self.config = config
        self.writer.settings = config.inbox
        if self._explicit_finder is None:
            self.finder = _finder_for(config)

    # ---- 한 건

    def import_one(self, message, *, now: datetime | None = None) -> ImportResult:
        key = message.key
        if message.is_empty:
            return ImportResult(key, SKIPPED, "내용이 없는 쪽지")
        if self.state.seen(key, message.content_hash()):
            return ImportResult(key, SKIPPED, "이미 가져온 쪽지")

        try:
            return self._save(message, now=now)
        except InboxError as e:
            log.warning("쪽지 %s 저장 실패: %s", key, e)
            return ImportResult(key, FAILED, str(e))
        except OSError as e:                      # 예상 못한 IO — 나머지는 계속 간다
            log.exception("쪽지 %s 처리 중 오류", key)
            return ImportResult(key, FAILED, f"저장 중 오류: {e}")

    def _save(self, message, *, now: datetime | None = None) -> ImportResult:
        o = self.config.output
        options = RenderOptions(split_quoted=o.split_quoted,
                                include_recipients=o.include_recipients,
                                include_cc=o.include_cc,
                                include_attachments=o.include_attachments)
        self.writer.ensure_dirs(attachments=bool(message.attachments))

        filename = naming.note_filename(message, o.filename_format, base_dir=self.writer.coolm_dir)
        if not naming.format_is_unique(o.filename_format):
            filename = naming.unique_path(self.writer.coolm_dir, filename).name

        links, ok = self._attachments(message)
        text = render(message, attachments=links, options=options, imported_at=now)
        md_path = self.writer.write_note(filename, text)

        self.state.record(message.key, message.content_hash(), md_path,
                          attach_total=len(links), attach_ok=ok, md_sha=md_sha(text))
        log.info("쪽지 %s 저장: %s (첨부 %d/%d)", message.key, md_path.name, ok, len(links))
        return ImportResult(message.key, SAVED, md_path=md_path,
                            attach_total=len(links), attach_ok=ok)

    def _attachments(self, message) -> tuple[list[AttachmentLink], int]:
        """첨부를 복사하고 md 에 넣을 링크 목록을 만든다. 실패는 쪽지 저장 실패가 아니다."""
        if not message.attachments or not self.config.output.include_attachments:
            return [], 0

        limit = self.config.inbox.max_attach_mb * 1024 * 1024
        sub = naming.attachment_dirname(message)
        dest_dir = self.writer.attach_dir / sub
        rel_base = f"{self.config.inbox.attach_folder_name}/{sub}"

        links: list[AttachmentLink] = []
        ok = 0
        for att, src in self.finder.find(message):
            link = AttachmentLink(att.name, att.size)
            if src is None:
                link.note = "원본을 찾지 못했습니다"
            elif limit and att.size and att.size > limit:
                link.note = f"용량 제한({self.config.inbox.max_attach_mb}MB)을 넘어 건너뛰었습니다"
            else:
                safe = naming.attachment_filename(att.name)
                try:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    target = naming.unique_path(dest_dir, safe)
                    self.writer.copy_attachment(src, dest_dir, target.name)
                    link.rel_path = f"{rel_base}/{target.name}"
                    ok += 1
                except (InboxError, OSError) as e:
                    link.note = f"복사하지 못했습니다: {e}"
                    log.warning("첨부 복사 실패 (쪽지 %s): %s", message.key, e)
            links.append(link)
        return links, ok

    # ---- 첨부 재시도 (FR-2.7)

    def retry_attachments(self, message, row) -> ImportResult:
        """이미 저장한 쪽지의 못 찾은 첨부를 다시 찾는다.

        쿨메신저는 사용자가 눌러서 받기 전까지 첨부를 PC 에 내려받지 않는다. 그래서 쪽지가
        도착한 시점에는 원본이 없다가 나중에 생기는 일이 흔하다. 매 폴링마다 다시 찾아 본다.

        md 를 다시 쓰는 것은 **우리가 쓴 그대로일 때만** 한다. 사용자가 메모를 덧붙였다면
        파일은 건드리지 않고 첨부만 복사한다 — 인박스는 사용자의 것이다.
        """
        md_path = Path(row.md_path)
        if not md_path.exists():
            return ImportResult(message.key, SKIPPED, "md 파일이 없습니다")

        links, ok = self._attachments(message)
        if ok <= row.attach_ok:
            return ImportResult(message.key, SKIPPED, "새로 찾은 첨부가 없습니다",
                                md_path=md_path, attach_total=len(links), attach_ok=ok)

        o = self.config.output
        text = render(message, attachments=links, imported_at=_parse_time(row.imported_at),
                      options=RenderOptions(split_quoted=o.split_quoted,
                                            include_recipients=o.include_recipients,
                                            include_cc=o.include_cc,
                                            include_attachments=o.include_attachments))
        untouched = row.md_sha and md_sha(md_path.read_text(encoding="utf-8")) == row.md_sha
        if untouched:
            self.writer.write_note(md_path.name, text)
            self.state.update_attachments(message.key, ok, md_sha(text))
            log.info("쪽지 %s 첨부 %d개를 뒤늦게 찾아 md 를 갱신했습니다", message.key, ok - row.attach_ok)
        else:
            self.state.update_attachments(message.key, ok)
            log.info("쪽지 %s 첨부 %d개를 복사했습니다 (md 는 손대지 않음 — 사용자가 편집함)",
                     message.key, ok - row.attach_ok)
        return ImportResult(message.key, SAVED, "" if untouched else "md 는 사용자 편집본이라 그대로 둠",
                            md_path=md_path, attach_total=len(links), attach_ok=ok)

    # ---- 여러 건

    def import_many(self, messages, *, on_progress=None, should_cancel=None) -> Summary:
        """순서대로 처리한다. 한 건이 실패해도 멈추지 않는다."""
        s = Summary()
        total = len(messages)
        for i, m in enumerate(messages, 1):
            if should_cancel is not None and should_cancel():
                log.info("가져오기 취소 (%d/%d)", i - 1, total)
                break
            r = s.add(self.import_one(m))
            if on_progress is not None:
                on_progress(i, total, r)
        return s
