"""시스템 트레이 아이콘 (FR-8).

창이 없는 앱이다. 사용자가 만나는 모든 조작이 이 메뉴 하나에 들어간다.
아이콘은 상태 5종 — 대기 / 배달 중 / 일시정지 / 오류 / 설정 필요.

이 클래스는 **아무 일도 하지 않는다.** 시그널만 내보내고 실제 동작은 컨트롤러가 맡는다.
그래야 트레이를 띄우지 않고도 나머지를 테스트할 수 있다.
"""
from __future__ import annotations

import sys
from enum import Enum
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from src import __version__


class AppState(Enum):
    """트레이 아이콘이 나타내는 상태 (FR-8.5)."""

    IDLE = "idle"          # 대기 — 가방 멘 펭귄
    WORKING = "working"    # 배달 중 — 폴링·저장 중 잠깐
    PAUSED = "paused"      # 일시정지 — 자는 펭귄
    ERROR = "error"        # 오류 — 고개 갸웃
    SETUP = "setup"        # 설정 필요 — 물음표


_LABEL = {
    AppState.IDLE: "대기 중",
    AppState.WORKING: "배달 중…",
    AppState.PAUSED: "일시정지",
    AppState.ERROR: "오류",
    AppState.SETUP: "설정이 필요합니다",
}


def assets_dir() -> Path:
    """PyInstaller 로 얼렸을 때도 찾을 수 있게."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "assets"


def state_icon(state: AppState) -> QIcon:
    """상태 아이콘. 파일이 없으면 기본 아이콘, 그것도 없으면 빈 QIcon (앱은 계속 뜬다)."""
    d = assets_dir()
    for candidate in (d / "penguin" / f"{state.value}.png", d / "icon.png"):
        if candidate.exists():
            return QIcon(str(candidate))
    return QIcon()


class Tray(QSystemTrayIcon):
    check_now_requested = Signal()
    pause_toggled = Signal(bool)        # True = 일시정지로 전환
    open_inbox_requested = Signal()
    settings_requested = Signal()
    logs_requested = Signal()
    about_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = AppState.IDLE
        self._paused = False
        self._detail = ""
        self._summary = "아직 확인하지 않았습니다"

        self._menu = QMenu()
        self.act_status = QAction("cool2inbox", self._menu)
        self.act_status.setEnabled(False)

        self.act_check = QAction("지금 확인", self._menu)
        self.act_check.triggered.connect(self.check_now_requested.emit)

        self.act_pause = QAction("일시정지", self._menu)
        self.act_pause.triggered.connect(self._toggle_pause)

        act_inbox = QAction("인박스 폴더 열기", self._menu)
        act_inbox.triggered.connect(self.open_inbox_requested.emit)

        act_settings = QAction("설정…", self._menu)
        act_settings.triggered.connect(self.settings_requested.emit)

        act_logs = QAction("로그 보기", self._menu)
        act_logs.triggered.connect(self.logs_requested.emit)

        act_about = QAction(f"cool2inbox {__version__} 정보", self._menu)
        act_about.triggered.connect(self.about_requested.emit)

        act_quit = QAction("종료", self._menu)
        act_quit.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(self.act_status)
        self._menu.addSeparator()
        self._menu.addAction(self.act_check)
        self._menu.addAction(self.act_pause)
        self._menu.addSeparator()
        self._menu.addAction(act_inbox)
        self._menu.addAction(act_settings)
        self._menu.addAction(act_logs)
        self._menu.addSeparator()
        self._menu.addAction(act_about)
        self._menu.addAction(act_quit)
        self.setContextMenu(self._menu)

        self.activated.connect(self._on_activated)
        self.set_state(AppState.IDLE)

    # ---- 상태

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def paused(self) -> bool:
        return self._paused

    def set_state(self, state: AppState, detail: str = "") -> None:
        """아이콘과 툴팁을 바꾼다. detail 은 오류 사유처럼 한 줄 덧붙일 말."""
        self._state = state
        self._detail = detail
        self.setIcon(state_icon(state))
        self._refresh_text()

    def set_paused(self, paused: bool) -> None:
        """컨트롤러가 실제로 멈춘 뒤 호출한다 (메뉴 글자와 아이콘을 맞춘다)."""
        self._paused = paused
        self.act_pause.setText("재개" if paused else "일시정지")
        self.act_check.setEnabled(not paused)
        if paused:
            self.set_state(AppState.PAUSED)
        elif self._state is AppState.PAUSED:
            self.set_state(AppState.IDLE)
        else:
            self._refresh_text()

    def set_summary(self, last_check: str = "", delivered_today: int = 0) -> None:
        """툴팁의 요약 줄 (FR-8.4)."""
        if last_check:
            self._summary = f"마지막 확인 {last_check}, 오늘 {delivered_today}건 배달"
        else:
            self._summary = "아직 확인하지 않았습니다"
        self._refresh_text()

    def tooltip_text(self) -> str:
        parts = [f"cool2inbox — {_LABEL[self._state]}", self._summary]
        if self._detail:
            parts.append(self._detail)
        return "\n".join(parts)

    def _refresh_text(self) -> None:
        text = self.tooltip_text()
        self.setToolTip(text)
        self.act_status.setText(text.replace("\n", " · "))

    # ---- 알림

    def notify(self, title: str, message: str, error: bool = False) -> None:
        """풍선 알림 (FR-8.6). 오류는 항상, 그 외는 컨트롤러가 설정을 보고 판단한다."""
        icon = QSystemTrayIcon.MessageIcon.Critical if error else QSystemTrayIcon.MessageIcon.Information
        self.showMessage(title, message, icon, 5000)

    # ---- 내부

    def _toggle_pause(self) -> None:
        self.pause_toggled.emit(not self._paused)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.open_inbox_requested.emit()
