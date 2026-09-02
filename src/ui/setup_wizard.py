"""첫 실행 설정 마법사 (#17, FR-7.1~7.4).

설정 창과 같은 값을 다루지만 목적이 다르다. 설정 창은 "이미 아는 것을 고치는" 곳이고,
마법사는 "아무것도 모르는 사람이 5분 안에 쓰기 시작하는" 곳이다. 그래서
**빈 칸을 최대한 미리 채워 준다** — 쿨메신저 폴더도 드롭박스 인박스도 자동으로 찾아 넣는다.

취소해도 프로그램을 끝내지 않는다. 일시정지 상태로 트레이에 남는다 (FR-7.4).
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QDialog, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QSpinBox, QStackedWidget, QVBoxLayout,
                               QWidget)

from src import osutil
from src.config import POLL_MAX, POLL_MIN, Config
from src.sources.attachments import AttachmentFinder, default_recv_dir
from src.sources.coolm import CoolmError, CoolmReader, default_memo_dir
from src.ui.tray import assets_dir
from src.ui.widgets import FolderPicker, StatusLabel

log = logging.getLogger(__name__)

# 과거 쪽지를 어떻게 할 것인가 (FR-7.3)
FUTURE_ONLY, RECENT, ALL = "future", "recent", "all"
DEFAULT_RECENT = 20


def _title(text: str) -> QLabel:
    label = QLabel(f"<h2>{text}</h2>")
    label.setTextFormat(Qt.TextFormat.RichText)
    return label


def _body(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class SetupWizard(QDialog):
    completed = Signal(object, str, int)     # Config, 과거 쪽지 처리 방식, 최근 N건

    def __init__(self, config: Config | None = None, parent=None):
        super().__init__(parent)
        self.config = config or Config()
        self.setWindowTitle("cool2inbox 시작하기")
        self.resize(620, 520)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_welcome())
        self.stack.addWidget(self._page_coolm())
        self.stack.addWidget(self._page_inbox())
        self.stack.addWidget(self._page_schedule())
        self.stack.addWidget(self._page_done())

        self.step_label = QLabel()
        self.step_label.setStyleSheet("color: #6b7280;")
        self.btn_back = QPushButton("이전")
        self.btn_next = QPushButton("다음")
        self.btn_cancel = QPushButton("나중에 하기")
        self.btn_back.clicked.connect(self.go_back)
        self.btn_next.clicked.connect(self.go_next)
        self.btn_cancel.clicked.connect(self.reject)

        row = QHBoxLayout()
        row.addWidget(self.step_label)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_back)
        row.addWidget(self.btn_next)

        v = QVBoxLayout(self)
        v.addWidget(self.stack, 1)
        v.addLayout(row)

        self.prefill()
        self._sync_buttons()

    # ---- 페이지

    def _page_welcome(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        icon = QLabel()
        png = assets_dir() / "penguin" / "idle.png"
        if png.exists():
            icon.setPixmap(QPixmap(str(png)).scaledToWidth(
                160, Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addStretch(1)
        v.addWidget(icon)
        v.addWidget(_title("<div align='center'>쿨메신저 쪽지를 인박스로 배달합니다</div>"))
        v.addWidget(_body(
            "<div align='center'>새 쪽지를 마크다운 파일 하나로 만들어 드롭박스에 저장합니다.<br>"
            "첨부파일도 함께 가져옵니다.<br><br>"
            "폴더 두 곳만 정하면 끝납니다. 대부분 자동으로 찾아 뒀습니다.</div>"))
        v.addStretch(2)
        return w

    def _page_coolm(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("쿨메신저 폴더"))
        v.addWidget(_body("쪽지가 저장된 폴더입니다. 쿨메신저를 설치했다면 자동으로 찾습니다."))

        self.pick_memo = FolderPicker("쿨메신저 쪽지 폴더", with_test=True)
        self.pick_memo.test_requested.connect(self.test_coolm)
        self.pick_memo.changed.connect(lambda _: self._sync_buttons())
        self.lbl_memo = StatusLabel()
        v.addWidget(QLabel("쪽지 폴더"))
        v.addWidget(self.pick_memo)
        v.addWidget(self.lbl_memo)

        v.addSpacing(12)
        self.pick_recv = FolderPicker("쿨메신저 수신 파일 폴더", with_test=True)
        self.pick_recv.test_requested.connect(self.test_recv)
        self.lbl_recv = StatusLabel("비워 두어도 됩니다. 그러면 첨부는 파일 이름만 기록합니다.")
        v.addWidget(QLabel("받은 파일 폴더 (선택)"))
        v.addWidget(self.pick_recv)
        v.addWidget(self.lbl_recv)
        v.addStretch(1)
        return w

    def _page_inbox(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("인박스 폴더"))
        v.addWidget(_body("쪽지를 저장할 곳입니다. 드롭박스 폴더를 찾아 인박스를 추천해 뒀습니다."))

        self.pick_inbox = FolderPicker("인박스 폴더")
        self.pick_inbox.changed.connect(lambda _: (self._update_preview(), self._sync_buttons()))
        v.addWidget(self.pick_inbox)
        self.lbl_preview = StatusLabel()
        v.addWidget(self.lbl_preview)

        warn = _body("⚠️ 저장한 파일은 드롭박스로 동기화됩니다. 업무 쪽지를 외부 클라우드에 "
                     "올려도 되는지 소속 기관의 규정을 먼저 확인해 주세요.")
        warn.setStyleSheet("color: #92400e;")
        v.addWidget(warn)
        v.addStretch(1)
        return w

    def _page_schedule(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("확인 주기와 과거 쪽지"))

        row = QHBoxLayout()
        self.spin_minutes = QSpinBox()
        self.spin_minutes.setRange(POLL_MIN, POLL_MAX)
        self.spin_minutes.setSuffix(" 분마다 확인")
        row.addWidget(self.spin_minutes)
        row.addStretch(1)
        v.addLayout(row)

        v.addSpacing(12)
        v.addWidget(_body("<b>지금까지 받은 쪽지는 어떻게 할까요?</b>"))
        self.past_group = QButtonGroup(self)
        self.rb_future = QRadioButton("앞으로 오는 쪽지만 가져오기")
        self.rb_recent = QRadioButton("최근 쪽지부터 가져오기")
        self.rb_all = QRadioButton("지금까지 받은 쪽지 전부 가져오기")
        for i, rb in enumerate((self.rb_future, self.rb_recent, self.rb_all)):
            self.past_group.addButton(rb, i)
            v.addWidget(rb)
        self.rb_future.setChecked(True)

        recent_row = QHBoxLayout()
        recent_row.addSpacing(24)
        self.spin_recent = QSpinBox()
        self.spin_recent.setRange(1, 1000)
        self.spin_recent.setValue(DEFAULT_RECENT)
        self.spin_recent.setSuffix(" 건")
        self.spin_recent.setEnabled(False)
        self.rb_recent.toggled.connect(self.spin_recent.setEnabled)
        recent_row.addWidget(self.spin_recent)
        recent_row.addStretch(1)
        v.addLayout(recent_row)

        v.addWidget(_body("전부 가져오기는 쪽지가 많으면 시간이 걸립니다. "
                          "중간에 멈출 수 있고, 나중에 설정에서 다시 할 수도 있습니다."))
        v.addStretch(1)
        return w

    def _page_done(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(_title("준비됐습니다"))
        self.lbl_done = _body("")
        v.addWidget(self.lbl_done)
        self.chk_autostart = QCheckBox("컴퓨터를 켤 때 자동으로 실행하기")
        self.chk_autostart.setChecked(True)
        v.addWidget(self.chk_autostart)
        self.chk_notify = QCheckBox("쪽지를 배달하면 알림 보여주기")
        self.chk_notify.setChecked(True)
        v.addWidget(self.chk_notify)
        v.addWidget(_body("프로그램은 트레이에 남아 조용히 일합니다. "
                          "언제든 트레이 아이콘을 눌러 잠시 멈추거나 설정을 바꿀 수 있습니다."))
        v.addStretch(1)
        return w

    # ---- 자동 채우기

    def prefill(self) -> None:
        """아는 것은 미리 채운다. 이미 설정이 있으면 그것이 우선이다."""
        self.pick_memo.set_value(self.config.coolm.memo_dir or default_memo_dir())
        self.pick_recv.set_value(self.config.coolm.recv_file_dir or default_recv_dir())
        self.pick_inbox.set_value(self.config.inbox.root_dir or osutil.suggest_inbox_dir())
        self.spin_minutes.setValue(self.config.schedule.poll_minutes)
        self._update_preview()

    # ---- 이동

    def go_next(self) -> None:
        if self.stack.currentIndex() == self.stack.count() - 1:
            self.finish()
            return
        self.stack.setCurrentIndex(self.stack.currentIndex() + 1)
        if self.stack.currentIndex() == self.stack.count() - 1:
            self._update_done_text()
        self._sync_buttons()

    def go_back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        i, last = self.stack.currentIndex(), self.stack.count() - 1
        self.step_label.setText(f"{i + 1} / {last + 1}")
        self.btn_back.setEnabled(i > 0)
        self.btn_next.setText("시작하기" if i == last else "다음")
        blocked = (i == 1 and not self.pick_memo.value()) or (i == 2 and not self.pick_inbox.value())
        self.btn_next.setEnabled(not blocked)

    # ---- 연결 테스트

    def test_coolm(self) -> None:
        try:
            with CoolmReader(self.pick_memo.value()) as r:
                self.lbl_memo.show_ok(r.summary())
        except CoolmError as e:
            self.lbl_memo.show_bad(str(e))

    def test_recv(self) -> None:
        text = AttachmentFinder(self.pick_recv.value()).summary()
        (self.lbl_recv.show_ok if text.startswith("연결 OK") else self.lbl_recv.show_bad)(text)

    # ---- 결과

    def past_choice(self) -> str:
        return {0: FUTURE_ONLY, 1: RECENT, 2: ALL}[self.past_group.checkedId()]

    def apply_to_config(self) -> Config:
        c = self.config
        c.coolm.memo_dir = self.pick_memo.value()
        c.coolm.recv_file_dir = self.pick_recv.value()
        c.inbox.root_dir = self.pick_inbox.value()
        c.schedule.poll_minutes = self.spin_minutes.value()
        c.schedule.autostart = self.chk_autostart.isChecked()
        c.schedule.notify = self.chk_notify.isChecked()
        c.schedule.paused = False
        c.ui.first_run_done = True
        c.normalize()
        return c

    def finish(self) -> None:
        c = self.apply_to_config()
        self.completed.emit(c, self.past_choice(), self.spin_recent.value())
        self.accept()

    # ---- 표시 갱신

    def _update_preview(self) -> None:
        root = self.pick_inbox.value()
        if not root:
            self.lbl_preview.show_plain("폴더를 고르면 저장 위치를 보여드립니다.")
            return
        name = self.config.inbox.coolm_folder_name
        self.lbl_preview.show_plain(f"쪽지는 여기에 쌓입니다 → {root}/{name}/")

    def _update_done_text(self) -> None:
        choice = {FUTURE_ONLY: "앞으로 오는 쪽지부터 가져옵니다.",
                  RECENT: f"최근 {self.spin_recent.value()}건부터 가져옵니다.",
                  ALL: "지금까지 받은 쪽지를 모두 가져옵니다."}[self.past_choice()]
        self.lbl_done.setText(
            f"{self.spin_minutes.value()}분마다 쿨메신저를 확인합니다. {choice}<br><br>"
            f"저장 위치: {self.pick_inbox.value()}/{self.config.inbox.coolm_folder_name}/")
