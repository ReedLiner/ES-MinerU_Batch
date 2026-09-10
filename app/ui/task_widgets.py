"""拖拽区与任务行控件。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.collect import ConvertTask


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DropZone(QLabel):
    paths_dropped = Signal(list)

    def __init__(self):
        super().__init__(
            "把文件或文件夹拖到这里<br>"
            "<span style='font-size:11px; color:#8e8b82;'>"
            "PDF / Word / PPT / Excel / 图片 / HTML · 超过 200 页自动分段转换"
            "</span>"
        )
        self.setObjectName("dropZone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(110)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            self._hover(True)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._hover(False)

    def dropEvent(self, event):
        self._hover(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)

    def _hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class TaskRow(QWidget):
    cancel_requested = Signal(int)
    open_requested = Signal(int)

    def __init__(self, task: ConvertTask, row_id: int):
        super().__init__()
        self.task = task
        self.row_id = row_id
        self.status = "排队中"
        self.setObjectName("taskRow")
        self.setMinimumHeight(60)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        name = QLabel(_elide(task.source.name, 40))
        name.setToolTip(str(task.source))
        top.addWidget(name)
        top.addStretch(1)
        self.status_label = QLabel("排队中")
        self.status_label.setObjectName("statusLabel")
        top.addWidget(self.status_label)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(22)
        self.cancel_btn.setToolTip("取消该任务（尚未提交给 MinerU，不消耗额度）")
        self.cancel_btn.clicked.connect(lambda: self.cancel_requested.emit(self.row_id))
        top.addWidget(self.cancel_btn)
        self.abandon_btn = QPushButton("放弃")
        self.abandon_btn.setFixedHeight(22)
        self.abandon_btn.setToolTip("放弃等待该任务（MinerU 服务端可能仍会完成转换并消耗额度）")
        self.abandon_btn.clicked.connect(lambda: self.cancel_requested.emit(self.row_id))
        self.abandon_btn.hide()
        top.addWidget(self.abandon_btn)
        self.open_btn = QPushButton("打开")
        self.open_btn.setFixedHeight(22)
        self.open_btn.setToolTip("打开输出文件所在文件夹")
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.row_id))
        self.open_btn.hide()
        top.addWidget(self.open_btn)
        layout.addLayout(top)

        bottom = QHBoxLayout()
        output = QLabel(_elide(str(task.output_md), 68))
        output.setObjectName("subtle")
        output.setToolTip(str(task.output_md))
        bottom.addWidget(output)
        bottom.addStretch(1)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.bar.setFixedWidth(140)
        self.bar.setFixedHeight(10)
        self.bar.setTextVisible(False)
        bottom.addWidget(self.bar)
        layout.addLayout(bottom)

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def _set_state(self, state: str | None) -> None:
        self.status_label.setProperty("state", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def set_busy(self) -> None:
        self.status = "转换中"
        self.status_label.setText("转换中")
        self._set_state(None)
        self.bar.setRange(0, 0)
        self.cancel_btn.hide()
        self.abandon_btn.show()

    def set_done(self, ok: bool) -> None:
        self.status = "完成" if ok else "失败"
        self.status_label.setText(self.status)
        self._set_state("done" if ok else "failed")
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        self.cancel_btn.hide()
        self.abandon_btn.hide()
        self.open_btn.setVisible(ok)
        if not ok:
            self.bar.setProperty("failed", True)
            self.style().unpolish(self.bar)
            self.style().polish(self.bar)

    def set_cancelled(self, msg: str) -> None:
        self.status = "已取消"
        self.status_label.setText("已取消")
        self._set_state("cancelled")
        self.setToolTip(msg)
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.cancel_btn.hide()
        self.abandon_btn.hide()
        self.open_btn.hide()
