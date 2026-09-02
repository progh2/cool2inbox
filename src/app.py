"""앱 컨트롤러 — 트레이 시그널을 실제 동작에 연결한다.

트레이(`ui/tray.py`)는 아무 일도 하지 않고 시그널만 낸다. 그 시그널을 받아 설정을 읽고
폴더를 열고 워커를 돌리는 것이 여기다. v0.1 에서는 폴링·설정 창이 아직 없어 자리만 잡아 둔다.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from src import config as cfg
from src import osutil
from src.logging_setup import log_path
from src.sources.watcher import Watcher
from src.state import StateDB
from src.ui.tray import AppState, Tray

log = logging.getLogger(__name__)


class AppController(QObject):
    """**QObject 여야 한다.** 워커 스레드가 낸 시그널을 평범한 함수에 연결하면 Qt 가
    DirectConnection 으로 붙여 워커 스레드에서 GUI 를 건드리게 된다 (catmoa 가 이걸로 크래시했다).
    QObject 의 메서드에 연결하면 Qt 가 알아서 메인 스레드로 큐잉해 준다.
    """

    def __init__(self, app, config: cfg.Config | None = None, tray: Tray | None = None,
                 state=None, watcher=None):
        super().__init__()
        self.app = app
        self.config = config if config is not None else cfg.Config.load()
        self.tray = tray if tray is not None else Tray()
        self.state = state if state is not None else StateDB(cfg.state_path())
        self.watcher = watcher if watcher is not None else Watcher(self.config, self.state, parent=self)
        self.instance_server = None          # main 이 넣어 준다 (종료할 때 닫는다)
        self._connect()
        self.refresh_state()
        self.watcher.apply_config()

    # ---- 배선

    def _connect(self) -> None:
        t = self.tray
        t.check_now_requested.connect(self.check_now)
        t.pause_toggled.connect(self.set_paused)
        t.open_inbox_requested.connect(self.open_inbox)
        t.settings_requested.connect(self.open_settings)
        t.logs_requested.connect(self.open_logs)
        t.about_requested.connect(self.show_about)
        t.quit_requested.connect(self.quit)

        w = self.watcher
        w.poll_started.connect(self.on_poll_started)
        w.poll_finished.connect(self.on_poll_finished)
        w.poll_error.connect(self.on_poll_error)

    def refresh_state(self) -> None:
        """설정과 일시정지 여부에 맞춰 아이콘·메뉴를 정한다. 설정 미완료가 최우선이다."""
        paused = self.config.schedule.paused
        self.tray.set_paused(paused)          # 메뉴 글자('일시정지'/'재개')를 먼저 맞춘다
        if not self.config.is_configured():
            self.tray.set_state(AppState.SETUP, "폴더를 지정해 주세요")
        elif not paused:
            self.tray.set_state(AppState.IDLE)

    # ---- 동작

    def check_now(self) -> None:
        """지금 확인 (FR-5.3)."""
        if not self.config.is_configured():
            self.open_settings()
            return
        self.watcher.poll_now()

    def set_paused(self, paused: bool) -> None:
        """일시정지/재개 (FR-5.2). 설정에 남겨 다음 실행에도 유지한다."""
        self.config.schedule.paused = bool(paused)
        self._save()
        self.tray.set_paused(bool(paused))
        if paused:
            self.watcher.pause()
        else:
            self.watcher.resume()
        log.info("일시정지 %s", "켬" if paused else "끔")

    # ---- 폴링 결과 (워커 스레드가 낸 시그널 — QObject 라 메인 스레드에서 실행된다)

    def on_poll_started(self) -> None:
        if self.tray.state is not AppState.PAUSED:
            self.tray.set_state(AppState.WORKING)

    def on_poll_finished(self, summary) -> None:
        self._update_summary()
        if summary.saved:
            log.info("배달 완료 — %s", summary.describe())
            if self.config.schedule.notify:
                self.tray.notify("cool2inbox", f"쪽지 {summary.saved}건을 인박스로 배달했어요.")
        if summary.failed and self.config.schedule.notify:
            self.tray.notify("cool2inbox", f"쪽지 {summary.failed}건을 저장하지 못했습니다. "
                                           "로그를 확인해 주세요.", error=True)

    def on_poll_error(self, message: str) -> None:
        """오류는 설정과 무관하게 항상 알린다 (FR-8.6)."""
        self.tray.set_state(AppState.ERROR, message.split("\n")[0])
        self.tray.notify("cool2inbox", message, error=True)

    def _update_summary(self) -> None:
        self.tray.set_summary(self.config.ui.last_check_at, self.watcher.delivered_today)
        if not self.config.schedule.paused and self.config.is_configured():
            self.tray.set_state(AppState.IDLE)

    def open_inbox(self) -> None:
        """인박스 폴더 열기 (FR-8.3). 아직 설정 전이면 설정으로 안내한다."""
        if not self.config.is_configured():
            self.open_settings()
            return
        d = self.config.inbox.coolm_dir()
        d.mkdir(parents=True, exist_ok=True)
        if not osutil.open_folder(d):
            self.tray.notify("cool2inbox", f"폴더를 열지 못했습니다:\n{d}", error=True)

    def open_settings(self) -> None:
        """설정 창은 #18, 첫 실행 마법사는 #17 에서 붙인다."""
        log.info("설정 창 요청 — 아직 구현 전입니다.")
        self.tray.notify("cool2inbox", "설정 창은 아직 준비 중입니다.")

    def open_logs(self) -> None:
        osutil.open_folder(log_path().parent)

    def show_about(self) -> None:
        from src import __version__

        self.tray.notify("cool2inbox", f"버전 {__version__}\n쿨메신저 쪽지를 인박스로 배달합니다.")

    def quit(self) -> None:
        log.info("종료합니다.")
        self.watcher.pause()
        self._save()
        try:
            self.state.close()
        except Exception:                    # 종료 경로에서는 무엇도 막지 않는다
            log.debug("상태 DB 를 닫지 못했습니다", exc_info=True)
        if self.instance_server is not None:
            self.instance_server.close()
        self.tray.hide()
        self.app.quit()

    # ---- 내부

    def _save(self) -> None:
        try:
            self.config.save()
        except OSError as e:
            log.warning("설정을 저장하지 못했습니다: %s", e)
