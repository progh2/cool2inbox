"""앱 컨트롤러 — 트레이 시그널을 실제 동작에 연결한다.

트레이(`ui/tray.py`)는 아무 일도 하지 않고 시그널만 낸다. 그 시그널을 받아 설정을 읽고
폴더를 열고 워커를 돌리는 것이 여기다. v0.1 에서는 폴링·설정 창이 아직 없어 자리만 잡아 둔다.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject

from src import autostart, config as cfg
from src import osutil
from src.logging_setup import log_path
from src.sources.attachments import AttachmentFinder
from src.sources.coolm import CoolmError
from src.sources.watcher import Watcher
from src.state import StateDB
from src.writer.backfill import Backfill
from src.ui.log_dialog import LogDialog
from src.ui.progress_dialog import BackfillProgressDialog
from src.ui.settings_dialog import SettingsDialog
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
        self._settings = None                # 열려 있는 설정 창
        self._logs = None                    # 열려 있는 로그 창
        self._backfill = None                # 돌고 있는 백필
        self._progress = None
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

    def prompt_setup_if_needed(self) -> bool:
        """설정이 없으면 설정 창을 띄운다 (FR-7.1).

        정식 첫 실행 마법사는 #17 에서 이 자리를 대신한다. 그때까지는 설정 창으로 안내한다.
        """
        if self.config.is_configured():
            return False
        log.info("설정이 없어 설정 창을 엽니다.")
        self.open_settings()
        return True

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
        """설정 창 (FR-6). 이미 열려 있으면 앞으로 가져온다."""
        if self._settings is not None and self._settings.isVisible():
            self._settings.raise_()
            self._settings.activateWindow()
            return
        self._settings = self.build_settings_dialog()
        self._settings.show()

    def build_settings_dialog(self) -> SettingsDialog:
        """창을 만들고 시그널을 연결한다 (테스트에서 그대로 쓴다)."""
        dlg = SettingsDialog(self.config, stats=self.state.stats())
        dlg.coolm_test_requested.connect(lambda: self._test_coolm(dlg))
        dlg.recv_test_requested.connect(lambda: self._test_recv(dlg))
        dlg.rebuild_requested.connect(lambda: self._rebuild_history(dlg))
        dlg.clear_history_requested.connect(lambda: self._clear_history(dlg))
        dlg.backfill_requested.connect(self.start_backfill)
        dlg.applied.connect(self.on_settings_applied)
        return dlg

    # ---- 설정 창이 요청하는 동작

    def _test_coolm(self, dlg: SettingsDialog) -> None:
        from src.sources.coolm import CoolmReader

        path = dlg.pick_memo.value()
        try:
            with CoolmReader(path) as r:
                dlg.show_coolm_result(r.summary())
        except CoolmError as e:
            dlg.show_coolm_result(str(e), ok=False)

    def _test_recv(self, dlg: SettingsDialog) -> None:
        path = dlg.pick_recv.value()
        text = AttachmentFinder(path, dlg.spin_attach_minutes.value()).summary()
        dlg.show_recv_result(text, ok=text.startswith("연결 OK"))

    def _rebuild_history(self, dlg: SettingsDialog) -> None:
        n = self.state.rebuild_from_inbox(self.config.inbox.coolm_dir())
        dlg.set_stats(self.state.stats())
        self.tray.notify("cool2inbox", f"인박스에서 이력 {n}건을 되살렸습니다."
                         if n else "되살릴 이력이 없습니다.")

    def _clear_history(self, dlg: SettingsDialog) -> None:
        n = self.state.clear()
        self.config.coolm.last_message_key = 0
        self._save()
        dlg.set_stats(self.state.stats())
        self.tray.notify("cool2inbox", f"이력 {n}건을 지웠습니다.")

    def start_backfill(self) -> None:
        """이전 쪽지 모두 가져오기 (FR-7.5). 미리보기로 확인을 받고 시작한다."""
        from PySide6.QtWidgets import QMessageBox

        if self._backfill is not None and self._backfill.running:
            self.tray.notify("cool2inbox", "이미 가져오는 중입니다.")
            return
        if not self.config.is_configured():
            self.open_settings()
            return

        backfill = Backfill(self.config, self.state, self.watcher.importer, parent=self)
        try:
            preview = backfill.preview(self.watcher.memo_dir())
        except CoolmError as e:
            self.tray.notify("cool2inbox", str(e), error=True)
            return

        parent = self._settings if self._settings is not None else None
        if not preview.to_import:
            QMessageBox.information(parent, "이전 쪽지 가져오기", preview.describe())
            return
        answer = QMessageBox.question(
            parent, "이전 쪽지 가져오기",
            f"{preview.describe()}\n\n지금 가져올까요?\n"
            "이미 인박스에 있는 쪽지는 건너뜁니다. 중간에 취소할 수 있습니다.")
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._backfill = backfill
        self._progress = BackfillProgressDialog(preview.to_import, parent)
        self._progress.cancel_requested.connect(backfill.cancel)
        backfill.progress.connect(self.on_backfill_progress)
        backfill.finished.connect(self.on_backfill_finished)
        backfill.failed.connect(self.on_backfill_failed)
        self.tray.set_state(AppState.WORKING)
        self._progress.show()
        backfill.start(self.watcher.memo_dir())

    def on_backfill_progress(self, done: int, total: int, name: str) -> None:
        if self._progress is not None:
            self._progress.set_progress(done, total, name)

    def on_backfill_finished(self, summary) -> None:
        cancelled = self._backfill is not None and self._backfill.cancelled
        self._close_progress()
        self.refresh_state()
        if self._settings is not None:
            self._settings.set_stats(self.state.stats())
        head = "가져오기를 멈췄습니다" if cancelled else "이전 쪽지를 모두 가져왔습니다"
        self.tray.notify("cool2inbox", f"{head} — {summary.describe()}")
        log.info("백필 결과: %s", summary.describe())

    def on_backfill_failed(self, message: str) -> None:
        self._close_progress()
        self.refresh_state()
        self.tray.notify("cool2inbox", message, error=True)

    def _close_progress(self) -> None:
        if self._progress is not None:
            self._progress.cancel_requested.disconnect()
            self._progress.close()
            self._progress = None

    def on_settings_applied(self, config) -> None:
        """설정 저장 직후 — 재시작 없이 반영한다 (FR-6.6)."""
        self.config = config
        try:
            autostart.set_enabled(config.schedule.autostart)
        except autostart.AutostartError as e:
            log.warning("자동 실행 설정 실패: %s", e)
            self.tray.notify("cool2inbox", str(e), error=True)
        self.watcher.apply_config(config)
        self.refresh_state()
        log.info("설정을 반영했습니다.")

    def open_logs(self) -> None:
        """로그 보기 창 (FR-9.1). 이미 열려 있으면 새로 고쳐 앞으로 가져온다."""
        if self._logs is not None and self._logs.isVisible():
            self._logs.reload()
            self._logs.raise_()
            self._logs.activateWindow()
            return
        self._logs = LogDialog(log_path())
        self._logs.open_folder_requested.connect(lambda: osutil.open_folder(log_path().parent))
        self._logs.show()

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
