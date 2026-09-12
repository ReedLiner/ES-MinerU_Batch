import json
import sys
import threading

import pytest

from app.core import config


@pytest.fixture()
def cfg_path(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    return path


def test_roundtrip(cfg_path):
    config.save_key("  sk-test-123  ")
    assert config.load_key() == "sk-test-123"


def test_load_key_missing(cfg_path):
    assert config.load_key() is None


def test_load_key_bad_json(cfg_path):
    cfg_path.write_text("{not json", encoding="utf-8")
    assert config.load_key() is None


def test_save_key_rejects_empty(cfg_path):
    with pytest.raises(ValueError):
        config.save_key("   ")
    assert not cfg_path.exists()


def test_key_roundtrip_and_not_in_plain_text(cfg_path):
    config.save_key("sk-super-secret")
    assert config.load_key() == "sk-super-secret"
    raw = cfg_path.read_text(encoding="utf-8")
    if config._dpapi_protect(b"probe") is not None:  # 本机支持加密时才校验
        assert "sk-super-secret" not in raw


def test_legacy_plain_key_still_readable(cfg_path):
    cfg_path.write_text(json.dumps({"api_key": "sk-legacy"}), encoding="utf-8")
    assert config.load_key() == "sk-legacy"


def test_key_falls_back_to_plain_when_unavailable(cfg_path, monkeypatch):
    monkeypatch.setattr(config, "_dpapi_protect", lambda _b: None)
    if sys.platform == "win32":
        # Windows 上不允许静默明文落盘（H6）
        with pytest.raises(RuntimeError):
            config.save_key("sk-plain")
        assert not cfg_path.exists()
    else:
        config.save_key("sk-plain")
        assert config.load_key() == "sk-plain"


def test_clear_key(cfg_path):
    config.save_key("sk-abc")
    config.clear_key()
    assert config.load_key() is None


def test_clear_key_keeps_settings(cfg_path):
    config.save_settings({"is_ocr": True, "language": "en"})
    config.save_key("sk-abc")
    config.clear_key()
    assert config.load_key() is None
    assert config.load_settings()["is_ocr"] is True
    assert config.load_settings()["language"] == "en"


def test_concurrent_saves_keep_key(cfg_path):
    """C1：两个线程并发保存设置，Key 不得丢失。"""
    config.save_key("sk-keep-me")
    config.save_settings({"output_dir": ""})

    def writer(tag: str) -> None:
        for i in range(60):
            config.save_settings({"output_dir": f"{tag}-{i}"})

    t1 = threading.Thread(target=writer, args=("A",))
    t2 = threading.Thread(target=writer, args=("B",))
    t1.start(); t2.start(); t1.join(); t2.join()

    raw = cfg_path.read_text(encoding="utf-8")
    data = json.loads(raw)  # 完整可解析
    assert config.load_key() == "sk-keep-me"
    assert data[config.SETTINGS_FIELD]["output_dir"].startswith(("A-", "B-"))


def test_corrupt_config_quarantined_and_restored(cfg_path):
    """C1：损坏配置被隔离，并从备份恢复 Key。"""
    config.save_key("sk-abc")            # 写入 + 生成 .bak
    cfg_path.write_text("{not json", encoding="utf-8")
    assert config.load_key() == "sk-abc"  # 从备份恢复
    quarantined = list(cfg_path.parent.glob("config.json.corrupt-*"))
    assert quararantine_exists(quarantined)


def quararantine_exists(items) -> bool:
    return len(items) >= 1


def test_plain_key_auto_migrates(cfg_path):
    """H6：读到明文 Key 自动升级为加密存储。"""
    cfg_path.write_text(json.dumps({"api_key": "sk-legacy-plain"}), encoding="utf-8")
    assert config.load_key() == "sk-legacy-plain"
    raw = cfg_path.read_text(encoding="utf-8")
    if config._dpapi_protect(b"x") is not None:
        assert "sk-legacy-plain" not in raw
        assert config.KEY_ENC_FIELD in raw


def test_masked():
    assert config.masked("sk-abcdefghij") == "sk-****"
    assert config.masked("abcd") == "****"
    assert config.masked("") == "****"


def test_config_path_under_appdata():
    assert config.CONFIG_PATH.name == "config.json"
    assert config.CONFIG_PATH.parent.name == "MinerUBatch"


def test_settings_default(cfg_path):
    assert config.load_settings() == config.DEFAULT_SETTINGS


def test_settings_roundtrip_keeps_key(cfg_path):
    config.save_key("sk-abc")
    config.save_settings({
        "is_ocr": True,
        "language": "japan",
        "output_dir": "D:/out",
        "rename_duplicates": True,
        "batch_size": 10,
        "auto_open": False,
    })
    assert config.load_key() == "sk-abc"
    s = config.load_settings()
    assert s["is_ocr"] is True
    assert s["language"] == "japan"
    assert s["output_dir"] == "D:/out"
    assert s["rename_duplicates"] is True
    assert s["batch_size"] == 10
    assert s["auto_open"] is False


def test_save_key_preserves_settings(cfg_path):
    config.save_settings({"is_ocr": True, "language": "en"})
    config.save_key("sk-abc")
    assert config.load_key() == "sk-abc"
    assert config.load_settings()["is_ocr"] is True
    assert config.load_settings()["language"] == "en"


def test_settings_rejects_bad_language(cfg_path):
    with pytest.raises(ValueError):
        config.save_settings({"is_ocr": False, "language": "xx"})
    assert config.load_settings()["language"] == "ch"


def test_settings_rejects_bad_batch_size(cfg_path):
    for bad in (0, 51, "10", 2.5):
        with pytest.raises(ValueError):
            config.save_settings({"batch_size": bad})
    assert config.load_settings()["batch_size"] == config.DEFAULT_SETTINGS["batch_size"]


def test_settings_bad_json_falls_back(cfg_path):
    cfg_path.write_text("{not json", encoding="utf-8")
    assert config.load_settings() == config.DEFAULT_SETTINGS


def test_settings_garbage_values_fall_back(cfg_path):
    cfg_path.write_text(
        json.dumps({"settings": {"is_ocr": "yes", "language": 42, "batch_size": 999}}),
        encoding="utf-8",
    )
    assert config.load_settings() == config.DEFAULT_SETTINGS
