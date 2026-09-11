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


def test_validation_error_friendly():
    msg = friendly_message(MineruError("x", code="-10002"))
    assert "文件名" in msg


def test_cancelled_friendly():
    msg = friendly_message(MineruError("x", code="CANCELLED"))
    assert "取消" in msg
    assert "额度" in msg
