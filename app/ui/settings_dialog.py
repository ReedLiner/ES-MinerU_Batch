"""API Key 与转换参数设置对话框。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.core import app_log
from app.core.config import (
    LANGUAGES,
    MAX_BATCH_FILES,
    clear_key,
    load_key,
    load_settings,
    masked,
    save_key,
    save_settings,
)

APPLY_URL = "https://mineru.net/apiManage"


class SettingsDialog(QDialog):
    key_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("MinerU API Key")
        title.setObjectName("appTitle")
        layout.addWidget(title)

        tip = QLabel(
            "每个使用的人都需要自己的 Key。\n"
            "点击下面按钮去 mineru.net 登录，在「API 管理」页生成后粘贴到此处："
        )
        tip.setObjectName("subtle")
        tip.setWordWrap(True)
        layout.addWidget(tip)

        apply_btn = QPushButton("打开 mineru.net 申请页面")
        apply_btn.clicked.connect(self._open_site)
        layout.addWidget(apply_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-...（已保存过可不填，留空则不修改）")
        layout.addWidget(self.key_edit)

        show_plain = QCheckBox("显示明文")
        show_plain.toggled.connect(self._toggle_echo)
        layout.addWidget(show_plain)

        self.current_label = QLabel()
        self.current_label.setObjectName("subtle")
        layout.addWidget(self.current_label)

        layout.addWidget(self._separator())

        section = QLabel("转换参数")
        section.setObjectName("sectionTitle")
        layout.addWidget(section)

        self.ocr_check = QCheckBox("启用 OCR（扫描版 PDF / 图片文字识别需要勾选）")
        layout.addWidget(self.ocr_check)

        lang_row = QHBoxLayout()
        lang_label = QLabel("文档语言")
        lang_row.addWidget(lang_label)
        self.lang_combo = QComboBox()
        for code, display in LANGUAGES.items():
            self.lang_combo.addItem(display, code)
        lang_row.addWidget(self.lang_combo, stretch=1)
        layout.addLayout(lang_row)

        layout.addWidget(self._separator())

        advanced = QLabel("输出与队列")
        advanced.setObjectName("sectionTitle")
        layout.addWidget(advanced)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("输出目录"))
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText("留空 = 输出到源文件旁 / 源文件夹同级的「同名（MinerU）」")
        out_row.addWidget(self.out_edit, stretch=1)
        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_output_dir)
        out_row.addWidget(browse_btn)
        layout.addLayout(out_row)

        self.rename_check = QCheckBox("同名输出自动加序号（a.md、a(1).md），不覆盖")
        layout.addWidget(self.rename_check)

        self.batch_check = QCheckBox("批量提速：一次最多 50 个文件一起提交（大 PDF / HTML 仍逐个转换）")
        layout.addWidget(self.batch_check)

        self.auto_open_check = QCheckBox("全部完成后自动打开输出文件夹")
        layout.addWidget(self.auto_open_check)

        note = QLabel("以上设置对新开始的转换任务生效；批量提速不会影响额度（按文件计费）。")
        note.setObjectName("subtle")
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QHBoxLayout()
        log_btn = QPushButton("打开日志")
        log_btn.clicked.connect(self._open_log)
        buttons.addWidget(log_btn)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        clear_btn = QPushButton("删除")
        clear_btn.clicked.connect(self._clear)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(save_btn)
        buttons.addWidget(clear_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._refresh()

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setObjectName("separator")
        line.setFixedHeight(1)
        return line

    def _refresh(self) -> None:
        key = load_key()
        self.current_label.setText(f"当前 Key：{masked(key)}" if key else "当前 Key：未设置")
        settings = load_settings()
        self.ocr_check.setChecked(settings["is_ocr"])
        idx = self.lang_combo.findData(settings["language"])
        if idx >= 0:
            self.lang_combo.setCurrentIndex(idx)
        self.out_edit.setText(settings["output_dir"])
        self.rename_check.setChecked(settings["rename_duplicates"])
        self.batch_check.setChecked(settings["batch_size"] > 1)
        self.auto_open_check.setChecked(settings["auto_open"])

    def _browse_output_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择统一输出目录")
        if path:
            self.out_edit.setText(path)

    @staticmethod
    def _open_log() -> None:
        folder = app_log.log_path().parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _toggle_echo(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.key_edit.setEchoMode(mode)

    def _open_site(self) -> None:
        QDesktopServices.openUrl(QUrl(APPLY_URL))

    def _save(self) -> None:
        key_text = self.key_edit.text().strip()
        if key_text:
            try:
                save_key(key_text)
            except ValueError as exc:
                QMessageBox.warning(self, "提示", str(exc))
                return
        try:
            save_settings({
                "is_ocr": self.ocr_check.isChecked(),
                "language": self.lang_combo.currentData(),
                "output_dir": self.out_edit.text().strip(),
                "rename_duplicates": self.rename_check.isChecked(),
                "batch_size": MAX_BATCH_FILES if self.batch_check.isChecked() else 1,
                "auto_open": self.auto_open_check.isChecked(),
            })
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.key_edit.clear()
        self._refresh()
        self.key_changed.emit()

    def _clear(self) -> None:
        ret = QMessageBox.question(
            self, "删除 Key",
            "确定删除已保存的 API Key 吗？\n（转换设置会保留，随时可以重新填写）",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        clear_key()
        self._refresh()
        self.key_changed.emit()
