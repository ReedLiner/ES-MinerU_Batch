"""错误类型与面向用户的大白话文案。"""

from __future__ import annotations

KEY_INVALID = "Key 失效了，请去 https://mineru.net/apiManage 重新生成，然后在设置里更换。"

_RESUME_HINT = "已保留进度，重试会跳过已完成的分段。"


class MineruError(RuntimeError):
    def __init__(self, message: str, code: str | None = None, friendly: str | None = None):
        super().__init__(message)
        self.code = code
        self.friendly = friendly


_FRIENDLY_BY_CODE = {
    "A0202": KEY_INVALID,
    "A0211": KEY_INVALID,
    "401": KEY_INVALID,
    "403": KEY_INVALID,
    "-60005": "这个文件超过 200MB，在线版处理不了，请拆分或压缩后再试。",
    "-60006": "页数超过单次上限，请重试（程序会自动分段处理）。",
    "-10002": "MinerU 拒绝了这次请求（通常是文件名过长或含特殊字符），请改短文件名后重试。",
    "-60018": "今天的转换额度用完了，明天再试或升级套餐。",
    "NETWORK": f"网络异常，请检查网络后重试。{_RESUME_HINT}",
    "TIMEOUT": f"转换超时了，请稍后重试。{_RESUME_HINT}",
    "CANCELLED": (
        "已取消该任务。已提交给 MinerU 的部分服务端可能仍会完成转换并消耗额度；"
        "已完成的分段文件已保留，重试可续跑。"
    ),
}


def friendly_message(exc: MineruError) -> str:
    if exc.friendly:
        return exc.friendly
    if exc.code and exc.code in _FRIENDLY_BY_CODE:
        return _FRIENDLY_BY_CODE[exc.code]
    return str(exc)
