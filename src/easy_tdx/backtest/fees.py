"""品种感知费率模型（v1.24 新增）。

此前引擎的佣金/最低佣金/印花税是全局扁平参数，默认值按 A 股股票设定
（佣金万3 最低5元、印花税千1 卖方）。同一组默认值套到 ETF / 可转债 / B 股
上会**错收印花税**（ETF 与债券法定免印花税）、错用最低佣金，长期低估
高频/小资金策略的相对收益——对 ETF 轮动类策略影响尤其大。

本模块按证券代码 + 市场推断品种类型，给出保守的默认费率组合：

======== ============ ============ ============
品种      佣金率        最低佣金      印花税（卖方）
======== ============ ============ ============
股票      0.0003       5.0          0.001
ETF/LOF  0.0003       5.0          **0**
可转债    0.0002       1.0          **0**
B 股      0.0005       5.0          0.001
其他/指数  0.0003       5.0          0
======== ============ ============ ============

说明：
- 印花税差异是法定事实（ETF/债券免征），是本模块的核心价值；
- 佣金取常见券商的**保守**默认（不高估收益）。部分券商对 ETF「免五」、
  费率更低——用户仍可显式传 ``commission`` / ``min_commission`` 覆盖；
- 北交所股票按股票口径处理（经手费差异不建模）。

用法（引擎侧）::

    BacktestEngine(..., symbol="SH:510300", auto_fees=True)
    # → commission/stamp_tax 按 ETF 口径自动解析（显式传入的值优先）

市场代码兼容两种表示：``"SH"/"SZ"/"BJ"`` 字符串或通达信 int（0=深 1=沪 2=北）。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

__all__ = [
    "FeeModel",
    "InstrumentKind",
    "detect_instrument_kind",
    "resolve_fee_model",
]


class InstrumentKind(Enum):
    """证券品种类型（按代码前缀推断）。"""

    STOCK = "stock"  # A 股股票（含北交所）
    ETF = "etf"  # 场内交易型开放式指数基金
    LOF = "lof"  # 上市开放式基金 / 封闭基金
    BOND = "bond"  # 可转债
    B_SHARE = "b_share"  # B 股（沪 B 美元 / 深 B 港币）
    INDEX = "index"  # 指数（不可交易，按无印花税处理）
    OTHER = "other"


@dataclass(frozen=True)
class FeeModel:
    """一组费率参数（与引擎的 commission/min_commission/stamp_tax 一一对应）。"""

    kind: InstrumentKind
    commission: float
    min_commission: float
    stamp_tax: float


# 保守默认费率表（详见模块 docstring 的说明）
_FEE_TABLE: dict[InstrumentKind, tuple[float, float, float]] = {
    InstrumentKind.STOCK: (0.0003, 5.0, 0.001),
    InstrumentKind.ETF: (0.0003, 5.0, 0.0),
    InstrumentKind.LOF: (0.0003, 5.0, 0.0),
    InstrumentKind.BOND: (0.0002, 1.0, 0.0),
    InstrumentKind.B_SHARE: (0.0005, 5.0, 0.001),
    InstrumentKind.INDEX: (0.0003, 5.0, 0.0),
    InstrumentKind.OTHER: (0.0003, 5.0, 0.0),
}


def _norm_market(market: str | int | None) -> str | None:
    """市场代码归一化为 'SH'/'SZ'/'BJ'（未知返回 None）。"""
    if market is None:
        return None
    if isinstance(market, int):
        return {0: "SZ", 1: "SH", 2: "BJ"}.get(market)
    m = str(market).strip().upper()
    if m in ("SH", "SZ", "BJ", "SSE", "SZSE"):
        return "SH" if m in ("SH", "SSE") else ("SZ" if m in ("SZ", "SZSE") else "BJ")
    return None


def detect_instrument_kind(
    symbol_or_code: str,
    market: str | int | None = None,
) -> InstrumentKind:
    """按代码前缀（+市场）推断品种类型。

    Args:
        symbol_or_code: 6 位代码（``"510300"``）或带市场前缀
            （``"SH:510300"`` / ``"sh510300"``）。
        market: 市场代码（可选；symbol 自带前缀时被覆盖）。

    Returns:
        :class:`InstrumentKind`。无法识别时返回 OTHER（按无印花税保守处理）。
    """
    code = str(symbol_or_code).strip()
    mkt: str | None
    if ":" in code:
        prefix, code = code.split(":", 1)
        mkt = _norm_market(prefix)
    elif len(code) > 6 and code[:2].upper() in ("SH", "SZ", "BJ"):
        mkt = code[:2].upper()
        code = code[2:]
    else:
        mkt = _norm_market(market)
    code = code.strip()

    # 沪市：900 B股 / 60/68 股票 / 51 56 58 ETF / 50x LOF·封基 / 11x 可转债 / 000 880 指数
    if mkt == "SH":
        if code.startswith("900"):
            return InstrumentKind.B_SHARE
        if code.startswith(("60", "68")):
            return InstrumentKind.STOCK
        if code.startswith(("51", "56", "58")):
            return InstrumentKind.ETF
        if code.startswith("50"):
            return InstrumentKind.LOF
        if code.startswith("11"):
            return InstrumentKind.BOND
        if code.startswith(("000", "880", "881", "999")):
            return InstrumentKind.INDEX
        return InstrumentKind.OTHER
    # 深市：200 B股 / 00 30 股票 / 159 ETF / 16x LOF / 12x 可转债 / 399 指数
    if mkt == "SZ":
        if code.startswith("200"):
            return InstrumentKind.B_SHARE
        if code.startswith(("00", "30")):
            return InstrumentKind.STOCK
        if code.startswith("159"):
            return InstrumentKind.ETF
        if code.startswith("16"):
            return InstrumentKind.LOF
        if code.startswith("12"):
            return InstrumentKind.BOND
        if code.startswith("399"):
            return InstrumentKind.INDEX
        return InstrumentKind.OTHER
    # 北交所：全部按股票
    if mkt == "BJ":
        return InstrumentKind.STOCK
    # 市场未知：仅按代码粗判（沪深代码空间基本不重叠）
    if code.startswith(("51", "56", "58", "159")):
        return InstrumentKind.ETF
    if code.startswith(("900", "200")):
        return InstrumentKind.B_SHARE
    if code.startswith(("60", "68", "00", "30")):
        return InstrumentKind.STOCK
    return InstrumentKind.OTHER


def resolve_fee_model(
    symbol_or_code: str,
    market: str | int | None = None,
) -> FeeModel:
    """按标的解析默认费率组合。

    Args:
        symbol_or_code: 代码或带市场前缀的 symbol。
        market: 市场代码（可选）。

    Returns:
        :class:`FeeModel`（含品种类型 + 佣金/最低佣金/印花税）。
    """
    kind = detect_instrument_kind(symbol_or_code, market)
    commission, min_commission, stamp_tax = _FEE_TABLE[kind]
    return FeeModel(
        kind=kind,
        commission=commission,
        min_commission=min_commission,
        stamp_tax=stamp_tax,
    )
