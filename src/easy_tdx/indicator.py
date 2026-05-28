"""技术指标计算模块 — 基于 MyTT 的纯计算层（无 IO）。"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import MyTT


@dataclass(frozen=True)
class IndicatorSpec:
    """单个技术指标的元数据。"""

    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    func: Callable[..., object]
    default_params: dict[str, int | float]
    description: str


_REGISTRY: dict[str, IndicatorSpec] = {}


def _reg(
    name: str,
    inputs: tuple[str, ...],
    outputs: tuple[str, ...],
    func: Callable[..., object],
    defaults: dict[str, int | float],
    desc: str,
) -> None:
    _REGISTRY[name.upper()] = IndicatorSpec(
        name=name.upper(),
        inputs=inputs,
        outputs=outputs,
        func=func,
        default_params=defaults,
        description=desc,
    )


# ── 仅需 close ──────────────────────────────────────────────────────────
_reg(
    "MACD",
    ("close",),
    ("MACD_DIF", "MACD_DEA", "MACD_HIST"),
    MyTT.MACD,
    {"SHORT": 12, "LONG": 26, "M": 9},
    "MACD 指数平滑异同移动平均线",
)
_reg("RSI", ("close",), ("RSI",), MyTT.RSI, {"N": 24}, "RSI 相对强弱指标")
_reg(
    "BOLL",
    ("close",),
    ("BOLL_UPPER", "BOLL_MID", "BOLL_LOWER"),
    MyTT.BOLL,
    {"N": 20, "P": 2},
    "BOLL 布林带",
)
_reg(
    "BIAS",
    ("close",),
    ("BIAS1", "BIAS2", "BIAS3"),
    MyTT.BIAS,
    {"L1": 6, "L2": 12, "L3": 24},
    "BIAS 乖离率",
)
_reg("PSY", ("close",), ("PSY", "PSY_MA"), MyTT.PSY, {"N": 12, "M": 6}, "PSY 心理线")
_reg(
    "TRIX",
    ("close",),
    ("TRIX", "TRIX_MA"),
    MyTT.TRIX,
    {"M1": 12, "M2": 20},
    "TRIX 三重指数平滑平均线",
)
_reg(
    "DPO", ("close",), ("DPO", "DPO_MA"), MyTT.DPO, {"M1": 20, "M2": 10, "M3": 6}, "DPO 区间震荡线"
)
_reg("MTM", ("close",), ("MTM", "MTM_MA"), MyTT.MTM, {"N": 12, "M": 6}, "MTM 动量指标")
_reg("ROC", ("close",), ("ROC", "ROC_MA"), MyTT.ROC, {"N": 12, "M": 6}, "ROC 变动率指标")
_reg(
    "EXPMA",
    ("close",),
    ("EXPMA_12", "EXPMA_50"),
    MyTT.EXPMA,
    {"N1": 12, "N2": 50},
    "EXPMA 指数平均数指标",
)
_reg("BBI", ("close",), ("BBI",), MyTT.BBI, {"M1": 3, "M2": 6, "M3": 12, "M4": 20}, "BBI 多空指标")
_reg(
    "DFMA",
    ("close",),
    ("DFMA_DIF", "DFMA_DMA"),
    MyTT.DFMA,
    {"N1": 10, "N2": 50, "M": 10},
    "DFMA 平行线差指标",
)

# ── 需要 close + high + low ─────────────────────────────────────────────
_reg(
    "KDJ",
    ("close", "high", "low"),
    ("KDJ_K", "KDJ_D", "KDJ_J"),
    MyTT.KDJ,
    {"N": 9, "M1": 3, "M2": 3},
    "KDJ 随机指标",
)
_reg(
    "DMI",
    ("close", "high", "low"),
    ("DMI_PDI", "DMI_MDI", "DMI_ADX", "DMI_ADXR"),
    MyTT.DMI,
    {"M1": 14, "M2": 6},
    "DMI 动向指标",
)
_reg("ATR", ("close", "high", "low"), ("ATR",), MyTT.ATR, {"N": 20}, "ATR 真实波幅均值")
_reg("WR", ("close", "high", "low"), ("WR1", "WR2"), MyTT.WR, {"N": 10, "N1": 6}, "WR 威廉指标")
_reg("CCI", ("close", "high", "low"), ("CCI",), MyTT.CCI, {"N": 14}, "CCI 顺势指标")
_reg("CR", ("close", "high", "low"), ("CR",), MyTT.CR, {"N": 20}, "CR 价格动量指标")
_reg(
    "KTN",
    ("close", "high", "low"),
    ("KTN_UPPER", "KTN_MID", "KTN_LOWER"),
    MyTT.KTN,
    {"N": 20, "M": 10},
    "KTN 肯特纳通道",
)
_reg(
    "XSII",
    ("close", "high", "low"),
    ("XSII_TD1", "XSII_TD2", "XSII_TD3", "XSII_TD4"),
    MyTT.XSII,
    {"N": 102, "M": 7},
    "XSII 薛斯通道II",
)

# ── 需要 close + vol ────────────────────────────────────────────────────
_reg("OBV", ("close", "vol"), ("OBV",), MyTT.OBV, {}, "OBV 能量潮指标")
_reg("VR", ("close", "vol"), ("VR",), MyTT.VR, {"M1": 26}, "VR 容量比率")

# ── 需要 high + low + vol ───────────────────────────────────────────────
_reg(
    "EMV",
    ("high", "low", "vol"),
    ("EMV", "EMV_MA"),
    MyTT.EMV,
    {"N": 14, "M": 9},
    "EMV 简易波动指标",
)
_reg(
    "MASS",
    ("high", "low"),
    ("MASS", "MASS_MA"),
    MyTT.MASS,
    {"N1": 9, "N2": 25, "M": 6},
    "MASS 梅斯线",
)

# ── 需要 close + high + low + vol ──────────────────────────────────────
_reg("MFI", ("close", "high", "low", "vol"), ("MFI",), MyTT.MFI, {"N": 14}, "MFI 资金流量指标")

# ── 需要 open + close + high + low ─────────────────────────────────────
_reg("BRAR", ("open", "close", "high", "low"), ("AR", "BR"), MyTT.BRAR, {"M1": 26}, "BRAR 情绪指标")
_reg(
    "ASI",
    ("open", "close", "high", "low"),
    ("ASI", "ASI_MA"),
    MyTT.ASI,
    {"M1": 26, "M2": 10},
    "ASI 振动升降指标",
)

# ── 仅需 high + low ────────────────────────────────────────────────────
_reg(
    "TAQ", ("high", "low"), ("TAQ_UP", "TAQ_MID", "TAQ_DOWN"), MyTT.TAQ, {"N": 20}, "TAQ 唐安奇通道"
)


def list_indicators() -> list[dict[str, object]]:
    """返回所有可用指标的元数据。"""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "inputs": list(spec.inputs),
            "outputs": list(spec.outputs),
            "default_params": dict(spec.default_params),
        }
        for spec in _REGISTRY.values()
    ]


def compute_indicators(
    df: pd.DataFrame,
    indicators: list[str],
    params: dict[str, dict[str, int | float]] | None = None,
    keep_ohlcv: bool = True,
    tail: int | None = None,
) -> pd.DataFrame:
    """在 K 线 DataFrame 上计算指定技术指标。

    Args:
        df: K 线数据，需包含 open/close/high/low/vol 等列。
        indicators: 指标名称列表（不区分大小写），如 ``["MACD", "KDJ"]``。
        params: 可选参数覆盖，如 ``{"MACD": {"SHORT": 10}}``。
        keep_ohlcv: True 则保留原始 OHLCV 列。
        tail: 计算后仅保留最后 N 行。

    Returns:
        包含指标列的 DataFrame。
    """
    if df.empty:
        return pd.DataFrame(df.copy())

    params = params or {}
    result_parts: list[pd.DataFrame] = []
    required_inputs: set[str] = set()

    names_upper = [n.strip().upper() for n in indicators]
    unknown = [n for n in names_upper if n not in _REGISTRY]
    if unknown:
        raise ValueError(f"未知指标: {unknown}。可用指标: {sorted(_REGISTRY.keys())}")

    for name in names_upper:
        spec = _REGISTRY[name]
        required_inputs.update(spec.inputs)

    missing_cols = required_inputs - set(df.columns)
    if missing_cols:
        raise ValueError(f"DataFrame 缺少必要列: {missing_cols}。指标需要这些列: {required_inputs}")

    if len(df) < 120:
        warnings.warn(
            f"数据仅 {len(df)} 行，EMA 类指标至少需要 120 行才能精确收敛",
            stacklevel=2,
        )

    for name in names_upper:
        spec = _REGISTRY[name]
        inputs = tuple(df[col].values for col in spec.inputs)
        override = params.get(name, params.get(spec.name, {}))
        kwargs = {**spec.default_params, **override}
        raw = spec.func(*inputs, **kwargs)

        if isinstance(raw, tuple):
            arrays = raw
        else:
            arrays = (raw,)

        if len(arrays) != len(spec.outputs):
            raise RuntimeError(f"{name}: 预期 {len(spec.outputs)} 个输出，实际 {len(arrays)} 个")

        part = pd.DataFrame(
            {col: arr for col, arr in zip(spec.outputs, arrays)},
            index=df.index,
        )
        result_parts.append(part)

    indicator_df: pd.DataFrame = pd.concat(result_parts, axis=1)

    if keep_ohlcv:
        out: pd.DataFrame = pd.concat([df, indicator_df], axis=1)
    else:
        time_cols = [c for c in ("datetime", "date") if c in df.columns]
        out = pd.concat([df[time_cols], indicator_df], axis=1) if time_cols else indicator_df

    if tail is not None and tail > 0:
        out = out.iloc[-tail:]

    return pd.DataFrame(out.reset_index(drop=True))
