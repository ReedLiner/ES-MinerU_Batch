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

from app.core.config import MAX_BATCH_FILES
from app.engine.errors import MineruError, friendly_message

API_BASE = "https://mineru.net/api/v4"
MAX_FILE_SIZE = 200 * 1024 * 1024  # 200 MB（MinerU 在线上限）

_POLL_INITIAL = 2.0
_POLL_MAX = 15.0
_UPLOAD_CHUNK = 8 * 1024 * 1024
_RETRY_TIMES = 2        # 网络类失败额外重试次数
_RETRY_INITIAL = 1.0    # 退避起始秒数

_SLEEP = time.sleep  # 测试可替换

DEFAULT_PARAMS = {
    "enable_formula": True,
    "enable_table": True,
}

ProgressCb = Callable[[str], None]
CancelCheck = Callable[[], bool]

HTML_EXTS = (".html", ".htm")


class MineruClient:
    def __init__(
        self,
        token: str,
        base: str = API_BASE,
        session: requests.Session | None = None,
        timeout: int = 1800,
        is_ocr: bool = False,
        language: str = "ch",
    ):
        key = (token or "").strip()
        if not key:
            raise ValueError("API Key 不能为空")
        self._token = key
        self._base = base.rstrip("/")
        self._session = session or requests.Session()
        self._timeout = timeout
        self._is_ocr = bool(is_ocr)
        self._language = language or "ch"

    # ---------- 主流程 ----------

    def convert(
        self,
        source: Path,
        out_md: Path,
        page_ranges: str | None = None,
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> None:
        source = Path(source)
        out_md = Path(out_md)
        if cancel_check and cancel_check():
            raise MineruError("已取消该任务", code="CANCELLED")
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise MineruError(
                f"文件不存在或无法访问：{source.name}",
                friendly=f"文件无法访问：{source.name}（可能已被移动、删除，或被其他程序占用）",
            ) from exc
        if size > MAX_FILE_SIZE:
            raise MineruError(f"文件 {source.name} 超过 200MB", code="-60005")
        out_md.parent.mkdir(parents=True, exist_ok=True)

        # 申请链接与上传阶段失败可安全重试（任务尚未开始，不产生额外额度）
        batch_id, raw_upload_url = self._retry(
            lambda: self._create_batch(source, page_ranges), cancel_check
        )
        upload_url = _require_https(raw_upload_url, "上传")
        _report(progress, "上传文件中…")
        self._retry(lambda: self._upload(upload_url, source), cancel_check)
        _report(progress, "MinerU 转换中…")
        data = self._poll_batch(batch_id, cancel_check)

        records = _records(data)
        record = records[0] if records else {}
        if record.get("err_msg"):
            raise MineruError(f"转换失败：{record['err_msg']}")
        zip_url = record.get("full_zip_url") or data.get("full_zip_url")
        if not zip_url:
            raise MineruError("任务完成但未返回下载地址")
        zip_url = _require_https(zip_url, "结果下载")

        tmp_zip = out_md.with_suffix(".zip.tmp")
        try:
            self._retry(lambda: self._download(zip_url, tmp_zip), cancel_check)
            _extract_full_md(tmp_zip, out_md)
        finally:
            tmp_zip.unlink(missing_ok=True)

    def _retry(self, op, cancel_check: CancelCheck | None = None):
        """仅对网络类错误做指数退避重试；业务错误（额度/鉴权等）立即抛出。"""
        delay = _RETRY_INITIAL
        last: MineruError | None = None
        for attempt in range(_RETRY_TIMES + 1):
            if cancel_check and cancel_check():
                raise MineruError("已取消该任务", code="CANCELLED")
            try:
                return op()
            except MineruError as exc:
                if exc.code != "NETWORK":
                    raise
                last = exc
                if attempt < _RETRY_TIMES:
                    _SLEEP(delay)
                    delay *= 2
        raise last

    def convert_batch(
        self,
        jobs: list[tuple[Path, Path]],
        progress: ProgressCb | None = None,
        cancel_check: CancelCheck | None = None,
    ) -> list[tuple[Path, Path, str | None]]:
        """一次提交多个文件（≤50）：批量申请链接 → 逐个上传 → 一次轮询 → 逐个写 md。

        返回 [(source, out_md, 错误原因|None), ...]，顺序与入参一致；
        单个文件失败只影响它自己，同批其它文件照常输出。
        注意：HTML 文件不参与批量（需专用模型），由调用方单独走 convert()。
        """
        if not jobs:
            return []
        if len(jobs) > MAX_BATCH_FILES:
            raise ValueError(f"单批最多 {MAX_BATCH_FILES} 个文件，收到 {len(jobs)} 个")

        sources: list[Path] = []
        for src, out_md in jobs:
            source = Path(src)
            try:
                if source.stat().st_size > MAX_FILE_SIZE:
                    raise MineruError(f"文件 {source.name} 超过 200MB", code="-60005")
            except OSError as exc:
                raise MineruError(
                    f"文件不存在或无法访问：{source.name}",
                    friendly=f"文件无法访问：{source.name}（可能已被移动、删除，或被其他程序占用）",
                ) from exc
            Path(out_md).parent.mkdir(parents=True, exist_ok=True)
            sources.append(source)

        batch_id, raw_urls = self._retry(
            lambda: self._create_batch_many(sources), cancel_check
        )
        if len(raw_urls) < len(sources):
            raise MineruError("申请到的上传链接数量不足")
        urls = [_require_https(u, "上传") for u in raw_urls[: len(sources)]]

        total = len(sources)
        for i, (url, src) in enumerate(zip(urls, sources), start=1):
            if cancel_check and cancel_check():
                raise MineruError("已取消该任务", code="CANCELLED")
            _report(progress, f"上传文件 {i}/{total}…")
            self._retry(lambda u=url, s=src: self._upload(u, s), cancel_check)

        _report(progress, f"MinerU 转换中（{total} 个文件）…")
        # 批量：单个文件失败不中断整批，等所有记录进入终态后逐个判定
        data = self._poll_batch(batch_id, cancel_check, fail_fast=False)
        records = _records(data)

        # 按 data_id 精确配对（提交时已保证唯一），返回顺序不可靠也不会错位
        by_id: dict[str, dict] = {}
        for rec in records:
            key = rec.get("data_id")
            if key:
                by_id[key] = rec

        results: list[tuple[Path, Path, str | None]] = []
        for idx, (src, out_md) in enumerate(jobs):
            source = Path(src)
            out_md = Path(out_md)
            rec = by_id.get(_data_id_for(source, idx))
            if rec is None and idx < len(records):
                rec = records[idx]  # 兜底：按提交顺序
            if rec is None:
                results.append((source, out_md, "未返回结果"))
                continue
            if rec.get("state") == "failed":
                results.append((source, out_md, f"转换失败：{rec.get('err_msg') or 'unknown'}"))
                continue
            try:
                zip_url = _require_https(rec.get("full_zip_url") or "", "结果下载")
                tmp_zip = out_md.with_suffix(".zip.tmp")
                try:
                    self._retry(lambda z=zip_url, t=tmp_zip: self._download(z, t), cancel_check)
                    _extract_full_md(tmp_zip, out_md)
                finally:
                    tmp_zip.unlink(missing_ok=True)
            except MineruError as exc:
                results.append((source, out_md, friendly_message(exc)))
            else:
                results.append((source, out_md, None))
        return results

    # ---------- 各步骤 ----------

    def _create_batch_many(self, sources: list[Path]) -> tuple[str, list[str]]:
        # data_id 必须唯一（同名文件会重名），用于把结果精确配对回源文件
        files = [
            {"name": s.name, "is_ocr": self._is_ocr, "data_id": _data_id_for(s, i)}
            for i, s in enumerate(sources)
        ]
        # 批量任务统一走 vlm（HTML 不参与批量）
        payload = {
            "files": files,
            "model_version": "vlm",
            "language": self._language,
            **DEFAULT_PARAMS,
        }
        body = self._post("/file-urls/batch", payload)
        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        urls = data.get("file_urls") or []
        if not batch_id or not urls:
            raise MineruError(f"申请上传链接失败: {body}")
        return batch_id, urls

    def _create_batch(self, source: Path, page_ranges: str | None) -> tuple[str, str]:
        files = [{"name": source.name, "is_ocr": self._is_ocr, "data_id": source.stem}]
        if page_ranges:
            files[0]["page_ranges"] = page_ranges
        # 官方要求：HTML 文件必须使用 MinerU-HTML 模型
        model = "MinerU-HTML" if source.suffix.lower() in HTML_EXTS else "vlm"
        payload = {
            "files": files,
            "model_version": model,
            "language": self._language,
            **DEFAULT_PARAMS,
        }
        body = self._post("/file-urls/batch", payload)
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
        except (requests.RequestException, OSError) as exc:
            # OSError：文件被占用/被删除等本地读取失败
            raise MineruError(
                f"上传失败：{exc}",
                code="NETWORK",
                friendly=f"读取或上传文件失败：{exc}。文件可能被其他程序占用，请关闭后重试。",
            ) from exc
        if resp.status_code >= 400:
            raise MineruError(f"上传失败 HTTP {resp.status_code}")

    def _poll_batch(
        self,
        batch_id: str,
        cancel_check: CancelCheck | None = None,
        fail_fast: bool = True,
    ) -> dict[str, Any]:
        """轮询结果。fail_fast=True 时任一失败立即报错；批量场景传 False，等全部终态后逐个判定。"""
        started = time.time()
        delay = _POLL_INITIAL
        while True:
            if cancel_check and cancel_check():
                raise MineruError("已放弃等待该任务", code="CANCELLED")
            body = self._get(f"/extract-results/batch/{batch_id}")
            data = body.get("data") or {}
            records = _records(data)
            states = [r.get("state") for r in records]
            if records and all(s == "done" for s in states):
                return data
            # 任一失败立即报错，避免空转到超时
            failed = next((r for r in records if r.get("state") == "failed"), None)
            if failed is not None:
                err = failed.get("err_msg") or "unknown"
                if fail_fast:
                    raise MineruError(f"转换失败：{err}")
                if records and all(s in ("done", "failed") for s in states):
                    return data
            if time.time() - started >= self._timeout:
                raise MineruError(f"转换超时（>{self._timeout}s）", code="TIMEOUT")
            _SLEEP(min(delay, _POLL_MAX))
            delay = min(delay * 1.5, _POLL_MAX)

    def _download(self, url: str, dest: Path) -> None:
        try:
            with self._session.get(url, timeout=300) as resp:
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


def _data_id_for(source: Path, index: int) -> str:
    """批内唯一的 data_id（文件名可能重名，用下标区分）。"""
    return f"{source.stem}_{index + 1}"


def _require_https(url: Any, what: str) -> str:
    """只允许 https 地址，避免把文件内容发到非加密/内网地址。"""
    if not isinstance(url, str) or not url.startswith("https://"):
        raise MineruError(f"{what}地址不是 https，已拒绝：{url}")
    return url


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
    except OSError as exc:
        raise MineruError(f"写入 Markdown 失败：{exc}（目标路径不可写或磁盘已满）") from exc


def _report(progress: ProgressCb | None, msg: str) -> None:
    if progress:
        progress(msg)
