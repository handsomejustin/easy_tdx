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
    AD,
    AROON,
    ASI,
    ATR,
    BBI,
    BBP,
    BBW,
    BIAS,
    BIAS_SIGNAL,
    BOLL,
    BRAR,
    CCI,
    CHANDELIER,
    CHOP,
    CMF,
    CMO,
    CR,
    CROSS,
    DFMA,
    DMI,
    DPO,
    EFI,
    EMA,
    EMV,
    EXPMA,
    FISHER,
    FK,
    FSL,
    HHV,
    HMA,
    ICHIMOKU,
    KAMA,
    KDJ,
    KTN,
    LLV,
    MA,
    MACD,
    MASS,
    MFI,
    MTM,
    OBV,
    PSY,
    REF,
    ROC,
    RSI,
    SAR,
    SQUEEZE,
    SUPERTREND,
    TAQ,
    TRIX,
    TSI,
    UOS,
    VR,
    VWAP,
    WR,
    XSII,
    ZHUOYAO,
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


# ═══════════════════════════════════════════════════════════════════════════
# V4.3 补齐：存量指标补策略（此前 MyTT 有指标但回测无对应内置策略）
# ═══════════════════════════════════════════════════════════════════════════


# ── PSY 心理线 ─────────────────────────────────────────────────────────────────


@register_strategy(
    name="psy_reversal",
    label="PSY 心理线超卖",
    description="心理线跌破超卖线买入（人气冰点），涨破超买线卖出（人气过热）。",
)
class PsyReversalStrategy(ParametrizedStrategy):
    """PSY 超卖买入、超买卖出。"""

    params = [
        Param("n", int, default=12, min_value=2, max_value=60, label="统计周期"),
        Param("m", int, default=6, min_value=2, max_value=30, label="信号线周期"),
        Param("oversold", int, default=25, min_value=5, max_value=45, label="超卖线"),
        Param("overbought", int, default=75, min_value=55, max_value=95, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.psy, self._psy_ma = self.I(PSY, self.data.close, self.p["n"], self.p["m"])

    def next(self) -> None:
        i = self._bar_index
        if self.psy[i] <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif self.psy[i] >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """PSY 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        psy = np.asarray(self.psy, dtype=np.float64)
        return psy <= self.p["oversold"], psy >= self.p["overbought"]


# ── MTM 动量指标 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="mtm_cross",
    label="MTM 动量金叉",
    description="MTM 上穿其均线买入（动量转强），下穿卖出（动量转弱）。",
)
class MtmCrossStrategy(ParametrizedStrategy):
    """MTM/MTMMA 金叉死叉。"""

    params = [
        Param("n", int, default=12, min_value=2, max_value=60, label="动量周期"),
        Param("m", int, default=6, min_value=2, max_value=30, label="均线周期"),
    ]

    def init(self) -> None:
        self.mtm, self.mtmma = self.I(MTM, self.data.close, self.p["n"], self.p["m"])
        self.gold = self.I(CROSS, self.mtm, self.mtmma)
        self.dead = self.I(CROSS, self.mtmma, self.mtm)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── ROC 变动率 ─────────────────────────────────────────────────────────────────


@register_strategy(
    name="roc_zero",
    label="ROC 零轴动量",
    description="ROC 转正买入（涨速转正），转负卖出（涨速转负）。",
)
class RocZeroStrategy(ParametrizedStrategy):
    """ROC 0 轴多空切换。"""

    params = [
        Param("n", int, default=12, min_value=2, max_value=60, label="ROC周期"),
    ]

    def init(self) -> None:
        self.roc, self._maroc = self.I(ROC, self.data.close, self.p["n"], 6)

    def next(self) -> None:
        i = self._bar_index
        if self.roc[i] > 0 and self.position["size"] == 0:
            self.buy()
        elif self.roc[i] < 0 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """ROC 上穿 0 轴进 / 下穿 0 轴出（与 next() 同一比较）。"""
        roc = np.asarray(self.roc, dtype=np.float64)
        return roc > 0, roc < 0


# ── EXPMA 指数平均数 ──────────────────────────────────────────────────────────


@register_strategy(
    name="expma_cross",
    label="EXPMA 双线交叉",
    description="快线 EXPMA 上穿慢线买入，下穿卖出（参数惯用 12/50）。",
)
class ExpmaCrossStrategy(ParametrizedStrategy):
    """EXPMA 12/50 金叉死叉。"""

    params = [
        Param("n1", int, default=12, min_value=2, max_value=60, label="快线周期"),
        Param("n2", int, default=50, min_value=5, max_value=120, label="慢线周期"),
    ]
    param_constraints = [("n1", "n2")]

    def init(self) -> None:
        self.fast, self.slow = self.I(EXPMA, self.data.close, self.p["n1"], self.p["n2"])
        self.gold = self.I(CROSS, self.fast, self.slow)
        self.dead = self.I(CROSS, self.slow, self.fast)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── DFMA 平行线差 ─────────────────────────────────────────────────────────────


@register_strategy(
    name="dfma_cross",
    label="DFMA 平行线差金叉",
    description="DIF 上穿 DIFMA 买入，下穿卖出（双均线差的趋势确认版）。",
)
class DfmaCrossStrategy(ParametrizedStrategy):
    """DFMA DIF/DIFMA 金叉死叉。"""

    params = [
        Param("n1", int, default=10, min_value=2, max_value=60, label="快均线"),
        Param("n2", int, default=50, min_value=5, max_value=120, label="慢均线"),
        Param("m", int, default=10, min_value=2, max_value=60, label="信号周期"),
    ]
    param_constraints = [("n1", "n2")]

    def init(self) -> None:
        self.dif, self.difma = self.I(
            DFMA, self.data.close, self.p["n1"], self.p["n2"], self.p["m"]
        )
        self.gold = self.I(CROSS, self.dif, self.difma)
        self.dead = self.I(CROSS, self.difma, self.dif)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── CR 能量指标 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="cr_reversal",
    label="CR 能量超卖",
    description="CR 跌破 40（能量冰点）买入，涨破 300（能量过热）卖出。",
)
class CrReversalStrategy(ParametrizedStrategy):
    """CR 超卖买入、超买卖出。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=60, label="统计周期"),
        Param("oversold", int, default=40, min_value=10, max_value=80, label="超卖线"),
        Param("overbought", int, default=300, min_value=150, max_value=500, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.cr = self.I(CR, self.data.close, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        if self.cr[i] <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif self.cr[i] >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """CR 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        cr = np.asarray(self.cr, dtype=np.float64)
        return cr <= self.p["oversold"], cr >= self.p["overbought"]


# ── XSII 薛斯通道II ───────────────────────────────────────────────────────────


@register_strategy(
    name="xsii_breakout",
    label="XSII 薛斯通道突破",
    description="收盘价突破薛斯通道上轨 TD1 买入，跌破下轨 TD2 卖出。",
)
class XsiiBreakoutStrategy(ParametrizedStrategy):
    """薛斯通道II 上下轨突破。"""

    params = [
        Param("n", int, default=102, min_value=50, max_value=150, label="通道宽度‰"),
        Param("m", int, default=7, min_value=1, max_value=20, label="动态通道%"),
    ]

    def init(self) -> None:
        self.td1, self.td2, self._td3, self._td4 = self.I(
            XSII, self.data.close, self.data.high, self.data.low, self.p["n"], self.p["m"]
        )

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close >= self.td1[i] and self.position["size"] == 0:
            self.buy()
        elif close <= self.td2[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """突破 TD1 上轨进 / 跌破 TD2 下轨出（NaN 预热期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return close >= self.td1, close <= self.td2


# ── OBV 能量潮 ────────────────────────────────────────────────────────────────


@register_strategy(
    name="obv_cross",
    label="OBV 能量潮金叉",
    description="OBV 上穿其均线买入（量能先行转强），下穿卖出。",
)
class ObvCrossStrategy(ParametrizedStrategy):
    """OBV 与其均线金叉死叉。"""

    params = [
        Param("m", int, default=30, min_value=5, max_value=120, label="均线周期"),
    ]

    def init(self) -> None:
        self.obv = self.I(OBV, self.data.close, self.data.vol)
        self.obv_ma = self.I(MA, self.obv, self.p["m"])
        self.gold = self.I(CROSS, self.obv, self.obv_ma)
        self.dead = self.I(CROSS, self.obv_ma, self.obv)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── VR 容量比率 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="vr_reversal",
    label="VR 容量超卖",
    description="VR 跌破 40（底部区）买入，涨破 160（过热区）卖出。",
)
class VrReversalStrategy(ParametrizedStrategy):
    """VR 超卖买入、超买卖出。"""

    params = [
        Param("m1", int, default=26, min_value=5, max_value=60, label="统计周期"),
        Param("oversold", int, default=40, min_value=10, max_value=70, label="超卖线"),
        Param("overbought", int, default=160, min_value=120, max_value=400, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.vr = self.I(VR, self.data.close, self.data.vol, self.p["m1"])

    def next(self) -> None:
        i = self._bar_index
        if self.vr[i] <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif self.vr[i] >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """VR 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        vr = np.asarray(self.vr, dtype=np.float64)
        return vr <= self.p["oversold"], vr >= self.p["overbought"]


# ── MASS 梅斯线 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="mass_cross",
    label="MASS 梅斯线金叉",
    description="MASS 上穿其均线买入，下穿卖出（波幅挤压释放的节奏判定）。",
)
class MassCrossStrategy(ParametrizedStrategy):
    """MASS/MA 金叉死叉。"""

    params = [
        Param("n1", int, default=9, min_value=2, max_value=30, label="窄波幅周期"),
        Param("n2", int, default=25, min_value=5, max_value=60, label="累计周期"),
        Param("m", int, default=6, min_value=2, max_value=30, label="信号周期"),
    ]

    def init(self) -> None:
        self.mass, self.mass_ma = self.I(
            MASS, self.data.high, self.data.low, self.p["n1"], self.p["n2"], self.p["m"]
        )
        self.gold = self.I(CROSS, self.mass, self.mass_ma)
        self.dead = self.I(CROSS, self.mass_ma, self.mass)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── MFI 资金流量 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="mfi_reversal",
    label="MFI 资金流超卖",
    description="MFI 跌破 20（资金流枯竭）买入，涨破 80（资金流过热）卖出。",
)
class MfiReversalStrategy(ParametrizedStrategy):
    """MFI 超卖买入、超买卖出。"""

    params = [
        Param("n", int, default=14, min_value=2, max_value=60, label="MFI周期"),
        Param("oversold", int, default=20, min_value=5, max_value=35, label="超卖线"),
        Param("overbought", int, default=80, min_value=65, max_value=95, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.mfi = self.I(
            MFI, self.data.close, self.data.high, self.data.low, self.data.vol, self.p["n"]
        )

    def next(self) -> None:
        i = self._bar_index
        if self.mfi[i] <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif self.mfi[i] >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """MFI 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        mfi = np.asarray(self.mfi, dtype=np.float64)
        return mfi <= self.p["oversold"], mfi >= self.p["overbought"]


# ── BRAR 情绪指标 ─────────────────────────────────────────────────────────────


@register_strategy(
    name="brar_reversal",
    label="ARBR 情绪冰点",
    description="AR 跌破 40（市场情绪冰点）买入，AR 涨破 180（情绪过热）卖出。",
)
class BrarReversalStrategy(ParametrizedStrategy):
    """AR 情绪超卖买入、超买卖出。"""

    params = [
        Param("m1", int, default=26, min_value=5, max_value=60, label="统计周期"),
        Param("oversold", int, default=40, min_value=10, max_value=60, label="超卖线"),
        Param("overbought", int, default=180, min_value=120, max_value=300, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.ar, self._br = self.I(
            BRAR, self.data.open, self.data.close, self.data.high, self.data.low, self.p["m1"]
        )

    def next(self) -> None:
        i = self._bar_index
        if self.ar[i] <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif self.ar[i] >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """AR 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        ar = np.asarray(self.ar, dtype=np.float64)
        return ar <= self.p["oversold"], ar >= self.p["overbought"]


# ── ASI 振动升降 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="asi_cross",
    label="ASI 振动升降金叉",
    description="ASI 上穿其均线买入（真实动能转强），下穿卖出。",
)
class AsiCrossStrategy(ParametrizedStrategy):
    """ASI/ASIT 金叉死叉。"""

    params = [
        Param("m1", int, default=26, min_value=5, max_value=60, label="ASI累计周期"),
        Param("m2", int, default=10, min_value=2, max_value=30, label="信号周期"),
    ]

    def init(self) -> None:
        self.asi, self.asit = self.I(
            ASI,
            self.data.open,
            self.data.close,
            self.data.high,
            self.data.low,
            self.p["m1"],
            self.p["m2"],
        )
        self.gold = self.I(CROSS, self.asi, self.asit)
        self.dead = self.I(CROSS, self.asit, self.asi)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── ZHUOYAO 多周期共振 ────────────────────────────────────────────────────────


@register_strategy(
    name="zhuoyao_trend",
    label="ZHUOYAO 多周期共振",
    description="短/中线与趋势线同向为正（多头共振）买入，短/中线同向为负（空头共振）卖出。",
)
class ZhuoyaoTrendStrategy(ParametrizedStrategy):
    """多周期涨幅共振排列。"""

    params = [
        Param("n1", int, default=120, min_value=60, max_value=250, label="长线周期"),
        Param("n2", int, default=60, min_value=20, max_value=120, label="中线周期"),
        Param("n3", int, default=20, min_value=5, max_value=60, label="短线周期"),
        Param("m", int, default=10, min_value=2, max_value=30, label="平滑周期"),
    ]
    param_constraints = [("n3", "n2"), ("n2", "n1")]

    def init(self) -> None:
        self.zy_long, self.zy_mid, self.zy_short, self.zy_trend = self.I(
            ZHUOYAO, self.data.close, self.p["n1"], self.p["n2"], self.p["n3"], self.p["m"]
        )

    def next(self) -> None:
        i = self._bar_index
        if (
            self.zy_short[i] > 0
            and self.zy_mid[i] > 0
            and self.zy_trend[i] > 0
            and self.position["size"] == 0
        ):
            self.buy()
        elif self.zy_short[i] < 0 and self.zy_mid[i] < 0 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """短/中线与趋势线同向为正进 / 短/中线同向为负出（链式比较逐元素展开，与 next() 一致）。"""
        return (
            (self.zy_short > 0) & (self.zy_mid > 0) & (self.zy_trend > 0),
            (self.zy_short < 0) & (self.zy_mid < 0),
        )


# ── BIAS_SIGNAL 乖离信号 ──────────────────────────────────────────────────────


@register_strategy(
    name="bias_signal_cross",
    label="BIAS_SIGNAL 乖离信号金叉",
    description="短信号线上穿长信号线买入（乖离拐头向上），下穿卖出。",
)
class BiasSignalCrossStrategy(ParametrizedStrategy):
    """乖离率短/长信号线金叉死叉。"""

    params = [
        Param("p", int, default=10, min_value=2, max_value=30, label="短信号周期"),
        Param("m", int, default=30, min_value=5, max_value=90, label="长信号周期"),
    ]
    param_constraints = [("p", "m")]

    def init(self) -> None:
        self._x, self.s_short, self.s_long = self.I(
            BIAS_SIGNAL, self.data.close, self.p["p"], self.p["m"]
        )
        self.gold = self.I(CROSS, self.s_short, self.s_long)
        self.dead = self.I(CROSS, self.s_long, self.s_short)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── SAR 抛物线跟随 ────────────────────────────────────────────────────────────


@register_strategy(
    name="sar_follow",
    label="SAR 抛物线跟随",
    description="收盘价上穿 SAR 买入，下穿 SAR 卖出（趋势跟随，SAR 即移动止损位）。",
)
class SarFollowStrategy(ParametrizedStrategy):
    """价格与 SAR 交叉的抛物线跟随。"""

    params = [
        Param("af_step", float, default=0.02, min_value=0.005, max_value=0.2, label="加速步长"),
        Param("af_max", float, default=0.2, min_value=0.05, max_value=0.5, label="加速上限"),
    ]
    param_constraints = [("af_step", "af_max")]

    def init(self) -> None:
        self.sar = self.I(SAR, self.data.high, self.data.low, self.p["af_step"], self.p["af_max"])
        self.gold = self.I(CROSS, self.data.close, self.sar)
        self.dead = self.I(CROSS, self.sar, self.data.close)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── VWAP 成本线 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="vwap_cross",
    label="VWAP 成本线穿越",
    description="收盘价上穿 N 日 VWAP 买入（站上机构成本），下穿卖出。",
)
class VwapCrossStrategy(ParametrizedStrategy):
    """价格与滚动 VWAP 交叉。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=60, label="VWAP周期"),
    ]

    def init(self) -> None:
        self.vwap = self.I(
            VWAP, self.data.close, self.data.high, self.data.low, self.data.vol, self.p["n"]
        )
        self.gold = self.I(CROSS, self.data.close, self.vwap)
        self.dead = self.I(CROSS, self.vwap, self.data.close)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── AROON 阿隆 ────────────────────────────────────────────────────────────────


@register_strategy(
    name="aroon_cross",
    label="AROON 阿隆金叉",
    description="阿隆上线（创新高动能）上穿下线（创新低动能）买入，反向卖出。",
)
class AroonCrossStrategy(ParametrizedStrategy):
    """AROON 上/下线金叉死叉。"""

    params = [
        Param("n", int, default=25, min_value=5, max_value=60, label="回看周期"),
    ]

    def init(self) -> None:
        self.up, self.down, self._osc = self.I(AROON, self.data.high, self.data.low, self.p["n"])
        self.gold = self.I(CROSS, self.up, self.down)
        self.dead = self.I(CROSS, self.down, self.up)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── FK 超卖反弹 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="fk_reversal",
    label="FK 超卖反弹",
    description="FK 转为 True（价格相对趋势外推线超卖）买入，转回 False 卖出。",
)
class FkReversalStrategy(ParametrizedStrategy):
    """FK 布尔信号的边沿触发。"""

    params = []  # 无参数策略（基类默认即空 schema，显式声明便于阅读）

    def init(self) -> None:
        fk = np.asarray(self.I(FK, self.data.close), dtype=bool)
        prev = np.concatenate(([False], fk[:-1]))
        self.sig_on = fk & ~prev  # FK 变 True：超卖反弹信号出现
        self.sig_off = ~fk & prev  # FK 变 False：反弹动能消退

    def next(self) -> None:
        i = self._bar_index
        if self.sig_on[i]:
            self.buy()
        elif self.sig_off[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（sig_on/sig_off 即 next() 判定用的同一组掩码数组）。"""
        return self.sig_on, self.sig_off


# ═══════════════════════════════════════════════════════════════════════════
# V4.3 新指标策略（MyTT 新增 16 个无未来函数指标的首发策略）
# ═══════════════════════════════════════════════════════════════════════════


# ── SuperTrend 超级趋势 ───────────────────────────────────────────────────────


@register_strategy(
    name="supertrend",
    label="SuperTrend 超级趋势",
    description="趋势方向翻多买入（价格上穿带），翻空卖出（价格下穿带）。带线即移动止损位。",
)
class SupertrendStrategy(ParametrizedStrategy):
    """SuperTrend 方向翻转跟随。"""

    params = [
        Param("n", int, default=10, min_value=5, max_value=50, label="ATR周期"),
        Param("m", float, default=3.0, min_value=1.0, max_value=6.0, label="ATR倍数"),
    ]

    def init(self) -> None:
        self.st, self.st_dir = self.I(
            SUPERTREND, self.data.close, self.data.high, self.data.low, self.p["n"], self.p["m"]
        )
        d = np.asarray(self.st_dir, dtype=float)
        prev = REF(d, 1)  # 首根为 NaN → 首根不产生信号
        self.gold = (d == 1) & (prev == -1)  # 翻多
        self.dead = (d == -1) & (prev == 1)  # 翻空

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """方向 翻多进 / 翻空出（与 next() 同一比较）。"""
        return self.gold, self.dead


# ── KAMA 自适应均线 ───────────────────────────────────────────────────────────


@register_strategy(
    name="kama_cross",
    label="KAMA 自适应均线穿越",
    description="收盘价上穿 KAMA 买入，下穿卖出（震荡期均线自动走平，减少假信号）。",
)
class KamaCrossStrategy(ParametrizedStrategy):
    """价格与 KAMA 交叉。"""

    params = [
        Param("n", int, default=10, min_value=5, max_value=60, label="效率比周期"),
        Param("fast", int, default=2, min_value=2, max_value=10, label="快平滑常数"),
        Param("slow", int, default=30, min_value=10, max_value=100, label="慢平滑常数"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.kama = self.I(KAMA, self.data.close, self.p["n"], self.p["fast"], self.p["slow"])
        self.gold = self.I(CROSS, self.data.close, self.kama)
        self.dead = self.I(CROSS, self.kama, self.data.close)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── HMA 赫尔均线 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="hma_cross",
    label="HMA 赫尔均线交叉",
    description="快 HMA 上穿慢 HMA 买入，下穿卖出（低滞后均线的经典双线用法）。",
)
class HmaCrossStrategy(ParametrizedStrategy):
    """快/慢 HMA 金叉死叉。"""

    params = [
        Param("fast", int, default=10, min_value=2, max_value=30, label="快线周期"),
        Param("slow", int, default=30, min_value=10, max_value=120, label="慢线周期"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.hma_fast = self.I(HMA, self.data.close, self.p["fast"])
        self.hma_slow = self.I(HMA, self.data.close, self.p["slow"])
        self.gold = self.I(CROSS, self.hma_fast, self.hma_slow)
        self.dead = self.I(CROSS, self.hma_slow, self.hma_fast)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── 吊灯止损系统 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="chandelier",
    label="吊灯止损系统",
    description="突破 N 日最高价买入（通道突破进场），跌破吊灯止损线 HHV-K×ATR 卖出。",
)
class ChandelierStrategy(ParametrizedStrategy):
    """通道突破进场 + 吊灯止损离场（LeBeau 经典组合）。"""

    params = [
        Param("n", int, default=22, min_value=10, max_value=100, label="突破/止损周期"),
        Param("m", int, default=22, min_value=5, max_value=50, label="ATR周期"),
        Param("k", float, default=3.0, min_value=1.0, max_value=6.0, label="ATR倍数"),
    ]

    def init(self) -> None:
        self.upper = self.I(HHV, self.data.high, self.p["n"])
        self.long_stop, self._short_stop = self.I(
            CHANDELIER,
            self.data.close,
            self.data.high,
            self.data.low,
            self.p["n"],
            self.p["m"],
            self.p["k"],
        )

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close >= self.upper[i] and self.position["size"] == 0:
            self.buy()
        elif close <= self.long_stop[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """突破 N 日高进 / 跌破吊灯止损线出（NaN 预热期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return close >= self.upper, close <= self.long_stop


# ── ICHIMOKU 一目均衡 ─────────────────────────────────────────────────────────


@register_strategy(
    name="ichimoku_cross",
    label="ICHIMOKU 一目均衡金叉",
    description="转换线上穿基准线且收盘在云层上方买入；转换线下穿基准线且收盘在云层下方卖出。",
)
class IchimokuCrossStrategy(ParametrizedStrategy):
    """转换/基准线交叉 + 云层位置确认。"""

    params = [
        Param("p1", int, default=9, min_value=2, max_value=30, label="转换线周期"),
        Param("p2", int, default=26, min_value=5, max_value=60, label="基准线/位移周期"),
        Param("p3", int, default=52, min_value=10, max_value=120, label="先行带B周期"),
    ]
    param_constraints = [("p1", "p2"), ("p2", "p3")]

    def init(self) -> None:
        self.tenkan, self.kijun, self.span_a, self.span_b, self._chikou = self.I(
            ICHIMOKU,
            self.data.high,
            self.data.low,
            self.data.close,
            self.p["p1"],
            self.p["p2"],
            self.p["p3"],
        )
        # 云顶/云底取先行带 A/B 的包络（先行带为 SHIFT 期前的值画到当前，仅引用过去数据）
        cloud_top = np.maximum(self.span_a, self.span_b)
        cloud_bot = np.minimum(self.span_a, self.span_b)
        close = self.data.close.raw
        self.gold = np.asarray(CROSS(self.tenkan, self.kijun)) & (close > cloud_top)
        self.dead = np.asarray(CROSS(self.kijun, self.tenkan)) & (close < cloud_bot)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """金叉且价在云上进 / 死叉且价在云下出（与 next() 同一比较）。"""
        return self.gold, self.dead


# ── UOS 终极指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="uos_reversal",
    label="UOS 终极超卖",
    description="UOS 跌破 30（三周期动量全面超卖）买入，涨破 70 卖出。",
)
class UosReversalStrategy(ParametrizedStrategy):
    """UOS 超卖买入、超买卖出。"""

    params = [
        Param("p1", int, default=7, min_value=2, max_value=14, label="短周期"),
        Param("p2", int, default=14, min_value=5, max_value=21, label="中周期"),
        Param("p3", int, default=28, min_value=10, max_value=60, label="长周期"),
        Param("oversold", int, default=30, min_value=5, max_value=45, label="超卖线"),
        Param("overbought", int, default=70, min_value=55, max_value=95, label="超买线"),
    ]
    param_constraints = [("p1", "p2"), ("p2", "p3"), ("oversold", "overbought")]

    def init(self) -> None:
        self.uos, self._uos_ma = self.I(
            UOS,
            self.data.close,
            self.data.high,
            self.data.low,
            self.p["p1"],
            self.p["p2"],
            self.p["p3"],
        )

    def next(self) -> None:
        i = self._bar_index
        if self.uos[i] <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif self.uos[i] >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """UOS 跌破超卖线进 / 涨破超买线出（与 next() 同一比较）。"""
        uos = np.asarray(self.uos, dtype=np.float64)
        return uos <= self.p["oversold"], uos >= self.p["overbought"]


# ── CMO 钱德动量 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="cmo_reversal",
    label="CMO 钱德动量超卖",
    description="CMO 跌破 -阈值（纯下跌动能极值）买入，涨破 +阈值 卖出。",
)
class CmoReversalStrategy(ParametrizedStrategy):
    """CMO 对称阈值反转。"""

    params = [
        Param("n", int, default=14, min_value=2, max_value=60, label="CMO周期"),
        Param("threshold", float, default=50.0, min_value=10.0, max_value=90.0, label="阈值"),
    ]

    def init(self) -> None:
        self.cmo = self.I(CMO, self.data.close, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        if self.cmo[i] <= -self.p["threshold"] and self.position["size"] == 0:
            self.buy()
        elif self.cmo[i] >= self.p["threshold"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """CMO 跌破 -阈值进 / 涨破 +阈值出（与 next() 同一比较）。"""
        cmo = np.asarray(self.cmo, dtype=np.float64)
        return cmo <= -self.p["threshold"], cmo >= self.p["threshold"]


# ── TSI 真实强度 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="tsi_cross",
    label="TSI 真实强度金叉",
    description="TSI 上穿信号线买入（双平滑动量转强），下穿卖出。",
)
class TsiCrossStrategy(ParametrizedStrategy):
    """TSI/信号线金叉死叉。"""

    params = [
        Param("r", int, default=25, min_value=5, max_value=60, label="一阶平滑"),
        Param("s", int, default=13, min_value=2, max_value=40, label="二阶平滑"),
        Param("m", int, default=13, min_value=2, max_value=40, label="信号周期"),
    ]

    def init(self) -> None:
        self.tsi, self.tsi_signal = self.I(
            TSI, self.data.close, self.p["r"], self.p["s"], self.p["m"]
        )
        self.gold = self.I(CROSS, self.tsi, self.tsi_signal)
        self.dead = self.I(CROSS, self.tsi_signal, self.tsi)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── FISHER 费雪变换 ───────────────────────────────────────────────────────────


@register_strategy(
    name="fisher_cross",
    label="FISHER 费雪拐点",
    description="Fisher 线上穿其触发线（前一期值）买入，下穿卖出（拐点尖锐、无钝化）。",
)
class FisherCrossStrategy(ParametrizedStrategy):
    """Fisher/触发线金叉死叉。"""

    params = [
        Param("n", int, default=9, min_value=2, max_value=30, label="归一化周期"),
    ]

    def init(self) -> None:
        self.fisher, self.trigger = self.I(FISHER, self.data.high, self.data.low, self.p["n"])
        self.gold = self.I(CROSS, self.fisher, self.trigger)
        self.dead = self.I(CROSS, self.trigger, self.fisher)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── SQUEEZE TTM 挤压突破 ──────────────────────────────────────────────────────


@register_strategy(
    name="squeeze_breakout",
    label="TTM 挤压突破",
    description="波动挤压（布林收进肯特纳）解除且动量为正时买入，动量转负卖出。",
)
class SqueezeBreakoutStrategy(ParametrizedStrategy):
    """挤压释放 + 动量方向确认。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=60, label="通道周期"),
        Param("bb", float, default=2.0, min_value=0.5, max_value=4.0, label="布林倍数"),
        Param("kc", float, default=1.5, min_value=0.5, max_value=4.0, label="肯特纳倍数"),
    ]

    def init(self) -> None:
        self.sqz, self.mom = self.I(
            SQUEEZE,
            self.data.close,
            self.data.high,
            self.data.low,
            self.p["n"],
            self.p["bb"],
            self.p["kc"],
        )
        sqz = np.asarray(self.sqz, dtype=bool)
        prev = np.concatenate(([False], sqz[:-1]))
        self.release = prev & ~sqz  # 挤压解除（当期脱离挤压态）
        self.mom_arr = np.asarray(self.mom, dtype=np.float64)

    def next(self) -> None:
        i = self._bar_index
        if self.release[i] and self.mom_arr[i] > 0 and self.position["size"] == 0:
            self.buy()
        elif self.mom_arr[i] < 0 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """挤压解除且动量为正进 / 动量转负出（与 next() 同一比较）。"""
        return self.release & (self.mom_arr > 0), self.mom_arr < 0


# ── CHOP 趋态过滤 ─────────────────────────────────────────────────────────────


@register_strategy(
    name="chop_trend",
    label="CHOP 趋态过滤",
    description="盘整指数跌破趋势线且价格在均线上方买入（趋势启动）；盘整指数升破震荡线卖出。",
)
class ChopTrendStrategy(ParametrizedStrategy):
    """CHOP 状态开关 + 均线方向过滤。"""

    params = [
        Param("n", int, default=14, min_value=5, max_value=40, label="CHOP周期"),
        Param("n_ma", int, default=20, min_value=5, max_value=120, label="方向均线周期"),
        Param("trend_th", float, default=38.2, min_value=20.0, max_value=50.0, label="趋势阈值"),
        Param("range_th", float, default=61.8, min_value=55.0, max_value=90.0, label="震荡阈值"),
    ]
    param_constraints = [("trend_th", "range_th")]

    def init(self) -> None:
        self.chop = self.I(CHOP, self.data.close, self.data.high, self.data.low, self.p["n"])
        self.ma = self.I(MA, self.data.close, self.p["n_ma"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if self.chop[i] <= self.p["trend_th"] and close > self.ma[i] and self.position["size"] == 0:
            self.buy()
        elif self.chop[i] >= self.p["range_th"] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """CHOP 进入趋势态且价在均线上进 / CHOP 进入震荡态出（与 next() 同一比较）。"""
        chop = np.asarray(self.chop, dtype=np.float64)
        close = self.data.close.raw
        return (chop <= self.p["trend_th"]) & (close > self.ma), chop >= self.p["range_th"]


# ── AD 累积/派发线 ────────────────────────────────────────────────────────────


@register_strategy(
    name="ad_cross",
    label="AD 累派线金叉",
    description="累积/派发线上穿其均线买入（吸筹转强），下穿卖出（派发占优）。",
)
class AdCrossStrategy(ParametrizedStrategy):
    """AD 与其均线金叉死叉。"""

    params = [
        Param("m", int, default=30, min_value=5, max_value=120, label="均线周期"),
    ]

    def init(self) -> None:
        self.ad = self.I(AD, self.data.close, self.data.high, self.data.low, self.data.vol)
        self.ad_ma = self.I(MA, self.ad, self.p["m"])
        self.gold = self.I(CROSS, self.ad, self.ad_ma)
        self.dead = self.I(CROSS, self.ad_ma, self.ad)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """与 next() 同源（gold/dead 即 next() 判定用的同一组掩码数组）。"""
        return self.gold, self.dead


# ── CMF 佳庆资金流 ────────────────────────────────────────────────────────────


@register_strategy(
    name="cmf_zero",
    label="CMF 资金流零轴",
    description="CMF 转正买入（资金净流入），转负卖出（资金净流出）。",
)
class CmfZeroStrategy(ParametrizedStrategy):
    """CMF 0 轴多空切换。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=60, label="CMF周期"),
    ]

    def init(self) -> None:
        self.cmf = self.I(
            CMF, self.data.close, self.data.high, self.data.low, self.data.vol, self.p["n"]
        )

    def next(self) -> None:
        i = self._bar_index
        if self.cmf[i] > 0 and self.position["size"] == 0:
            self.buy()
        elif self.cmf[i] < 0 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """CMF 上穿 0 轴进 / 下穿 0 轴出（与 next() 同一比较）。"""
        cmf = np.asarray(self.cmf, dtype=np.float64)
        return cmf > 0, cmf < 0


# ── EFI 艾尔德强力指数 ────────────────────────────────────────────────────────


@register_strategy(
    name="efi_zero",
    label="EFI 强力指数零轴",
    description="强力指数转正买入（多方力量占优），转负卖出（空方力量占优）。",
)
class EfiZeroStrategy(ParametrizedStrategy):
    """EFI 0 轴多空切换。"""

    params = [
        Param("n", int, default=13, min_value=2, max_value=60, label="平滑周期"),
    ]

    def init(self) -> None:
        self.efi = self.I(EFI, self.data.close, self.data.vol, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        if self.efi[i] > 0 and self.position["size"] == 0:
            self.buy()
        elif self.efi[i] < 0 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """EFI 上穿 0 轴进 / 下穿 0 轴出（与 next() 同一比较）。"""
        efi = np.asarray(self.efi, dtype=np.float64)
        return efi > 0, efi < 0


# ── BBP 布林位置 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="bbp_reversal",
    label="BBP 布林位置超卖",
    description="%B 跌破 0（收盘跌破布林下轨）买入，涨破 100（升破上轨）卖出。",
)
class BbpReversalStrategy(ParametrizedStrategy):
    """%B 0/100 上下轨反转。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=60, label="布林周期"),
        Param("p", float, default=2.0, min_value=0.5, max_value=4.0, label="标准差倍数"),
    ]

    def init(self) -> None:
        self.bbp = self.I(BBP, self.data.close, self.p["n"], self.p["p"])

    def next(self) -> None:
        i = self._bar_index
        if self.bbp[i] <= 0 and self.position["size"] == 0:
            self.buy()
        elif self.bbp[i] >= 100 and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """%B 跌破 0 进 / 涨破 100 出（与 next() 同一比较）。"""
        bbp = np.asarray(self.bbp, dtype=np.float64)
        return bbp <= 0, bbp >= 100


# ── BBW 布林带宽挤压 ──────────────────────────────────────────────────────────


@register_strategy(
    name="bbw_squeeze",
    label="BBW 带宽挤压突破",
    description="带宽收敛至 N 日最低（波动挤压）且价格站上均线买入；跌破均线卖出。",
)
class BbwSqueezeStrategy(ParametrizedStrategy):
    """带宽极值挤压 + 均线方向突破。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=60, label="带宽/挤压周期"),
        Param("p", float, default=2.0, min_value=0.5, max_value=4.0, label="标准差倍数"),
        Param("n_ma", int, default=20, min_value=5, max_value=120, label="方向均线周期"),
    ]

    def init(self) -> None:
        self.bbw = self.I(BBW, self.data.close, self.p["n"], self.p["p"])
        self.bbw_low = self.I(LLV, self.bbw, self.p["n"])
        self.ma = self.I(MA, self.data.close, self.p["n_ma"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if self.bbw[i] <= self.bbw_low[i] and close > self.ma[i] and self.position["size"] == 0:
            self.buy()
        elif close < self.ma[i] and self.position["size"] > 0:
            self.sell()

    def entry_exit_masks(self) -> tuple[Any, Any]:
        """带宽触 N 日低且价在均线上进 / 价跌破均线出（NaN 预热期比较为 False，与 next() 一致）。"""
        close = self.data.close.raw
        return (self.bbw <= self.bbw_low) & (close > self.ma), close < self.ma
