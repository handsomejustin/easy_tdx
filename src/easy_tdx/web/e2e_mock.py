"""E2E 合成行情数据源（``EASY_TDX_E2E_MOCK=1`` 时由 serve 激活）。

**为什么在 FastAPI 层 mock 而不是用 Playwright ``page.route`` 拦截**：

1. 回测 / WF / 一条龙评估 / 自选 / 策略库全部走**真实后端代码路径**（纯计算 +
   SQLite CRUD，本来就不依赖行情连接），E2E 能捕获后端 schema 变更；route 拦截
   的静态 JSON 会与后端 schema 漂移，测试通过不代表系统可用。
2. SSE（``/stream/quotes``，EventSource）无法用 ``page.route`` 稳定 mock（需要
   流式 body）；mock 客户端让 QuoteStreamer 真正轮询合成数据，前端 SSE 链路
   （连接→首帧→快照渲染）也被覆盖。
3. 任务型端点（提交→task_id→轮询→done）在 route 拦截里要手写状态机，mock
   客户端天然支持。

代价：本模块必须与真实客户端的方法签名/返回列保持一致——由
``tests/unit/test_e2e_mock.py`` 与 E2E 套件本身共同守护。

数据特征：

- **确定性**：每个 (market, code) 用 CRC32 做随机种子，同一进程内多次调用、
  不同机器上跑 E2E，行情完全一致（回测结果可复现、断言可写死）。
- **锚定今天**：K 线序列以「今天」为最新一根（bdate_range），与前端默认日期
  范围（开始 2020-01-06 ~ 结束今天）自然咬合。
- **分页语义**与真实 /bars 一致：``start=0`` 返回最新 ``count`` 根（页内升序），
  ``start`` 递增向更早翻页（前端 fetchBars 依赖此语义拼接）。
"""

from __future__ import annotations

import logging
import time
import zlib
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

__all__ = ["MockTdxClient", "MockMacClient", "E2E_MOCK_ENV"]

#: 激活环境变量名（serve 启动时读取，见 web/app.py lifespan）。
E2E_MOCK_ENV = "EASY_TDX_E2E_MOCK"

# 合成 K 线总根数（约 10.4 年日线）。前端默认区间 2020-01-06 ~ 今天约 1660 根，
# 翻页上限 10×800；2600 根既覆盖默认区间，又让第 3 页就翻到数据起点。
_HISTORY_BARS = 2600

# 已知代码 → 中文名（提升 E2E 可读性；未命中用「股票XXXXXX」兜底）。
_KNOWN_NAMES: dict[str, str] = {
    "600519": "贵州茅台",
    "000001": "平安银行",
    "603986": "兆易创新",
    "600000": "浦发银行",
    "300750": "宁德时代",
    "000001|SH": "上证指数",
    "399001": "深证成指",
    "399006": "创业板指",
    "000688": "科创50",
    "000300": "沪深300",
}


def _market_str(market: Any) -> str:
    """任意市场表示（枚举/int/字符串）→ 规范字符串 SZ/SH/BJ。"""
    mapping = {
        "0": "SZ",
        "1": "SH",
        "2": "BJ",
        "MARKET.SZ": "SZ",
        "MARKET.SH": "SH",
        "MARKET.BJ": "BJ",
    }
    s = str(market).upper()
    return mapping.get(s, s)


def _seed(market: Any, code: str) -> int:
    """(market, code) → 确定性随机种子（CRC32）。"""
    return zlib.crc32(f"{_market_str(market)}{code}".encode())


def _display_name(market: Any, code: str) -> str:
    """代码 → 中文名。仅 SH 的 000001 有歧义（平安银行 vs 上证指数），用
    ``code|SH`` 键消歧；其余市场直接按代码查。"""
    if _market_str(market) == "SH" and f"{code}|SH" in _KNOWN_NAMES:
        return _KNOWN_NAMES[f"{code}|SH"]
    return _KNOWN_NAMES.get(code, f"股票{code}")


def _synth_closes(market: Any, code: str, n: int) -> np.ndarray:
    """生成 n 根确定性随机游走收盘价（指数基准价位 5~50 元）。"""
    rng = np.random.default_rng(_seed(market, code))
    base = 5.0 + rng.uniform(0.0, 45.0)
    rets = rng.normal(0.0004, 0.018, n)
    return base * np.cumprod(1.0 + rets)


def _synth_ohlcv(market: Any, code: str, n: int) -> pd.DataFrame:
    """生成 n 根升序 OHLCV 日线（datetime 为 pd.Timestamp，MAC 契约）。"""
    rng = np.random.default_rng(_seed(market, code))
    close = _synth_closes(market, code, n)
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1] * (1.0 + rng.normal(0.0, 0.004, n - 1))
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.006, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.006, n)))
    vol = rng.integers(50_000, 5_000_000, n).astype(np.float64)
    amount = vol * close * 100.0
    dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=n)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": amount,
        }
    )


def _page_bars(full: pd.DataFrame, start: int, count: int) -> pd.DataFrame:
    """按真实 /bars 分页语义切片：start=0 → 最新 count 根（页内升序）。"""
    n = len(full)
    lo = max(0, n - start - count)
    hi = n - start
    if hi <= 0 or lo >= n:
        return full.iloc[0:0]
    return full.iloc[lo:hi]


def _quote_dict(mkt_enum: Any, code: str) -> dict[str, Any]:
    """单标的五档快照（列集合对齐 quote_streamer._QUOTE_FIELDS 白名单）。"""
    closes = _synth_closes(market_enum_key(mkt_enum), code, 30)
    price = float(closes[-1])
    pre_close = float(closes[-2])
    rng = np.random.default_rng(_seed(market_enum_key(mkt_enum), code) ^ 0xBEEF)
    bid1 = round(price - 0.02, 2)
    ask1 = round(price + 0.02, 2)
    return {
        "market": mkt_enum,
        "code": code,
        "price": price,
        "pre_close": pre_close,
        "open": float(closes[-1]),
        "high": round(price * 1.01, 2),
        "low": round(price * 0.99, 2),
        "vol": float(rng.integers(10_000, 900_000)),
        "cur_vol": float(rng.integers(10, 900)),
        "amount": price * float(rng.integers(10_000, 900_000)) * 100.0,
        "s_vol": float(rng.integers(1000, 9000)),
        "b_vol": float(rng.integers(1000, 9000)),
        "rise_speed": round(float(rng.uniform(-1, 1)), 2),
        "limit_up": round(pre_close * 1.1, 2),
        "limit_down": round(pre_close * 0.9, 2),
        "decimal_point": 2,
        "server_time": "10:30:00",
        "trading_status": 0,
        **{f"bid{i}": round(bid1 - 0.01 * (i - 1), 2) for i in range(1, 6)},
        **{f"ask{i}": round(ask1 + 0.01 * (i - 1), 2) for i in range(1, 6)},
        **{f"bid_vol{i}": float(rng.integers(10, 500)) for i in range(1, 6)},
        **{f"ask_vol{i}": float(rng.integers(10, 500)) for i in range(1, 6)},
    }


def market_enum_key(mkt_enum: Any) -> str:
    """Market 枚举 → 种子用的字符串键（SZ/SH/BJ）。"""
    from easy_tdx.models.enums import Market

    return {Market.SZ: "SZ", Market.SH: "SH", Market.BJ: "BJ"}.get(mkt_enum, str(mkt_enum))


def _int_market_to_enum(value: int) -> Any:
    """int 市场 → Market 枚举（MAC 客户端约定 int）。"""
    from easy_tdx.models.enums import Market

    return {0: Market.SZ, 1: Market.SH, 2: Market.BJ}.get(int(value), Market.SZ)


class MockTdxClient:
    """AsyncTdxClient 的合成数据替身（覆盖 web 路由用到的方法）。"""

    async def close(self) -> None:
        """lifespan 关闭时调用（无真实连接，空操作）。"""

    async def get_security_bars(
        self,
        market: Any,
        code: str,
        category: Any,
        start: int = 0,
        count: int = 800,
        *,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """个股 K 线（/bars 回退路径，MAC 可用时不会走到）。"""
        df = _page_bars(_synth_ohlcv(market_enum_key(market), code, _HISTORY_BARS), start, count)
        daily = _is_daily_category(category)
        return _bars_to_legacy_cols(df, daily)

    async def get_index_bars(
        self,
        market: Any,
        code: str,
        category: Any,
        start: int = 0,
        count: int = 800,
        *,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """指数 K 线（/bars/index，看板迷你 K 线与情绪雷达数据源）。"""
        df = _page_bars(_synth_ohlcv(market_enum_key(market), code, _HISTORY_BARS), start, count)
        return _bars_to_legacy_cols(df, _is_daily_category(category))

    async def get_minute_time_data(self, market: Any, code: str) -> pd.DataFrame:
        """今日分时（240 点：价格围绕昨收随机游走 + 每分钟量）。"""
        rng = np.random.default_rng(_seed(market_enum_key(market), code) ^ 0xCAFE)
        pre_close = float(_synth_closes(market_enum_key(market), code, 30)[-2])
        prices = pre_close * np.cumprod(1.0 + rng.normal(0.0, 0.0015, 240))
        t0 = datetime.now().replace(hour=9, minute=30, second=0, microsecond=0)
        times = [t0 + timedelta(minutes=i) for i in range(240)]
        return pd.DataFrame(
            {
                "datetime": [t.strftime("%H:%M") for t in times],
                "price": prices,
                "vol": rng.integers(100, 9000, 240).astype(float),
            }
        )

    async def get_security_quotes(self, stocks: list[tuple[Any, str]]) -> pd.DataFrame:
        """批量五档快照（POST /quotes + QuoteStreamer SSE 共用）。"""
        return pd.DataFrame([_quote_dict(m, c) for m, c in stocks])

    async def get_market_stat(self) -> pd.DataFrame:
        """全市场涨跌统计（看板「市场统计」卡，单行 df）。"""
        rng = np.random.default_rng(20260901)
        up = int(rng.integers(1800, 2800))
        down = int(rng.integers(1800, 2800))
        return pd.DataFrame(
            [
                {
                    "up_count": up,
                    "down_count": down,
                    "neutral_count": int(rng.integers(100, 300)),
                    "suspended_count": int(rng.integers(10, 60)),
                    "total_count": up + down + 300,
                    "total_amount": float(rng.uniform(7e11, 1.1e12)),
                    "total_volume": float(rng.uniform(6e11, 9e11)),
                    "total_market_cap": float(rng.uniform(6e13, 8.5e13)),
                    "limit_up_count": int(rng.integers(30, 80)),
                    "limit_down_count": int(rng.integers(5, 40)),
                }
            ]
        )

    async def get_transaction_data(
        self, market: Any, code: str, start: int = 0, count: int = 800
    ) -> pd.DataFrame:
        """当日逐笔（个股弹窗用；简化为合成 tick 序列）。"""
        rng = np.random.default_rng(_seed(market_enum_key(market), code) ^ 0x7777)
        closes = _synth_closes(market_enum_key(market), code, 30)
        n = max(1, min(count, 200))
        return pd.DataFrame(
            {
                "time": [f"10:{i % 60:02d}" for i in range(n)],
                "price": closes[-1] * (1.0 + rng.normal(0.0, 0.002, n)),
                "vol": rng.integers(1, 500, n).astype(float),
                "buyorsell": rng.integers(0, 2, n).astype(int),
            }
        )


class MockMacClient:
    """AsyncMacClient 的合成数据替身（覆盖 web 路由用到的方法）。"""

    async def close(self) -> None:
        """lifespan 关闭时调用（无真实连接，空操作）。"""

    async def get_stock_quotes(
        self, stocks: list[tuple[int, str]], fields: Any = None
    ) -> pd.DataFrame:
        """批量五档快照（RealtimeStreamHub → RealtimeDataFeed 的轮询入口）。

        与 feed._row_to_event 的取数口径对齐：最新价落在 close 列、
        market 为 int；价格在合成序列上随每次调用轻微漂移（绕过 feed 去重，
        让 WS/E2E 在盘外也能持续看到推送帧）。
        """
        rows = []
        for market, code in stocks:
            closes = _synth_closes(market_enum_key(_int_market_to_enum(int(market))), code, 30)
            jitter = 1.0 + ((time.time() % 60.0) / 60.0 - 0.5) * 0.002
            price = float(closes[-1]) * jitter
            rows.append(
                {
                    "market": int(market),
                    "code": code,
                    "close": price,
                    "vol": 100_000.0 + (time.time() % 60.0) * 10.0,
                    "open": float(closes[-1]),
                    "high": price * 1.005,
                    "low": price * 0.995,
                    "pre_close": float(closes[-2]),
                    "amount": price * 100_000.0,
                    "name": _display_name(market, code),
                }
            )
        return pd.DataFrame(rows)

    async def get_stock_kline(
        self,
        market: Any,
        code: str,
        period: Any,
        start: int = 0,
        count: int = 800,
        times: int = 1,
        *,
        adjust: Any = None,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """个股 K 线（/bars 主路径）。market 为 int（MAC 协议约定）。

        返回 MAC 契约列：datetime（含 00:00 时分）+ OHLC + vol/amount +
        float_shares（会被 bars 路由的 _normalize_mac_df 丢弃/规整）。
        """
        df = _page_bars(
            _synth_ohlcv(market_enum_key(_int_market_to_enum(int(market))), code, _HISTORY_BARS),
            start,
            count,
        )
        out = df.copy()
        out["float_shares"] = 1.5e9
        return out

    async def get_symbol_info(self, *, market: Any, code: str) -> pd.DataFrame:
        """证券名称快照（/mac/symbol-info，自选补名用）。"""
        return pd.DataFrame(
            [{"market": int(market), "code": code, "name": _display_name(market, code)}]
        )

    async def get_stock_quotes_list(
        self,
        *,
        category: Any = None,
        start: int = 0,
        count: int = 80,
        sort_type: Any = None,
        sort_order: Any = None,
        exclude_flags: Any = None,
    ) -> pd.DataFrame:
        """排行行情（/mac/quote-list，看板涨跌榜/分布懒加载）。

        固定 40 只合成标的，按 close/pre_close 排序返回 count 根（封顶 200，
        避免分布懒加载的 3000 只请求生成过大 df）。
        """
        rng = np.random.default_rng(0xE2E5)
        n = 40
        codes = [f"6{i:05d}" for i in range(n // 2)] + [f"0{i:05d}" for i in range(n - n // 2)]
        rows = []
        for i, code in enumerate(codes):
            closes = _synth_closes("SH" if code.startswith("6") else "SZ", code, 30)
            rows.append(
                {
                    "market": 1 if code.startswith("6") else 0,
                    "code": code,
                    "name": _display_name("SH" if code.startswith("6") else "SZ", code),
                    "close": float(closes[-1]),
                    "pre_close": float(closes[-2]),
                    "vol": float(rng.integers(10_000, 900_000)),
                    "amount": float(closes[-1]) * float(rng.integers(10_000, 900_000)),
                    "turnover_rate": round(float(rng.uniform(0.1, 25.0)), 2),
                }
            )
        df = pd.DataFrame(rows)
        df["_pct"] = df["close"] / df["pre_close"] - 1.0
        df = df.sort_values("_pct", ascending=(str(sort_order).upper() == "ASC"))
        df = df.drop(columns=["_pct"]).iloc[start : start + min(count, 200)]
        return df.reset_index(drop=True)

    async def get_board_list(
        self, *, board_type: Any = None, count: int = 500, sort_column: Any = None
    ) -> pd.DataFrame:
        """板块列表（/board-mac/list，看板行业/概念热度榜）。"""
        rng = np.random.default_rng(0xB0AD)
        names = [
            "银行",
            "证券",
            "半导体",
            "白酒",
            "新能源车",
            "光伏",
            "军工",
            "医药",
            "房地产",
            "煤炭",
            "钢铁",
            "传媒",
            "计算机",
            "通信",
            "家电",
            "食品饮料",
        ]
        rows = []
        for i, name in enumerate(names):
            closes = _synth_closes("BOARD", name, 30)
            rows.append(
                {
                    "code": f"8810{i % 10}{i:02d}",
                    "name": name,
                    "price": float(closes[-1]),
                    "pre_close": float(closes[-2]),
                    "sort_value": float(rng.uniform(-5, 5)),
                }
            )
        df = pd.DataFrame(rows)
        df["_pct"] = df["price"] / df["pre_close"] - 1.0
        df = df.sort_values("_pct", ascending=False).drop(columns=["_pct"])
        return df.head(min(count, len(df))).reset_index(drop=True)

    async def get_board_members(
        self, *, board_symbol: str, count: int = 100, sort_type: Any = None, sort_order: Any = None
    ) -> pd.DataFrame:
        """板块成分股（板块弹窗）。"""
        return await self.get_stock_quotes_list(
            count=count, sort_type=sort_type, sort_order=sort_order
        )

    async def get_belong_board(self, *, market: Any, code: str) -> pd.DataFrame:
        """个股所属板块（个股弹窗）。"""
        return pd.DataFrame(
            [
                {"code": "881001", "name": "银行"},
                {"code": "881101", "name": "上证主力"},
            ]
        )

    async def get_unusual(
        self, *, market: Any = None, start: int = 0, count: int = 50
    ) -> pd.DataFrame:
        """市场异动流（看板异动雷达）。"""
        rng = np.random.default_rng(_seed("UNUSUAL", str(market)) ^ 0x5EED)
        descs = ["火箭发射", "大笔买入", "封涨停板", "打开跌停板", "快速反弹", "有大买盘"]
        rows = []
        for i in range(min(count, 12)):
            mkt_int = int(market) if market is not None else 1
            prefix = "6" if mkt_int == 1 else "0"  # SH→6 开头，SZ→0 开头
            code = f"{prefix}{int(rng.integers(0, 99999)):05d}"
            hh = 9 + int(i / 12 * 6)
            mm = int(rng.integers(0, 60))
            rows.append(
                {
                    "time": f"{hh:02d}:{mm:02d}:{int(rng.integers(0, 60)):02d}",
                    "code": code,
                    "name": _display_name(market, code),
                    "desc": str(rng.choice(descs)),
                    "value": f"+{rng.uniform(2, 11):.1f}%",
                }
            )
        return pd.DataFrame(rows)


# ── 内部辅助 ─────────────────────────────────────────────────────────────────


def _is_daily_category(category: Any) -> bool:
    """日线及以上周期 → True（复用 bars 路由的判定口径）。"""
    from easy_tdx._df import _category_to_minutes

    return _category_to_minutes(int(category)) is None


def _bars_to_legacy_cols(df: pd.DataFrame, daily: bool) -> pd.DataFrame:
    """把内部 datetime OHLCV 规整为旧 /bars 契约（日线 date / 分钟 datetime）。"""
    if df.empty:
        return df
    out = df.copy()
    col = "date" if daily else "datetime"
    if daily:
        out["datetime"] = pd.to_datetime(out["datetime"]).dt.strftime("%Y-%m-%d")
    else:
        out["datetime"] = pd.to_datetime(out["datetime"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    return out.rename(columns={"datetime": col})


def is_e2e_mock_enabled() -> bool:
    """当前进程是否处于 E2E mock 模式。"""
    import os

    return os.environ.get(E2E_MOCK_ENV) == "1"


def log_mock_banner() -> None:
    """serve 启动时打一行显式提示（避免误把 mock 数据当真实行情）。"""
    logger.warning(
        "[E2E-MOCK] EASY_TDX_E2E_MOCK=1 — 行情接口返回合成数据（仅限 Playwright E2E 使用）"
    )
