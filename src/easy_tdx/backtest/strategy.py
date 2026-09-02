"""策略基类和数据代理。

提供策略编写的声明式 API：
- StrategyDataProxy: K线数据访问层，支持 OHLCV + 自定义指标列
- Strategy: 策略基类，init() 注册指标，next() 生成信号
- crossover: 金叉检测辅助函数
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt
import pandas as pd

from easy_tdx.backtest.types import Signal

if TYPE_CHECKING:
    from collections.abc import Callable

    NDArray = npt.NDArray[np.float64]
else:
    NDArray = np.ndarray

# ── 数据序列访问器 ─────────────────────────────────────────────────────────────


class _SeriesAccessor:
    """数据序列访问器，支持相对索引和 numpy 数组转换。

    Examples:
        >>> close = data.close
        >>> close[0]      # 当前 bar 的收盘价
        >>> close[-1]     # 前一根 bar 的收盘价
        >>> ma = MyTT.MA(close.raw, 20)  # 传入 numpy 数组
    """

    __slots__ = ("_series", "_bar_index")

    def __init__(self, series: NDArray, bar_index: int) -> None:
        self._series = series
        self._bar_index = bar_index

    def __getitem__(self, key: int) -> float:
        """获取相对索引的值。

        Args:
            key: 0=当前值, -1=前一根, -2=前两根,依此类推

        Returns:
            对应位置的 float 值；越界（回测早期数据不足）返回 ``nan``，
            而非抛 IndexError —— 策略里写 ``close[-1]`` 在首根 bar 不会崩溃，
            与 warmup 机制配合避免指标预热期误信号。
        """
        idx = self._bar_index + key
        if idx < 0:
            return float("nan")
        return float(self._series[idx])

    def __len__(self) -> int:
        """返回数组长度。"""
        return len(self._series)

    def __array__(self) -> NDArray:
        """允许传入 MyTT 函数（自动解包为 numpy 数组）。"""
        return self._series

    @property
    def raw(self) -> NDArray:
        """获取完整原始 numpy 数组。"""
        return self._series


# ── K线数据代理 ────────────────────────────────────────────────────────────────


class StrategyDataProxy:
    """K线数据代理，将 DataFrame 转为高效的 numpy 数组访问。

    内部将所有列（除 datetime）转为 numpy 数组，通过 _SeriesAccessor
    提供相对索引访问（[0] 当前, [-1] 前一根）。

    支持标准 OHLCV 列和任意自定义列（如 MACD_DIF, BOLL_UPPER）。
    """

    __slots__ = ("_arrays", "_bar_index")

    def __init__(self, df: pd.DataFrame) -> None:
        """初始化数据代理。

        Args:
            df: K线 DataFrame，必须包含 datetime, open, close, high, low, vol, amount
                可包含额外列（如 MACD_DIF, BOLL_UPPER）
        """
        self._arrays: dict[str, NDArray] = {}
        self._bar_index = 0

        # 将所有列（除 datetime）转为 numpy 数组
        for col in df.columns:
            if col == "datetime":
                continue
            arr = df[col].to_numpy()
            if len(arr) > 0 and isinstance(arr[0], np.datetime64 | pd.Timestamp):
                # datetime 列转为 int (YYYYMMDD)
                self._arrays[col] = _datetime_to_int(arr)
            else:
                # copy=False：已是 float64 时零拷贝复用同一数组对象——
                # 网格寻优复用同一 df 时，IndicatorCache 按 (id, shape) 签名
                # 才能跨网格点命中（见 indicator_cache.py）
                self._arrays[col] = arr.astype(np.float64, copy=False)

    def _set_index(self, idx: int) -> None:
        """设置当前 bar 索引（引擎调用）。"""
        self._bar_index = idx

    @property
    def open(self) -> _SeriesAccessor:
        """开盘价序列。"""
        return _SeriesAccessor(self._arrays["open"], self._bar_index)

    @property
    def close(self) -> _SeriesAccessor:
        """收盘价序列。"""
        return _SeriesAccessor(self._arrays["close"], self._bar_index)

    @property
    def high(self) -> _SeriesAccessor:
        """最高价序列。"""
        return _SeriesAccessor(self._arrays["high"], self._bar_index)

    @property
    def low(self) -> _SeriesAccessor:
        """最低价序列。"""
        return _SeriesAccessor(self._arrays["low"], self._bar_index)

    @property
    def vol(self) -> _SeriesAccessor:
        """成交量序列。"""
        return _SeriesAccessor(self._arrays["vol"], self._bar_index)

    @property
    def amount(self) -> _SeriesAccessor:
        """成交额序列。"""
        return _SeriesAccessor(self._arrays["amount"], self._bar_index)

    def __getattr__(self, name: str) -> _SeriesAccessor:
        """访问额外列（如 MACD_DIF, BOLL_UPPER）。

        Raises:
            AttributeError: 列不存在
        """
        if name not in self._arrays:
            raise AttributeError(f"列 '{name}' 不存在于数据中")
        return _SeriesAccessor(self._arrays[name], self._bar_index)


# ── 金叉检测 ─────────────────────────────────────────────────────────────────────


def crossover(
    a: NDArray | pd.Series | _SeriesAccessor,
    b: NDArray | pd.Series | _SeriesAccessor,
) -> NDArray:
    """检测 a 从下方穿越 b（金叉）。

    Args:
        a: 快线序列
        b: 慢线序列

    Returns:
        bool 数组，True 表示发生金叉

    Examples:
        >>> ma5 = MyTT.MA(data.close.raw, 5)
        >>> ma20 = MyTT.MA(data.close.raw, 20)
        >>> cross = crossover(ma5, ma20)  # ma5 上穿 ma20
        >>> if cross[bar_index]:
        ...     strategy.buy(size=100)
    """
    # 解包 _SeriesAccessor
    if isinstance(a, _SeriesAccessor):
        a = a.raw
    if isinstance(b, _SeriesAccessor):
        b = b.raw

    # pd.Series 转 numpy
    if isinstance(a, pd.Series):
        a = a.to_numpy().astype(np.float64)
    if isinstance(b, pd.Series):
        b = b.to_numpy().astype(np.float64)

    # 金叉：前一根 a <= b，当前 a > b
    mask = np.zeros(len(a), dtype=bool)
    mask[1:] = (a[:-1] <= b[:-1]) & (a[1:] > b[1:])
    return mask


# ── 策略基类 ───────────────────────────────────────────────────────────────────


class Strategy(ABC):
    """策略基类，提供声明式回测 API。

    用户子类实现：
        - init(): 注册指标（通过 self.I()）
        - next(): 生成交易信号（通过 self.buy()/self.sell()）

    内部状态：
        - self.data: StrategyDataProxy，访问 K线数据
        - self.position: {"size": float}，当前持仓
        - self.chanlun: 缠论分析结果（预留）

    示例:
        >>> class MyStrategy(Strategy):
        ...     def init(self):
        ...         self.ma5 = self.I(MyTT.MA, self.data.close, 5)
        ...         self.ma20 = self.I(MyTT.MA, self.data.close, 20)
        ...         self.cross = crossover(self.ma5, self.ma20)
        ...
        ...     def next(self):
        ...         if self.cross[self._bar_index]:
        ...             self.buy(size=100)
        ...         elif self.position["size"] > 0:
        ...             self.sell(size=0)
    """

    def __init__(self) -> None:
        """初始化策略内部状态。"""
        self._data_proxy: StrategyDataProxy | None = None
        self._bar_index = 0
        self._signals: list[Signal] = []
        self._indicators: dict[str, NDArray] = {}
        self._chanlun_result: dict[str, Any] | None = None
        self._position_size = 0.0
        self._cash = 0.0
        self._datetime_array: NDArray | None = None
        # 两段式寻优加速：引擎挂载的指标缓存（None = 直接计算）
        self._indicator_cache: Any = None

    # ── 用户实现方法 ─────────────────────────────────────────────────────────────

    @abstractmethod
    def init(self) -> None:
        """注册指标。

        在回测开始前调用一次，用户通过 self.I() 注册技术指标。
        """

    @abstractmethod
    def next(self) -> None:
        """生成交易信号。

        每根 bar 调用一次，用户通过 self.buy()/self.sell() 生成信号。
        """

    # ── 向量化快速路径钩子（v1.28） ────────────────────────────────────────────

    def entry_exit_masks(self) -> tuple[NDArray, NDArray] | None:
        """返回 (entry_mask, exit_mask) 布尔数组以启用向量化信号生成。

        默认返回 None（不支持向量化，引擎走逐 bar 路径）。策略满足以下
        约束时可覆写本方法，让 :class:`~easy_tdx.backtest.engine.BacktestEngine`
        用 numpy 一次性产出信号数组（网格寻优提速的关键路径）：

        - ``init()`` 只注册指标（副作用仅写入 ``self`` 属性）；
        - ``next()`` 只读 ``self.data`` / 指标数组的**当根值**（或整段掩码），
          仅调用无参 ``buy()`` / ``sell()``（size=0 全仓、无限价、无止损止盈）；
        - 持仓判断只依赖「空仓 / 持仓」两态（``self.position["size"]`` 的
          零与非零），无动态仓位。

        语义约定（掩码与 ``next()`` 必须等价，由对拍单测守护）：

        - ``entry_mask[i]`` 在**空仓**时触发买入；``exit_mask[i]`` 在**持仓**
          时触发卖出——等价于 ``if entry and 空仓: buy() elif exit and 持仓:
          sell()``。金叉/死叉这类交替掩码天然满足；
        - 同一根 bar 两个掩码**不应同时为 True**；
        - 掩码只依赖当根及更早数据（无未来函数），NaN 参与的比较按 False
          处理（与逐 bar 路径一致）。

        Returns:
            (entry_mask, exit_mask) 与 K 线等长的 bool 数组；None = 不支持。
        """
        return None

    # ── 指标注册 ───────────────────────────────────────────────────────────────

    def I(  # noqa: E743
        self, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> Any:
        """注册指标。

        将 _SeriesAccessor 参数自动解包为 numpy 数组，调用 func 计算指标。
        返回结果（通常是 ndarray，但 MACD/KDJ 等返回 tuple）存入
        ``self._indicators``，可在 ``next()`` 中访问。

        Args:
            func: 指标函数（如 MyTT.MA）
            *args: 参数（可能是 _SeriesAccessor，会自动解包）
            **kwargs: 关键字参数

        Returns:
            指标值数组（numpy ndarray）

        Examples:
            >>> ma5 = self.I(MyTT.MA, self.data.close, 5)
            >>> macd = self.I(MyTT.MACD, self.data.close, self.data.low, self.data.high)
        """
        # 解包 _SeriesAccessor 参数
        unpacked_args = []
        for arg in args:
            if isinstance(arg, _SeriesAccessor):
                unpacked_args.append(arg.raw)
            else:
                unpacked_args.append(arg)

        # 两段式加速：挂载了 IndicatorCache（网格寻优场景）时按
        # (函数, 参数) 复用跨网格点的指标计算结果
        if self._indicator_cache is not None:
            result = self._indicator_cache.get_or_compute(func, tuple(unpacked_args), kwargs)
        else:
            result = func(*unpacked_args, **kwargs)

        # 存储指标（用于调试/日志）
        func_name = getattr(func, "__name__", str(func))
        self._indicators[func_name] = result

        return result

    # ── 交易信号生成 ─────────────────────────────────────────────────────────────

    def buy(
        self,
        size: float = 0,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        trail_stop: float | None = None,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
    ) -> None:
        """生成买入信号（可携带 bracket 止损/止盈/移动止损，OCO 联动）。

        akquant ``place_bracket`` 风格：进出场一体化，不必再手写止损监控。
        三条退出线任一触发即全部失效（OCO），由引擎逐 bar 监控并自动
        生成 SELL（``source="stop"``，延迟到下一根开盘成交，消除前视偏差）。

        Args:
            size: 交易数量（0 = 全仓，由引擎计算）
            price: 限价（None = 市价单）
            stop_loss: 止损价（绝对价；与 stop_loss_pct 同时给时绝对价优先）
            take_profit: 止盈价（绝对价；与 take_profit_pct 同时给时绝对价优先）
            trail_stop: 移动止损百分比（如 0.08 = 自持仓期间最高收盘价
                回撤 8% 触发）。固定 stop_loss 优先于移动止损。
            stop_loss_pct: 止损百分比（相对当前收盘价，如 0.05 = 跌 5% 止损）
            take_profit_pct: 止盈百分比（相对当前收盘价，如 0.10 = 涨 10% 止盈）

        Examples:
            >>> # 买入并带 5% 止损 / 10% 止盈（自动换算价格）
            ... self.buy(stop_loss_pct=0.05, take_profit_pct=0.10)
            >>> # 买入并带 8% 移动止损（涨得越多止损线跟得越高）
            ... self.buy(trail_stop=0.08)
        """
        if self._data_proxy is None:
            raise RuntimeError("策略未绑定数据，请先调用 _bind_data()")
        if self._datetime_array is None:
            raise RuntimeError("数据未正确初始化")

        # 百分比便捷参数 → 绝对价（显式绝对价优先）
        ref_price = price if price is not None else float(self.data.close[0])
        if stop_loss is None and stop_loss_pct is not None:
            stop_loss = ref_price * (1.0 - stop_loss_pct)
        if take_profit is None and take_profit_pct is not None:
            take_profit = ref_price * (1.0 + take_profit_pct)

        signal = Signal(
            datetime=int(self._datetime_array[self._bar_index]),
            direction="BUY",
            size=size,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            trail_stop=trail_stop,
        )
        self._signals.append(signal)

    def sell(
        self,
        size: float = 0,
        price: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> None:
        """生成卖出信号。

        Args:
            size: 交易数量（0 = 全仓，由引擎计算）
            price: 限价（None = 市价单）
            stop_loss: 止损价（None = 不设置）
            take_profit: 止盈价（None = 不设置）
        """
        if self._data_proxy is None:
            raise RuntimeError("策略未绑定数据，请先调用 _bind_data()")
        if self._datetime_array is None:
            raise RuntimeError("数据未正确初始化")

        signal = Signal(
            datetime=int(self._datetime_array[self._bar_index]),
            direction="SELL",
            size=size,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        self._signals.append(signal)

    # ── 状态访问 ─────────────────────────────────────────────────────────────────

    @property
    def data(self) -> StrategyDataProxy:
        """K线数据代理。"""
        if self._data_proxy is None:
            raise RuntimeError("策略未绑定数据，请先调用 _bind_data()")
        return self._data_proxy

    @property
    def position(self) -> dict[str, float]:
        """当前持仓（简化 dict 格式）。

        Returns:
            {"size": float}，正=多头，负=空头，0=空仓
        """
        return {"size": self._position_size}

    @property
    def chanlun(self) -> Any:
        """缠论分析结果。

        通过 BacktestEngine(chanlun_level=...) 自动注入 ChanlunResult，
        或通过 engine.run(chanlun_result=...) 手动注入任意对象。
        """
        return self._chanlun_result

    # ── 内部方法（引擎调用） ─────────────────────────────────────────────────────

    def _bind_data(self, df: pd.DataFrame) -> None:
        """绑定 K线数据（引擎调用）。

        Args:
            df: K线 DataFrame
        """
        self._data_proxy = StrategyDataProxy(df)
        # 提取 datetime 数组
        if "datetime" in df.columns:
            dt_arr = df["datetime"].to_numpy()
            self._datetime_array = _datetime_to_int(dt_arr)
        else:
            raise ValueError("DataFrame 必须包含 datetime 列")

    def _call_init(self) -> None:
        """调用用户 init() 方法（引擎调用）。"""
        self.init()

    def _set_bar_index(self, idx: int) -> None:
        """设置当前 bar 索引（引擎调用）。

        Args:
            idx: bar 索引
        """
        self._bar_index = idx
        if self._data_proxy is not None:
            self._data_proxy._set_index(idx)

    def _call_next(self) -> None:
        """调用用户 next() 方法（引擎调用）。"""
        self.next()

    def _get_datetime(self) -> int:
        """获取当前 bar 的 datetime（引擎调用）。

        Returns:
            datetime int (YYYYMMDD)
        """
        if self._datetime_array is None:
            raise RuntimeError("数据未正确初始化")
        return int(self._datetime_array[self._bar_index])

    def _clear_signals(self) -> list[Signal]:
        """清空并返回已生成的信号（引擎调用）。

        Returns:
            当前累积的信号列表
        """
        signals = self._signals
        self._signals = []
        return signals


# ── 辅助函数 ─────────────────────────────────────────────────────────────────────


def _datetime_to_int(arr: NDArray) -> NDArray:
    """将 datetime 数组转为 int (YYYYMMDD)。

    向量化实现，自动处理 datetime64、object（Timestamp）和数值类型。
    datetime 走 ``year*10000 + month*100 + day`` 整数算术而非
    ``strftime``——strftime 是逐元素格式化（Python 层循环），在
    ``StrategyDataProxy`` 每次 ``_bind_data`` 都要转一遍的热路径上实测
    慢一个数量级（v1.28 性能工作的一部分；输出与 strftime 零填充完全一致，
    NaT → NaN 的行为也一致）。

    Args:
        arr: datetime 数组（np.datetime64、pd.Timestamp 或数值）

    Returns:
        float64 数组，格式 YYYYMMDD
    """
    if len(arr) == 0:
        return np.array([], dtype=np.float64)
    arr = np.asarray(arr)

    def _ymd_to_int(series: pd.Series) -> NDArray:
        out = (series.dt.year * 10000 + series.dt.month * 100 + series.dt.day).to_numpy(
            dtype=np.float64
        )
        return np.asarray(out, dtype=np.float64)

    # datetime64 → 向量化转换
    if arr.dtype.kind == "M":
        return _ymd_to_int(pd.to_datetime(pd.Series(arr)))
    # object 数组（可能包含 Timestamp）
    if arr.dtype == object:
        if len(arr) > 0 and isinstance(arr[0], pd.Timestamp | np.datetime64):
            return _ymd_to_int(pd.to_datetime(pd.Series(arr)))
    # 已经是数值类型
    return arr.astype(np.float64)
