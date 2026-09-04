"""指标计算缓存（两段式寻优加速，v1.25 新增）。

借鉴 backtest-system ``register_two_stage`` 的思路：把**指标计算**（只依赖
数据 + 指标参数）与**信号组合 + 订单模拟**解耦。网格寻优中同一份 K 线被
所有网格点共用，而指标只依赖 ``(指标函数, 数据数组, 指标参数)``——
例如 ``{"fast": [5,10,20], "slow": [10,20,30]}`` 的 9 个点里，
``MA(close, 5)`` 会被计算 3 次（与每个 slow 组合各一次），实际只需 1 次。

:key 设计：``(函数限定名, 参数原子序列)``。数组参数用 ``(dtype, shape,
内容哈希)`` 做签名——引擎每次 run 会重建数组对象（对象 id 不稳定），
必须按内容寻址才能跨网格点命中；标量参数直接 repr。哈希用
blake2b（16 字节摘要），对回测级数组（KB 量级）开销可忽略。跨进程不
共享（进程池并行模式下各 worker 各自建缓存）。

收益上限取决于指标层在回测耗时中的占比；引擎的逐 bar Python 循环无法
通用缓存，故大网格另配 ``ParamGridOptimizer(workers=N)`` 进程级并行，
两者叠加使用。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import numpy as np

__all__ = ["IndicatorCache"]


class IndicatorCache:
    """跨回测运行的指标计算缓存（线程内使用，非线程安全）。"""

    def __init__(self) -> None:
        self._store: dict[tuple[Any, ...], Any] = {}
        self.hits = 0
        self.misses = 0

    @property
    def total(self) -> int:
        """总请求次数。"""
        return self.hits + self.misses

    def get_or_compute(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> Any:
        """命中则返回缓存，未命中则计算并缓存。"""
        key = self._make_key(func, args, kwargs)
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        result = func(*args, **kwargs)
        self._store[key] = result
        return result

    def stats(self) -> dict[str, int | float]:
        """缓存统计（命中率诊断用）。"""
        total = self.total
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total": total,
            "hit_rate": round(self.hits / total, 4) if total else 0.0,
        }

    # ── 内部 ─────────────────────────────────────────────────────────────────

    def _make_key(
        self,
        func: Callable[..., Any],
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> tuple[Any, ...]:
        parts: list[Any] = [
            getattr(func, "__module__", ""),
            getattr(func, "__qualname__", str(func)),
        ]
        parts.extend(self._atom(a) for a in args)
        for k in sorted(kwargs):
            parts.append(k)
            parts.append(self._atom(kwargs[k]))
        return tuple(parts)

    def _atom(self, a: Any) -> Any:
        """把单个参数转为可哈希原子。"""
        if isinstance(a, np.ndarray):
            # 内容寻址：同值不同对象必须视为同一数据（引擎每次 run 重建数组，
            # 对象 id 不稳定）。NaN 按字节参与哈希，位模式不同只多算一次，
            # 不会误命中。
            digest = hashlib.blake2b(a.tobytes(), digest_size=16).hexdigest()
            return ("arr", str(a.dtype), a.shape, digest)
        if isinstance(a, int | float | str | bool | None):
            return ("s", type(a).__name__, repr(a))
        return ("o", type(a).__name__, repr(a))
