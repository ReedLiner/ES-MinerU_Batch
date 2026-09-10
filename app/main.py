"""ES MinerU Batch 入口。

支持命令行传入文件/文件夹：ES MinerU Batch.exe a.pdf D:\资料
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from app.core import app_log
from app.core.config import load_key
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import APP_QSS


def main() -> int:
    log_path = app_log.setup()
    app = QApplication(sys.argv)
    app.setApplicationName("ES MinerU Batch")
    app.setStyleSheet(APP_QSS)
    app_log.get().info("程序启动")

    if not load_key():
        SettingsDialog().exec()
        if not load_key():
            app_log.get().info("未设置 Key，退出")
            return 0

    initial = [Path(p) for p in sys.argv[1:]]
    window = MainWindow(initial_paths=initial)
    window.show()
    app_log.get().info("日志位置：%s", log_path)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
