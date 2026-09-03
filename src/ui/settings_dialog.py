"""설정 창 (#18, FR-6).

탭 5개 — 폴더 / 확인 주기 / 출력 형식 / 가져오기 / 정보.

이 창은 설정을 **읽고 쓰기만** 한다. 백필 실행이나 이력 복구 같은 실제 작업은 시그널로 넘긴다.
그래야 워커·상태 DB 없이도 창을 띄워 테스트할 수 있다.
"""
from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                               QPushButton, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from src import __version__
from src.config import POLL_MAX, POLL_MIN, Config
from src.sources.coolm import Message
from src.ui.tray import assets_dir
from src.ui.widgets import FolderPicker, StatusLabel
from src.writer import naming

log = logging.getLogger(__name__)

FORMAT_HELP = "쓸 수 있는 항목: {date} {time} {sender} {title} {key}"


class SettingsDialog(QDialog):
    coolm_test_requested = Signal()
    recv_test_requested = Signal()
    backfill_requested = Signal()
    rebuild_requested = Signal()
    clear_history_requested = Signal()
    applied = Signal(object)             # 저장된 Config

    def __init__(self, config: Config, stats: dict | None = None, parent=None):
        super().__init__(parent)
        self.config = config
        self._stats = stats or {}
        self.setWindowTitle("cool2inbox 설정")
        self.resize(640, 520)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._folders_tab(), "폴더")
        self.tabs.addTab(self._schedule_tab(), "확인 주기")
        self.tabs.addTab(self._output_tab(), "출력 형식")
        self.tabs.addTab(self._import_tab(), "가져오기")
        self.tabs.addTab(self._about_tab(), "정보")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)

        self.load_from_config()

    # ---- 탭

    def _folders_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.pick_memo = FolderPicker("쿨메신저 쪽지 폴더", with_test=True)
        self.pick_memo.test_requested.connect(self.coolm_test_requested.emit)
        self.lbl_memo = StatusLabel("쪽지 DB(.udb)가 있는 폴더입니다. 보통 "
                                    "%LOCALAPPDATA%\\CoolMessenger\\Memo")
        form.addRow("쿨메신저 쪽지 폴더", self.pick_memo)
        form.addRow("", self.lbl_memo)

        self.pick_recv = FolderPicker("쿨메신저 수신 파일 폴더", with_test=True)
        self.pick_recv.test_requested.connect(self.recv_test_requested.emit)
        self.lbl_recv = StatusLabel("비워 두면 첨부는 파일 이름만 기록합니다. 보통 "
                                    "문서\\CoolMessenger Files\\Received Files")
        form.addRow("수신 파일 폴더", self.pick_recv)
        form.addRow("", self.lbl_recv)

        self.pick_inbox = FolderPicker("인박스 폴더")
        self.lbl_inbox = StatusLabel("드롭박스 인박스 폴더를 고르세요. 이 아래에 쪽지 폴더가 생깁니다.")
        form.addRow("인박스 폴더", self.pick_inbox)
        form.addRow("", self.lbl_inbox)

        self.edit_coolm_name = QLineEdit()
        self.edit_attach_name = QLineEdit()
        self.edit_coolm_name.textChanged.connect(self._update_path_preview)
        self.edit_attach_name.textChanged.connect(self._update_path_preview)
        self.pick_inbox.changed.connect(self._update_path_preview)
        form.addRow("쪽지 폴더 이름", self.edit_coolm_name)
        form.addRow("첨부파일 폴더 이름", self.edit_attach_name)

        self.lbl_paths = StatusLabel()
        form.addRow("저장 위치", self.lbl_paths)

        self.edit_archives = QPlainTextEdit()
        self.edit_archives.setPlaceholderText(
            "이전에 내보낸 쪽지를 다른 곳으로 옮겼다면 그 폴더를 한 줄에 하나씩 적으세요.\n"
            "여기 있는 쪽지는 '이미 가져온 것'으로 보고 다시 만들지 않습니다. 하위 폴더까지 살핍니다.")
        self.edit_archives.setFixedHeight(72)
        form.addRow("아카이브 폴더", self.edit_archives)

        warn = QLabel("⚠️ 저장되는 파일은 드롭박스로 동기화됩니다. 업무 쪽지의 외부 클라우드 "
                      "동기화가 조직 규정에 어긋나지 않는지 확인해 주세요.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: #92400e;")
        form.addRow("", warn)
        return w

    def _schedule_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.spin_minutes = QSpinBox()
        self.spin_minutes.setRange(POLL_MIN, POLL_MAX)
        self.spin_minutes.setSuffix(" 분마다")
        form.addRow("확인 주기", self.spin_minutes)

        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 1000)
        self.spin_max.setSuffix(" 건")
        form.addRow("한 번에 처리할 최대", self.spin_max)

        self.chk_autostart = QCheckBox("Windows 시작할 때 자동 실행")
        self.chk_notify = QCheckBox("배달했을 때 알림 표시 (오류는 항상 알립니다)")
        form.addRow("", self.chk_autostart)
        form.addRow("", self.chk_notify)

        self.spin_attach_minutes = QSpinBox()
        self.spin_attach_minutes.setRange(0, 24 * 60)
        self.spin_attach_minutes.setSuffix(" 분 (0 = 제한 없음)")
        form.addRow("첨부 시각 허용 오차", self.spin_attach_minutes)

        self.spin_attach_mb = QSpinBox()
        self.spin_attach_mb.setRange(0, 100000)
        self.spin_attach_mb.setSuffix(" MB (0 = 무제한)")
        form.addRow("첨부 최대 크기", self.spin_attach_mb)
        return w

    def _output_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.edit_format = QLineEdit()
        self.edit_format.textChanged.connect(self._update_name_preview)
        form.addRow("파일명 서식", self.edit_format)
        help_label = QLabel(FORMAT_HELP)
        help_label.setStyleSheet("color: #6b7280;")
        form.addRow("", help_label)

        self.lbl_preview = StatusLabel()
        form.addRow("미리보기", self.lbl_preview)

        box = QGroupBox("머리말에 넣을 항목")
        v = QVBoxLayout(box)
        self.chk_recipients = QCheckBox("받는 사람 목록")
        self.chk_cc = QCheckBox("참조 목록")
        self.chk_attachments = QCheckBox("첨부파일")
        self.chk_split = QCheckBox("인용된 이전 대화를 따로 분리")
        for c in (self.chk_recipients, self.chk_cc, self.chk_attachments, self.chk_split):
            v.addWidget(c)
        form.addRow(box)

        self.chk_sent = QCheckBox("내가 보낸 쪽지도 가져오기 (보낸쪽지 폴더에 따로 저장)")
        form.addRow("보낸 쪽지", self.chk_sent)
        return w

    def _import_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        self.lbl_stats = StatusLabel()
        v.addWidget(self.lbl_stats)

        btn_backfill = QPushButton("이전 쪽지 모두 가져오기…")
        btn_backfill.clicked.connect(self.backfill_requested.emit)
        v.addWidget(btn_backfill)

        btn_rebuild = QPushButton("인박스에서 이력 다시 읽기")
        btn_rebuild.setToolTip("인박스의 md 파일을 훑어 처리 이력을 되살립니다. "
                               "이력 파일을 잃어버렸을 때 씁니다.")
        btn_rebuild.clicked.connect(self.rebuild_requested.emit)
        v.addWidget(btn_rebuild)

        btn_clear = QPushButton("이력 초기화")
        btn_clear.setToolTip("처리 이력을 모두 지웁니다. 다음 가져오기에서 쪽지를 다시 저장합니다.")
        btn_clear.clicked.connect(self._confirm_clear)
        v.addWidget(btn_clear)
        v.addStretch(1)
        return w

    def _about_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        icon = QLabel()
        png = assets_dir() / "penguin" / "idle.png"
        if png.exists():
            icon.setPixmap(QPixmap(str(png)).scaledToWidth(96, Qt.TransformationMode.SmoothTransformation))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(icon)

        text = QLabel(
            f"<h3 style='text-align:center'>cool2inbox {__version__}</h3>"
            "<p style='text-align:center'>쿨메신저 쪽지를 드롭박스 인박스로 배달합니다.<br>"
            "쪽지 1건 = 마크다운 1파일, 첨부파일까지.</p>"
            "<p style='text-align:center'>이 프로그램은 쿨메신저를 <b>읽기만</b> 합니다. "
            "쪽지를 보내거나 읽음 처리하거나 삭제하지 않습니다.</p>"
            "<p style='text-align:center'>MIT License · "
            "<a href='https://github.com/progh2/cool2inbox'>github.com/progh2/cool2inbox</a></p>")
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        v.addWidget(text)
        v.addStretch(1)
        return w

    # ---- 값 주고받기

    def load_from_config(self) -> None:
        c = self.config
        self.pick_memo.set_value(c.coolm.memo_dir)
        self.pick_recv.set_value(c.coolm.recv_file_dir)
        self.pick_inbox.set_value(c.inbox.root_dir)
        self.edit_coolm_name.setText(c.inbox.coolm_folder_name)
        self.edit_attach_name.setText(c.inbox.attach_folder_name)
        self.edit_archives.setPlainText("\n".join(c.inbox.archive_dirs))

        self.spin_minutes.setValue(c.schedule.poll_minutes)
        self.spin_max.setValue(c.schedule.max_per_poll)
        self.chk_autostart.setChecked(c.schedule.autostart)
        self.chk_notify.setChecked(c.schedule.notify)
        self.spin_attach_minutes.setValue(c.coolm.attach_match_minutes)
        self.spin_attach_mb.setValue(c.inbox.max_attach_mb)

        self.edit_format.setText(c.output.filename_format)
        self.chk_recipients.setChecked(c.output.include_recipients)
        self.chk_cc.setChecked(c.output.include_cc)
        self.chk_attachments.setChecked(c.output.include_attachments)
        self.chk_split.setChecked(c.output.split_quoted)
        self.chk_sent.setChecked(c.coolm.include_sent)

        self._update_path_preview()
        self._update_name_preview()
        self.set_stats(self._stats)

    def apply_to_config(self, config: Config | None = None) -> Config:
        """화면 값을 Config 에 담는다 (저장하지는 않는다)."""
        c = config or self.config
        c.coolm.memo_dir = self.pick_memo.value()
        c.coolm.recv_file_dir = self.pick_recv.value()
        c.coolm.attach_match_minutes = self.spin_attach_minutes.value()
        c.inbox.root_dir = self.pick_inbox.value()
        c.inbox.coolm_folder_name = self.edit_coolm_name.text().strip()
        c.inbox.attach_folder_name = self.edit_attach_name.text().strip()
        c.inbox.archive_dirs = [ln.strip() for ln in self.edit_archives.toPlainText().splitlines() if ln.strip()]
        c.inbox.max_attach_mb = self.spin_attach_mb.value()
        c.schedule.poll_minutes = self.spin_minutes.value()
        c.schedule.max_per_poll = self.spin_max.value()
        c.schedule.autostart = self.chk_autostart.isChecked()
        c.schedule.notify = self.chk_notify.isChecked()
        c.output.filename_format = self.edit_format.text().strip()
        c.output.include_recipients = self.chk_recipients.isChecked()
        c.output.include_cc = self.chk_cc.isChecked()
        c.output.include_attachments = self.chk_attachments.isChecked()
        c.output.split_quoted = self.chk_split.isChecked()
        c.coolm.include_sent = self.chk_sent.isChecked()
        c.normalize()
        return c

    def save(self) -> None:
        """검증 → 저장 → applied 시그널. 문제가 있으면 창을 닫지 않는다 (FR-6.7)."""
        c = self.apply_to_config()
        problems = c.problems()
        if problems:
            QMessageBox.warning(self, "설정을 저장할 수 없습니다", "\n".join(f"• {p}" for p in problems))
            return
        try:
            c.save()
        except OSError as e:
            QMessageBox.critical(self, "저장 실패", f"설정을 저장하지 못했습니다:\n{e}")
            return
        self.applied.emit(c)
        self.accept()

    # ---- 표시 갱신

    def set_stats(self, stats: dict) -> None:
        self._stats = stats or {}
        n = self._stats.get("notes", 0)
        if not n:
            self.lbl_stats.show_plain("아직 가져온 쪽지가 없습니다.")
            return
        att = self._stats.get("attachments_ok", 0)
        last = self._stats.get("last_imported_at", "") or "-"
        pending = self._stats.get("attachments_pending_notes", 0)
        extra = f" · 첨부 미완료 {pending}건" if pending else ""
        self.lbl_stats.show_plain(f"가져온 쪽지 {n:,}건 · 첨부 {att:,}개 · 마지막 {last}{extra}")

    def show_coolm_result(self, text: str, ok: bool = True) -> None:
        (self.lbl_memo.show_ok if ok else self.lbl_memo.show_bad)(text)

    def show_recv_result(self, text: str, ok: bool = True) -> None:
        (self.lbl_recv.show_ok if ok else self.lbl_recv.show_bad)(text)

    def _update_path_preview(self) -> None:
        root = self.pick_inbox.value()
        if not root:
            self.lbl_paths.show_plain("인박스 폴더를 고르면 저장 위치가 표시됩니다.")
            return
        coolm = (self.edit_coolm_name.text().strip() or "쿨메신저")
        attach = (self.edit_attach_name.text().strip() or "첨부파일")
        self.lbl_paths.show_plain(f"{root}/{coolm}/  ·  {root}/{coolm}/{attach}/")

    def _update_name_preview(self) -> None:
        fmt = self.edit_format.text().strip() or naming.DEFAULT_FORMAT
        sample = Message(key=1234, received=datetime(2026, 9, 2, 17, 4),
                         sender="홍길동(hong)", title="2학기 교육과정 협의회", body="본문")
        try:
            self.lbl_preview.show_plain(naming.note_filename(sample, fmt))
        except Exception:                        # 사용자가 이상한 서식을 넣어도 창이 죽지 않게
            self.lbl_preview.show_bad("서식을 해석할 수 없습니다.")

    def _confirm_clear(self) -> None:
        ok = QMessageBox.question(
            self, "이력 초기화",
            "처리 이력을 모두 지웁니다.\n인박스의 파일은 지우지 않지만, 다음 가져오기에서 "
            "쪽지를 다시 저장합니다.\n\n계속할까요?")
        if ok == QMessageBox.StandardButton.Yes:
            self.clear_history_requested.emit()
