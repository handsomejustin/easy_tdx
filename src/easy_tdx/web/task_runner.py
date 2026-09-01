"""回测后台任务执行器。

在进程内 ThreadPoolExecutor 上运行回测任务，通过 task_id 轮询结果。
不引入外部依赖（Celery/Redis），适合单机部署。

设计取舍：
- 回测本身是 CPU-bound（numpy/pandas 持 GIL），线程池主要价值是**不阻塞
  FastAPI 的 asyncio event loop**——回测在独立线程跑，HTTP handler 立即返回。
- 任务结果双写：内存 OrderedDict（LRU 上限 100，热路径零磁盘 IO）+
  SQLite（``~/.easy_tdx/tasks.db``，v1.24 起持久化，serve 重启不丢历史）。
  查询走「内存优先、磁盘兜底」；列表合并两源。磁盘侧由
  :mod:`easy_tdx.web.task_store` 管理淘汰（保留 500 条）与中断任务恢复。
  ``EASY_TDX_NO_TASK_DB=1`` 可整体关闭持久化（测试用）。

并发正确性要点（task_runner.py 审计修复）：
- ``submit`` 把「注册 task state」与「提交 executor」放在**同一把锁**内，
  避免任务在拿到 future 前就被淘汰（Finding: submit-future 竞态窗口）。
- ``_run`` 写状态时**不假设** ``self._tasks[task_id]`` 仍在表中——并发淘汰
  可能在任务运行期间移除其条目。``move_to_end`` 用 try/except 容忍，状态
  写到本地 ``state`` 引用（即使被淘汰也无害，GC 回收）。
- ``_evict_if_needed_locked`` 跳过 ``running`` 状态的任务——正在执行的任务
  恰好是 OrderedDict 头部（完成时才 move_to_end），盲目 FIFO 淘汰会优先
  杀掉在途任务。淘汰改用「最旧的 non-running 条目」。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Literal

from easy_tdx.web.task_store import get_task_store

logger = logging.getLogger(__name__)

TaskStatus = Literal["pending", "running", "done", "failed"]

# 结果表上限：超过后丢弃最旧的已完成/失败任务（LRU）。running 任务不会被淘汰。
# 每个全市场组合回测结果约几百 KB，100 条上限内存占用 < 100 MB。
_MAX_RESULTS = 100


@dataclass
class TaskState:
    """单个回测任务的状态快照。"""

    task_id: str
    status: TaskStatus = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    # 供前端展示的描述（策略名 + 标的等），不参与业务逻辑
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 兼容字典（供轮询接口返回）。"""
        return {
            "task_id": self.task_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "description": self.description,
            "elapsed": (self.finished_at or time.time()) - (self.started_at or self.created_at),
        }


class BacktestTaskRunner:
    """回测任务执行器（全局单例）。

    Thread-safety: 所有对 ``self._tasks`` 的读写都在 ``self._lock`` 内。
    worker 线程的 ``_run`` 写状态时持锁，但写的是本地 ``state`` 引用——
    即使条目已被并发淘汰，写入也无副作用（写入的对象不再被 ``_tasks`` 引用，
    GC 回收）。``move_to_end`` 容忍 KeyError。
    """

    def __init__(self, max_workers: int = 4, max_results: int = _MAX_RESULTS) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="backtest-worker",
        )
        self._tasks: OrderedDict[str, TaskState] = OrderedDict()
        self._lock = Lock()
        self._max_results = max_results
        self._shutdown = False

    def submit(
        self,
        func: Callable[[], dict[str, Any]],
        *,
        description: str = "",
    ) -> str:
        """提交一个回测任务，立即返回 task_id。

        注册 task state 与提交 executor 在同一把锁内，避免任务在拿到 future
        前就被并发淘汰。

        Args:
            func: 无参可调用，返回 ``dict[str, Any]`` 形式的回测结果。
                内部异常会被捕获并记入 ``TaskState.error``。
            description: 任务描述（前端展示用）。

        Returns:
            task_id（uuid4 十六进制）。
        """
        task_id = uuid.uuid4().hex
        with self._lock:
            if self._shutdown:
                raise RuntimeError("任务执行器已关闭，拒绝提交")
            state = TaskState(task_id=task_id, description=description)
            self._tasks[task_id] = state
            # 持久化 pending 态必须先于 executor.submit——否则工作线程可能
            # 先写 running/done，随后被这里的旧 pending 快照覆盖（状态回退）。
            self._persist_locked(state)
            # 提交 executor 也在锁内——避免「注册后被淘汰再提交」的窗口。
            # executor.submit 本身很快（入队即返回），不会显著持锁。
            self._executor.submit(self._run, task_id, func)
            self._evict_if_needed_locked()
        return task_id

    def get(self, task_id: str) -> TaskState:
        """取任务状态，不存在抛 KeyError。"""
        with self._lock:
            if task_id in self._tasks:
                return self._tasks[task_id]
        # 锁外做磁盘恢复（_restore_from_store 内部自行加锁）
        restored = self._restore_from_store(task_id)
        if restored is None:
            raise KeyError(f"未知任务 '{task_id}'")
        return restored

    def peek(self, task_id: str) -> TaskState | None:
        """取任务状态，不存在返回 None（不抛异常，便于轮询）。"""
        with self._lock:
            state = self._tasks.get(task_id)
            if state is not None:
                return state
        return self._restore_from_store(task_id)

    def list_recent(self, limit: int = 20) -> list[TaskState]:
        """返回最近 N 个任务（内存 + 磁盘合并，按完成/创建时间倒序）。

        Args:
            limit: 最多返回的任务数（默认 20）。
        """
        with self._lock:
            memory_items = list(self._tasks.values())
        seen = {s.task_id for s in memory_items}
        # 磁盘侧多取一些（覆盖内存 LRU 已淘汰的），再合并排序
        try:
            disk_items = [
                self._dict_to_state(d)
                for d in get_task_store().list_recent(limit=limit + len(seen))
                if d["task_id"] not in seen
            ]
        except Exception:  # noqa: BLE001 — 持久化故障不阻断列表查询
            logger.exception("任务持久化：list_recent 读盘失败，仅返回内存任务")
            disk_items = []
        merged = memory_items + disk_items
        merged.sort(key=lambda s: s.finished_at or s.created_at, reverse=True)
        return merged[:limit]

    def status(self, task_id: str) -> TaskStatus | None:
        """取任务状态字符串，不存在返回 None。"""
        state = self.peek(task_id)
        return state.status if state else None

    def shutdown(self, wait: bool = True) -> None:
        """关闭执行器（应用退出时调用）。

        取消排队中的 pending 任务，等待 running 任务完成（wait=True）。
        之后再 submit 会抛 RuntimeError。
        """
        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
        self._executor.shutdown(wait=wait, cancel_futures=True)

    # ── 内部实现 ───────────────────────────────────────────────────────────────

    def _run(self, task_id: str, func: Callable[[], dict[str, Any]]) -> None:
        """在工作线程内执行：更新状态、跑任务、捕获异常。

        状态写入用本地 ``state`` 引用，不假设条目仍在 ``self._tasks`` 中——
        并发淘汰可能在任务运行期间移除条目。``move_to_end`` 容忍 KeyError。
        每次状态跃迁（running/done/failed）同步落盘 SQLite。
        """
        # 取本地引用；若已被淘汰则静默退出（无副作用）
        with self._lock:
            state = self._tasks.get(task_id)
            if state is None:
                logger.warning("任务 %s 在执行前已被淘汰，跳过", task_id)
                return
            state.status = "running"
            state.started_at = time.time()
        self._persist(state)

        try:
            result = func()
            with self._lock:
                # 即使被淘汰也写到本地 state（无害），move_to_end 容忍缺失
                state.result = result
                state.status = "done"
                state.finished_at = time.time()
                try:
                    self._tasks.move_to_end(task_id)
                except KeyError:
                    pass  # 已被淘汰，无需移动
        except Exception as exc:  # noqa: BLE001 — 故意宽口径，任务级兜底
            logger.exception("回测任务 %s 失败", task_id)
            with self._lock:
                state.error = f"{type(exc).__name__}: {exc}"
                state.status = "failed"
                state.finished_at = time.time()
                try:
                    self._tasks.move_to_end(task_id)
                except KeyError:
                    pass
        self._persist(state)

    # ── SQLite 持久化辅助 ─────────────────────────────────────────────────────

    def _persist_locked(self, state: TaskState) -> None:
        """把状态快照落盘（调用方需持 ``self._lock``，避免与跃迁竞争）。"""
        try:
            get_task_store().save(
                task_id=state.task_id,
                status=state.status,
                description=state.description,
                created_at=state.created_at,
                started_at=state.started_at,
                finished_at=state.finished_at,
                error=state.error,
                result=state.result,
            )
        except Exception:  # noqa: BLE001 — 持久化故障不阻断回测主流程
            logger.exception("任务 %s 持久化失败（不影响任务本身）", state.task_id)

    def _persist(self, state: TaskState) -> None:
        """把状态快照落盘（工作线程跃迁后调用，state 已稳定）。"""
        with self._lock:
            self._persist_locked(state)

    def _restore_from_store(self, task_id: str) -> TaskState | None:
        """从磁盘恢复任务到内存（内存淘汰/进程重启后的查询兜底）。"""
        try:
            d = get_task_store().load(task_id)
        except Exception:  # noqa: BLE001
            logger.exception("任务 %s 读盘失败", task_id)
            return None
        if d is None:
            return None
        state = self._dict_to_state(d)
        with self._lock:
            # 竞态兜底：等待期间可能已被并发查询/提交加载进内存
            existing = self._tasks.get(task_id)
            if existing is not None:
                return existing
            self._tasks[task_id] = state
            self._evict_if_needed_locked()
        return state

    @staticmethod
    def _dict_to_state(d: dict[str, Any]) -> TaskState:
        """task_store 行字典 → TaskState。"""
        return TaskState(
            task_id=d["task_id"],
            status=d["status"],
            result=d.get("result"),
            error=d.get("error"),
            created_at=float(d.get("created_at") or 0.0),
            started_at=(float(d["started_at"]) if d.get("started_at") is not None else None),
            finished_at=(float(d["finished_at"]) if d.get("finished_at") is not None else None),
            description=d.get("description", ""),
        )

    def _evict_if_needed_locked(self) -> None:
        """超过上限时丢弃最旧的 non-running 任务（调用方需持锁）。

        running 任务不会被淘汰（它们恰在 OrderedDict 头部，但盲淘汰会杀在途任务）。
        只淘汰 pending/done/failed 中最旧者。
        """
        while len(self._tasks) > self._max_results:
            # 找第一个 non-running 条目淘汰；若无则停止（全在 running，不强制淘汰）
            evict_id: str | None = None
            for tid, st in self._tasks.items():
                if st.status != "running":
                    evict_id = tid
                    break
            if evict_id is None:
                break  # 全部 running，暂时无法淘汰
            self._tasks.pop(evict_id, None)


# ── 全局单例 ───────────────────────────────────────────────────────────────────

_RUNNER: BacktestTaskRunner | None = None
_RUNNER_LOCK = Lock()


def get_runner() -> BacktestTaskRunner:
    """获取全局回测任务执行器单例（惰性初始化，线程安全）。"""
    global _RUNNER  # noqa: PLW0603 — 模块级单例
    if _RUNNER is None:
        with _RUNNER_LOCK:
            # double-checked locking：拿到锁后再确认一次，避免重复创建
            if _RUNNER is None:
                _RUNNER = BacktestTaskRunner()
    return _RUNNER


def shutdown_runner() -> None:
    """关闭全局执行器（应用退出时调用，幂等）。"""
    global _RUNNER  # noqa: PLW0603
    with _RUNNER_LOCK:
        if _RUNNER is not None:
            _RUNNER.shutdown()
            _RUNNER = None
