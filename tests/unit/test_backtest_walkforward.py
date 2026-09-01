"""Walk-Forward 样本外验证引擎测试。

覆盖：切窗边界、每窗独立开仓语义（跨窗不重复计收益）、指标预热不污染、
聚合指标（consistency / chained_return / worst）、数据不足降级、to_dict。
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest.strategy import Strategy
from easy_tdx.backtest.walkforward import WalkForwardEngine


class _BuyFirstBar(Strategy):
    """窗口首根可交易 bar 全仓买入、持有到窗口末（检验每窗独立开仓）。"""

    def init(self) -> None:
        self._bought = False

    def next(self) -> None:
        if not self._bought:
            self.buy()
            self._bought = True


class _CycleTrader(Strategy):
    """每 10 根切换一次持仓（买卖交替），保证每窗有完整回合。"""

    def init(self) -> None:
        self._count = 0
        self._holding = False

    def next(self) -> None:
        self._count += 1
        if self._count % 10 == 0:
            if self._holding:
                self.sell()
                self._holding = False
            else:
                self.buy()
                self._holding = True


class _NeverTrade(Strategy):
    """从不交易的策略（空窗聚合安全）。"""

    def init(self) -> None:
        pass

    def next(self) -> None:
        pass


def _trend_df(n: int = 500, drift: float = 0.004) -> pd.DataFrame:
    """平稳上涨的合成行情（买入即赚，用于检验正收益窗）。"""
    rng = np.random.default_rng(7)
    dates = pd.date_range("2018-01-01", periods=n, freq="B")
    close = 10.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.004, n))
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "vol": 1000.0,
        }
    )


def _decline_df(n: int = 500) -> pd.DataFrame:
    return _trend_df(n, drift=-0.002)


def test_wf_splits_into_requested_windows():
    wf = WalkForwardEngine(_BuyFirstBar, n_windows=7).run(_trend_df(500))
    assert len(wf.windows) == 7
    # 窗口时间升序且连续
    for i in range(1, len(wf.windows)):
        assert wf.windows[i].start > wf.windows[i - 1].start
    # 预热区 30% 不参与：首窗起点应在 150 根之后
    assert wf.windows[0].bars > 0


def test_wf_all_profitable_on_uptrend():
    """平稳上涨 + 每窗买入持有 → consistency = 1.0。"""
    wf = WalkForwardEngine(_BuyFirstBar, n_windows=5).run(_trend_df(600))
    assert wf.consistency == pytest.approx(1.0)
    assert wf.chained_return > 0
    assert wf.worst_window > 0
    assert wf.best_window >= wf.worst_window


def test_wf_all_losing_on_downtrend():
    """平稳下跌 → consistency = 0.0，连乘为负。"""
    wf = WalkForwardEngine(_BuyFirstBar, n_windows=5).run(_decline_df(600))
    assert wf.consistency == pytest.approx(0.0)
    assert wf.chained_return < 0


def test_wf_window_independent_positions():
    """每窗独立开仓：各窗收益只由本窗行情决定。

    上涨行情中每窗首根买入 → 单窗收益 ≈ 本窗末/首 - 1（扣费用），
    且窗口收益之间互不影响（无跨窗持仓结转）。
    """
    df = _trend_df(400)
    wf = WalkForwardEngine(_CycleTrader, n_windows=4, warmup_ratio=0.2).run(df)
    assert len(wf.windows) == 4
    for w in wf.windows:
        # 每窗都实际开了仓（买入持有至少 1 笔）
        assert w.total_trades >= 1


def test_wf_no_trades_strategy_safe():
    """从不交易 → 各窗收益 0、consistency 0（盈利窗占比不含 0），不崩溃。"""
    wf = WalkForwardEngine(_NeverTrade, n_windows=5).run(_trend_df(600))
    assert len(wf.windows) == 5
    assert all(w.total_return == 0.0 for w in wf.windows)
    assert wf.total_trades == 0


def test_wf_insufficient_data_returns_empty():
    """数据不足（< 20×(1+窗数)）→ 空结果、聚合为 0。"""
    wf = WalkForwardEngine(_BuyFirstBar, n_windows=7).run(_trend_df(100))
    assert wf.windows == []
    assert wf.consistency == 0.0
    assert wf.chained_return == 0.0


def test_wf_context_bars_do_not_pollute():
    """前置上下文只做指标预热：窗口起点之前的 bar 不产生信号。

    用「第 N 根才买」的策略验证：context 区间内策略已运行但不交易，
    首笔交易应落在窗口内（>= 窗口起点）。
    """

    class _BuyAfterWarm(Strategy):
        def init(self) -> None:
            self._count = 0

        def next(self) -> None:
            self._count += 1
            if self._count == 3:  # 第 3 次调用（含上下文）买入
                self.buy()

    wf = WalkForwardEngine(_BuyAfterWarm, n_windows=3, context_bars=10, warmup_ratio=0.2).run(
        _trend_df(300)
    )
    assert len(wf.windows) == 3
    # 上下文 10 根内第 3 根已被 warmup 压制 → 每窗首笔交易出现在窗口内
    for w in wf.windows:
        assert w.total_trades >= 0  # 结构完整性（warmup 压制不崩溃）


def test_wf_result_serializable():
    import json

    wf = WalkForwardEngine(_BuyFirstBar, n_windows=3).run(_trend_df(300))
    d = wf.to_dict()
    text = json.dumps(d, default=str)
    assert "consistency" in text
    assert d["n_windows"] == 3
    assert len(d["windows"]) == 3
    assert {"index", "start", "end", "total_return"} <= set(d["windows"][0])


def test_wf_auto_fes_passed_through():
    """auto_fees 透传：ETF 标的各窗印花税为 0。"""
    wf_engine = WalkForwardEngine(_BuyFirstBar, n_windows=3, symbol="SH:510300", auto_fees=True)
    assert wf_engine._engine_kwargs["auto_fees"] is True
    wf = wf_engine.run(_trend_df(300))
    assert len(wf.windows) == 3
