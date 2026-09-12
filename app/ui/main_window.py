"""主窗口：拖拽 / 选择 → 收集 → 队列 → 结果。"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from app.core.collect import collect_paths
from app.core.config import load_key, load_settings
from app.ui.settings_dialog import SettingsDialog
from app.ui.task_widgets import DropZone, TaskRow
from app.ui.theme import ACCENT
from app.ui.worker import NOT_SUBMITTED_MSG, ConvertWorker


class MainWindow(QMainWindow):
    def __init__(self, initial_paths: list[Path] | None = None):
        super().__init__()
        self.setWindowTitle("ES MinerU Batch")
        self.resize(760, 600)             # 默认尺寸
        self.setMinimumSize(660, 520)     # 允许拖拽边缘自由缩放

        self._rows: list[TaskRow] = []
        self._rows_by_id: dict[int, TaskRow] = {}
        self._worker: ConvertWorker | None = None
        self._next_id = 0
        self._stopped = False
        self._initial_paths = list(initial_paths or [])

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        brand_mark = QFrame()
        brand_mark.setObjectName("brandMark")
        brand_mark.setFixedSize(12, 12)
        header.addWidget(brand_mark)
        header.addSpacing(8)
        title = QLabel("ES MinerU Batch")
        title.setObjectName("appTitle")
        header.addWidget(title)
        header.addStretch(1)
        settings_btn = QPushButton("⚙ 设置")
        settings_btn.clicked.connect(self._open_settings)
        header.addWidget(settings_btn)
        layout.addLayout(header)

        self.drop_zone = DropZone()
        self.drop_zone.paths_dropped.connect(self._on_paths)
        layout.addWidget(self.drop_zone)

        pick_row = QHBoxLayout()
        pick_file = QPushButton("选择文件…")
        pick_file.clicked.connect(self._pick_files)
        pick_dir = QPushButton("选择文件夹…")
        pick_dir.clicked.connect(self._pick_folder)
        pick_row.addWidget(pick_file)
        pick_row.addWidget(pick_dir)
        pick_row.addStretch(1)
        layout.addLayout(pick_row)

        self.task_list = QListWidget()
        self.task_list.setMinimumHeight(220)
        self.task_list.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.task_list, stretch=1)

        footer = QVBoxLayout()
        footer.setSpacing(6)
        self.overall = QProgressBar()
        footer.addWidget(self.overall)
        bottom = QHBoxLayout()
        self.summary = QLabel("拖入文件或文件夹开始转换")
        self.summary.setObjectName("subtle")
        bottom.addWidget(self.summary)
        bottom.addStretch(1)
        self.stop_btn = QPushButton("全部停止")
        self.stop_btn.setToolTip("中断当前转换，并取消所有尚未开始的任务")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_all)
        bottom.addWidget(self.stop_btn)
        clear_btn = QPushButton("清空已完成")
        clear_btn.clicked.connect(self._clear_finished)
        bottom.addWidget(clear_btn)
        footer.addLayout(bottom)
        layout.addLayout(footer)

        self._tray = QSystemTrayIcon(self._tray_icon(), self)
        self._tray.setVisible(False)
        self._tray.messageClicked.connect(self._auto_open_last_output)
        self._tray_timer = QTimer(self)
        self._tray_timer.setSingleShot(True)
        self._tray_timer.timeout.connect(self._hide_tray)

        if self._initial_paths:
            QTimer.singleShot(0, lambda: self._on_paths(self._initial_paths))

    # ---------- 任务来源 ----------

    def _pick_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要转换的文件", "",
            "支持的文件 (*.pdf *.doc *.docx *.ppt *.pptx *.xls *.xlsx *.png *.jpg *.jpeg *.bmp *.webp *.html *.htm);;所有文件 (*.*)",
        )
        if paths:
            self._on_paths([Path(p) for p in paths])

    def _pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择要转换的文件夹")
        if path:
            self._on_paths([Path(path)])

    # ---------- 拖入 ----------

    def _on_paths(self, paths: list[Path]) -> None:
        settings = load_settings()
        out_dir = Path(settings["output_dir"]) if settings["output_dir"] else None
        tasks, skipped, collisions, errors = collect_paths(
            paths, output_dir=out_dir, rename_duplicates=settings["rename_duplicates"]
        )
        # M4/M7：仅按“仍在排队/转换中”的行去重；失败/取消/完成的行允许重拖重新入队
        existing = {
            (os.path.normcase(str(row.task.source)), os.path.normcase(str(row.task.output_md)))
            for row in self._rows if row.status in ("排队中", "转换中")
        }
        fresh = [
            t for t in tasks
            if (os.path.normcase(str(t.source)), os.path.normcase(str(t.output_md))) not in existing
        ]
        for t in fresh:
            row = TaskRow(t, self._next_id)
            self._next_id += 1
            row.cancel_requested.connect(self._on_row_cancel)
            row.open_requested.connect(self._on_row_open)
            self._rows.append(row)
            self._rows_by_id[row.row_id] = row
            row.adjustSize()
            hint = row.sizeHint()
            hint.setHeight(max(hint.height(), 66))  # 兜底行高，避免状态文字被裁切
            item = QListWidgetItem()
            item.setSizeHint(hint)
            self.task_list.addItem(item)
            self.task_list.setItemWidget(item, row)

        if collisions:
            lines = "\n".join(
                f"{out.name} ← {', '.join(s.name for s in srcs)}" for out, srcs in collisions
            )
            QMessageBox.warning(
                self, "同名冲突",
                "以下文件会生成同名 Markdown，后转的会覆盖先转的：\n" + lines,
            )
        if errors:
            lines = "\n".join(f"{p}" for p, _reason in errors[:10])
            more = f"\n…等共 {len(errors)} 个" if len(errors) > 10 else ""
            QMessageBox.warning(
                self, "部分路径无法访问",
                f"以下 {len(errors)} 个文件/文件夹无法读取（多为无权限）：\n{lines}{more}",
            )
        if skipped:
            self.summary.setText(f"已跳过 {len(skipped)} 个不支持的文件")
        if fresh:
            self._stopped = False  # 有新任务进来，解除"已停止"状态
            if self._worker is not None:
                # 队列运行中加入的新任务也纳入总进度
                self.overall.setMaximum(self.overall.maximum() + len(fresh))
            self._start_worker()

    # ---------- 队列 ----------

    def _row_by_id(self, row_id: int) -> TaskRow | None:
        return self._rows_by_id.get(row_id)

    def _start_worker(self) -> None:
        if self._worker is not None:
            return
        pending = [row for row in self._rows if row.status == "排队中"]
        if not pending:
            return
        key = load_key()
        if not key:
            QMessageBox.warning(self, "未设置 Key", "请先在设置里填入 MinerU API Key。")
            self._open_settings()
            key = load_key()
            if not key:
                self.summary.setText("未设置 API Key，任务未开始（点「⚙ 设置」填写）")
                return
        self.overall.setMaximum(len(pending))
        self.overall.setValue(0)
        settings = load_settings()
        items = [(row.row_id, row.task) for row in pending]
        worker = ConvertWorker(
            items, key, self,
            is_ocr=settings["is_ocr"],
            language=settings["language"],
            batch_size=settings["batch_size"],
        )
        worker.task_started.connect(self._on_task_started)
        worker.task_progress.connect(self._on_task_progress)
        worker.task_finished.connect(self._on_task_finished)
        worker.task_cancelled.connect(self._on_task_cancelled)
        worker.all_done.connect(self._on_all_done)
        self._worker = worker
        self.stop_btn.setEnabled(True)
        worker.start()

    def _stop_all(self) -> None:
        """全部停止：中断当前转换，其余排队任务一律不再提交。"""
        worker = self._worker
        if worker is None:
            for row in self._rows:
                if row.status == "排队中":
                    row.set_cancelled(NOT_SUBMITTED_MSG)
            self.summary.setText("已停止：没有正在进行的转换")
            return
        self._stopped = True
        self.stop_btn.setEnabled(False)
        worker.cancel_all()
        # 排队中的行立即标记取消（含运行中新加入、还不归 worker 管的），
        # 正在转换的那一行交给 worker 的信号收尾
        for row in self._rows:
            if row.status == "排队中":
                worker.cancel(row.row_id)
                row.set_cancelled(NOT_SUBMITTED_MSG)
        self.summary.setText("正在停止…（当前任务会中断，其余排队任务不再提交）")

    def _on_row_cancel(self, row_id: int) -> None:
        row = self._row_by_id(row_id)
        if row is None or row.status not in ("排队中", "转换中"):
            return
        if self._worker is not None and self._worker.cancel(row_id):
            return  # 由 worker 发信号更新该行
        row.set_cancelled(NOT_SUBMITTED_MSG)

    def _on_row_open(self, row_id: int) -> None:
        row = self._row_by_id(row_id)
        if row is not None:
            self._open_folder(row.task.output_md.parent)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        idx = self.task_list.row(item)
        if 0 <= idx < len(self._rows):
            self._open_folder(self._rows[idx].task.output_md.parent)

    def _on_task_started(self, row_id: int) -> None:
        row = self._row_by_id(row_id)
        if row is not None:
            row.set_busy()

    def _on_task_progress(self, row_id: int, msg: str) -> None:
        row = self._row_by_id(row_id)
        if row is not None:
            row.set_status(msg)

    def _on_task_finished(self, row_id: int, ok: bool, msg: str) -> None:
        row = self._row_by_id(row_id)
        if row is not None:
            row.set_done(ok)
            row.setToolTip(msg)
        self.overall.setValue(self.overall.value() + 1)

    def _on_task_cancelled(self, row_id: int, msg: str) -> None:
        row = self._row_by_id(row_id)
        if row is not None:
            row.set_cancelled(msg)
        self.overall.setValue(self.overall.value() + 1)

    def _on_all_done(self, ok: int, fail: int, cancelled: int) -> None:
        parts = [f"成功 {ok} 个", f"失败 {fail} 个"]
        if cancelled:
            parts.append(f"取消 {cancelled} 个")
        text = "全部完成：" + "，".join(parts)
        if self._stopped:
            text = "已停止：" + "，".join(parts)
        self.summary.setText(text)
        self._worker = None
        self.stop_btn.setEnabled(False)
        if ok and load_settings()["auto_open"]:
            self._auto_open_last_output()
        self._notify("ES MinerU Batch", text)
        if not self._stopped:
            self._start_worker()  # 续跑：转换期间新加入的排队任务自动开始

    # ---------- 打开输出 / 通知 ----------

    def _auto_open_last_output(self) -> None:
        for row in reversed(self._rows):
            if row.status == "完成":
                self._open_folder(row.task.output_md.parent)
                return

    @staticmethod
    def _open_folder(folder: Path) -> None:
        folder = Path(folder)
        if not folder.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.parent)))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _notify(self, title: str, text: str) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable() and QSystemTrayIcon.supportsMessages():
            self._tray.setVisible(True)
            self._tray.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, 5000)
            self._tray_timer.start(8000)

    def _hide_tray(self) -> None:
        try:
            self._tray.setVisible(False)
        except RuntimeError:
            pass  # 窗口已关闭、底层对象已销毁

    @staticmethod
    def _tray_icon() -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill(QColor(ACCENT))
        return QIcon(pix)

    # ---------- 其他 ----------

    def closeEvent(self, event) -> None:
        """转换进行中关闭窗口：先确认，再安全收尾线程，避免 Qt 崩溃。"""
        self._tray_timer.stop()
        try:
            self._tray.setVisible(False)
        except RuntimeError:
            pass
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel_all()
        worker = self._worker
        if worker is not None and worker.isRunning():
            ret = QMessageBox.question(
                self, "转换进行中",
                "还有任务在转换，退出会中断当前转换。\n"
                "已完成的分段会被保留，下次重试可续跑。确定退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for signal, slot in (
                (worker.task_started, self._on_task_started),
                (worker.task_progress, self._on_task_progress),
                (worker.task_finished, self._on_task_finished),
                (worker.task_cancelled, self._on_task_cancelled),
                (worker.all_done, self._on_all_done),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            worker.requestInterruption()
            worker.quit()
            if not worker.wait(3000):
                worker.terminate()
                worker.wait(2000)
            self._worker = None
        event.accept()

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _clear_finished(self) -> None:
        for i in reversed(range(len(self._rows))):
            if self._rows[i].status in ("完成", "失败", "已取消"):
                self.task_list.takeItem(i)
                self._rows_by_id.pop(self._rows[i].row_id, None)
                del self._rows[i]
