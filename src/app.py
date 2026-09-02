"""앱 컨트롤러 — 트레이 시그널을 실제 동작에 연결한다.

트레이(`ui/tray.py`)는 아무 일도 하지 않고 시그널만 낸다. 그 시그널을 받아 설정을 읽고
폴더를 열고 워커를 돌리는 것이 여기다. v0.1 에서는 폴링·설정 창이 아직 없어 자리만 잡아 둔다.
"""
from __future__ import annotations

import logging

from src import config as cfg
from src import osutil
from src.logging_setup import log_path
from src.ui.tray import AppState, Tray

log = logging.getLogger(__name__)


class AppController:
    def __init__(self, app, config: cfg.Config | None = None, tray: Tray | None = None):
        self.app = app
        self.config = config if config is not None else cfg.Config.load()
        self.tray = tray if tray is not None else Tray()
        self.instance_server = None          # main 이 넣어 준다 (종료할 때 닫는다)
        self._connect()
        self.refresh_state()

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
        """지금 확인 (FR-5.3). 폴링은 #14 에서 붙인다."""
        if not self.config.is_configured():
            self.open_settings()
            return
        log.info("지금 확인 요청 — 폴링은 아직 구현 전입니다.")
        self.tray.notify("cool2inbox", "쪽지 확인 기능은 아직 준비 중입니다.")

    def set_paused(self, paused: bool) -> None:
        """일시정지/재개 (FR-5.2). 설정에 남겨 다음 실행에도 유지한다."""
        self.config.schedule.paused = bool(paused)
        self._save()
        self.tray.set_paused(bool(paused))
        log.info("일시정지 %s", "켬" if paused else "끔")

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
        self._save()
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
