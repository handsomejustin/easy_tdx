"""内置策略集合。

每个策略通过 :func:`~easy_tdx.backtest.strategies.registry.register_strategy`
登记到全局注册表，并声明参数 schema 供 Web API 表单动态渲染。

导入本模块即触发所有策略的注册。Web API / CLI 通过 ``get_registry()```
发现策略，无需手动枚举。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from easy_tdx.backtest.strategies.registry import (
    Param,
    ParametrizedStrategy,
    register_strategy,
)
from easy_tdx.MyTT import (
    ATR,
    BBI,
    BIAS,
    BOLL,
    CCI,
    CROSS,
    DMI,
    DPO,
    EMA,
    EMV,
    FSL,
    HHV,
    KDJ,
    KTN,
    MA,
    MACD,
    RSI,
    TAQ,
    TRIX,
    WR,
    ZIG,
)

__all__: list[str] = []  # 注册副作用即可，无需导出符号


# ── 双均线交叉 ─────────────────────────────────────────────────────────────────


@register_strategy(
    name="ma_cross",
    label="双均线交叉",
    description="快线上穿慢线买入，快线下穿慢线卖出。最经典的趋势跟随策略。",
)
class MaCrossStrategy(ParametrizedStrategy):
    """快慢均线金叉买入、死叉卖出。"""

    params = [
        Param("fast", int, default=5, min_value=1, max_value=60, label="快线周期"),
        Param("slow", int, default=20, min_value=5, max_value=250, label="慢线周期"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.ma_fast = self.I(MA, self.data.close, self.p["fast"])
        self.ma_slow = self.I(MA, self.data.close, self.p["slow"])
        self.gold = self.I(CROSS, self.ma_fast, self.ma_slow)
        self.dead = self.I(CROSS, self.ma_slow, self.ma_fast)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── MACD 金叉 ──────────────────────────────────────────────────────────────────


@register_strategy(
    name="macd",
    label="MACD 金叉",
    description="DIF 上穿 DEA 买入（金叉），DIF 下穿 DEA 卖出（死叉）。",
)
class MacdStrategy(ParametrizedStrategy):
    """MACD 金叉/死叉。"""

    params = [
        Param("short", int, default=12, min_value=2, max_value=50, label="短期EMA"),
        Param("long", int, default=26, min_value=5, max_value=100, label="长期EMA"),
        Param("signal", int, default=9, min_value=2, max_value=50, label="信号周期"),
    ]
    param_constraints = [("short", "long")]

    def init(self) -> None:
        self.dif, self.dea, self._hist = self.I(
            MACD,
            self.data.close,
            self.p["short"],
            self.p["long"],
            self.p["signal"],
        )
        self.gold = self.I(CROSS, self.dif, self.dea)
        self.dead = self.I(CROSS, self.dea, self.dif)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── 布林带突破 ─────────────────────────────────────────────────────────────────


@register_strategy(
    name="boll_breakout",
    label="布林带突破",
    description="收盘价突破下轨买入，突破上轨卖出（均值回归思路）。",
)
class BollBreakoutStrategy(ParametrizedStrategy):
    """价格触及下轨买入、触及上轨卖出。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=100, label="周期"),
        Param("p", float, default=2.0, min_value=0.5, max_value=4.0, label="标准差倍数"),
    ]

    def init(self) -> None:
        self.upper, self.mid, self.lower = self.I(BOLL, self.data.close, self.p["n"], self.p["p"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        # 触及下轨买入（均值回归）；触及上轨获利了结
        if close <= self.lower[i] and self.position["size"] == 0:
            self.buy()
        elif close >= self.upper[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """触及下轨进 / 触及上轨出（NaN 轨道期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return close <= self.lower, close >= self.upper


# ── RSI 超买超卖 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="rsi_reversal",
    label="RSI 超卖反弹",
    description="RSI 低于超卖线买入，RSI 高于超买线卖出。",
)
class RsiReversalStrategy(ParametrizedStrategy):
    """RSI 超卖买入、超买卖出。"""

    params = [
        Param("n", int, default=14, min_value=2, max_value=50, label="RSI周期"),
        Param("oversold", int, default=30, min_value=5, max_value=45, label="超卖线"),
        Param("overbought", int, default=70, min_value=55, max_value=95, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.rsi = self.I(RSI, self.data.close, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        rsi = self.rsi[i]
        if rsi <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif rsi >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """RSI 超卖进 / 超买出（NaN 预热期比较为 False，与 next() 一致）。"""
        rsi = np.asarray(self.rsi, dtype=np.float64)
        return rsi <= self.p["oversold"], rsi >= self.p["overbought"]


# ── KDJ 金叉 ───────────────────────────────────────────────────────────────────


@register_strategy(
    name="kdj_cross",
    label="KDJ 金叉",
    description="K 线上穿 D 线买入（金叉），K 线下穿 D 线卖出（死叉）。",
)
class KdjCrossStrategy(ParametrizedStrategy):
    """KDJ K/D 金叉死叉。"""

    params = [
        Param("n", int, default=9, min_value=2, max_value=30, label="RSV周期"),
    ]

    def init(self) -> None:
        self.k, self.d, self._j = self.I(
            KDJ,
            self.data.close,
            self.data.high,
            self.data.low,
            self.p["n"],
        )
        self.gold = self.I(CROSS, self.k, self.d)
        self.dead = self.I(CROSS, self.d, self.k)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── EMA 双线交叉 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="ema_cross",
    label="EMA 双线交叉",
    description="指数均线金叉买入、死叉卖出。比简单均线反应更灵敏。",
)
class EmaCrossStrategy(ParametrizedStrategy):
    params = [
        Param("fast", int, default=12, min_value=2, max_value=60, label="快线周期"),
        Param("slow", int, default=26, min_value=5, max_value=120, label="慢线周期"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.ema_fast = self.I(EMA, self.data.close, self.p["fast"])
        self.ema_slow = self.I(EMA, self.data.close, self.p["slow"])
        self.gold = self.I(CROSS, self.ema_fast, self.ema_slow)
        self.dead = self.I(CROSS, self.ema_slow, self.ema_fast)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── 三均线系统 ────────────────────────────────────────────────────────────────


@register_strategy(
    name="triple_ma",
    label="三均线系统",
    description="短中长期均线多头排列买入、空头排列卖出。",
)
class TripleMaStrategy(ParametrizedStrategy):
    params = [
        Param("short", int, default=5, min_value=1, max_value=30, label="短期"),
        Param("mid", int, default=20, min_value=5, max_value=60, label="中期"),
        Param("long", int, default=60, min_value=20, max_value=250, label="长期"),
    ]
    param_constraints = [("short", "mid"), ("mid", "long")]

    def init(self) -> None:
        self.ma_s = self.I(MA, self.data.close, self.p["short"])
        self.ma_m = self.I(MA, self.data.close, self.p["mid"])
        self.ma_l = self.I(MA, self.data.close, self.p["long"])

    def next(self) -> None:
        i = self._bar_index
        if self.ma_s[i] > self.ma_m[i] > self.ma_l[i] and self.position["size"] == 0:
            self.buy()
        elif self.ma_s[i] < self.ma_m[i] < self.ma_l[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """均线多头排列进 / 空头排列出（链式比较逐元素展开，与 next() 一致）。"""
        return (
            (self.ma_s > self.ma_m) & (self.ma_m > self.ma_l),
            (self.ma_s < self.ma_m) & (self.ma_m < self.ma_l),
        )


# ── 唐安奇通道（海龟）────────────────────────────────────────────────────────


@register_strategy(
    name="donchian",
    label="唐安奇通道突破",
    description="突破N日最高价买入，跌破N日最低价卖出。海龟交易法核心。",
)
class DonchianStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=20, min_value=5, max_value=100, label="通道周期"),
    ]

    def init(self) -> None:
        self.upper, self._mid, self.lower = self.I(TAQ, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close >= self.upper[i] and self.position["size"] == 0:
            self.buy()
        elif close <= self.lower[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """突破 N 日高进 / 跌破 N 日低出（NaN 预热期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return close >= self.upper, close <= self.lower


# ── 肯特纳通道 ────────────────────────────────────────────────────────────────


@register_strategy(
    name="keltner",
    label="肯特纳通道",
    description="收盘价突破上轨买入，跌破下轨卖出。ATR-based 通道。",
)
class KeltnerStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=20, min_value=5, max_value=100, label="均线周期"),
        Param("m", int, default=10, min_value=2, max_value=50, label="ATR周期"),
    ]

    def init(self) -> None:
        self.upper, self._mid, self.lower = self.I(
            KTN, self.data.close, self.data.high, self.data.low, self.p["n"], self.p["m"]
        )

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close >= self.upper[i] and self.position["size"] == 0:
            self.buy()
        elif close <= self.lower[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """突破上轨进 / 跌破下轨出（NaN 预热期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return close >= self.upper, close <= self.lower


# ── BBI 多空指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="bbi",
    label="BBI 多空指标",
    description="收盘价上穿BBI买入，下穿BBI卖出。多空综合指标。",
)
class BbiStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=3, min_value=1, max_value=20, label="均线1"),
        Param("m2", int, default=6, min_value=2, max_value=30, label="均线2"),
        Param("m3", int, default=12, min_value=5, max_value=60, label="均线3"),
        Param("m4", int, default=20, min_value=10, max_value=120, label="均线4"),
    ]

    def init(self) -> None:
        self.bbi = self.I(
            BBI, self.data.close, self.p["m1"], self.p["m2"], self.p["m3"], self.p["m4"]
        )

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close > self.bbi[i] and self.position["size"] == 0:
            self.buy()
        elif close < self.bbi[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """上穿 BBI 进 / 下穿 BBI 出（NaN 预热期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return close > self.bbi, close < self.bbi


# ── CCI 顺势指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="cci",
    label="CCI 超卖反弹",
    description="CCI 跌破-100后回升买入，涨破+100卖出。",
)
class CciStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=14, min_value=2, max_value=50, label="CCI周期"),
        Param("oversold", int, default=-100, min_value=-200, max_value=0, label="超卖线"),
        Param("overbought", int, default=100, min_value=0, max_value=200, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.cci = self.I(CCI, self.data.close, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        cci = self.cci[i]
        if cci <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif cci >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """CCI 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        cci = np.asarray(self.cci, dtype=np.float64)
        return cci <= self.p["oversold"], cci >= self.p["overbought"]


# ── WR 威廉指标 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="wr_reversal",
    label="WR 威廉超卖",
    description="WR 进入超卖区（<-80）买入，进入超买区（>-20）卖出。",
)
class WrReversalStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=14, min_value=2, max_value=50, label="WR周期"),
        Param("oversold", int, default=-80, min_value=-100, max_value=-40, label="超卖线"),
        Param("overbought", int, default=-20, min_value=-60, max_value=0, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.wr, self._wr1 = self.I(WR, self.data.close, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        wr = self.wr[i]
        if wr <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif wr >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """WR 进入超卖区进 / 超买区出（与 next() 同一比较）。"""
        wr = np.asarray(self.wr, dtype=np.float64)
        return wr <= self.p["oversold"], wr >= self.p["overbought"]


# ── BIAS 乖离率 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="bias_reversal",
    label="BIAS 乖离反弹",
    description="乖离率低于负阈值（超跌）买入，高于正阈值（超涨）卖出。",
)
class BiasReversalStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=6, min_value=2, max_value=30, label="均线周期"),
        Param("threshold", float, default=5.0, min_value=1.0, max_value=20.0, label="乖离阈值%"),
    ]

    def init(self) -> None:
        self.bias, self._b2, self._b3 = self.I(BIAS, self.data.close, self.p["n"], 12, 24)

    def next(self) -> None:
        i = self._bar_index
        bias_pct = self.bias[i] * 100
        threshold = self.p["threshold"]
        if bias_pct <= -threshold and self.position["size"] == 0:
            self.buy()
        elif bias_pct >= threshold and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """负乖离超跌进 / 正乖离超涨出（与 next() 同一比较，阈值放大 100 倍口径）。"""
        bias_pct = np.asarray(self.bias, dtype=np.float64) * 100
        threshold = self.p["threshold"]
        return bias_pct <= -threshold, bias_pct >= threshold


# ── DMI 趋向指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="dmi",
    label="DMI 趋向指标",
    description="+DI 上穿-DI 买入（多头趋强），+DI 下穿-DI 卖出。",
)
class DmiStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=14, min_value=2, max_value=30, label="DI周期"),
        Param("m2", int, default=6, min_value=2, max_value=20, label="ADX周期"),
    ]

    def init(self) -> None:
        self.pdi, self.mdi, self._adx, self._adxr = self.I(
            DMI, self.data.close, self.data.high, self.data.low, self.p["m1"], self.p["m2"]
        )
        self.gold = self.I(CROSS, self.pdi, self.mdi)
        self.dead = self.I(CROSS, self.mdi, self.pdi)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── TRIX 三重平滑 ─────────────────────────────────────────────────────────────


@register_strategy(
    name="trix",
    label="TRIX 三重平滑",
    description="TRIX 上穿信号线买入，下穿卖出。过滤短期波动的趋势指标。",
)
class TrixStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=12, min_value=2, max_value=30, label="TRIX周期"),
        Param("m2", int, default=20, min_value=5, max_value=60, label="信号周期"),
    ]

    def init(self) -> None:
        self.trix, self.trma = self.I(TRIX, self.data.close, self.p["m1"], self.p["m2"])
        self.gold = self.I(CROSS, self.trix, self.trma)
        self.dead = self.I(CROSS, self.trma, self.trix)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── EMV 简易波动 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="emv",
    label="EMV 简易波动",
    description="EMV 上穿0轴买入，下穿0轴卖出。量价结合指标。",
)
class EmvStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=14, min_value=2, max_value=30, label="EMV周期"),
    ]

    def init(self) -> None:
        self.emv, self._maemv = self.I(
            EMV, self.data.high, self.data.low, self.data.vol, self.p["n"]
        )

    def next(self) -> None:
        i = self._bar_index
        if self.emv[i] > 0 and self.position["size"] == 0:
            self.buy()
        elif self.emv[i] < 0 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """EMV 上穿 0 轴进 / 下穿 0 轴出（与 next() 同一比较）。"""
        emv = np.asarray(self.emv, dtype=np.float64)
        return emv > 0, emv < 0


# ── DPO 区间震荡 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="dpo",
    label="DPO 区间震荡",
    description="DPO 上穿信号线买入，下穿卖出。去除趋势的震荡指标。",
)
class DpoStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=20, min_value=5, max_value=60, label="DPO周期"),
    ]

    def init(self) -> None:
        self.dpo, self.madpo = self.I(DPO, self.data.close, self.p["m1"])
        self.gold = self.I(CROSS, self.dpo, self.madpo)
        self.dead = self.I(CROSS, self.madpo, self.dpo)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── ATR 通道突破 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="atr_breakout",
    label="ATR 通道突破",
    description="收盘价突破 均线+K×ATR 买入，跌破 均线-K×ATR 卖出。",
)
class AtrBreakoutStrategy(ParametrizedStrategy):
    params = [
        Param("n_ma", int, default=20, min_value=5, max_value=100, label="均线周期"),
        Param("n_atr", int, default=20, min_value=5, max_value=50, label="ATR周期"),
        Param("k", float, default=2.0, min_value=0.5, max_value=5.0, label="ATR倍数"),
    ]

    def init(self) -> None:
        self.ma = self.I(MA, self.data.close, self.p["n_ma"])
        self.atr = self.I(ATR, self.data.close, self.data.high, self.data.low, self.p["n_atr"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        upper = self.ma[i] + self.p["k"] * self.atr[i]
        lower = self.ma[i] - self.p["k"] * self.atr[i]
        if close >= upper and self.position["size"] == 0:
            self.buy()
        elif close <= lower and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """突破 均线+K×ATR 进 / 跌破 均线-K×ATR 出（与 next() 同一比较）。"""
        close = self.data.close.raw
        upper = self.ma + self.p["k"] * self.atr
        lower = self.ma - self.p["k"] * self.atr
        return close >= upper, close <= lower


# ── FSL 分水岭指标 ────────────────────────────────────────────────────────────


@register_strategy(
    name="fsl",
    label="FSL 分水岭",
    description="SWL 上穿 SWS 买入（多头占优），SWL 下穿 SWS 卖出（空头占优）。",
)
class FslStrategy(ParametrizedStrategy):
    """FSL 分水岭 SWL/SWS 金叉死叉。"""

    params = [
        Param(
            "capital",
            float,
            default=1e8,
            min_value=1e6,
            max_value=1e12,
            label="流通股本(股)",
        ),
    ]

    def init(self) -> None:
        self.swl, self.sws = self.I(FSL, self.data.close, self.data.vol, self.p["capital"])
        self.gold = self.I(CROSS, self.swl, self.sws)
        self.dead = self.I(CROSS, self.sws, self.swl)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── ZIG 右侧突破回补 ─────────────────────────────────────────────────────────


@register_strategy(
    name="zig_breakout",
    label="ZIG 右侧突破回补",
    description=(
        "ZIG 向上启动（波谷确认）全仓买入；ZIG 见顶回落清仓并记录 N 日最高点，"
        "其后收盘突破前高×(1+确认比例) 时右侧回补。两路径买入均带硬止损，"
        "对冲 ZIG 波谷确认的前视偏差（未来函数，实盘信号会滞后）。"
    ),
)
class ZigBreakoutStrategy(ParametrizedStrategy):
    """ZIG 右侧突破回补（Re-entry on Breakout + 硬止损保护）。

    ZIG 是未来函数：波峰/波谷只有在其后走势确认转向才回溯标出，回测里
    "波谷启动"信号天然偷看未来。本策略用两层保护缓解而非消除该偏差：

    1. 买入即挂 ``stop_loss_pct`` 硬止损（引擎逐 bar 监控，跌破自动平仓），
       假波谷不至于深套；
    2. 卖出后不追 ZIG 新波谷，而是等价格**右侧突破**前高确认_pct 再回补，
       把"猜底"换成"确认后进场"。

    交易逻辑::

        空仓 + ZIG 上行            → 全仓买入（带止损）
        持仓 + ZIG 下行（见顶）    → 全仓卖出，记录 HHV(high, N) 为前高
        空仓 + 收盘 ≥ 前高×(1+确认) → 右侧回补（带止损）

    注意：``_breakout_level`` 随持仓路径变化，信号不可向量化，故不实现
    ``entry_exit_masks``——引擎自动走逐 bar 回放路径（与 next() 完全一致）。
    """

    params = [
        Param(
            "zig_delta",
            float,
            default=10.0,
            min_value=0.5,
            max_value=50.0,
            label="ZIG转向阈值%",
        ),
        Param(
            "confirm_pct",
            float,
            default=2.0,
            min_value=0.1,
            max_value=20.0,
            label="突破确认比例%",
        ),
        Param("hhv_period", int, default=20, min_value=5, max_value=120, label="前高周期"),
        Param(
            "stop_loss_pct",
            float,
            default=3.0,
            min_value=0.0,
            max_value=30.0,
            label="硬止损%",
        ),
    ]

    def init(self) -> None:
        self.zig = self.I(ZIG, self.data.close, self.p["zig_delta"])
        self.hhv = self.I(HHV, self.data.high, self.p["hhv_period"])
        # 见顶清仓时记录的前高（0 = 未记录，等待首次建仓-见顶周期）
        self._breakout_level: float = 0.0

    def next(self) -> None:
        i = self._bar_index
        if i == 0:
            return

        cur_close = float(self.data.close[0])
        cur_zig = float(self.zig[i])
        prev_zig = float(self.zig[i - 1])
        cur_pos = self.position["size"]

        # 持仓：ZIG 见顶回落 → 清仓，并记录突破位（HHV 含未来 bar 已确认的高点）
        if cur_pos > 0 and cur_zig < prev_zig:
            self._breakout_level = float(self.hhv[i])
            self.sell(size=0)
            return

        if cur_pos == 0:
            # 路径 1：ZIG 向上启动（波谷确认）→ 初始建仓
            if cur_zig > prev_zig:
                self._breakout_level = 0.0
                self._buy_with_stop()
                return

            # 路径 2：右侧突破前高 → 回补（洗盘结束、主升确立）
            if self._breakout_level > 0:
                threshold = self._breakout_level * (1.0 + self.p["confirm_pct"] / 100.0)
                if cur_close >= threshold:
                    self._breakout_level = 0.0
                    self._buy_with_stop()

    def _buy_with_stop(self) -> None:
        """市价全仓买入并按 ``stop_loss_pct`` 挂硬止损（0 = 不挂）。

        市价单（price=None）由引擎在下一根开盘成交，与本地其他内置策略
        口径一致，避免信号 bar 收盘价成交的前视味道。
        """
        pct = self.p["stop_loss_pct"] / 100.0
        if pct > 0:
            self.buy(size=0, stop_loss_pct=pct)
        else:
            self.buy(size=0)
