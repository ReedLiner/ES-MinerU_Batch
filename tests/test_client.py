import zipfile
from pathlib import Path

import pytest
import requests

from app.engine import client as client_mod
from app.engine.client import MineruClient
from app.engine.convert import convert_many
from app.engine.errors import MineruError, friendly_message


class FakeResp:
    def __init__(self, status=200, body=None, content=b"", headers=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.content = content
        self.text = ""
        self.headers = headers or {}

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
    assert s.posts[0]["json"]["files"][0]["data_id"] == "f1"  # 不使用文件名（避免超 128 字符）
    assert s.puts == [("https://up/1", b"pdf-bytes")]
    assert s.gets[0].endswith("/extract-results/batch/b1")


def test_convert_passes_page_ranges(tmp_path):
    src = tmp_path / "big.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://zip/1"}]}}),
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
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "failed", "err_msg": "bad"}]}})]
    with pytest.raises(MineruError, match="bad"):
        _client(s).convert(src, tmp_path / "o.md")


def test_poll_timeout(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "doing"}]}})]
    with pytest.raises(MineruError) as ei:
        _client(s, timeout=0).convert(src, tmp_path / "o.md")
    assert ei.value.code == "TIMEOUT"


def test_records_dict_normalized(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": {"state": "done", "full_zip_url": "https://zip/1"}}}),
                       FakeResp(content=_make_zip(tmp_path / "z", {"x/full_markdown.md": b"ok"}))]
    _client(s).convert(src, tmp_path / "o.md")
    assert (tmp_path / "o.md").read_bytes() == b"ok"


def test_missing_full_md_in_zip(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://zip/1"}]}}),
                       FakeResp(content=_make_zip(tmp_path / "z", {"img.png": b"i"}))]
    with pytest.raises(MineruError, match="没有 Markdown"):
        _client(s).convert(src, tmp_path / "o.md")


def test_cancel_check_before_start(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md", cancel_check=lambda: True)
    assert ei.value.code == "CANCELLED"
    assert s.posts == [] and s.puts == []


def test_cancel_check_aborts_polling(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "doing"}]}})] * 10
    calls = {"n": 0}

    def cancel_check():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md", cancel_check=cancel_check)
    assert ei.value.code == "CANCELLED"
    assert not (tmp_path / "o.md").exists()
    assert not list(tmp_path.glob("*.zip.tmp"))


def test_is_ocr_and_language_passed(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://zip/1"}]}}),
                       FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"x"}))]
    c = MineruClient("sk-test", base="https://api.test/v4", session=s,
                     is_ocr=True, language="japan")
    c.convert(src, tmp_path / "o.md")
    assert s.posts[0]["json"]["files"][0]["is_ocr"] is True
    assert s.posts[0]["json"]["language"] == "japan"


def test_missing_source_raises_friendly_error(tmp_path):
    src = tmp_path / "不存在.pdf"
    with pytest.raises(MineruError) as ei:
        _client(FakeSession()).convert(src, tmp_path / "o.md")
    assert "无法访问" in friendly_message(ei.value)


def test_upload_oserror_becomes_mineru_error(tmp_path, monkeypatch):
    """M3：本地 OSError 归类为 LOCAL_ERROR，不进入网络重试。"""
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    puts = {"n": 0}

    def _boom(*args, **kwargs):
        puts["n"] += 1
        raise OSError("文件被占用")

    monkeypatch.setattr(s, "put", _boom)
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md")
    assert ei.value.code == "LOCAL_ERROR"
    assert puts["n"] == 1  # 没有重试


def test_non_https_upload_url_rejected(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["http://insecure/1"]}})]
    with pytest.raises(MineruError, match="https"):
        _client(s).convert(src, tmp_path / "o.md")
    assert s.puts == []


def test_non_https_zip_url_rejected(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "http://z/1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"x"})),
    ]
    with pytest.raises(MineruError, match="https"):
        _client(s).convert(src, tmp_path / "o.md")


def test_any_failed_record_fails_fast(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [FakeResp(body={"data": {"extract_result": [
        {"state": "done", "full_zip_url": "https://z/1"},
        {"state": "failed", "err_msg": "boom"},
    ]}})]
    with pytest.raises(MineruError, match="boom"):
        _client(s).convert(src, tmp_path / "o.md")


def test_write_failure_becomes_mineru_error(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://z/1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"x"})),
    ]
    # out_md 指向一个目录 → 写入必然失败
    out_dir = tmp_path / "已存在目录"
    out_dir.mkdir()
    with pytest.raises(MineruError, match="写入"):
        _client(s).convert(src, out_dir)


def test_convert_batch_happy_path(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"aa")
    b = tmp_path / "b.docx"; b.write_bytes(b"bb")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b1", "file_urls": ["https://up/1", "https://up/2"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [
            {"state": "done", "full_zip_url": "https://z/1"},
            {"state": "done", "full_zip_url": "https://z/2"},
        ]}}),
        FakeResp(content=_make_zip(tmp_path / "z1", {"full.md": b"AAA"})),
        FakeResp(content=_make_zip(tmp_path / "z2", {"full.md": b"BBB"})),
    ]
    _client(s).convert_batch([(a, tmp_path / "a.md"), (b, tmp_path / "b.md")])

    assert (tmp_path / "a.md").read_bytes() == b"AAA"
    assert (tmp_path / "b.md").read_bytes() == b"BBB"
    assert [u for u, _ in s.puts] == ["https://up/1", "https://up/2"]
    assert len(s.gets) == 3  # 1 次轮询 + 2 次下载
    assert s.posts[0]["json"]["model_version"] == "vlm"
    assert [f["name"] for f in s.posts[0]["json"]["files"]] == ["a.pdf", "b.docx"]


def test_convert_batch_failed_record_is_per_file(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"x")
    b = tmp_path / "b.pdf"; b.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b1", "file_urls": ["https://up/1", "https://up/2"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [
            {"state": "done", "full_zip_url": "https://z/1", "data_id": "f1"},
            {"state": "failed", "err_msg": "nope", "data_id": "f2"},
        ]}}),
        FakeResp(content=_make_zip(tmp_path / "z1", {"full.md": b"AAA"})),
    ]
    # 单文件失败不应影响同批其他文件
    results = _client(s).convert_batch([(a, tmp_path / "a.md"), (b, tmp_path / "b.md")])
    assert (tmp_path / "a.md").read_bytes() == b"AAA"
    assert results[0][2] is None
    assert "nope" in results[1][2]


def test_convert_batch_unique_data_ids(tmp_path):
    d1 = tmp_path / "d1"; d1.mkdir()
    d2 = tmp_path / "d2"; d2.mkdir()
    a = d1 / "同名.pdf"; a.write_bytes(b"a")
    b = d2 / "同名.pdf"; b.write_bytes(b"b")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b1", "file_urls": ["https://up/1", "https://up/2"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [
            {"state": "done", "full_zip_url": "https://z/1", "data_id": "f1"},
            {"state": "done", "full_zip_url": "https://z/2", "data_id": "f2"},
        ]}}),
        FakeResp(content=_make_zip(tmp_path / "z1", {"full.md": b"AAA"})),
        FakeResp(content=_make_zip(tmp_path / "z2", {"full.md": b"BBB"})),
    ]
    results = _client(s).convert_batch([(a, tmp_path / "o1.md"), (b, tmp_path / "o2.md")])
    ids = [f["data_id"] for f in s.posts[0]["json"]["files"]]
    assert len(set(ids)) == 2
    assert (tmp_path / "o1.md").read_bytes() == b"AAA"
    assert (tmp_path / "o2.md").read_bytes() == b"BBB"
    assert [e for _, _, e in results] == [None, None]


def test_convert_batch_matches_records_by_data_id(tmp_path, monkeypatch):
    """返回顺序被打乱时，仍要按 data_id 配对到正确文件（按 URL 返回对应内容）。"""
    a = tmp_path / "a.pdf"; a.write_bytes(b"a")
    b = tmp_path / "b.pdf"; b.write_bytes(b"b")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b1", "file_urls": ["https://up/1", "https://up/2"]}})]

    zips = {
        "https://z/1": _make_zip(tmp_path / "z1", {"full.md": b"AAA"}),
        "https://z/2": _make_zip(tmp_path / "z2", {"full.md": b"BBB"}),
    }

    def fake_get(url, **kwargs):
        if url.endswith("/b1"):  # 轮询：故意把 b 的记录放在前面
            return FakeResp(body={"data": {"extract_result": [
                {"state": "done", "full_zip_url": "https://z/2", "data_id": "f2"},
                {"state": "done", "full_zip_url": "https://z/1", "data_id": "f1"},
                ]}})
        return FakeResp(content=zips[url])

    monkeypatch.setattr(s, "get", fake_get)
    _client(s).convert_batch([(a, tmp_path / "a.md"), (b, tmp_path / "b.md")])
    assert (tmp_path / "a.md").read_bytes() == b"AAA"
    assert (tmp_path / "b.md").read_bytes() == b"BBB"


def test_data_id_is_short_and_ascii(tmp_path):
    """中文长文件名也不能让 data_id 触到 MinerU 的 128 字符上限。"""
    long_name = tmp_path / (("超长文件名" * 20) + ".pdf")
    long_name.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b1", "file_urls": ["https://up/1"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [
            {"state": "done", "full_zip_url": "https://z/1", "data_id": "f1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z1", {"full.md": b"AAA"})),
    ]
    _client(s).convert_batch([(long_name, tmp_path / "o.md")])
    ids = [f["data_id"] for f in s.posts[0]["json"]["files"]]
    assert ids == ["f1"]
    assert all(len(i) <= 8 and i.isascii() for i in ids)


def test_convert_batch_size_limit(tmp_path):
    jobs = [(tmp_path / f"{i}.pdf", tmp_path / f"{i}.md") for i in range(51)]
    with pytest.raises(ValueError):
        _client(FakeSession()).convert_batch(jobs)


def test_convert_batch_cancel_before_upload(tmp_path):
    a = tmp_path / "a.pdf"; a.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b1", "file_urls": ["https://up/1"]}})]
    with pytest.raises(MineruError) as ei:
        _client(s).convert_batch([(a, tmp_path / "a.md")], cancel_check=lambda: True)
    assert ei.value.code == "CANCELLED"
    assert s.puts == []


def test_create_batch_retries_on_network_error(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://z/1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"ok"})),
    ]
    calls = {"n": 0}

    def flaky_post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.ConnectionError("网络抖了一下")
        s.posts.append({"url": url, "json": json, "headers": headers})
        return FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})

    monkeypatch.setattr(s, "post", flaky_post)
    _client(s).convert(src, tmp_path / "o.md")
    assert calls["n"] == 2
    assert (tmp_path / "o.md").read_bytes() == b"ok"


def test_create_batch_retry_gives_up(tmp_path, monkeypatch):
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    calls = {"n": 0}

    def always_fail(*args, **kwargs):
        calls["n"] += 1
        raise requests.ConnectionError("断网了")

    monkeypatch.setattr(s, "post", always_fail)
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md")
    assert ei.value.code == "NETWORK"
    assert calls["n"] == client_mod._RETRY_TIMES + 1


def test_download_write_failure_becomes_mineru_error(tmp_path):
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    (tmp_path / "o.zip.tmp").mkdir()  # 占位目录，让临时文件写入失败
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {
        "batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [
            {"state": "done", "full_zip_url": "https://z/1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"AAA"})),
    ]
    with pytest.raises(MineruError, match="写入临时文件失败"):
        _client(s).convert(src, tmp_path / "o.md")


def test_rate_limit_backoff_with_retry_after(tmp_path, monkeypatch):
    """C2/TC8：429 按 Retry-After 退避重试后成功。"""
    sleeps: list[float] = []
    monkeypatch.setattr(client_mod, "_SLEEP", lambda s: sleeps.append(s))
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    calls = {"n": 0}

    def post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(status=429, headers={"Retry-After": "2"})
        s.posts.append({"url": url, "json": json, "headers": headers})
        return FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})

    monkeypatch.setattr(s, "post", post)
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://z/1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"OK"})),
    ]
    _client(s).convert(src, tmp_path / "o.md")
    assert calls["n"] == 2
    assert sleeps and sleeps[0] >= 2  # 首次退避尊重 Retry-After


def test_batch_rate_limit_no_degrade(tmp_path, monkeypatch):
    """C2/TC9：批量遇 429 整批退避重试，不降级为逐个提交。"""
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    jobs = []
    for i in range(3):
        f = tmp_path / f"{i}.docx"; f.write_bytes(b"x")
        jobs.append((f, tmp_path / f"{i}.md"))
    s = FakeSession()
    calls = {"n": 0}

    def post(url, headers=None, json=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(status=429, headers={"Retry-After": "1"})
        return FakeResp(body={"code": 0, "data": {
            "batch_id": "b", "file_urls": [f"https://up/{i}" for i in range(3)]}})

    monkeypatch.setattr(s, "post", post)
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [
            {"state": "done", "full_zip_url": f"https://z/{i}", "data_id": f"f{i + 1}"}
            for i in range(3)]}}),
    ] + [FakeResp(content=_make_zip(tmp_path / f"z{i}", {"full.md": b"x"})) for i in range(3)]
    client = _client(s)
    results = convert_many(client, jobs)
    assert calls["n"] == 2                     # 1 次 429 + 1 次成功，而非 1+3
    assert [e for _, _, e in results] == [None, None, None]


def test_upload_5xx_retried(tmp_path, monkeypatch):
    """C2/TC10：上传 503 有退避重试。"""
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    s.get_responses = [
        FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://z/1"}]}}),
        FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"OK"})),
    ]
    puts = {"n": 0}

    def put(url, data=None, timeout=None):
        puts["n"] += 1
        if puts["n"] <= 2:
            return FakeResp(status=503)
        s.puts.append((url, b"".join(data)))
        return FakeResp()

    monkeypatch.setattr(s, "put", put)
    _client(s).convert(src, tmp_path / "o.md")
    assert puts["n"] == 3
    assert (tmp_path / "o.md").exists()


def test_poll_survives_transient_network_errors(tmp_path, monkeypatch):
    """H1/TC7：轮询期两次瞬断后恢复，任务照常完成。"""
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    gets = {"n": 0}

    def flaky_get(url, **kwargs):
        gets["n"] += 1
        if gets["n"] <= 2:
            raise requests.ConnectionError("瞬断")
        if url.endswith("/b"):
            s.gets.append(url)
            return FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://z/1"}]}})
        s.gets.append(url)
        return FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"OK"}))

    monkeypatch.setattr(s, "get", flaky_get)
    _client(s).convert(src, tmp_path / "o.md")
    assert (tmp_path / "o.md").read_bytes() == b"OK"


def test_presigned_url_redacted_in_errors(tmp_path, monkeypatch):
    """H2：预签名 URL 的 Signature 不得进入错误消息。"""
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]

    def bad_put(url, data=None, timeout=None):
        raise requests.ConnectionError(
            "PUT failed: https://up/1?Expires=1760000000&Signature=REALSIGabc123&Key-Pair-Id=APK"

        )

    monkeypatch.setattr(s, "put", bad_put)
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md")
    assert "REALSIG" not in str(ei.value)
    assert "<REDACTED>" in str(ei.value)


def test_local_permission_error_not_retried(tmp_path, monkeypatch):
    """M3：本地无权限错误不进入网络重试。"""
    monkeypatch.setattr(client_mod, "_SLEEP", lambda _s: None)
    src = tmp_path / "a.pdf"; src.write_bytes(b"x")
    s = FakeSession()
    s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
    puts = {"n": 0}

    def deny(url, data=None, timeout=None):
        puts["n"] += 1
        raise PermissionError("拒绝访问")

    monkeypatch.setattr(s, "put", deny)
    with pytest.raises(MineruError) as ei:
        _client(s).convert(src, tmp_path / "o.md")
    assert ei.value.code == "LOCAL_ERROR"
    assert puts["n"] == 1  # 没有重试


def test_extract_atomic_no_tmp_left(tmp_path):
    """M1：结果 md 原子落盘，不留 .tmp 残骸。"""
    zip_bytes = _make_zip(tmp_path / "z", {"full.md": b"# hi"})
    zp = tmp_path / "r.zip"
    zp.write_bytes(zip_bytes)
    out = tmp_path / "r.md"
    client_mod._extract_full_md(zp, out)
    assert out.read_bytes() == b"# hi"
    assert not list(tmp_path.glob("*.tmp"))


def test_html_file_uses_mineru_html_model(tmp_path):
    for name, expected in [("a.html", "MinerU-HTML"), ("b.htm", "MinerU-HTML"), ("c.pdf", "vlm")]:
        src = tmp_path / name
        src.write_bytes(b"x")
        s = FakeSession()
        s.post_responses = [FakeResp(body={"code": 0, "data": {"batch_id": "b", "file_urls": ["https://up/1"]}})]
        s.get_responses = [FakeResp(body={"data": {"extract_result": [{"state": "done", "full_zip_url": "https://zip/1"}]}}),
                           FakeResp(content=_make_zip(tmp_path / "z", {"full.md": b"x"}))]
        _client(s).convert(src, tmp_path / "o.md")
        assert s.posts[0]["json"]["model_version"] == expected
