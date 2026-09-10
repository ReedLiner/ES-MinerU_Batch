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
    output_dir: Path | None = None,
    rename_duplicates: bool = False,
) -> tuple[list[ConvertTask], list[Path], list[tuple[Path, list[Path]]]]:
    """把拖入的路径解析为转换任务。

    output_dir：非空时所有输出放到该目录下（单文件 → 目录/同名.md；
    文件夹 → 目录/文件夹名/…），为空则输出到源文件旁 / 源文件夹同级的「同名（MinerU）」。
    rename_duplicates：为 True 时同名输出自动加序号（a.md、a(1).md），不再产生冲突。

    返回 (任务列表, 跳过的路径, 同名输出冲突)。冲突项 = (输出 md, [来源文件, ...])。
    """
    tasks: list[ConvertTask] = []
    skipped: list[Path] = []
    fixed_root = Path(output_dir) if output_dir else None
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            if is_supported(p):
                tasks.append(_task_for_file(p, fixed_root or p.parent))
            else:
                skipped.append(p)
        elif p.is_dir():
            out_root = (fixed_root / p.name) if fixed_root else p.parent / f"{p.name}（MinerU）"
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
    if rename_duplicates:
        tasks = _rename_duplicates(tasks)
        return tasks, skipped, []
    return tasks, skipped, _find_collisions(tasks)


def _rename_duplicates(tasks: list[ConvertTask]) -> list[ConvertTask]:
    """同名输出自动加 (1)/(2)… 序号，避免相互覆盖。"""
    used: set[Path] = set()
    result: list[ConvertTask] = []
    for t in tasks:
        target = t.output_md
        if target in used:
            n = 1
            while target.with_name(f"{t.output_md.stem}({n}).md") in used:
                n += 1
            target = target.with_name(f"{t.output_md.stem}({n}).md")
        used.add(target)
        result.append(
            t if target == t.output_md else ConvertTask(t.source, target, t.stem)
        )
    return result


def _task_for_file(source: Path, out_dir: Path) -> ConvertTask:
    return ConvertTask(source=source, output_md=out_dir / f"{source.stem}.md", stem=source.stem)


def _find_collisions(tasks: list[ConvertTask]) -> list[tuple[Path, list[Path]]]:
    by_out: dict[Path, list[Path]] = {}
    for t in tasks:
        by_out.setdefault(t.output_md, []).append(t.source)
    return [(out, srcs) for out, srcs in by_out.items() if len(srcs) > 1]
