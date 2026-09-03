"""폴링 워처 (#14, FR-5).

주기마다 udb 를 읽어 새 쪽지를 Importer 에 넘긴다.

**DB 읽기와 파일 쓰기는 워커 스레드에서** 한다 (FR-5.4). UI 는 절대 멈추지 않는다.
워커에서 GUI 를 직접 건드리지 않고 시그널로만 알린다 — 받는 쪽이 QObject 여야 Qt 가
큐 연결로 메인 스레드에 넘겨준다. 평범한 함수에 연결하면 **워커 스레드에서 그대로 실행되어**
GUI 를 건드리게 된다 (catmoa 가 이걸로 크래시했다).

마지막 처리 키는 **실패한 쪽지 앞에서 멈춘다.** 실패한 건을 지나쳐 버리면 영영 다시 시도되지 않는다.
"""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime

from PySide6.QtCore import QObject, QTimer, Signal

from src.sources.coolm import CoolmError, CoolmReader, default_memo_dir
from src.writer.importer import SAVED, SKIPPED, Importer, Summary

log = logging.getLogger(__name__)

RETRY_PER_POLL = 30      # 한 번에 다시 확인할 미완료 첨부 쪽지 수


class Watcher(QObject):
    poll_started = Signal()
    poll_finished = Signal(object)      # Summary
    poll_error = Signal(str)
    status = Signal(str)

    def __init__(self, config, state, parent=None, importer=None):
        super().__init__(parent)
        self.config = config
        self.state = state
        self.importer = importer if importer is not None else Importer(config, state)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.poll_now)
        self._busy = False
        self._last_error = ""
        self._delivered_today = 0
        self._today = date.today()

    # ---- 제어

    def apply_config(self, config=None) -> None:
        """설정이 바뀌면 호출한다. 재시작 없이 주기·일시정지가 반영된다 (FR-6.6)."""
        if config is not None:
            self.config = config
            self.importer.apply_config(config)
        s = self.config.schedule
        if s.paused or not self.config.is_configured():
            self._timer.stop()
            self.status.emit("일시정지" if s.paused else "설정이 필요합니다")
            return
        self._timer.start(max(1, int(s.poll_minutes)) * 60 * 1000)
        self.status.emit(f"{s.poll_minutes}분마다 확인합니다")

    def pause(self) -> None:
        self._timer.stop()
        self.status.emit("일시정지")

    def resume(self) -> None:
        """재개하면 밀린 쪽지를 바로 배달한다 (FR-5.2)."""
        self.apply_config()
        if self._timer.isActive():
            QTimer.singleShot(0, self.poll_now)

    @property
    def active(self) -> bool:
        return self._timer.isActive()

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def delivered_today(self) -> int:
        self._roll_day()
        return self._delivered_today

    def memo_dir(self) -> str:
        return self.config.coolm.memo_dir or default_memo_dir()

    # ---- 폴링

    def poll_now(self) -> None:
        """즉시 1회 확인 (FR-5.3). 이미 돌고 있으면 무시한다."""
        if self._busy:
            log.debug("이미 확인 중이라 건너뜁니다.")
            return
        if not self.config.is_configured():
            self.poll_error.emit("쿨메신저 폴더와 인박스 폴더를 먼저 지정해 주세요.")
            return
        self._busy = True
        self.poll_started.emit()
        t = threading.Thread(target=self._run, name="cool2inbox-poll", daemon=True)
        t.start()

    def _run(self) -> None:
        """워커 스레드. 여기서 GUI 를 건드리지 않는다 — 시그널만 낸다.

        `_busy` 는 **시그널을 다 낸 뒤에** 내린다. 먼저 내리면 결과가 전달되기 전에 다음 폴링이
        시작될 수 있다.
        """
        try:
            try:
                summary = self._collect()
            except CoolmError as e:
                self._emit_error(str(e))
                return
            except Exception as e:                   # 예상 못한 오류에도 상주는 계속된다 (FR-9.4)
                log.exception("폴링 중 예상하지 못한 오류")
                self._emit_error(f"쪽지를 확인하는 중 오류가 났습니다: {e}")
                return
            self._last_error = ""
            self._note_delivery(summary)
            self.poll_finished.emit(summary)
        finally:
            self._busy = False

    def _collect(self) -> Summary:
        c = self.config.coolm
        limit = max(1, int(self.config.schedule.max_per_poll))
        with CoolmReader(self.memo_dir()) as r:
            messages = r.messages_after(c.last_message_key, limit=limit)
            summary = self.importer.import_many(messages) if messages else Summary()
            self._advance(summary, "recv")
            if c.include_sent and r.has_sent:
                sent = r.sent_after(c.last_sent_key, limit=limit)
                if sent:
                    ss = self.importer.import_many(sent)
                    summary.results.extend(ss.results)
                    self._advance(ss, "send")
            summary = self._retry_attachments(r, summary)
        return summary

    def _retry_attachments(self, reader, summary: Summary) -> Summary:
        """못 찾았던 첨부를 다시 찾는다 (FR-2.7).

        쿨메신저는 사용자가 눌러서 받기 전까지 첨부를 PC 에 내려받지 않는다. 쪽지가 도착한
        시점에는 원본이 없다가 나중에 생기는 것이 오히려 보통이다. 그래서 매 폴링마다
        미완료 목록을 다시 훑는다.
        """
        pending = self.state.pending_attachments()[:RETRY_PER_POLL]
        if not pending:
            return summary
        recv_rows = {r.message_key: r for r in pending if r.kind == "recv"}
        sent_rows = {r.message_key: r for r in pending if r.kind == "send"}
        for msgs, rows in ((reader.messages_by_keys(list(recv_rows)), recv_rows),
                           (reader.sent_by_keys(list(sent_rows)) if reader.has_sent else [], sent_rows)):
            for m in msgs:
                try:
                    result = self.importer.retry_attachments(m, rows[m.key])
                except OSError as e:
                    log.warning("첨부 재시도 실패 (쪽지 %s): %s", m.key, e)
                    continue
                if result.status == SAVED:
                    summary.add(result)
        return summary

    def _advance(self, summary: Summary, kind: str = "recv") -> None:
        """마지막 처리 키를 옮긴다. **실패한 쪽지 앞에서 멈춘다.** kind 별로 따로 관리한다."""
        attr = "last_message_key" if kind == "recv" else "last_sent_key"
        advance = getattr(self.config.coolm, attr)
        for r in summary.results:
            if r.status in (SAVED, SKIPPED):
                advance = max(advance, r.message_key)
            else:
                break
        if advance != getattr(self.config.coolm, attr):
            setattr(self.config.coolm, attr, advance)
            self._save_config()

    def _emit_error(self, message: str) -> None:
        if message != self._last_error:          # 같은 오류는 한 번만 알린다 (FR-5.6)
            self._last_error = message
            self.poll_error.emit(message)
        else:
            log.debug("같은 오류가 계속됩니다: %s", message)

    def _note_delivery(self, summary: Summary) -> None:
        self._roll_day()
        self._delivered_today += summary.saved
        self.config.ui.last_check_at = f"{datetime.now():%H:%M}"
        self._save_config()

    def _roll_day(self) -> None:
        today = date.today()
        if today != self._today:
            self._today, self._delivered_today = today, 0

    def _save_config(self) -> None:
        try:
            self.config.save()
        except OSError as e:
            log.warning("설정을 저장하지 못했습니다: %s", e)

    # ---- 설정 창에서 쓰는 동기 호출

    def check_connection(self) -> str:
        """'연결 테스트' 버튼 (FR-6.2). 예외는 CoolmError 로 나간다."""
        with CoolmReader(self.memo_dir()) as r:
            return r.summary()
