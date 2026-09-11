"""转换编排：非 PDF / 小 PDF 直转；大 PDF 分段转换后合并。

断点续跑：已存在的 .partN.md 直接跳过（成功的转换不会留下分段文件，
所以已完成的文件重拖 = 完整重转 + 覆盖，见设计文档 5.3）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from app.core.config import MAX_BATCH_FILES
from app.engine.client import HTML_EXTS, MineruClient, ProgressCb
from app.engine.errors import MineruError, friendly_message

CHUNK_SIZE = 200  # MinerU 单次任务页数上限
_RETRY_CODES = ("NETWORK", "TIMEOUT", "-60006")  # 分段失败后值得重试的错误


def can_batch(source: Path) -> bool:
    """能否参与批量提交。

    排除：HTML（需专用模型）、>200 页的 PDF（需分段）、
    以及页数读不出的 PDF（交给单文件流程，给出本地可读的明确报错）。
    """
    source = Path(source)
    suffix = source.suffix.lower()
    if suffix in HTML_EXTS:
        return False
    if suffix != ".pdf":
        return True
    try:
        pages = count_pdf_pages(source)
    except MineruError:
        return False
    return pages <= CHUNK_SIZE


def plan_chunks(pages: int, size: int = CHUNK_SIZE) -> list[tuple[int, int]]:
    if pages < 1:
        raise ValueError("页数必须 >= 1")
    return [(s, min(s + size - 1, pages)) for s in range(1, pages + 1, size)]


def chunk_size_for(pages: int) -> int:
    """页数越多，单段越小，降低一次失败的重试成本。"""
    if pages > 1000:
        return 100
    if pages > 600:
        return 150
    return CHUNK_SIZE


def count_pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise MineruError("缺少 pypdf 依赖，无法统计 PDF 页数") from exc
    try:
        return len(PdfReader(str(path)).pages)
    except Exception as exc:
        raise MineruError(f"无法读取 PDF 页数（文件可能损坏或加密）：{exc}") from exc


def is_large_pdf(source: Path) -> bool:
    """是否需要分段（>200 页的 PDF）；读不出页数时按“不需要”处理，由转换流程报错。"""
    source = Path(source)
    if source.suffix.lower() != ".pdf":
        return False
    try:
        return count_pdf_pages(source) > CHUNK_SIZE
    except MineruError:
        return False


def convert_many(
    client: MineruClient,
    jobs: list[tuple[Path, Path]],
    progress: ProgressCb | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> list[tuple[Path, Path, str | None]]:
    """批量转换：自动按每批 ≤50 个文件切分提交。

    返回 [(source, out_md, 错误原因|None)]，顺序与入参一致。
    """
    jobs = [(Path(s), Path(o)) for s, o in jobs]
    results: list[tuple[Path, Path, str | None]] = []
    for i in range(0, len(jobs), MAX_BATCH_FILES):
        chunk = jobs[i : i + MAX_BATCH_FILES]
        try:
            results.extend(
                client.convert_batch(chunk, progress=progress, cancel_check=cancel_check)
            )
        except MineruError as exc:
            # 仅在"提交阶段被拒"时降级（此时还没上传任何文件，不会重复扣额度）；
            # 已进入上传/轮询后的失败必须原样抛出，避免同一文件被提交两次
            if exc.code != "BATCH_REJECTED":
                raise
            _report(progress, f"批量提交失败：{exc}；改为逐个转换…")
            results.extend(_convert_one_by_one(client, chunk, progress, cancel_check))
    return results


def _convert_one_by_one(
    client: MineruClient,
    jobs: list[tuple[Path, Path]],
    progress: ProgressCb | None,
    cancel_check: Callable[[], bool] | None,
) -> list[tuple[Path, Path, str | None]]:
    results: list[tuple[Path, Path, str | None]] = []
    for src, out_md in jobs:
        try:
            convert_file(src, out_md, client, progress=progress, cancel_check=cancel_check)
        except MineruError as exc:
            results.append((src, out_md, friendly_message(exc)))
        except Exception as exc:  # 兜底
            results.append((src, out_md, f"未预期错误：{exc}"))
        else:
            results.append((src, out_md, None))
    return results


def convert_file(
    source: Path,
    out_md: Path,
    client: MineruClient,
    progress: ProgressCb | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    source = Path(source)
    out_md = Path(out_md)

    if source.suffix.lower() != ".pdf":
        client.convert(source, out_md, progress=progress, cancel_check=cancel_check)
        return out_md

    pages = count_pdf_pages(source)
    if pages <= CHUNK_SIZE:
        client.convert(source, out_md, progress=progress, cancel_check=cancel_check)
        return out_md

    chunks = plan_chunks(pages, chunk_size_for(pages))
    parts = [out_md.parent / f"{out_md.stem}.part{i}.md" for i in range(1, len(chunks) + 1)]
    total = len(chunks)
    for i, ((s, e), part) in enumerate(zip(chunks, parts), start=1):
        if cancel_check and cancel_check():
            raise MineruError("已取消该任务", code="CANCELLED")
        if _part_done(part):
            _report(progress, f"{source.name}：第 {i}/{total} 段已完成，跳过")
            continue
        _report(progress, f"{source.name}：转换第 {i}/{total} 段（第 {s}-{e} 页）")
        try:
            client.convert(source, part, page_ranges=f"{s}-{e}", cancel_check=cancel_check)
        except MineruError as exc:
            if exc.code not in _RETRY_CODES:
                raise
            _report(progress, f"{source.name}：第 {i}/{total} 段失败，重试一次…")
            client.convert(source, part, page_ranges=f"{s}-{e}", cancel_check=cancel_check)

    _merge(parts, out_md)
    for part in parts:
        part.unlink(missing_ok=True)
    _report(progress, f"{source.name}：完成（{pages} 页，{total} 段合并）")
    return out_md


def _part_done(part: Path) -> bool:
    """分段文件存在且非空才算完成（0 字节通常是上次崩溃的残留）。"""
    try:
        return part.exists() and part.stat().st_size > 0
    except OSError:
        return False


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
