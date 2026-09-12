"""ES MinerU Batch 入口。

支持命令行传入文件/文件夹：ES MinerU Batch.exe a.pdf D:\资料
"""

from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from app.core import app_log
from app.core.config import load_key
from app.engine.errors import redact
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import APP_QSS


def _install_excepthook() -> None:
    """M6：windowed 模式下主线程异常会静默丢失，统一写日志（脱敏）。"""
    def _hook(exc_type, exc_value, exc_tb) -> None:
        try:
            summary = "".join(traceback.format_exception_only(exc_type, exc_value)).strip()
            app_log.get().error("未捕获异常：%s", redact(summary))
            detail = "".join(traceback.format_tb(exc_tb)).strip()
            if detail:
                app_log.get().error(redact(detail[-2000:]))
        except Exception:
            pass

    sys.excepthook = _hook


def _apply_font(app: QApplication) -> None:
    """字体：拉丁字符用 Segoe UI（Variable），中文回退微软雅黑，观感更清爽。"""
    font = QFont()
    font.setFamilies([
        "Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei",
    ])
    font.setPixelSize(13)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)


def main() -> int:
    log_path = app_log.setup()
    _install_excepthook()

    app = QApplication(sys.argv)
    app.setApplicationName("ES MinerU Batch")
    app.setStyleSheet(APP_QSS)
    _apply_font(app)
    app_log.get().info("程序启动")

    # M5：单实例保护（双开会竞写配置、重复转换）
    lock = QLockFile(str(Path(tempfile.gettempdir()) / "ESMinerUBatch SingleInstance.lock"))
    if not lock.tryLock(0):
        QMessageBox.warning(
            None, "已在运行",
            "ES MinerU Batch 已经在运行了。\n请使用已打开的窗口（可在任务栏找到）。",
        )
        return 0

    if not load_key():
        SettingsDialog().exec()
        if not load_key():
            app_log.get().info("未设置 Key，退出")
            return 0

    initial = [Path(p) for p in sys.argv[1:]]
    window = MainWindow(initial_paths=initial)
    window.show()
    app_log.get().info("日志位置：%s", log_path)
    ret = app.exec()
    lock.unlock()
    return ret


if __name__ == "__main__":
    sys.exit(main())
