"""설정 창과 마법사가 함께 쓰는 작은 위젯들."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QWidget)


class FolderPicker(QWidget):
    """경로 입력칸 + [찾아보기]. 필요하면 [연결 테스트] 버튼도 붙는다."""

    changed = Signal(str)
    test_requested = Signal()

    def __init__(self, title: str = "폴더 선택", with_test: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)

        self.edit = QLineEdit()
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.edit.textChanged.connect(self.changed.emit)
        row.addWidget(self.edit, 1)

        self.btn_browse = QPushButton("찾아보기…")
        self.btn_browse.clicked.connect(self.browse)
        row.addWidget(self.btn_browse)

        self.btn_test = None
        if with_test:
            self.btn_test = QPushButton("연결 테스트")
            self.btn_test.clicked.connect(self.test_requested.emit)
            row.addWidget(self.btn_test)

    def value(self) -> str:
        return self.edit.text().strip()

    def set_value(self, v: str) -> None:
        self.edit.setText(v or "")

    def browse(self) -> None:                    # pragma: no cover - 파일 대화상자
        start = self.value() or str(Path.home())
        got = QFileDialog.getExistingDirectory(self, self._title, start)
        if got:
            self.set_value(got)


class StatusLabel(QLabel):
    """연결 테스트 결과 한 줄. 성공/실패에 따라 색이 바뀐다."""

    OK = "color: #1a7f37;"
    BAD = "color: #b3261e;"
    PLAIN = "color: #6b7280;"

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet(self.PLAIN)

    def show_ok(self, text: str) -> None:
        self.setText("✅ " + text)
        self.setStyleSheet(self.OK)

    def show_bad(self, text: str) -> None:
        self.setText("⚠️ " + text)
        self.setStyleSheet(self.BAD)

    def show_plain(self, text: str) -> None:
        self.setText(text)
        self.setStyleSheet(self.PLAIN)
