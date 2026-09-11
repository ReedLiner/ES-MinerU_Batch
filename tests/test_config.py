import json

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
    config.save_key("sk-plain")
    assert config.load_key() == "sk-plain"
    assert "sk-plain" in cfg_path.read_text(encoding="utf-8")


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


def test_masked():
    assert config.masked("sk-abcdefghij") == "sk-a****"
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
