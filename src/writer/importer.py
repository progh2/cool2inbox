"""쪽지 1건 처리 (#13). PRD 6.4 액티비티 다이어그램을 그대로 옮긴 것이다.

삭제 판정 → 키 판정 → 해시 판정 → 파일명 → 본문 조립 → 첨부 → 원자적 쓰기 → 이력 기록.

**저장에 성공한 뒤에만 이력을 남긴다.** 실패한 건은 이력에 없으므로 다음 폴링에서 다시 시도된다.
한 건이 실패해도 나머지는 계속 처리한다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from src.writer import naming
from src.writer.inbox import InboxError, InboxWriter
from src.writer.markdown import AttachmentLink, RenderOptions, render

log = logging.getLogger(__name__)

SAVED, SKIPPED, FAILED = "saved", "skipped", "failed"


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


class Importer:
    def __init__(self, config, state, finder=None, writer: InboxWriter | None = None):
        self.config = config
        self.state = state
        self.finder = finder if finder is not None else NullAttachmentFinder()
        self.writer = writer if writer is not None else InboxWriter(config.inbox)

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
                          attach_total=len(links), attach_ok=ok)
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
