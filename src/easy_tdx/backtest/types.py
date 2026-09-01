"""回测引擎核心数据类型定义。

使用纯 dataclass + 类型注解，保持 mypy strict 兼容。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

# ── 交易信号 ────────────────────────────────────────────────────────────────


@dataclass
class Signal:
    """策略产生的交易信号。

    Attributes:
        datetime: 信号时间（YYYYMMDD 整数格式，如 20240101）
        direction: 交易方向
        size: 交易数量（0 = 全仓/清仓）
        price: 限价（None = 市价单）
        stop_loss: 止损价（None = 不设置）
        take_profit: 止盈价（None = 不设置）
        source: 信号来源。"strategy"=策略产生（默认）；
            "stop"=止损/止盈触发。stop 来源的信号不在信号 bar 当根成交，
            而是延迟到下一根开盘（消除用当根 intrabar 触发价成交的前视偏差）。
    """

    datetime: int
    direction: Literal["BUY", "SELL"]
    size: float
    price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    source: str = "strategy"


# ── 成交记录 ────────────────────────────────────────────────────────────────


@dataclass
class Trade:
    """已成交记录。

    Attributes:
        datetime: 成交时间（YYYYMMDD 整数格式，如 20240101）
        direction: 交易方向
        size: 成交数量
        price: 成交价格
        commission: 手续费
        slippage: 滑点成本
        pnl: 已实现盈亏（仅平仓时计算，绝对金额单位：元）
        cost_basis: SELL 对应的持仓成本基数（元），用于派生单笔收益率 pnl/cost_basis
        rejected: 是否被拒绝（资金不足/不允许做空等）
    """

    datetime: int
    direction: Literal["BUY", "SELL"]
    size: float
    price: float
    commission: float
    slippage: float
    pnl: float = 0.0
    # SELL 对应的持仓成本基数（移动加权平均 × 本次卖出数量），用于计算收益率。
    # BUY 行恒为 0.0。仅 _compute_pnls 平仓时填入。
    cost_basis: float = 0.0
    rejected: bool = False


# ── 持仓快照 ────────────────────────────────────────────────────────────────


@dataclass
class Position:
    """持仓快照。

    Attributes:
        datetime: 快照时间（YYYYMMDD 整数格式，如 20240101）
        size: 持仓数量（正=多头，负=空头，0=空仓）
        avg_price: 平均持仓成本
        market_value: 市值
        unrealized_pnl: 未实现盈亏
    """

    datetime: int
    size: float
    avg_price: float
    market_value: float
    unrealized_pnl: float


# ── 回测结果 ────────────────────────────────────────────────────────────────


def to_json_native(obj: Any) -> Any:
    """递归把 numpy 标量/Timestamp/NaN 清洗为 JSON 原生类型。

    供各结果 dataclass 的 ``to_dict`` 在源头清洗（REST 任务结果与
    Pydantic 序列izer 都不认 numpy.int64/float64）。
    """
    import math

    import numpy as np

    if isinstance(obj, dict):
        return {str(k): to_json_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_json_native(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


@dataclass
class BacktestResult:
    """回测完整结果。

    Attributes:
        performance: 绩效指标字典（总收益率、夏普比率、最大回撤等）
        equity_curve: 资金曲线 DataFrame（index=datetime, columns=equity/drawdown等）
        trades: 成交记录 DataFrame
        positions: 持仓快照 DataFrame
        config: 配置参数字典
        diagnostic: 数据异常诊断（资金曲线不足/恒定时的提示），无异常时为 None
    """

    performance: dict[str, float]
    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    config: dict[str, Any]
    diagnostic: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """将结果转换为 JSON 兼容字典。

        DataFrame 转为 records 列表格式。
        """
        return {
            "performance": self.performance,
            "equity_curve": self.equity_curve.to_dict(orient="records"),
            "trades": self.trades.to_dict(orient="records"),
            "positions": self.positions.to_dict(orient="records"),
            "config": self.config,
            "diagnostic": self.diagnostic,
        }

    def to_json(self) -> str:
        """将结果序列化为 JSON 字符串。"""
        d = self.to_dict()
        return json.dumps(d, ensure_ascii=False, indent=2, default=self._json_default)

    @staticmethod
    def _json_default(obj: Any) -> Any:
        """JSON serializer for objects not serializable by default json code."""
        if hasattr(obj, "item"):
            # numpy types
            return obj.item()
        if hasattr(obj, "isoformat"):
            # datetime/timestamp objects
            return obj.isoformat()
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def summary(self) -> None:
        """打印回测概要（标准输出）。"""
        print("=== 回测绩效概要 ===")
        for key, value in self.performance.items():
            if isinstance(value, float):
                print(f"{key}: {value:.4f}")
            else:
                print(f"{key}: {value}")

        print(f"\n成交记录数: {len(self.trades)}")
        print(f"持仓快照数: {len(self.positions)}")
        print(f"资金曲线点数: {len(self.equity_curve)}")
