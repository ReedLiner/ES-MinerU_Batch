"""API Key 的本机存取（仅存当前用户目录，界面只显示掩码）。"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from app.core import app_log

try:
    import msvcrt
except ImportError:  # 非 Windows（开发环境）
    msvcrt = None

_APPDATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
CONFIG_PATH = _APPDATA / "MinerUBatch" / "config.json"

KEY_FIELD = "api_key"
KEY_ENC_FIELD = "api_key_enc"  # Windows DPAPI 加密后的 Key（Base64）
SETTINGS_FIELD = "settings"

_LOCK = threading.RLock()  # 进程内互斥（可重入，允许 load 迁移内部调 save）


def _bak_path() -> Path:
    return CONFIG_PATH.with_name(CONFIG_PATH.name + ".bak")


def _file_lock(timeout: float = 5.0):
    """跨进程锁：对 config.json.lock 首字节加 msvcrt 锁；拿不到也放行（尽力而为）。"""
    if msvcrt is None or sys.platform != "win32":
        return None
    lock_path = CONFIG_PATH.with_name(CONFIG_PATH.name + ".lock")
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    except OSError:
        return None
    deadline = time.time() + timeout
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return fd
        except OSError:
            if time.time() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.05)


def _file_unlock(fd) -> None:
    if fd is None:
        return
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    finally:
        os.close(fd)


@contextmanager
def _config_lock():
    """读-改-写临界区：进程内 RLock + 跨进程文件锁。"""
    with _LOCK:
        fd = _file_lock()
        try:
            yield
        finally:
            _file_unlock(fd)


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_protect(data: bytes) -> bytes | None:
    """用 Windows DPAPI 加密（仅当前用户可解密）；失败返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        buf = ctypes.create_string_buffer(data, len(data))
        blob_in = _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_unprotect(blob: bytes) -> bytes | None:
    """解密 DPAPI 数据；失败返回 None。"""
    if sys.platform != "win32":
        return None
    try:
        buf = ctypes.create_string_buffer(blob, len(blob))
        blob_in = _DATA_BLOB(len(blob), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
        blob_out = _DATA_BLOB()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)
        )
        if not ok:
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None

# MinerU 支持的文档语言（API language 参数的可选子集）
LANGUAGES = {
    "ch": "中英文（默认）",
    "en": "英文",
    "chinese_cht": "繁体中文",
    "japan": "日文",
    "korean": "韩文",
    "latin": "拉丁语系（法/德/西等）",
    "cyrillic": "西里尔语系（俄文等）",
    "arabic": "阿拉伯语系",
}

MAX_BATCH_FILES = 50  # MinerU 单次任务最多 50 个文件

DEFAULT_SETTINGS = {
    "is_ocr": False,
    "language": "ch",
    "output_dir": "",          # 空 = 输出到源文件旁 / 源文件夹同级
    "rename_duplicates": False,  # 同名输出自动加序号，而不是覆盖
    "batch_size": MAX_BATCH_FILES,  # 1 = 逐个转换（关闭批量提速）
    "auto_open": True,         # 全部完成后自动打开输出文件夹
}


def _quarantine_corrupt() -> None:
    """损坏的配置改名保留现场，供排障。"""
    backup_name = f"{CONFIG_PATH.name}.corrupt-{int(time.time())}"
    try:
        CONFIG_PATH.rename(CONFIG_PATH.with_name(backup_name))
        app_log.get().error("配置文件损坏，已隔离为 %s", backup_name)
    except OSError:
        pass


def _restore_from_bak() -> dict:
    bak = _bak_path()
    if not bak.exists():
        return {}
    try:
        data = json.loads(bak.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _read_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        _quarantine_corrupt()
        restored = _restore_from_bak()
        if restored:
            app_log.get().error("配置已从备份 %s 恢复", _bak_path().name)
        return restored
    except OSError:
        return {}


def _write_config(data: dict) -> None:
    """原子写：同目录临时文件 + fsync + os.replace；成功后滚动备份。"""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(CONFIG_PATH.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        fd = -1  # fdopen 的 with 已关闭句柄，避免二次 close 误伤复用的句柄号
        os.replace(tmp, CONFIG_PATH)  # Windows 同盘 replace 原子
    finally:
        if fd >= 0:
            try:
                os.close(fd)
            except OSError:
                pass
        Path(tmp).unlink(missing_ok=True)  # replace 成功时不存在，防御残留
    try:
        shutil.copyfile(CONFIG_PATH, _bak_path())
    except OSError:
        pass


def load_key() -> str | None:
    """读取已保存的 Key：优先读加密字段，兼容旧的明文配置（读到即自动迁移为加密）。"""
    data = _read_config()
    enc = data.get(KEY_ENC_FIELD)
    if isinstance(enc, str) and enc:
        try:
            raw = _dpapi_unprotect(base64.b64decode(enc))
        except Exception:
            raw = None
        if raw:
            return raw.decode("utf-8", errors="ignore") or None
    key = (data.get(KEY_FIELD) or "").strip()
    if key and sys.platform == "win32":
        # 明文迁移：读到明文立即重存为 DPAPI 加密（H6）
        try:
            save_key(key)
        except (RuntimeError, OSError):
            pass  # 迁移失败不阻断读取
    return key or None


def save_key(key: str) -> None:
    key = (key or "").strip()
    if not key:
        raise ValueError("Key 不能为空")
    with _config_lock():
        data = _read_config()
        protected = _dpapi_protect(key.encode("utf-8"))
        if protected is not None:
            data.pop(KEY_FIELD, None)
            data[KEY_ENC_FIELD] = base64.b64encode(protected).decode("ascii")
        elif sys.platform == "win32":
            # Windows 上不允许静默明文落盘（H6）
            raise RuntimeError("本机加密不可用（DPAPI 调用失败），Key 未保存")
        else:
            data[KEY_FIELD] = key  # 非 Windows 开发环境保留明文回退
        _write_config(data)


def clear_key() -> None:
    """删除已保存的 Key，但保留转换设置等其它配置。"""
    with _config_lock():
        data = _read_config()
        if not data:
            return
        data.pop(KEY_FIELD, None)
        data.pop(KEY_ENC_FIELD, None)
        if data:
            _write_config(data)
        else:
            CONFIG_PATH.unlink(missing_ok=True)


def load_settings() -> dict:
    """读取转换参数（OCR / 语言）；缺失或值非法时回退默认。"""
    result = dict(DEFAULT_SETTINGS)
    s = _read_config().get(SETTINGS_FIELD)
    if isinstance(s, dict):
        if isinstance(s.get("is_ocr"), bool):
            result["is_ocr"] = s["is_ocr"]
        if s.get("language") in LANGUAGES:
            result["language"] = s["language"]
        if isinstance(s.get("output_dir"), str):
            result["output_dir"] = s["output_dir"]
        if isinstance(s.get("rename_duplicates"), bool):
            result["rename_duplicates"] = s["rename_duplicates"]
        if isinstance(s.get("batch_size"), int) and 1 <= s["batch_size"] <= MAX_BATCH_FILES:
            result["batch_size"] = s["batch_size"]
        if isinstance(s.get("auto_open"), bool):
            result["auto_open"] = s["auto_open"]
    return result


def save_settings(settings: dict) -> None:
    """保存转换参数；与 api_key 共存于同一配置文件。"""
    is_ocr = settings.get("is_ocr", DEFAULT_SETTINGS["is_ocr"])
    language = settings.get("language", DEFAULT_SETTINGS["language"])
    output_dir = settings.get("output_dir", DEFAULT_SETTINGS["output_dir"])
    rename_duplicates = settings.get("rename_duplicates", DEFAULT_SETTINGS["rename_duplicates"])
    batch_size = settings.get("batch_size", DEFAULT_SETTINGS["batch_size"])
    auto_open = settings.get("auto_open", DEFAULT_SETTINGS["auto_open"])

    if not isinstance(is_ocr, bool):
        raise ValueError("OCR 开关必须为布尔值")
    if language not in LANGUAGES:
        raise ValueError(f"不支持的语言：{language}")
    if not isinstance(output_dir, str):
        raise ValueError("输出目录必须是字符串（留空表示输出到源文件旁）")
    if not isinstance(rename_duplicates, bool):
        raise ValueError("同名处理方式必须为布尔值")
    if not isinstance(batch_size, int) or not 1 <= batch_size <= MAX_BATCH_FILES:
        raise ValueError(f"每批文件数必须在 1-{MAX_BATCH_FILES} 之间")
    if not isinstance(auto_open, bool):
        raise ValueError("自动打开设置必须为布尔值")

    with _config_lock():
        data = _read_config()
        data[SETTINGS_FIELD] = {
            "is_ocr": is_ocr,
            "language": language,
            "output_dir": output_dir,
            "rename_duplicates": rename_duplicates,
            "batch_size": batch_size,
            "auto_open": auto_open,
        }
        _write_config(data)


def masked(key: str | None) -> str:
    """掩码不露出 sk- 前缀之外的任何真实字符（L2）。"""
    key = (key or "").strip()
    if key.startswith("sk-"):
        return "sk-****"
    return "****"
