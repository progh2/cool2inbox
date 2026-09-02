"""로그 보기 창 (#20, FR-9.1).

로그 파일 전체를 메모리에 올리지 않는다 — 회전 상한이 1MB 라 크지는 않지만, 사용자가 보고 싶은
것은 언제나 **끝부분**이다. 마지막 N줄만 읽어 보여주고 새로 고칠 수 있게 한다.

로그에는 쪽지 본문·제목이 들어가지 않는다 (FR-9.2). 그래서 이 창을 그대로 캡처해 공유해도 된다.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout)

TAIL_LINES = 500
READ_BYTES = 512 * 1024      # 끝에서 이만큼만 읽는다


def tail(path: str | Path, lines: int = TAIL_LINES) -> str:
    """파일 끝 몇 줄. 없으면 안내 문구."""
    p = Path(path)
    if not p.exists():
        return "(아직 기록된 로그가 없습니다)"
    try:
        size = p.stat().st_size
        with open(p, "rb") as f:
            if size > READ_BYTES:
                f.seek(size - READ_BYTES)
                f.readline()             # 잘린 첫 줄은 버린다
            data = f.read()
    except OSError as e:
        return f"(로그를 읽지 못했습니다: {e})"
    text = data.decode("utf-8", "replace")
    return "\n".join(text.splitlines()[-lines:])


class LogDialog(QDialog):
    open_folder_requested = Signal()

    def __init__(self, log_path: str | Path, parent=None):
        super().__init__(parent)
        self.log_path = Path(log_path)
        self.setWindowTitle("cool2inbox 로그")
        self.resize(760, 520)

        self.path_label = QLabel(str(self.log_path))
        self.path_label.setStyleSheet("color: #6b7280;")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        note = QLabel("쪽지 본문과 제목은 로그에 남기지 않습니다.")
        note.setStyleSheet("color: #6b7280;")

        row = QHBoxLayout()
        self.btn_refresh = QPushButton("새로 고침")
        self.btn_refresh.clicked.connect(self.reload)
        self.btn_folder = QPushButton("폴더 열기")
        self.btn_folder.clicked.connect(self.open_folder_requested.emit)
        row.addWidget(self.btn_refresh)
        row.addWidget(self.btn_folder)
        row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)

        v = QVBoxLayout(self)
        v.addWidget(self.path_label)
        v.addWidget(self.view, 1)
        v.addWidget(note)
        v.addLayout(row)
        v.addWidget(buttons)

        self.reload()

    def reload(self) -> None:
        self.view.setPlainText(tail(self.log_path))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())          # 항상 끝을 보여준다
