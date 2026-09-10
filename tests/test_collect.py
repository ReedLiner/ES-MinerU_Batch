from pathlib import Path

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
    tasks, skipped, collisions = collect_paths([f])
    assert len(tasks) == 1
    assert tasks[0].source == f
    assert tasks[0].output_md == tmp_path / "年报.md"
    assert tasks[0].stem == "年报"
    assert skipped == [] and collisions == []


def test_folder_recursive_mirror(tmp_path):
    folder = tmp_path / "资料"
    (folder / "子目录").mkdir(parents=True)
    a = folder / "a.pdf"; a.write_bytes(b"x")
    b = folder / "子目录" / "b.docx"; b.write_bytes(b"x")
    txt = folder / "说明.txt"; txt.write_text("x")

    tasks, skipped, collisions = collect_paths([folder])

    assert {t.source for t in tasks} == {a, b}
    by_src = {t.source: t for t in tasks}
    # 输出根 = 源文件夹同级的「同名（MinerU）」目录，内部结构镜像
    assert by_src[a].output_md == tmp_path / "资料（MinerU）" / "a.md"
    assert by_src[b].output_md == tmp_path / "资料（MinerU）" / "子目录" / "b.md"
    assert skipped == [txt]
    assert collisions == []


def test_collision_detected(tmp_path):
    folder = tmp_path / "冲突"
    folder.mkdir()
    a = folder / "a.pdf"; a.write_bytes(b"x")
    b = folder / "a.docx"; b.write_bytes(b"x")

    tasks, skipped, collisions = collect_paths([folder])

    assert len(tasks) == 2
    assert len(collisions) == 1
    out_md, srcs = collisions[0]
    assert out_md == tmp_path / "冲突（MinerU）" / "a.md"
    assert set(srcs) == {a, b}


def test_unsupported_and_missing_skipped(tmp_path):
    txt = tmp_path / "a.txt"; txt.write_text("x")
    ghost = tmp_path / "不存在.pdf"
    tasks, skipped, collisions = collect_paths([txt, ghost])
    assert tasks == []
    assert set(skipped) == {txt, ghost}


def test_output_dir_applies_to_file_and_folder(tmp_path):
    fixed = tmp_path / "统一输出"
    f = tmp_path / "a.pdf"; f.write_bytes(b"x")
    tasks, _, _ = collect_paths([f], output_dir=fixed)
    assert tasks[0].output_md == fixed / "a.md"

    folder = tmp_path / "资料"; folder.mkdir()
    (folder / "b.pdf").write_bytes(b"x")
    tasks, _, _ = collect_paths([folder], output_dir=fixed)
    assert tasks[0].output_md == fixed / "资料" / "b.md"


def test_rename_duplicates(tmp_path):
    folder = tmp_path / "冲突"; folder.mkdir()
    (folder / "a.pdf").write_bytes(b"x")
    (folder / "a.docx").write_bytes(b"x")

    tasks, skipped, collisions = collect_paths([folder], rename_duplicates=True)

    assert sorted(t.output_md.name for t in tasks) == ["a(1).md", "a.md"]
    assert collisions == []
