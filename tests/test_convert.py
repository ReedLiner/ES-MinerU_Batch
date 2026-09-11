from pathlib import Path

import pytest
from pypdf import PdfWriter

from app.engine.convert import (
    can_batch,
    chunk_size_for,
    convert_file,
    convert_many,
    count_pdf_pages,
    is_large_pdf,
    plan_chunks,
)
from app.engine.errors import MineruError


class FakeBatchClient:
    """记录每次批量调用，并把每个输出写成占位内容。"""

    def __init__(self):
        self.batches: list[list[tuple[Path, Path]]] = []

    def convert_batch(self, jobs, progress=None, cancel_check=None):
        jobs = list(jobs)
        self.batches.append(jobs)
        results = []
        for src, out in jobs:
            out = Path(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text("batched", encoding="utf-8")
            results.append((src, out, None))
        return results


class FakeClient:
    """记录调用并按 page_ranges 写标记内容，模拟 MineruClient.convert。"""

    def __init__(self):
        self.calls: list[dict] = []

    def convert(self, source, out_md, page_ranges=None, progress=None, cancel_check=None):
        source = Path(source)
        out_md = Path(out_md)
        self.calls.append({
            "source": source,
            "out_md": out_md,
            "page_ranges": page_ranges,
            "cancel_check": cancel_check,
        })
        out_md.parent.mkdir(parents=True, exist_ok=True)
        out_md.write_text(f"content-{page_ranges or 'full'}", encoding="utf-8")


class RejectingBatchClient(FakeClient):
    """提交阶段被拒（未上传任何文件），单文件转换正常。"""

    def __init__(self):
        super().__init__()
        self.batch_calls = 0

    def convert_batch(self, jobs, progress=None, cancel_check=None):
        self.batch_calls += 1
        raise MineruError(
            'field "files.data_id" cannot exceed 128 characters', code="BATCH_REJECTED"
        )


class UploadFailClient(FakeClient):
    """已进入上传阶段后失败：不能降级重试，否则会重复提交、重复扣额度。"""

    def convert_batch(self, jobs, progress=None, cancel_check=None):
        raise MineruError("上传失败：连接中断", code="NETWORK")


class FlakyClient(FakeClient):
    """前 N 次调用抛“临时故障”，用于验证分段重试。"""

    def __init__(self, fail_times: int = 1):
        super().__init__()
        self.fail_times = fail_times

    def convert(self, *args, **kwargs):
        if self.fail_times > 0:
            self.fail_times -= 1
            self.calls.append({"page_ranges": kwargs.get("page_ranges"), "failed": True})
            raise MineruError("临时故障", code="NETWORK")
        return super().convert(*args, **kwargs)


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


def test_chunk_size_for():
    assert chunk_size_for(500) == 200
    assert chunk_size_for(700) == 150
    assert chunk_size_for(1200) == 100


def test_chunk_failure_retries_once(tmp_path):
    src = _make_pdf(tmp_path / "r.pdf", 201)
    client = FlakyClient(fail_times=1)
    convert_file(src, tmp_path / "r.md", client)
    # 第 1 段失败后自动重试一次，再继续第 2 段
    assert [c["page_ranges"] for c in client.calls] == ["1-200", "1-200", "201-201"]


def test_chunk_failure_gives_up(tmp_path):
    src = _make_pdf(tmp_path / "r.pdf", 201)
    client = FlakyClient(fail_times=9)
    with pytest.raises(MineruError):
        convert_file(src, tmp_path / "r.md", client)
    assert len(client.calls) == 2  # 1 次 + 1 次重试


def test_can_batch(tmp_path):
    small = _make_pdf(tmp_path / "small.pdf", 10)
    big = _make_pdf(tmp_path / "big.pdf", 201)
    doc = tmp_path / "d.docx"; doc.write_bytes(b"x")
    html = tmp_path / "p.html"; html.write_bytes(b"<p>x</p>")
    broken = tmp_path / "broken.pdf"; broken.write_bytes(b"not a pdf")

    assert can_batch(small) is True
    assert can_batch(doc) is True
    assert can_batch(big) is False          # 需要分段，单独转换
    assert can_batch(html) is False         # 需 MinerU-HTML 模型
    assert can_batch(broken) is False       # 页数读不出，交给单文件流程给出明确报错


def test_is_large_pdf(tmp_path):
    assert is_large_pdf(_make_pdf(tmp_path / "big.pdf", 201)) is True
    assert is_large_pdf(_make_pdf(tmp_path / "s.pdf", 10)) is False
    d = tmp_path / "d.docx"; d.write_bytes(b"x")
    assert is_large_pdf(d) is False


def test_convert_many_splits_batches(tmp_path):
    client = FakeBatchClient()
    jobs = [(tmp_path / f"{i}.pdf", tmp_path / f"{i}.md") for i in range(51)]
    convert_many(client, jobs)
    assert [len(b) for b in client.batches] == [50, 1]
    assert (tmp_path / "50.md").exists()


def test_convert_many_falls_back_to_single_when_batch_rejected(tmp_path):
    """整批被拒（如某文件名超长）时，自动改为逐个转换，不连累同批其它文件。"""
    a = tmp_path / "a.docx"; a.write_bytes(b"x")
    b = tmp_path / "b.docx"; b.write_bytes(b"x")
    client = RejectingBatchClient()
    results = convert_many(client, [(a, tmp_path / "a.md"), (b, tmp_path / "b.md")])
    assert client.batch_calls == 1
    assert len(client.calls) == 2  # 已降级为逐个转换
    assert [e for _, _, e in results] == [None, None]
    assert (tmp_path / "a.md").exists() and (tmp_path / "b.md").exists()


def test_convert_many_does_not_fall_back_after_upload(tmp_path):
    """上传阶段之后的失败不应再逐个重试，避免同一文件被提交两次。"""
    a = tmp_path / "a.docx"; a.write_bytes(b"x")
    client = UploadFailClient()
    with pytest.raises(MineruError):
        convert_many(client, [(a, tmp_path / "a.md")])
    assert client.calls == []  # 没有重复提交


def test_empty_part_is_reconverted(tmp_path):
    # 上次崩溃残留的 0 字节分段文件不能算“已完成”
    src = _make_pdf(tmp_path / "e.pdf", 201)
    (tmp_path / "e.part1.md").write_bytes(b"")
    client = FakeClient()
    convert_file(src, tmp_path / "e.md", client)
    assert [c["page_ranges"] for c in client.calls] == ["1-200", "201-201"]


def test_progress_callback_optional(tmp_path):
    src = _make_pdf(tmp_path / "a.pdf", 3)
    convert_file(src, tmp_path / "a.md", FakeClient())  # 不传 progress 不报错


def test_cancel_check_forwarded(tmp_path):
    src = tmp_path / "f.docx"
    src.write_bytes(b"x")
    client = FakeClient()
    flag = lambda: False  # noqa: E731
    convert_file(src, tmp_path / "f.md", client, cancel_check=flag)
    assert client.calls[0]["cancel_check"] is flag


def test_cancel_between_chunks_keeps_parts(tmp_path):
    src = _make_pdf(tmp_path / "k.pdf", 201)
    client = FakeClient()
    state = {"checks": 0}

    def cancel_check():
        state["checks"] += 1
        return state["checks"] > 1

    with pytest.raises(MineruError) as ei:
        convert_file(src, tmp_path / "k.md", client, cancel_check=cancel_check)
    assert ei.value.code == "CANCELLED"
    # 第 1 段已转换并保留（可续跑），第 2 段未开始，最终 md 未生成
    assert (tmp_path / "k.part1.md").exists()
    assert not (tmp_path / "k.part2.md").exists()
    assert not (tmp_path / "k.md").exists()
