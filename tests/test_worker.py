"""worker 并发核心回归测试（H4：放弃一个任务不得连锁取消后续批次）。"""

from pathlib import Path

import pytest

from app.ui import worker as worker_mod
from app.ui.worker import ConvertWorker

qt = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    app = qt.QApplication.instance() or qt.QApplication([])
    yield app


def _task(tmp_path: Path, name: str):
    src = tmp_path / name
    src.write_bytes(b"x")
    return src, src.with_suffix(".md")


def test_abandon_does_not_chain_cancel(qapp, tmp_path, monkeypatch):
    """H4/TC20：放弃单文件任务后，后续批量组必须正常提交。"""
    html, html_out = _task(tmp_path, "single.html")       # HTML 不参与批量 → 单文件流程
    b1, b1_out = _task(tmp_path, "b1.docx")
    b2, b2_out = _task(tmp_path, "b2.docx")

    items = [(0, type("T", (), {"source": html, "output_md": html_out})()),
             (1, type("T", (), {"source": b1, "output_md": b1_out})()),
             (2, type("T", (), {"source": b2, "output_md": b2_out})())]
    w = ConvertWorker(items, "sk-test", batch_size=2)

    seen = {"cancel_at_batch": None}

    def fake_convert_file(source, out_md, client, progress=None, cancel_check=None):
        # 模拟用户在单文件任务进行中点了「放弃」
        w._abandon = True
        from app.engine.errors import MineruError
        raise MineruError("已放弃等待该任务", code="CANCELLED")

    def fake_convert_many(client, jobs, progress=None, cancel_check=None):
        seen["cancel_at_batch"] = bool(cancel_check())
        return [(s, o, None) for s, o in jobs]

    monkeypatch.setattr(worker_mod, "convert_file", fake_convert_file)
    monkeypatch.setattr(worker_mod, "convert_many", fake_convert_many)

    events = {"finished": [], "cancelled": [], "done": None}
    w.task_finished.connect(lambda i, ok, m: events["finished"].append((i, ok)))
    w.task_cancelled.connect(lambda i, m: events["cancelled"].append(i))
    w.all_done.connect(lambda ok, f, c: events.update(done=(ok, f, c)))

    w.run()

    assert seen["cancel_at_batch"] is False          # 批量组未被放弃标记污染
    assert events["cancelled"] == [0]                # 只有被放弃的那一个
    assert events["finished"] == [(1, True), (2, True)]
    assert events["done"] == (2, 0, 1)


def test_cancel_all_during_batch_building(qapp, tmp_path, monkeypatch):
    """攒批期间点「全部停止」：已攒的任务不得再提交（避免白扣额度）。"""
    from pypdf import PdfWriter

    b1, b1_out = _task(tmp_path, "b1.docx")
    mid = tmp_path / "mid.pdf"                       # 可批量的 PDF，数页数期间触发停止
    w_pdf = PdfWriter()
    for _ in range(3):
        w_pdf.add_blank_page(width=612, height=792)
    with mid.open("wb") as fh:
        w_pdf.write(fh)
    b3, b3_out = _task(tmp_path, "b3.docx")

    items = [(0, type("T", (), {"source": b1, "output_md": b1_out})()),
             (1, type("T", (), {"source": mid, "output_md": mid.with_suffix(".md")})()),
             (2, type("T", (), {"source": b3, "output_md": b3_out})())]
    w = ConvertWorker(items, "sk-test", batch_size=10)

    submitted = {"jobs": None}

    def fake_convert_many(client, jobs, progress=None, cancel_check=None):
        submitted["jobs"] = list(jobs)
        return [(s, o, None) for s, o in jobs]

    monkeypatch.setattr(worker_mod, "convert_many", fake_convert_many)
    monkeypatch.setattr(worker_mod, "convert_file", lambda *a, **k: None)

    orig_can_batch = worker_mod.can_batch

    def can_batch_with_cancel(source):
        result = orig_can_batch(source)
        if source.suffix == ".pdf":
            w.cancel_all()  # 模拟攒批期间用户点了「全部停止」
        return result

    monkeypatch.setattr(worker_mod, "can_batch", can_batch_with_cancel)

    events = {"cancelled": [], "done": None}
    w.task_cancelled.connect(lambda i, m: events["cancelled"].append(i))
    w.all_done.connect(lambda ok, f, c: events.update(done=(ok, f, c)))

    w.run()

    assert submitted["jobs"] in (None, [])           # 一个都没提交
    assert sorted(events["cancelled"]) == [0, 1, 2]
    assert events["done"] == (0, 0, 3)
