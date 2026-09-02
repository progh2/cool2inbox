"""백필 진행률 창 (#19).

취소를 누르면 즉시 창을 닫지 않는다 — 워커가 지금 쓰고 있는 파일을 마저 끝내야 하므로
'취소하는 중…' 을 보여주고 워커가 끝났다고 알려 줄 때 닫는다.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QProgressBar, QVBoxLayout)


class BackfillProgressDialog(QDialog):
    cancel_requested = Signal()

    def __init__(self, total: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("이전 쪽지 가져오기")
        self.setModal(True)
        self.resize(460, 150)
        self._total = total

        self.label = QLabel(f"쪽지 {total:,}건을 인박스로 옮기는 중입니다…")
        self.label.setWordWrap(True)
        self.detail = QLabel(" ")
        self.detail.setStyleSheet("color: #6b7280;")
        self.detail.setWordWrap(True)

        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, total))
        self.bar.setValue(0)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.rejected.connect(self._on_cancel)

        v = QVBoxLayout(self)
        v.addWidget(self.label)
        v.addWidget(self.bar)
        v.addWidget(self.detail)
        v.addWidget(self.buttons)

    def set_progress(self, done: int, total: int, name: str = "") -> None:
        if total != self._total:
            self._total = total
            self.bar.setRange(0, max(1, total))
        self.bar.setValue(done)
        self.label.setText(f"{done:,} / {total:,}건")
        if name:
            self.detail.setText(name)

    def _on_cancel(self) -> None:
        self.buttons.setEnabled(False)
        self.label.setText("취소하는 중… 지금 저장 중인 쪽지까지만 끝냅니다.")
        self.cancel_requested.emit()

    def closeEvent(self, event) -> None:        # 창을 닫아도 워커에게 취소를 알린다
        self.cancel_requested.emit()
        super().closeEvent(event)
