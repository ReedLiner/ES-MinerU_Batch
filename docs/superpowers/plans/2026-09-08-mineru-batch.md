# MinerU Batch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个 Windows 桌面小工具：拖入文件/文件夹 → 调用 MinerU 精准解析 API → 产出与源文件同名的 full Markdown；打包为单文件 exe 分发给任意用户。

**Architecture:** PySide6 界面层 + 内置转换引擎（1:1 移植 `C:\Users\admin\.qoder-cn\skills\mineru\scripts\` 的 `_common.py`/`mineru.py`/`mineru_chunked.py` 逻辑，不调用外部脚本、不读 `~/.qoder*` 配置）。严格单并发队列，后台 QThread 执行，Qt 信号驱动界面。

**Tech Stack:** Python 3.14 / PySide6 / requests / pypdf / pytest / PyInstaller

**Spec:** `docs/superpowers/specs/2026-09-08-mineru-batch-design.md`（先读它）

**环境注意：** 所有命令在 Git Bash 中、项目根目录（`E:\QoderCN Document\Vibe Coding\MinerU Batch`）执行。Python 用 venv 里的（Task 1 创建）。本机全局已装 requests/pypdf/pytest，但项目内一律用 venv。

---

### Task 1: 项目骨架与依赖

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `.gitignore`
- Create: `conftest.py`（空文件，确保 pytest 把项目根加入 sys.path）
- Create: `app/__init__.py`、`app/core/__init__.py`、`app/engine/__init__.py`、`app/ui/__init__.py`（均为空文件）

- [ ] **Step 1: 创建骨架文件**

`requirements.txt`:
```
PySide6>=6.6
requests>=2.31
pypdf>=4.0
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest>=8.0
pyinstaller>=6.0
```

`.gitignore`:
```
.venv/
__pycache__/
*.pyc
dist/
build/
*.zip.tmp
```

- [ ] **Step 2: 创建 venv 并安装依赖**

```bash
cd "E:/QoderCN Document/Vibe Coding/MinerU Batch"
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements-dev.txt
```

Expected: 安装成功无 ERROR；`python -c "import PySide6, requests, pypdf, pytest; print('deps ok')"` 输出 `deps ok`。

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: 项目骨架与依赖"
```

---

### Task 2: core/config.py — API Key 本机存取

**Files:**
- Create: `app/core/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试**

`tests/test_config.py`:
```python
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


def test_clear_key(cfg_path):
    config.save_key("sk-abc")
    config.clear_key()
    assert config.load_key() is None


def test_masked():
    assert config.masked("sk-abcdefghij") == "sk-a****"
    assert config.masked("abcd") == "****"
    assert config.masked("") == "****"


def test_config_path_under_appdata():
    assert config.CONFIG_PATH.name == "config.json"
    assert config.CONFIG_PATH.parent.name == "MinerUBatch"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.core.config'`）

- [ ] **Step 3: 实现 config.py**

`app/core/config.py`:
```python
"""API Key 的本机存取（仅存当前用户目录，界面只显示掩码）。"""

from __future__ import annotations

import json
import os
from pathlib import Path

_APPDATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
CONFIG_PATH = _APPDATA / "MinerUBatch" / "config.json"

KEY_FIELD = "api_key"


def load_key() -> str | None:
    """读取已保存的 Key；文件不存在/损坏都返回 None。"""
    if not CONFIG_PATH.exists():
        return None
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    key = (data.get(KEY_FIELD) or "").strip()
    return key or None


def save_key(key: str) -> None:
    key = (key or "").strip()
    if not key:
        raise ValueError("Key 不能为空")
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps({KEY_FIELD: key}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass  # Windows 下 chmod 语义不同，忽略


def clear_key() -> None:
    CONFIG_PATH.unlink(missing_ok=True)


def masked(key: str | None) -> str:
    key = (key or "").strip()
    if len(key) <= 4:
        return "****"
    return key[:4] + "****"
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/config.py tests/test_config.py
git commit -m "feat(core): API Key 本机存取"
```

---

### Task 3: core/collect.py — 拖拽目标收集与输出路径映射

**Files:**
- Create: `app/core/collect.py`
- Test: `tests/test_collect.py`

- [ ] **Step 1: 写失败测试**

`tests/test_collect.py`:
```python
from pathlib import Path

import pytest

from app.core import collect
from app.core.collect import SUPPORTED_EXTS, collect_paths, is_supported


@pytest.fixture()
def docs(tmp_path, monkeypatch):
    d = tmp_path / "Documents"
    d.mkdir()
    monkeypatch.setattr(collect, "documents_dir", lambda: d)
    return d


def test_is_supported(tmp_path):
    f = tmp_path / "a.PDF"
    f.write_text("x")
    assert is_supported(f)
    t = tmp_path / "b.txt"
    t.write_text("x")
    assert not is_supported(t)


def test_supported_exts_cover_spec():
    for ext in [".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".html"]:
        assert ext in SUPPORTED_EXTS


def test_single_file_maps_to_same_dir(tmp_path):
    f = tmp_path / "年报.pdf"
    f.write_bytes(b"x")
    tasks, skipped, collisions = collect_paths([f])
    assert len(tasks) == 1
    assert tasks[0].source == f
    assert tasks[0].output_md == tmp_path / "年报.md"
    assert tasks[0].stem == "年报"
    assert skipped == [] and collisions == []


def test_folder_recursive_mirror(docs, tmp_path):
    folder = tmp_path / "资料"
    (folder / "子目录").mkdir(parents=True)
    a = folder / "a.pdf"; a.write_bytes(b"x")
    b = folder / "子目录" / "b.docx"; b.write_bytes(b"x")
    txt = folder / "说明.txt"; txt.write_text("x")

    tasks, skipped, collisions = collect_paths([folder])

    assert {t.source for t in tasks} == {a, b}
    by_src = {t.source: t for t in tasks}
    assert by_src[a].output_md == docs / "MinerU" / "资料" / "a.md"
    assert by_src[b].output_md == docs / "MinerU" / "资料" / "子目录" / "b.md"
    assert skipped == [txt]
    assert collisions == []


def test_collision_detected(docs, tmp_path):
    folder = tmp_path / "冲突"
    folder.mkdir()
    a = folder / "a.pdf"; a.write_bytes(b"x")
    b = folder / "a.docx"; b.write_bytes(b"x")

    tasks, skipped, collisions = collect_paths([folder])

    assert len(tasks) == 2
    assert len(collisions) == 1
    out_md, srcs = collisions[0]
    assert out_md == docs / "MinerU" / "冲突" / "a.md"
    assert set(srcs) == {a, b}


def test_unsupported_and_missing_skipped(tmp_path):
    txt = tmp_path / "a.txt"; txt.write_text("x")
    ghost = tmp_path / "不存在.pdf"
    tasks, skipped, collisions = collect_paths([txt, ghost])
    assert tasks == []
    assert set(skipped) == {txt, ghost}
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_collect.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'app.core.collect'`）

- [ ] **Step 3: 实现 collect.py**

`app/core/collect.py`:
```python
"""拖拽目标解析：递归收集受支持的文件，并映射输出路径。"""

from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_EXTS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx",
    ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".html", ".htm",
}


@dataclass(frozen=True)
class ConvertTask:
    source: Path
    output_md: Path
    stem: str


def documents_dir() -> Path:
    """当前用户的「文档」目录（兼容 OneDrive 重定向）。"""
    if sys.platform == "win32":
        buf = ctypes.create_unicode_buffer(260)
        # CSIDL_PERSONAL = 5
        ctypes.windll.shell32.SHGetFolderPathW(0, 5, 0, 0, buf)
        if buf.value:
            return Path(buf.value)
    return Path.home() / "Documents"


def is_supported(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_EXTS


def collect_paths(
    paths: list[Path],
) -> tuple[list[ConvertTask], list[Path], list[tuple[Path, list[Path]]]]:
    """把拖入的路径解析为转换任务。

    返回 (任务列表, 跳过的路径, 同名输出冲突)。冲突项 = (输出 md, [来源文件, ...])。
    """
    tasks: list[ConvertTask] = []
    skipped: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if is_supported(p):
                tasks.append(_task_for_file(p, p.parent))
            else:
                skipped.append(p)
        elif p.is_dir():
            out_root = documents_dir() / "MinerU" / p.name
            for child in sorted(p.rglob("*")):
                if child.is_dir():
                    continue
                if is_supported(child):
                    rel_parent = child.relative_to(p).parent
                    tasks.append(_task_for_file(child, out_root / rel_parent))
                else:
                    skipped.append(child)
        else:
            skipped.append(p)
    return tasks, skipped, _find_collisions(tasks)


def _task_for_file(source: Path, out_dir: Path) -> ConvertTask:
    return ConvertTask(source=source, output_md=out_dir / f"{source.stem}.md", stem=source.stem)


def _find_collisions(tasks: list[ConvertTask]) -> list[tuple[Path, list[Path]]]:
    by_out: dict[Path, list[Path]] = {}
    for t in tasks:
        by_out.setdefault(t.output_md, []).append(t.source)
    return [(out, srcs) for out, srcs in by_out.items() if len(srcs) > 1]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_collect.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add app/core/collect.py tests/test_collect.py
git commit -m "feat(core): 拖拽目标收集与输出路径映射"
```

---

### Task 4: engine/errors.py — 错误类型与用户文案映射

**Files:**
- Create: `app/engine/errors.py`
- Test: `tests/test_errors.py`

- [ ] **Step 1: 写失败测试**

`tests/test_errors.py`:
```python
from app.engine.errors import MineruError, friendly_message


def test_friendly_by_code():
    assert "Key 失效" in friendly_message(MineruError("x", code="A0202"))
    assert "Key 失效" in friendly_message(MineruError("x", code="401"))
    assert "200MB" in friendly_message(MineruError("x", code="-60005"))
    assert "额度" in friendly_message(MineruError("x", code="-60018"))
    assert "网络" in friendly_message(MineruError("x", code="NETWORK"))


def test_friendly_override_wins():
    exc = MineruError("raw", code="A0202", friendly="自定义")
    assert friendly_message(exc) == "自定义"


def test_unknown_code_falls_back_to_raw():
    exc = MineruError("原始错误")
    assert friendly_message(exc) == "原始错误"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_errors.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 errors.py**

`app/engine/errors.py`:
```python
"""错误类型与面向用户的大白话文案。"""

from __future__ import annotations

KEY_INVALID = "Key 失效了，请去 https://mineru.net/apiManage 重新生成，然后在设置里更换。"

_RESUME_HINT = "已保留进度，重试会跳过已完成的分段。"


class MineruError(RuntimeError):
    def __init__(self, message: str, code: str | None = None, friendly: str | None = None):
        super().__init__(message)
        self.code = code
        self.friendly = friendly


_FRIENDLY_BY_CODE = {
    "A0202": KEY_INVALID,
    "A0211": KEY_INVALID,
    "401": KEY_INVALID,
    "403": KEY_INVALID,
    "-60005": "这个文件超过 200MB，在线版处理不了，请拆分或压缩后再试。",
    "-60006": "页数超过单次上限，请重试（程序会自动分段处理）。",
    "-60018": "今天的转换额度用完了，明天再试或升级套餐。",
    "NETWORK": f"网络异常，请检查网络后重试。{_RESUME_HINT}",
    "TIMEOUT": f"转换超时了，请稍后重试。{_RESUME_HINT}",
}


def friendly_message(exc: MineruError) -> str:
    if exc.friendly:
        return exc.friendly
    if exc.code and exc.code in _FRIENDLY_BY_CODE:
        return _FRIENDLY_BY_CODE[exc.code]
    return str(exc)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_errors.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/errors.py tests/test_errors.py
git commit -m "feat(engine): 错误类型与用户文案映射"
```

---

### Task 5: engine/client.py — MinerU API 客户端

**Files:**
- Create: `app/engine/client.py`
- Test: `tests/test_client.py`

接口契约（移植自 skill 源码，基址 `https://mineru.net/api/v4`）：
- `POST /file-urls/batch`，payload `{"files":[{"name","is_ocr":false,"data_id":<stem>,"page_ranges"?}], "model_version":"vlm","enable_formula":True,"enable_table":True,"language":"ch"}` → `data.batch_id` + `data.file_urls[0]`
- `PUT file_urls[0]` 上传原文件（8MB 分块，超时 300s）
- 轮询 `GET /extract-results/batch/{batch_id}`：初始 2s、×1.5 退避、上限 15s；`extract_result[]` 全 `done` 成功 / 全 `failed` 失败；超时 1800s
- 取 `record.full_zip_url` 下载 ZIP，仅抽取其中 `full.md` / `full_markdown.md` 条目写出

- [ ] **Step 1: 写失败测试**

`tests/test_client.py`:
```python
import zipfile
from pathlib import Path

import pytest

from app.engine import client as client_mod
from app.engine.client import MineruClient
from app.engine.errors import MineruError


class FakeResp:
    def __init__(self, status=200, body=None, content=b""):
        self.status_code = status
        self._body = body if body is not None else {}
        self.content = content
        self.text = ""

    def json(self):
        if not isinstance(self._body, dict):
            raise ValueError("no json")
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeSession:
    """按顺序吐出预置响应；记录收到的请求。"""

    def __init__(self):
        self.posts: list[dict] = []
        self.gets: list[str] = []
        self.puts: list[tuple[str, bytes]] = []
        self.post_responses: list[FakeResp] = []
        self.get_responses: list[FakeResp] = []
        self.put_response = FakeResp()

    def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "json": json, "headers": headers})
        return self.post_responses.pop(0)

    def get(self, url, **kwargs):
        self.gets.append(url)
        return self.get_responses.pop(0)

    def put(self, url, data=None, timeout=None):
        self.puts.append((url, b"".join(data)))
        return self.put_response


def _make_zip(path: Path, files: dict[str, bytes]) -> bytes:
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _client(session: FakeSession, **kw) -> MineruClient:
    return MineruClient("sk-test", base="https://api.test/v4", session=session, **kw)


def test_convert_happy_path(tmp_path, monkeypatch):
    src = tmp_path / "报告.pdf"
    src.write_bytes(b"pdf-bytes")
    out_md = tmp_path / "报告.md"
    zip_bytes = _make_zip(tmp_path / "r.zip", {
        "报告/images/p1.png": b"img",
        "报告/full.md": b"# hello",
    })
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)

    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b1", "file_urls": ["https://up/1"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [{"state": "doing"}]}}),
        FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://zip/1"}]}}),
        FakeResp(content=zip_bytes),
    ]

    c = _client(s)
    c.convert(src, out_md, progress=lambda m: None)

    assert out_md.read_bytes() == b"# hello"
    assert s.posts[0]["url"] == "https://api.test/v4/file-urls/batch"
    assert s.posts[0]["json"]["files"][0]["name"] == "报告.pdf"
    assert s.posts[0]["json"]["files"][0]["data_id"] == "报告"
    assert s.puts == [("https://up/1", b"pdf-bytes")]
    assert s.gets[0].endswith("/extract-results/batch/b1")


def test_convert_passes_page_ranges(tmp_path):
    src = tmp_path / "big.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["u"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "z"}]}}),
                       FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"x"}))]
    _client(s).convert(src, tmp_path / "out.md", page_ranges="201-400")
    assert s.posts[0]["json"]["files"][0]["page_ranges"] == "201-400"


def test_size_precheck(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "MAX_FILE_SIZE", 4)
    src = tmp_path / "big.pdf"; src.write_bytes(b"12345")
    with pytest.raises(MineruError) as ei:
        _client(FakeSession()).convert(src, tmp_path / "o.md")
    assert ei.value.code == "-60005"


def test_business_error_code(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": -60018, "msg": "quota"})]
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md")
    assert ei.value.code == "-60018"


def test_auth_error(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(status=401, body={})]
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md")
    assert ei.value.code == "401"


def test_poll_failed_state(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["u"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "failed", "err_msg": "bad"}]}})]
    with pytest.raises(MineruError, match="bad"):
        _client(s).convert(src, tmp_path / "o.md")


def test_poll_timeout(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["u"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "doing"}]}})]
    with pytest.raises(MineruError) as ei:
        _client(s, timeout=0).convert(src, tmp_path / "o.md")
    assert ei.value.code == "TIMEOUT"


def test_records_dict_normalized(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["u"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": {"state": "done", "full_zip_url": "z"}}}),
                       FakeResp(content=_make_zip(tmp_path / "z", {"x/full_markdown.md": b"ok"}))]
    _client(s).convert(src, tmp_path / "o.md")
    assert (tmp_path / "o.md").read_bytes() == b"ok"


def test_missing_full_md_in_zip(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["u"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "z"}]}}),
                       FakeResp(content=_make_zip(tmp_path / "z", {"img.png": b"i"}))]
    with pytest.raises(MineruError, match="没有 Markdown"):
        _client(s).convert(src, tmp_path / "o.md")
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 client.py**

`app/engine/client.py`:
```python
"""MinerU 精准解析 API 客户端。

移植自 mineru skill（_common.py / mineru.py 的本地文件分支），行为 1:1：
创建批量任务 → PUT 上传 → 轮询 → 下载 ZIP → 仅抽取 full.md。
"""

from __future__ import annotations

import time
import zipfile
from pathlib import Path
from typing import Any, Callable

import requests

from app.engine.errors import MineruError

API_BASE = "https://mineru.net/api/v4"
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB（MinerU 在线上限）

_POLL_INITIAL = 2.0
_POLL_MAX = 15.0
_UPLOAD_CHUNK = 8 * 1024 * 1024

_SLEEP = time.sleep  # 测试可替换

DEFAULT_PARAMS = {
    "model_version": "vlm",
    "enable_formula": True,
    "enable_table": True,
    "language": "ch",
}

ProgressCb = Callable[[str], None]


class MineruClient:
    def __init__(
        self,
        token: str,
        base: str = API_BASE,
        session: requests.Session | None = None,
        timeout: int = 1800,
    ):
        key = (token or "").strip()
        if not key:
            raise ValueError("API Key 不能为空")
        self._token = key
        self._base = base.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout

    # ---------- 主流程 ----------

    def convert(
        self,
        source: Path,
        out_md: Path,
        page_ranges: str | None = None,
        progress: ProgressCb | None = None,
    ) -> None:
        source = Path(source)
        out_md = Path(out_md)
        if source.stat().st_size > MAX_FILE_SIZE:
            raise MineruError(f"文件 {source.name} 超过 200MB", code="-60005")
        out_md.parent.mkdir(parents=True, exist_ok=True)

        batch_id, upload_url = self._create_batch(source, page_ranges)
        _report(progress, "上传文件中…")
        self._upload(upload_url, source)
        _report(progress, "MinerU 转换中…")
        data = self._poll_batch(batch_id)

        records = _records(data)
        record = records[0] if records else {}
        if record.get("err_msg"):
            raise MineruError(f"转换失败：{record['err_msg']}")
        zip_url = record.get("full_zip_url") or data.get("full_zip_url")
        if not zip_url:
            raise MineruError("任务完成但未返回下载地址")

        tmp_zip = out_md.with_suffix(".zip.tmp")
        try:
            self._download(zip_url, tmp_zip)
            _extract_full_md(tmp_zip, out_md)
        finally:
            tmp_zip.unlink(missing_ok=True)

    # ---------- 各步骤 ----------

    def _create_batch(self, source: Path, page_ranges: str | None) -> tuple[str, str]:
        files = [{"name": source.name, "is_ocr": False, "data_id": source.stem}]
        if page_ranges:
            files[0]["page_ranges"] = page_ranges
        body = self._post("/file-urls/batch", {"files": files, **DEFAULT_PARAMS})
        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or []
        if not batch_id or not urls:
            raise MineruError(f"申请上传链接失败: {body}")
        return batch_id, urls[0]

    def _upload(self, url: str, source: Path) -> None:
        def _stream():
            with source.open("rb") as fh:
                while chunk := fh.read(_UPLOAD_CHUNK):
                    yield chunk

        try:
            resp = self._session.put(url, data=_stream(), timeout=300)
        except requests.RequestException as exc:
            raise MineruError(f"上传失败：{exc}", code="NETWORK") from exc
        if resp.status_code >= 400:
            raise MineruError(f"上传失败 HTTP {resp.status_code}")

    def _poll_batch(self, batch_id: str) -> dict[str, Any]:
        started = time.time()
        delay = _POLL_INITIAL
        while True:
            body = self._get(f"/extract-results/batch/{batch_id}")
            data = body.get("data") or {}
            records = _records(data)
            states = [r.get("state") for r in records]
            if records and all(s == "done" for s in states):
                return data
            if records and all(s == "failed" for s in states):
                err = records[0].get("err_msg") or "unknown"
                raise MineruError(f"转换失败：{err}")
            if time.time() - started >= self._timeout:
                raise MineruError(f"转换超时（>{self._timeout}s）", code="TIMEOUT")
            _SLEEP(min(delay, _POLL_MAX))
            delay = min(delay * 1.5, _POLL_MAX)

    def _download(self, url: str, dest: Path) -> None:
        try:
            with self._session.get(url, stream=True, timeout=300) as resp:
                if resp.status_code >= 400:
                    raise MineruError(f"下载结果失败 HTTP {resp.status_code}")
                dest.write_bytes(resp.content)
        except requests.RequestException as exc:
            raise MineruError(f"下载结果失败：{exc}", code="NETWORK") from exc

    # ---------- HTTP 基础 ----------

    def _post(self, path: str, payload: dict) -> dict:
        try:
            resp = self._session.post(
                self._base + path, headers=self._headers(), json=payload, timeout=60
            )
        except requests.RequestException as exc:
            raise MineruError(f"网络请求失败：{exc}", code="NETWORK") from exc
        return self._check(resp)

    def _get(self, path: str) -> dict:
        try:
            resp = self._session.get(self._base + path, headers=self._headers(), timeout=60)
        except requests.RequestException as exc:
            raise MineruError(f"网络请求失败：{exc}", code="NETWORK") from exc
        return self._check(resp)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    @staticmethod
    def _check(resp) -> dict:
        if resp.status_code < 400:
            try:
                body = resp.json()
            except ValueError:
                return {}
            code = body.get("code")
            if code not in (0, "0", None, ""):
                msg = body.get("msg") or body.get("message") or ""
                raise MineruError(f"MinerU 错误 code={code}：{msg}", code=str(code))
            return body
        if resp.status_code in (401, 403):
            raise MineruError(f"鉴权失败 (HTTP {resp.status_code})", code=str(resp.status_code))
        raise MineruError(f"MinerU HTTP {resp.status_code}：{resp.text[:200]}")


# ---------- 模块级辅助 ----------

def _records(data: dict) -> list[dict]:
    records = data.get("extract_result") or []
    if isinstance(records, dict):
        records = [records]
    return records


def _extract_full_md(zip_path: Path, out_md: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = zf.namelist()
            candidates = [n for n in names if n.endswith("full.md") or n.endswith("full_markdown.md")]
            if not candidates:
                raise MineruError(
                    f"结果包中没有 Markdown，包含：{names[:10]}{'...' if len(names) > 10 else ''}"
                )
            with zf.open(candidates[0]) as src, out_md.open("wb") as dst:
                dst.write(src.read())
    except zipfile.BadZipFile as exc:
        raise MineruError(f"结果包损坏：{exc}") from exc


def _report(progress: ProgressCb | None, msg: str) -> None:
    if progress:
        progress(msg)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_client.py -v`
Expected: 9 passed

- [ ] **Step 5: Commit**

```bash
git add app/engine/client.py tests/test_client.py
git commit -m "feat(engine): MinerU API 客户端"
```

---

### Task 6: engine/convert.py — 转换编排（分段 / 合并 / 续跑）

**Files:**
- Create: `app/engine/convert.py`
- Test: `tests/test_convert.py`

- [ ] **Step 1: 写失败测试**

`tests/test_convert.py`:
```python
from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.engine.convert import convert_file, count_pdf_pages, plan_chunks


class FakeClient:
    """记录调用并按 page_ranges 写标记内容，模拟 MinerUClient.convert。"""

    def __init__(self):
        self.calls: list[dict] = []

    def convert(self, source, out_md, page_ranges=None, progress=None):
        source = Path(source)
        out_md = Path(out_md)
        self.calls.append({"source": source, "out_md": out_md, "page_ranges": page_ranges})
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(f"content-{page_ranges or 'full'}", encoding="utf-8")


def _make_pdf(path: Path, pages: int) -> Path:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=612, height=792)
    with path.open("wb") as fh:
        w.write(fh)
    return path


def test_plan_chunks():
    assert plan_chunks(199) == [(1, 199)]
    assert plan_chunks(200) == [(1, 200)]
    assert plan_chunks(201) == [(1, 200), (201, 201)]
    assert plan_chunks(601) == [(1, 200), (201, 400), (401, 600), (601, 601)]


def test_count_pdf_pages(tmp_path):
    assert count_pdf_pages(_make_pdf(tmp_path / "a.pdf", 3)) == 3


def test_non_pdf_single_pass(tmp_path):
    src = tmp_path / "报告.docx"
    src.write_bytes(b"x")
    client = FakeClient()
    out = convert_file(src, tmp_path / "报告.md", client)
    assert out == tmp_path / "报告.md"
    assert len(client.calls) == 1
    assert client.calls[0]["page_ranges"] is None


def test_small_pdf_single_pass(tmp_path):
    src = _make_pdf(tmp_path / "小.pdf", 10)
    client = FakeClient()
    convert_file(src, tmp_path / "小.md", client)
    assert len(client.calls) == 1
    assert client.calls[0]["page_ranges"] is None


def test_large_pdf_chunks_and_merges(tmp_path):
    src = _make_pdf(tmp_path / "大.pdf", 201)
    client = FakeClient()
    messages = []
    convert_file(src, tmp_path / "大.md", client, progress=messages.append)

    assert [c["page_ranges"] for c in client.calls] == ["1-200", "201-201"]
    assert (tmp_path / "大.md").read_text(encoding="utf-8") == "content-1-200\n\ncontent-201-201"
    # 分段文件合并后已清理
    assert not list(tmp_path.glob("*.part*.md"))
    assert any("第 1/2 段" in m for m in messages)
    assert any("第 2/2 段" in m for m in messages)


def test_resume_skips_finished_parts(tmp_path):
    src = _make_pdf(tmp_path / "续.pdf", 201)
    part1 = tmp_path / "续.part1.md"
    part1.write_text("content-1-200", encoding="utf-8")
    client = FakeClient()
    convert_file(src, tmp_path / "续.md", client)

    assert len(client.calls) == 1
    assert client.calls[0]["page_ranges"] == "201-201"
    assert (tmp_path / "续.md").read_text(encoding="utf-8") == "content-1-200\n\ncontent-201-201"


def test_progress_callback_optional(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf", 3)
    convert_file(src, tmp_path / "a.md", FakeClient())  # 不传 progress 不报错
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_convert.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 convert.py**

`app/engine/convert.py`:
```python
"""转换编排：非 PDF / 小 PDF 直转；大 PDF 分段转换后合并。

断点续跑：已存在的 .partN.md 直接跳过（成功的转换不会留下分段文件，
所以已完成的文件重拖 = 完整重转 + 覆盖，见设计文档 5.3）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.engine.client import MineruClient, ProgressCb
from app.engine.errors import MineruError

CHUNK_SIZE = 200  # MinerU 单次任务页数上限


def plan_chunks(pages: int, size: int = CHUNK_SIZE) -> list[tuple[int, int]]:
    if pages < 1:
        raise ValueError("页数必须 >= 1")
    return [(s, min(s + size - 1, pages)) for s in range(1, pages + 1, size)]


def count_pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise MineruError("缺少 pypdf 依赖，无法统计 PDF 页数") from exc
    try:
        return len(PdfReader(str(path)).pages)
    except Exception as exc:
        raise MineruError(f"无法读取 PDF 页数（文件可能损坏或加密）：{exc}") from exc


def convert_file(
    source: Path,
    out_md: Path,
    client: MineruClient,
    progress: ProgressCb | None = None,
) -> Path:
    source = Path(source)
    out_md = Path(out_md)

    if source.suffix.lower() != ".pdf":
        client.convert(source, out_md, progress=progress)
        return out_md

    pages = count_pdf_pages(source)
    if pages <= CHUNK_SIZE:
        client.convert(source, out_md, progress=progress)
        return out_md

    chunks = plan_chunks(pages)
    parts = [out_md.parent / f"{out_md.stem}.part{i}.md" for i in range(1, len(chunks) + 1)]
    total = len(chunks)
    for i, ((s, e), part) in enumerate(zip(chunks, parts), start=1):
        if part.exists():
            _report(progress, f"{source.name}：第 {i}/{total} 段已完成，跳过")
            continue
        _report(progress, f"{source.name}：转换第 {i}/{total} 段（第 {s}-{e} 页）")
        client.convert(source, part, page_ranges=f"{s}-{e}")

    _merge(parts, out_md)
    for part in parts:
        part.unlink(missing_ok=True)
    _report(progress, f"{source.name}：完成（{pages} 页，{total} 段合并）")
    return out_md


def _merge(parts: list[Path], out_md: Path) -> None:
    try:
        with out_md.open("wb") as dst:
            for idx, part in enumerate(parts):
                if idx:
                    dst.write(b"\n\n")
                dst.write(part.read_bytes())
    except OSError as exc:
        raise MineruError(f"合并分段失败：{exc}。分段文件已保留，重试可续跑。") from exc


def _report(progress: Callable[[str], None] | None, msg: str) -> None:
    if progress:
        progress(msg)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_convert.py -v`
Expected: 7 passed

- [ ] **Step 5: 跑全部测试**

Run: `python -m pytest tests/ -v`
Expected: 33 passed（累计）

- [ ] **Step 6: Commit**

```bash
git add app/engine/convert.py tests/test_convert.py
git commit -m "feat(engine): 转换编排（大 PDF 分段/合并/续跑）"
```

---

### Task 7: ui/theme.py + ui/settings_dialog.py

**Files:**
- Create: `app/ui/theme.py`
- Create: `app/ui/settings_dialog.py`

本任务无自动化测试，Step 3 为手动验证。

- [ ] **Step 1: 实现 theme.py**

`app/ui/theme.py`:
```python
"""深色 + 青色光效主题（Qt Style Sheet）。"""

BG = "#0f141b"
CARD = "#171e28"
BORDER = "#2a3646"
TEXT = "#e6edf3"
SUBTLE = "#8b98a9"
ACCENT = "#22d3ee"
DANGER = "#f47067"

APP_QSS = f"""
* {{
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QWidget {{
    background: {BG};
    color: {TEXT};
}}
QLabel#appTitle {{
    font-size: 18px;
    font-weight: bold;
    color: {ACCENT};
}}
QLabel#subtle {{
    color: {SUBTLE};
}}
QLabel#dropZone {{
    background: #131a23;
    border: 2px dashed {BORDER};
    border-radius: 10px;
    color: {SUBTLE};
    font-size: 14px;
}}
QLabel#dropZone[hover="true"] {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton {{
    background: #1c2634;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {TEXT};
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background: #16202c;
}}
QLineEdit {{
    background: #131a23;
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    color: {TEXT};
    selection-background-color: {ACCENT};
    selection-color: {BG};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}
QListWidget {{
    background: #12181f;
    border: 1px solid #1e2836;
    border-radius: 8px;
    outline: none;
}}
QListWidget::item {{
    border-bottom: 1px solid #1a2330;
}}
QProgressBar {{
    background: #131a23;
    border: 1px solid {BORDER};
    border-radius: 6px;
    text-align: center;
    color: {SUBTLE};
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}
QProgressBar[failed="true"]::chunk {{
    background: {DANGER};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QToolTip {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px;
}}
"""
```

- [ ] **Step 2: 实现 settings_dialog.py**

`app/ui/settings_dialog.py`:
```python
"""API Key 设置对话框。"""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from app.core.config import clear_key, load_key, masked, save_key

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
        self.key_edit.setPlaceholderText("sk-...")
        layout.addWidget(self.key_edit)

        show_plain = QCheckBox("显示明文")
        show_plain.toggled.connect(self._toggle_echo)
        layout.addWidget(show_plain)

        self.current_label = QLabel()
        self.current_label.setObjectName("subtle")
        layout.addWidget(self.current_label)

        buttons = QHBoxLayout()
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

    def _refresh(self) -> None:
        key = load_key()
        self.current_label.setText(f"当前 Key：{masked(key)}" if key else "当前 Key：未设置")

    def _toggle_echo(self, checked: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        self.key_edit.setEchoMode(mode)

    def _open_site(self) -> None:
        QDesktopServices.openUrl(QUrl(APPLY_URL))

    def _save(self) -> None:
        try:
            save_key(self.key_edit.text())
        except ValueError as exc:
            QMessageBox.warning(self, "提示", str(exc))
            return
        self.key_edit.clear()
        self._refresh()
        self.key_changed.emit()

    def _clear(self) -> None:
        clear_key()
        self._refresh()
        self.key_changed.emit()
```

- [ ] **Step 3: 手动验证**

```bash
source .venv/Scripts/activate
python -c "from PySide6.QtWidgets import QApplication, QLabel; import sys; from app.ui.theme import APP_QSS; from app.ui.settings_dialog import SettingsDialog; app = QApplication(sys.argv); app.setStyleSheet(APP_QSS); d = SettingsDialog(); d.show(); app.exec()"
```

Expected: 弹出深色设置对话框，显示"当前 Key：未设置"；勾选"显示明文"后输入框明文/密文切换正常；点击"打开 mineru.net 申请页面"浏览器打开 https://mineru.net/apiManage。关闭窗口结束。

- [ ] **Step 4: Commit**

```bash
git add app/ui/theme.py app/ui/settings_dialog.py
git commit -m "feat(ui): 深色科技风主题与设置对话框"
```

---

### Task 8: ui/worker.py + task_widgets.py + main_window.py + main.py — 界面整合

**Files:**
- Create: `app/ui/worker.py`
- Create: `app/ui/task_widgets.py`
- Create: `app/ui/main_window.py`
- Create: `app/main.py`

- [ ] **Step 1: 实现 worker.py**

`app/ui/worker.py`:
```python
"""后台转换线程：严格单并发顺序执行队列。"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.core.collect import ConvertTask
from app.engine.client import MineruClient
from app.engine.convert import convert_file
from app.engine.errors import MineruError, friendly_message


class ConvertWorker(QThread):
    """items = [(行号, 任务), ...]；信号里的 idx 即行号（对应主窗口任务列表）。"""

    task_progress = Signal(int, str)
    task_finished = Signal(int, bool, str)
    all_done = Signal(int, int)

    def __init__(self, items: list[tuple[int, ConvertTask]], key: str, parent=None):
        super().__init__(parent)
        self._items = list(items)
        self._key = key

    def run(self) -> None:
        client = MineruClient(self._key)
        ok = fail = 0
        for idx, task in self._items:
            try:
                convert_file(
                    task.source,
                    task.output_md,
                    client,
                    progress=lambda msg, i=idx: self.task_progress.emit(i, msg),
                )
            except MineruError as exc:
                fail += 1
                self.task_finished.emit(idx, False, friendly_message(exc))
            except Exception as exc:  # 兜底，避免线程静默崩溃
                fail += 1
                self.task_finished.emit(idx, False, f"未预期错误：{exc}")
            else:
                ok += 1
                self.task_finished.emit(idx, True, str(task.output_md))
        self.all_done.emit(ok, fail)
```

- [ ] **Step 2: 实现 task_widgets.py**

`app/ui/task_widgets.py`:
```python
"""拖拽区与任务行控件。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from app.core.collect import ConvertTask


def _elide(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


class DropZone(QLabel):
    paths_dropped = Signal(list)

    def __init__(self):
        super().__init__("把文件或文件夹拖到这里\n（PDF / Word / PPT / Excel / 图片 / HTML）")
        self.setObjectName("dropZone")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(120)
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
    def __init__(self, task: ConvertTask):
        super().__init__()
        self.task = task
        self.status = "排队中"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(4)

        top = QHBoxLayout()
        name = QLabel(_elide(task.source.name, 40))
        name.setToolTip(str(task.source))
        top.addWidget(name)
        top.addStretch(1)
        self.status_label = QLabel("排队中")
        self.status_label.setObjectName("subtle")
        top.addWidget(self.status_label)
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

    def set_busy(self) -> None:
        self.status = "转换中"
        self.status_label.setText("转换中")
        self.bar.setRange(0, 0)

    def set_done(self, ok: bool) -> None:
        self.status = "完成" if ok else "失败"
        self.status_label.setText(self.status)
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if not ok:
            self.bar.setProperty("failed", True)
            self.style().unpolish(self.bar)
            self.style().polish(self.bar)
```

- [ ] **Step 3: 实现 main_window.py**

`app/ui/main_window.py`:
```python
"""主窗口：拖拽 → 收集 → 队列 → 结果。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.core.collect import collect_paths
from app.core.config import load_key
from app.ui.settings_dialog import SettingsDialog
from app.ui.task_widgets import DropZone, TaskRow
from app.ui.worker import ConvertWorker


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MinerU Batch")
        self.setFixedSize(720, 560)

        self._tasks = []
        self._rows: list[TaskRow] = []
        self._worker: ConvertWorker | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("MinerU Batch")
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

        self.task_list = QListWidget()
        self.task_list.setMinimumHeight(240)
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
        clear_btn = QPushButton("清空已完成")
        clear_btn.clicked.connect(self._clear_finished)
        bottom.addWidget(clear_btn)
        footer.addLayout(bottom)
        layout.addLayout(footer)

    # ---------- 拖入 ----------

    def _on_paths(self, paths: list[Path]) -> None:
        tasks, skipped, collisions = collect_paths(paths)
        existing = {(t.source, t.output_md) for t in self._tasks}
        fresh = [t for t in tasks if (t.source, t.output_md) not in existing]
        for t in fresh:
            self._tasks.append(t)
            row = TaskRow(t)
            self._rows.append(row)
            item = QListWidgetItem()
            item.setSizeHint(row.sizeHint())
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
        if skipped:
            self.summary.setText(f"已跳过 {len(skipped)} 个不支持的文件")
        if fresh:
            self._start_worker()

    # ---------- 队列 ----------

    def _start_worker(self) -> None:
        if self._worker is not None:
            return
        pending = [i for i, row in enumerate(self._rows) if row.status == "排队中"]
        if not pending:
            return
        key = load_key()
        if not key:
            QMessageBox.warning(self, "未设置 Key", "请先在设置里填入 MinerU API Key。")
            self._open_settings()
            key = load_key()
            if not key:
                return
        for i in pending:
            self._rows[i].set_busy()
        self.overall.setMaximum(len(pending))
        self.overall.setValue(0)
        items = [(i, self._tasks[i]) for i in pending]
        worker = ConvertWorker(items, key, self)
        worker.task_progress.connect(self._on_task_progress)
        worker.task_finished.connect(self._on_task_finished)
        worker.all_done.connect(self._on_all_done)
        self._worker = worker
        worker.start()

    def _on_task_progress(self, idx: int, msg: str) -> None:
        if 0 <= idx < len(self._rows):
            self._rows[idx].set_status(msg)

    def _on_task_finished(self, idx: int, ok: bool, msg: str) -> None:
        if 0 <= idx < len(self._rows):
            self._rows[idx].set_done(ok)
            self._rows[idx].setToolTip(msg)
        self.overall.setValue(self.overall.value() + 1)

    def _on_all_done(self, ok: int, fail: int) -> None:
        self.summary.setText(f"全部完成：成功 {ok} 个，失败 {fail} 个")
        self._worker = None

    # ---------- 其他 ----------

    def _open_settings(self) -> None:
        SettingsDialog(self).exec()

    def _clear_finished(self) -> None:
        for i in reversed(range(len(self._rows))):
            if self._rows[i].status in ("完成", "失败"):
                self.task_list.takeItem(i)
                del self._rows[i]
                del self._tasks[i]
```

- [ ] **Step 4: 实现 main.py**

`app/main.py`:
```python
"""MinerU Batch 入口。"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.core.config import load_key
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui.theme import APP_QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("MinerU Batch")
    app.setStyleSheet(APP_QSS)

    if not load_key():
        SettingsDialog().exec()
        if not load_key():
            return 0

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 手动验证（会消耗 1 次真实 API 任务额度）**

```bash
source .venv/Scripts/activate
python -m app.main
```

按序验证：
1. 首次运行弹出设置对话框 → 粘贴真实 Key → 保存 → 关闭对话框 → 主窗口出现，深色主题正常。
2. 拖入一个小 PDF（<200 页）→ 行出现"排队中"→"转换中…"→ 状态依次显示"上传文件中… / MinerU 转换中…"→"完成"。
3. 源文件同目录生成同名 `.md`，内容非空。
4. 鼠标悬停任务行，状态 label 的 tooltip 显示输出路径（完成后）或错误原因（失败后）。
5. 点"⚙ 设置"→ 显示"当前 Key：sk-x\*\*\*\*"掩码 → 关闭。
6. 再拖入同一文件 → 新行"转换中"→ 覆盖生成（再消耗 1 次额度）；或跳过此步省额度。
7. 关闭窗口退出。

- [ ] **Step 6: Commit**

```bash
git add app/ui/worker.py app/ui/task_widgets.py app/ui/main_window.py app/main.py
git commit -m "feat(ui): 主窗口、拖拽区与任务队列"
```

---

### Task 9: 端到端实测（检查点，需用户在场）

**Files:** 无新增（可能产生测试输出，不入库）

- [ ] **Step 1: 准备测试样本**

准备 4 个文件（用户提供）：
1. 普通 PDF（<200 页，含文字/表格）
2. 一个 >200 页大 PDF（如招股书/年报；没有则用 `python -c` 生成 201 页空白 PDF 仅验证分段流程，内容抽查另找真实文件）
3. 一个 Word 文档
4. 一张图片（png/jpg，含文字）

生成 201 页空白 PDF（备用，仅验证分段流程）：
```bash
source .venv/Scripts/activate
python -c "from pypdf import PdfWriter; w=PdfWriter(); [w.add_blank_page(width=612, height=792) for _ in range(201)]; f=open('测试201页.pdf','wb'); w.write(f); f.close()"
```
Expected: 当前目录生成 `测试201页.pdf`。

- [ ] **Step 2: 单文件实测**

逐个拖入样本 1/3/4 → 确认：同目录生成同名 md；Word/图片内容正确；状态与 tooltip 正常。

- [ ] **Step 3: 大 PDF 实测**

拖入样本 2 → 观察"第 x/N 段"进度 → 完成后确认单个 md 生成、无残留 .partN.md → 人工抽查第 200/201 页附近内容衔接（无重复、无大段缺失）。

- [ ] **Step 4: 文件夹实测**

建测试文件夹：`测试夹/子目录/`，混入样本 1/3 + 一个 `.txt` → 整体拖入 → 确认输出到 `文档\MinerU\测试夹\`，子目录结构镜像，txt 被跳过且底部提示"已跳过 1 个不支持的文件"。

- [ ] **Step 5: 失败路径实测（可选，不消耗额度可跳过）**

设置里故意改成错误 Key → 拖文件 → 行显示"失败"，tooltip 为"Key 失效了…"，队列继续；改回正确 Key。

---

### Task 10: PyInstaller 单文件打包

**Files:**
- Create: `packaging/mineru_batch.spec`
- Create: `packaging/build.bat`

- [ ] **Step 1: 编写 spec 与构建脚本**

`packaging/mineru_batch.spec`:
```python
# -*- mode: python ; coding: utf-8 -*-
import os

app_root = os.path.abspath(os.path.join(SPECPATH, "..", "app"))

a = Analysis(
    [os.path.join(app_root, "main.py")],
    pathex=[app_root],
    binaries=[],
    datas=[],
    hiddenimports=["pypdf"],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MinerUBatch",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
)
```

`packaging/build.bat`:
```bat
@echo off
cd /d %~dp0\..
call .venv\Scripts\activate.bat
pyinstaller --noconfirm --clean packaging\mineru_batch.spec --distpath dist --workpath build
if errorlevel 1 (echo BUILD FAILED & exit /b 1)
echo OK: dist\MinerUBatch.exe
```

- [ ] **Step 2: 构建**

```bash
source .venv/Scripts/activate
pyinstaller --noconfirm --clean packaging/mineru_batch.spec --distpath dist --workpath build
```

Expected: 末尾输出 `Building EXE completed successfully.`；生成 `dist/MinerUBatch.exe`（约 30-60MB，首次构建需几分钟）。

- [ ] **Step 3: 验证 exe**

双击运行 `dist\MinerUBatch.exe`（或在 Git Bash 运行 `./dist/MinerUBatch.exe`）：
1. 无控制台窗口弹窗，直接出现图形界面。
2. 已存过 Key 则直接进主窗口；拖一个小文件实测转换（消耗 1 次额度）。
3. 把 exe 复制到桌面双击也能运行（验证不依赖项目目录）。

- [ ] **Step 4: Commit**

```bash
git add packaging/mineru_batch.spec packaging/build.bat .gitignore
git commit -m "chore(packaging): PyInstaller 单文件打包"
```

（dist/ 已在 .gitignore，不入库。）

---

### Task 11: README 与收尾

**Files:**
- Create: `README.md`

- [ ] **Step 1: 编写 README**

`README.md`:
```markdown
# MinerU Batch

把 PDF / Word / PPT / Excel / 图片 / HTML 拖进窗口，自动转成 Markdown（基于 MinerU 精准解析 API）。

## 使用者（拿到 exe 的人）

1. 双击 `MinerUBatch.exe`（无需安装任何东西）。
2. 首次打开会要求填 Key：去 https://mineru.net/apiManage 登录并生成 API Key，粘贴保存。
3. 拖入文件或文件夹：
   - 单个文件 → 在同目录生成同名 `.md`。
   - 文件夹 → 在「文档\MinerU\文件夹名\」下生成整批 `.md`（子文件夹结构保留，不支持的文件自动跳过）。
4. 超过 200 页的 PDF 会自动分段转换后合并成一个 `.md`；中途失败重试会从断点续跑。

注意：每个人需要自己的 Key；每天有用量额度；单个文件不能超过 200MB。

## 开发者

```bash
python -m venv .venv
source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements-dev.txt
python -m pytest tests/         # 运行测试
python -m app.main              # 启动程序
```

打包：`packaging\build.bat`（或手动跑其中的 pyinstaller 命令），产物在 `dist\MinerUBatch.exe`。

## 设计文档

见 `docs/superpowers/specs/2026-09-08-mineru-batch-design.md`。
```

- [ ] **Step 2: 最终全量测试 + Commit**

```bash
python -m pytest tests/ -v
git add README.md
git commit -m "docs: 使用说明 README"
```

Expected: 全部测试通过；git log 共 11 个提交。

---

## 自查记录（Self-Review）

- **Spec 覆盖**：§5.1 界面→T7/T8；§5.2 收集/输出/覆盖/冲突→T3/T8；§5.3 引擎（API/分段/合并/续跑）→T5/T6；§5.4 Key 管理→T2/T7；§5.5 单并发队列→T8；§5.6 错误文案→T4/T8；§6 打包→T10；§7 结构→T1；§8 测试→各任务 TDD + T9。无遗漏。
- **占位符**：无 TBD/TODO；所有代码步骤含完整代码。
- **类型一致性**：`ConvertTask(source, output_md, stem)`（T3 定义，T6/T8 使用）；`MineruClient.convert(source, out_md, page_ranges=None, progress=None)`（T5 定义，T6 调用）；`convert_file(source, out_md, client, progress=None)`（T6 定义，T8 调用）；`friendly_message(exc)`（T4 定义，T8 使用）；worker 信号 idx = 主窗口 `_rows` 行号（T1 定义 worker items 为 `(行号, 任务)`，T8 组装与消费一致）。
