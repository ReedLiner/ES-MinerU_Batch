from pathlib import Path

from app.core import collect
from app.core.collect import SUPPORTED_EXTS, collect_paths, is_supported


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
    tasks, skipped, collisions, errors = collect_paths([f])
    assert len(tasks) == 1
    assert tasks[0].source == f
    assert tasks[0].output_md == tmp_path / "年报.md"
    assert tasks[0].stem == "年报"
    assert skipped == [] and collisions == [] and errors == []


def test_folder_recursive_mirror(tmp_path):
    folder = tmp_path / "资料"
    (folder / "子目录").mkdir(parents=True)
    a = folder / "a.pdf"; a.write_bytes(b"x")
    b = folder / "子目录" / "b.docx"; b.write_bytes(b"x")
    txt = folder / "说明.txt"; txt.write_text("x")

    tasks, skipped, collisions, errors = collect_paths([folder])

    assert {t.source for t in tasks} == {a, b}
    by_src = {t.source: t for t in tasks}
    # 输出根 = 源文件夹同级的「同名（MinerU）」目录，内部结构镜像
    assert by_src[a].output_md == tmp_path / "资料（MinerU）" / "a.md"
    assert by_src[b].output_md == tmp_path / "资料（MinerU）" / "子目录" / "b.md"
    assert skipped == [txt]
    assert collisions == [] and errors == []


def test_collision_detected(tmp_path):
    folder = tmp_path / "冲突"
    folder.mkdir()
    a = folder / "a.pdf"; a.write_bytes(b"x")
    b = folder / "a.docx"; b.write_bytes(b"x")

    tasks, skipped, collisions, errors = collect_paths([folder])

    assert len(tasks) == 2
    assert len(collisions) == 1
    out_md, srcs = collisions[0]
    assert out_md == tmp_path / "冲突（MinerU）" / "a.md"
    assert set(srcs) == {a, b}
    assert errors == []


def test_case_insensitive_collision(tmp_path):
    """M4：Windows 大小写不敏感，A.md 与 a.md 视为同名冲突。"""
    folder = tmp_path / "大小写"
    folder.mkdir()
    (folder / "A.pdf").write_bytes(b"x")
    (folder / "a.docx").write_bytes(b"x")

    tasks, skipped, collisions, errors = collect_paths([folder])
    assert len(collisions) == 1

    tasks, skipped, collisions, errors = collect_paths([folder], rename_duplicates=True)
    assert collisions == []
    assert len({Path(str(t.output_md)).name.lower() for t in tasks}) == 2  # 已区分开


def test_unsupported_and_missing_skipped(tmp_path):
    txt = tmp_path / "a.txt"; txt.write_text("x")
    ghost = tmp_path / "不存在.pdf"
    tasks, skipped, collisions, errors = collect_paths([txt, ghost])
    assert tasks == []
    assert set(skipped) == {txt, ghost}


def test_output_dir_applies_to_file_and_folder(tmp_path):
    fixed = tmp_path / "统一输出"
    f = tmp_path / "a.pdf"; f.write_bytes(b"x")
    tasks, _, _, _ = collect_paths([f], output_dir=fixed)
    assert tasks[0].output_md == fixed / "a.md"

    folder = tmp_path / "资料"; folder.mkdir()
    (folder / "b.pdf").write_bytes(b"x")
    tasks, _, _, _ = collect_paths([folder], output_dir=fixed)
    assert tasks[0].output_md == fixed / "资料" / "b.md"


def test_rename_duplicates(tmp_path):
    folder = tmp_path / "冲突"
    folder.mkdir()
    (folder / "a.pdf").write_bytes(b"x")
    (folder / "a.docx").write_bytes(b"x")

    tasks, skipped, collisions, errors = collect_paths([folder], rename_duplicates=True)

    assert sorted(t.output_md.name for t in tasks) == ["a(1).md", "a.md"]
    assert collisions == []


def test_walk_permission_error_reported(tmp_path, monkeypatch):
    """H5：遍历子目录被拒时应报告，而不是静默吞掉。"""
    folder = tmp_path / "受控"; folder.mkdir()
    (folder / "a.pdf").write_bytes(b"x")

    def fake_walk(top, onerror=None):
        if onerror:
            err = PermissionError("denied")
            err.filename = str(top)
            onerror(err)
        return iter([])

    monkeypatch.setattr(collect.os, "walk", fake_walk)
    tasks, skipped, collisions, errors = collect_paths([folder])
    assert tasks == []
    assert errors and "无法访问" in errors[0][1]


def test_unreadable_single_file_reported(tmp_path, monkeypatch):
    """H5：存在但读不了的文件归类为无法访问，不进任务。"""
    f = tmp_path / "a.pdf"; f.write_bytes(b"x")
    monkeypatch.setattr(collect.Path, "is_file", lambda self: False)
    tasks, skipped, collisions, errors = collect_paths([f])
    assert tasks == []
    assert errors and errors[0][0] == f
