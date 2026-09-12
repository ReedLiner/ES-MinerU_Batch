"""后台转换线程：严格单并发顺序执行队列；支持批量提交、取消/放弃。"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from app.core import app_log
from app.core.collect import ConvertTask
from app.engine.client import MineruClient
from app.engine.convert import can_batch, convert_file, convert_many
from app.engine.errors import MineruError, friendly_message, redact

NOT_SUBMITTED_MSG = "已取消（尚未提交给 MinerU，不消耗额度）"


class ConvertWorker(QThread):
    """items = [(行 ID, 任务), ...]；信号里的 id 对应 TaskRow.row_id。"""

    task_started = Signal(int)
    task_progress = Signal(int, str)
    task_finished = Signal(int, bool, str)
    task_cancelled = Signal(int, str)
    all_done = Signal(int, int, int)

    def __init__(
        self,
        items: list[tuple[int, ConvertTask]],
        key: str,
        parent=None,
        is_ocr: bool = False,
        language: str = "ch",
        batch_size: int = 1,
    ):
        super().__init__(parent)
        self._items = list(items)
        self._ids = {row_id for row_id, _ in self._items}
        self._key = key
        self._is_ocr = bool(is_ocr)
        self._language = language or "ch"
        self._batch_size = max(1, int(batch_size or 1))
        self._current_id: int | None = None
        self._abandon = False
        self._cancelled_ids: set[int] = set()

    def cancel(self, row_id: int) -> bool:
        """取消一个任务；正在转换的标记为放弃。返回 False 表示该行不归本 worker 管。"""
        if row_id not in self._ids:
            return False
        if row_id == self._current_id:
            self._abandon = True
        else:
            self._cancelled_ids.add(row_id)
        return True

    def cancel_all(self) -> None:
        """全部停止：放弃当前任务，并取消本批尚未开始的所有任务。"""
        self._abandon = True
        for row_id, _ in self._items:
            self._cancelled_ids.add(row_id)

    # ---------- 内部 ----------

    def _report(self, rows: list[tuple[int, ConvertTask]], msg: str) -> None:
        for row_id, _ in rows:
            self.task_progress.emit(row_id, msg)

    def _finish_rows(self, rows, ok: bool, msg: str) -> None:
        for row_id, task in rows:
            if ok:
                self.task_finished.emit(row_id, True, str(task.output_md))
            else:
                self.task_finished.emit(row_id, False, msg)

    def run(self) -> None:
        try:
            client = MineruClient(self._key, is_ocr=self._is_ocr, language=self._language)
        except Exception as exc:
            # 构造失败也要收尾，否则主窗口会一直以为队列还在跑
            app_log.get().error("无法创建 MinerU 客户端：%s", exc)
            for row_id, _ in self._items:
                self.task_finished.emit(row_id, False, f"无法开始转换：{exc}")
            self.all_done.emit(0, len(self._items), 0)
            return

        ok = fail = cancelled = 0
        group: list[tuple[int, ConvertTask]] = []

        def flush_group() -> None:
            nonlocal ok, fail, cancelled
            if not group:
                return
            rows_all = list(group)
            group.clear()
            # 攒批期间被「全部停止」的任务不再提交（避免白扣额度）
            rows = [(rid, t) for rid, t in rows_all if rid not in self._cancelled_ids]
            for rid, _t in rows_all:
                if rid in self._cancelled_ids:
                    cancelled += 1
                    self.task_cancelled.emit(rid, NOT_SUBMITTED_MSG)
            if not rows:
                return
            self._abandon = False  # H4：清掉上一个任务的放弃标记，避免连锁误取消
            for row_id, _ in rows:
                self.task_started.emit(row_id)
            app_log.get().info("批量提交 %d 个文件", len(rows))
            try:
                results = convert_many(
                    client,
                    [(t.source, t.output_md) for _, t in rows],
                    progress=lambda m: self._report(rows, m),
                    cancel_check=lambda: self._abandon,
                )
            except MineruError as exc:
                if exc.code == "CANCELLED":
                    cancelled += len(rows)
                    for row_id, _ in rows:
                        self.task_cancelled.emit(row_id, friendly_message(exc))
                else:
                    fail += len(rows)
                    app_log.get().error("批量转换失败：%s", redact(str(exc)))
                    self._finish_rows(rows, False, friendly_message(exc))
            except Exception as exc:  # 兜底
                fail += len(rows)
                app_log.get().exception("批量转换未预期错误：%s", exc)
                self._finish_rows(rows, False, f"未预期错误：{exc}")
            else:
                # 结果按文件粒度回写：失败只影响对应的行
                for (row_id, task), (_src, _out, err) in zip(rows, results):
                    if err:
                        fail += 1
                        app_log.get().error("批量中该件失败 %s：%s", task.source.name, redact(err))
                        self.task_finished.emit(row_id, False, err)
                    else:
                        ok += 1
                        self.task_finished.emit(row_id, True, str(task.output_md))
                # 兜底：结果条数不足时也要收尾，避免有行一直停在"转换中"
                if len(results) < len(rows):
                    for row_id, _ in rows[len(results):]:
                        fail += 1
                        self.task_finished.emit(row_id, False, "未返回结果")

        for row_id, task in self._items:
            if row_id in self._cancelled_ids:
                cancelled += 1
                self.task_cancelled.emit(row_id, NOT_SUBMITTED_MSG)
                continue

            if self._batch_size > 1 and can_batch(task.source):
                group.append((row_id, task))
                if len(group) >= self._batch_size:
                    flush_group()
                continue

            flush_group()  # 先提交已攒的可批量任务，再单独处理这一个
            if row_id in self._cancelled_ids:
                cancelled += 1
                self.task_cancelled.emit(row_id, NOT_SUBMITTED_MSG)
                continue
            self._current_id = row_id
            self._abandon = False
            self.task_started.emit(row_id)
            app_log.get().info("开始转换：%s -> %s", task.source, task.output_md)
            try:
                convert_file(
                    task.source,
                    task.output_md,
                    client,
                    progress=lambda msg, i=row_id: self.task_progress.emit(i, msg),
                    cancel_check=lambda: self._abandon,
                )
            except MineruError as exc:
                if exc.code == "CANCELLED":
                    cancelled += 1
                    self.task_cancelled.emit(row_id, friendly_message(exc))
                else:
                    fail += 1
                    app_log.get().error("转换失败 %s：%s", task.source.name, redact(str(exc)))
                    self.task_finished.emit(row_id, False, friendly_message(exc))
            except Exception as exc:  # 兜底，避免线程静默崩溃
                fail += 1
                app_log.get().exception("未预期错误 %s：%s", task.source.name, exc)
                self.task_finished.emit(row_id, False, f"未预期错误：{exc}")
            else:
                ok += 1
                app_log.get().info("转换完成：%s", task.output_md)
                self.task_finished.emit(row_id, True, str(task.output_md))

        flush_group()
        self._current_id = None
        app_log.get().info("队列结束：成功 %d / 失败 %d / 取消 %d", ok, fail, cancelled)
        self.all_done.emit(ok, fail, cancelled)
