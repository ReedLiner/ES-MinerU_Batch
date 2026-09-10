"""应用日志：写在本机 %LOCALAPPDATA%，便于排障。

只记录任务与错误摘要，绝不记录 API Key 等敏感信息。
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_LOCAL = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
LOG_DIR = _DEFAULT_LOCAL / "ES MinerU Batch"
LOG_FILE = "app.log"

_LOGGER_NAME = "es_mineru_batch"
_MAX_BYTES = 1024 * 1024
_BACKUPS = 3


def log_path() -> Path:
    return LOG_DIR / LOG_FILE


def setup(log_dir: Path | None = None) -> Path:
    """初始化日志文件（可重复调用，不会重复挂 handler）。"""
    global LOG_DIR
    if log_dir is not None:
        LOG_DIR = Path(log_dir)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = log_path()

    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    existed = [h for h in list(logger.handlers) if isinstance(h, RotatingFileHandler)]
    if any(Path(h.baseFilename) == path for h in existed) and len(existed) == 1:
        return path  # 已挂好且目标一致
    for h in existed:
        logger.removeHandler(h)
        h.close()

    handler = RotatingFileHandler(
        path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    return path


def get() -> logging.Logger:
    return logging.getLogger(_LOGGER_NAME)
