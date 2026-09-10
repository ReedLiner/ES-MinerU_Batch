from logging.handlers import RotatingFileHandler

from app.core import app_log


def _rotating_handlers():
    return [h for h in app_log.get().handlers if isinstance(h, RotatingFileHandler)]


def test_setup_creates_log_file(tmp_path):
    path = app_log.setup(tmp_path / "logs")
    assert path.exists()
    app_log.get().info("hello")
    for h in _rotating_handlers():
        h.flush()
    assert "hello" in path.read_text(encoding="utf-8")


def test_setup_idempotent(tmp_path):
    app_log.setup(tmp_path)
    n1 = len(_rotating_handlers())
    app_log.setup(tmp_path)
    n2 = len(_rotating_handlers())
    assert n1 == n2 == 1


def test_log_path_under_dir(tmp_path):
    app_log.setup(tmp_path)
    assert app_log.log_path() == tmp_path / "app.log"
