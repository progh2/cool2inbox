"""이전 쪽지 모두 가져오기 (#19, FR-7.5·7.6).

몇 년치 이력을 한 번에 옮기는 작업이다. 폴링과 다른 점 셋:

- **미리보기 먼저.** 몇 건을 가져오고 몇 건이 이미 있는지 보여주고 확인을 받는다.
- **취소할 수 있다.** 취소해도 그때까지 저장한 것은 그대로 둔다.
- **last_message_key 를 건드리지 않는다.** 백필은 과거를 채우는 일이고, 폴링이 어디까지
  처리했는지와는 별개다. 여기서 키를 옮기면 폴링이 최신 쪽지를 건너뛸 수 있다.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from src.sources.coolm import CoolmError, CoolmReader
from src.writer.importer import Summary

log = logging.getLogger(__name__)

BATCH = 200


@dataclass
class BackfillPreview:
    total: int = 0              # DB 에 있는 쪽지 전체
    already: int = 0            # 이미 가져온 것
    to_import: int = 0          # 이번에 가져올 것
    attachments: int = 0        # 가져올 쪽지에 딸린 첨부 수 (추정)

    def describe(self) -> str:
        if not self.to_import:
            return f"쪽지 {self.total:,}건이 모두 이미 인박스에 있습니다."
        return (f"가져올 쪽지 {self.to_import:,}건 · 이미 있음 {self.already:,}건 "
                f"· 예상 첨부 {self.attachments:,}개")


class Backfill(QObject):
    progress = Signal(int, int, str)     # 처리한 수, 전체, 지금 파일명
    finished = Signal(object)            # Summary
    failed = Signal(str)

    def __init__(self, config, state, importer, parent=None, pace_seconds: float = 0.0):
        super().__init__(parent)
        self.config = config
        self.state = state
        self.importer = importer
        self.pace_seconds = pace_seconds     # 드롭박스 부하 완화용 (건당 지연)
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 미리보기 (동기 — 읽기만 해서 빠르다)

    def preview(self, memo_dir: str) -> BackfillPreview:
        with CoolmReader(memo_dir) as r:
            keys = r.all_keys()
            done = self.state.keys()
            todo = [k for k in keys if k not in done]
            attachments = 0
            for i in range(0, len(todo), BATCH):
                for m in r.messages_by_keys(todo[i:i + BATCH]):
                    attachments += len(m.attachments)
        return BackfillPreview(total=len(keys), already=len(keys) - len(todo),
                               to_import=len(todo), attachments=attachments)

    # ---- 실행

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, memo_dir: str) -> None:
        if self.running:
            return
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, args=(memo_dir,),
                                        name="cool2inbox-backfill", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def _run(self, memo_dir: str) -> None:
        summary = Summary()
        try:
            with CoolmReader(memo_dir) as r:
                done = self.state.keys()
                todo = [k for k in r.all_keys() if k not in done]
                total = len(todo)
                log.info("백필 시작 — 가져올 쪽지 %d건", total)
                processed = 0
                for i in range(0, total, BATCH):
                    if self._cancel.is_set():
                        break
                    for m in r.messages_by_keys(todo[i:i + BATCH]):
                        if self._cancel.is_set():
                            break
                        result = summary.add(self.importer.import_one(m))
                        processed += 1
                        name = result.md_path.name if result.md_path else ""
                        self.progress.emit(processed, total, name)
                        if self.pace_seconds:
                            time.sleep(self.pace_seconds)
        except CoolmError as e:
            log.warning("백필 실패: %s", e)
            self.failed.emit(str(e))
            return
        except Exception as e:                    # 도중에 무슨 일이 나도 앱은 계속 돈다
            log.exception("백필 중 예상하지 못한 오류")
            self.failed.emit(f"이전 쪽지를 가져오는 중 오류가 났습니다: {e}")
            return
        log.info("백필 끝 — %s%s", summary.describe(), " (취소됨)" if self._cancel.is_set() else "")
        self.finished.emit(summary)
