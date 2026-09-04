"""baostock 自动兜底数据源（仅日线及以上，TDX 全部路径失败时的最后一级回退）。

定位与边界：
- baostock 是 EOD 数据源，当日数据约 17:30 后才可查，**盘中实时能力为零**；
  因此本模块只承接 DAY/WEEK/MONTH 的历史 K 线，分钟线/分时/逐笔/板块/实时
  报价一律返回不可用（None），由上层维持原错误。
- 启用条件自动判断：已安装 baostock 且未设置环境变量 ``EASY_TDX_BAOSTOCK=0``
  即启用；未安装时本模块整体静默关闭，核心功能零影响。
- baostock 客户端是单条全局连接且非线程安全，本模块内部全程持锁串行，
  供 async 调用方经 ``asyncio.to_thread`` 使用。
- 数据口径：volume 为股（与 /bars 输出契约一致，无需换算）；停牌日
  （tradestatus=0 或 volume=0）剔除，与通达信 K 线不含停牌日的口径对齐；
  复权经 adjustflag 原生支持（QFQ/HFQ/NONE），North Exchange（BJ）不覆盖。
"""

from __future__ import annotations

import importlib
import os
import threading
from datetime import datetime, timedelta

import pandas as pd

BAOSTOCK_DISABLE_ENV = "EASY_TDX_BAOSTOCK"

# baostock 的全局连接锁（该库单连接、非线程安全）
_bs_lock = threading.Lock()
_logged_in = False
# 兜底路径的锁等待上限：拿不到锁说明另一个兜底请求正在进行，
# 与其排队不如放弃本次兜底（回退路径宁快勿堵）。
_LOCK_TIMEOUT_SECONDS = 30.0

# 支持兜底的周期（baostock frequency）：日线及以上；分钟线/季年线不兜
_FREQ_BY_CATEGORY: dict[str, str] = {"DAY": "d", "WEEK": "w", "MONTH": "m"}
# 复权映射：baostock adjustflag — 1=后复权 2=前复权 3=不复权
_ADJUST_FLAG = {"NONE": "3", "QFQ": "2", "HFQ": "1"}
_MARKET_PREFIX = {"SZ": "sz", "SH": "sh"}  # BJ baostock 不覆盖

# 拉取窗口的日历天数系数（start+count 根 × 周期占的日历天 + 节假日缓冲）
_WINDOW_DAYS = {"d": (1.6, 30), "w": (7.2, 40), "m": (32.0, 100)}
# 偏移窗口规模上限（/bars 的 start 无上界，防极端参数把兜底源拖死）
_MAX_TOTAL_BARS = 10_000


def is_enabled() -> bool:
    """自动判断兜底是否可用：未禁用（环境变量）且 baostock 已安装。"""
    disabled = os.environ.get(BAOSTOCK_DISABLE_ENV, "").strip().lower() in {"0", "false", "off"}
    if disabled:
        return False
    try:
        importlib.import_module("baostock")
    except ImportError:
        return False
    return True


def _login_if_needed(bs: object) -> None:
    """确保 baostock 已登录（匿名账户；调用方需已持有 _bs_lock）。"""
    global _logged_in
    if _logged_in:
        return
    lg = bs.login()  # type: ignore[attr-defined]
    error_code = str(getattr(lg, "error_code", ""))
    if error_code != "0":
        raise RuntimeError(f"baostock 登录失败: {getattr(lg, 'error_msg', error_code)}")
    _logged_in = True


def _query_rows(bs: object, **kwargs: str) -> list[list[str]]:
    """执行 query_history_k_data_plus 并取回全部行（调用方需已持锁）。"""
    rs = bs.query_history_k_data_plus(**kwargs)  # type: ignore[attr-defined]
    if str(getattr(rs, "error_code", "")) != "0":
        raise RuntimeError(f"baostock 查询失败: {getattr(rs, 'error_msg', '')}")
    rows: list[list[str]] = []
    while rs.next() or False:
        rows.append(rs.get_row_data())
    return rows


def fetch_bars(
    market: str,
    code: str,
    category: str,
    start: int,
    count: int,
    adjust: str,
) -> pd.DataFrame | None:
    """拉取日线及以上 K 线，输出对齐 /bars 契约的 DataFrame。

    Args:
        market: "SZ" / "SH"（BJ 不支持，返回 None）。
        code: 6 位代码。
        category: 周期名（DAY/WEEK/MONTH 之外返回 None）。
        start: 跳过最新 start 根（与 TDX offset 语义一致）。
        count: 最多返回 count 根。
        adjust: "NONE" / "QFQ" / "HFQ"。

    Returns:
        按 [date, open, close, high, low, vol, amount] 列序、时间升序的
        DataFrame；兜底不可用 / 不适用 / 无数据时返回 None（调用方继续
        维持原错误，不吞异常）。
    """
    global _logged_in
    if not is_enabled():
        return None
    prefix = _MARKET_PREFIX.get(market.upper())
    frequency = _FREQ_BY_CATEGORY.get(category.upper())
    adjustflag = _ADJUST_FLAG.get(adjust.upper())
    if prefix is None or frequency is None or adjustflag is None:
        return None

    total = start + count
    if total <= 0 or total > _MAX_TOTAL_BARS:
        return None
    coef, buffer_days = _WINDOW_DAYS[frequency]
    end_date = datetime.now()
    start_date = end_date - timedelta(days=total * coef + buffer_days)

    # baostock 全局单连接：持锁串行；等待超时则放弃本次兜底
    if not _bs_lock.acquire(timeout=_LOCK_TIMEOUT_SECONDS):
        return None
    try:
        bs = importlib.import_module("baostock")
        try:
            _login_if_needed(bs)
            rows = _query_rows(
                bs,
                code=f"{prefix}.{code}",
                fields="date,open,high,low,close,volume,amount,tradestatus",
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                frequency=frequency,
                adjustflag=adjustflag,
            )
        except Exception:
            # 连接可能中途断开：重置登录态，下次兜底重新登录
            _logged_in = False
            raise
    except Exception:
        # 兜底源自身的任何失败都不向上抛：调用方按"无兜底数据"处理
        return None
    finally:
        _bs_lock.release()

    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["date", "open", "high", "low", "close", "vol", "amount", "tradestatus"]
    )
    for col in ("open", "high", "low", "close", "vol", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # 停牌日剔除（tradestatus=0 或无成交），对齐通达信 K 线不含停牌日的口径
    if "tradestatus" in df.columns:
        df = df[df["tradestatus"] != "0"]
    df = df.dropna(subset=["close"])
    df = df[df["close"] > 0]
    df = df[df["vol"] > 0]
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()

    # TDX offset 语义：跳过最新 start 根，再取至多 count 根（时间升序）
    end_pos = len(df) - start
    if end_pos <= 0:
        return None
    df = df.iloc[max(0, end_pos - count) : end_pos]
    if df.empty:
        return None

    return df[["date", "open", "close", "high", "low", "vol", "amount"]].reset_index(drop=True)
