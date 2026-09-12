"""拖拽目标解析：递归收集受支持的文件，并映射输出路径。"""

from __future__ import annotations

import ctypes
import os
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
    output_dir: Path | None = None,
    rename_duplicates: bool = False,
) -> tuple[list[ConvertTask], list[Path], list[tuple[Path, list[Path]]], list[tuple[Path, str]]]:
    """把拖入的路径解析为转换任务。

    output_dir：非空时所有输出放到该目录下（单文件 → 目录/同名.md；
    文件夹 → 目录/文件夹名/…），为空则输出到源文件旁 / 源文件夹同级的「同名（MinerU）」。
    rename_duplicates：为 True 时同名输出自动加序号（a.md、a(1).md），不再产生冲突。

    返回 (任务列表, 跳过的路径, 同名输出冲突, 无法访问的路径)。
    冲突项 = (输出 md, [来源文件, ...])；无法访问项 = (路径, 原因)。
    """
    tasks: list[ConvertTask] = []
    skipped: list[Path] = []
    errors: list[tuple[Path, str]] = []
    fixed_root = Path(output_dir) if output_dir else None

    def _walk_error(err: OSError) -> None:
        name = getattr(err, "filename", None) or ""
        errors.append((Path(name), f"无法访问（可能无权限）：{err}"))

    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if is_supported(p):
                tasks.append(_task_for_file(p, fixed_root or p.parent))
            else:
                skipped.append(p)
        elif p.is_dir():
            out_root = (fixed_root / p.name) if fixed_root else p.parent / f"{p.name}（MinerU）"
            for root, _dirs, files in os.walk(p, onerror=_walk_error):
                rel = Path(root).relative_to(p)
                for fn in sorted(files):
                    child = Path(root) / fn
                    if is_supported(child):
                        tasks.append(_task_for_file(child, out_root / rel))
                    else:
                        skipped.append(child)
        elif os.path.lexists(p):
            errors.append((p, "无法访问（可能无权限或被占用）"))
        else:
            skipped.append(p)
    if rename_duplicates:
        tasks = _rename_duplicates(tasks)
        return tasks, skipped, [], errors
    return tasks, skipped, _find_collisions(tasks), errors


def _norm_key(path: Path) -> str:
    """Windows 文件系统大小写不敏感，碰撞判断统一用 normcase（M4）。"""
    return os.path.normcase(str(path))


def _rename_duplicates(tasks: list[ConvertTask]) -> list[ConvertTask]:
    """同名输出自动加 (1)/(2)… 序号，避免相互覆盖（大小写不敏感）。"""
    used: set[str] = set()
    result: list[ConvertTask] = []
    for t in tasks:
        target = t.output_md
        if _norm_key(target) in used:
            n = 1
            while _norm_key(target.with_name(f"{t.output_md.stem}({n}).md")) in used:
                n += 1
            target = target.with_name(f"{t.output_md.stem}({n}).md")
        used.add(_norm_key(target))
        result.append(
            t if _norm_key(target) == _norm_key(t.output_md) else ConvertTask(t.source, target, t.stem)
        )
    return result


def _task_for_file(source: Path, out_dir: Path) -> ConvertTask:
    return ConvertTask(source=source, output_md=out_dir / f"{source.stem}.md", stem=source.stem)


def _find_collisions(tasks: list[ConvertTask]) -> list[tuple[Path, list[Path]]]:
    by_out: dict[str, tuple[Path, list[Path]]] = {}
    for t in tasks:
        key = _norm_key(t.output_md)
        if key in by_out:
            by_out[key][1].append(t.source)
        else:
            by_out[key] = (t.output_md, [t.source])
    return [entry for entry in by_out.values() if len(entry[1]) > 1]
