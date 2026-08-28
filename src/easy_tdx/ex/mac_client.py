"""MAC 协议扩展市场高层 API：MacExClient（同步）和 AsyncMacExClient（asyncio）。

期货/港股/美股等扩展市场通过 MAC 协议命令（0x122B/0x122E/0x122D/0x122F/0x2562）
获取数据，使用 ExTdxConnection（端口 7727，单包握手）。
"""

import asyncio
import logging
import time
from collections.abc import Awaitable
from datetime import date
from types import TracebackType
from typing import Any, TypeVar

import pandas as pd

from .._df import _to_df
from .._health import record_failure, record_success
from .._reconnect import (
    _RETRY_DELAYS,
    AsyncHeartbeatMixin,
    select_best_host_async,
    select_best_host_sync,
)
from ..commands.base import BaseCommand
from ..config import get_best_mac_ex_host, get_mac_ex_hosts, save_best_mac_ex_host
from ..exceptions import TdxConnectionError
from ..mac.commands.chart_sampling import ChartSamplingCmd
from ..mac.commands.symbol_bar import SymbolBarCmd
from ..mac.commands.symbol_quotes import SymbolQuotesCmd
from ..mac.commands.symbol_tick_chart import SymbolTickChartCmd
from ..mac.commands.symbol_transaction import SymbolTransactionCmd
from ..mac.enums import Adjust, Period, SortOrder, SortType
from ..mac.models import MacQuoteField
from ._hk_transaction import (
    _fetch_all_hk_transactions_async,
    _fetch_all_hk_transactions_sync,
    _fetch_hk_transactions_async,
    _fetch_hk_transactions_sync,
    is_hk_stock_market,
)
from .commands.get_instrument_count import GetExInstrumentCountCmd
from .commands.get_instrument_info import GetExInstrumentInfoCmd
from .commands.login import MacExLoginCmd
from .transport.async_ import AsyncExTdxConnection
from .transport.sync import ExTdxConnection, ping_ex_all

_DEFAULT_PORT = 7727
_T = TypeVar("_T")

logger = logging.getLogger(__name__)


def _coerce_query_date(query_date: int | date | None) -> date | None:
    """把查询日期统一为 date 对象。

    兼容两种调用方式（与 A 股 MacClient.get_tick_chart 的 YYYYMMDD 整数
    语义保持一致）：int 视为 YYYYMMDD，date 原样透传，None 表示今天。
    """
    if query_date is None or isinstance(query_date, date):
        return query_date
    return date(query_date // 10000, (query_date % 10000) // 100, query_date % 100)


def _quotes_to_df(result: list[MacQuoteField]) -> pd.DataFrame:
    """将 MacQuoteField 列表展开为 DataFrame。"""
    rows: list[dict[str, Any]] = []
    for item in result:
        row: dict[str, Any] = {"market": item.market, "code": item.code, "name": item.name}
        row.update(item.fields)
        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ============================================================
# 同步客户端
# ============================================================


class MacExClient:
    """同步 MAC 协议扩展市场客户端（期货/港股/美股，端口 7727）。

    使用示例::

        with MacExClient() as c:
            df = c.goods_kline(ExMarket.CFFEX_FUTURES, "IFL0", Period.DAILY)
            df = c.goods_quotes([(ExMarket.HK_MAIN_BOARD, "00700")])
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = _DEFAULT_PORT,
        timeout: float = 15.0,
        auto_reconnect: bool = True,
    ) -> None:
        self._host = host if host is not None else get_best_mac_ex_host()
        self._port = port
        self._timeout = timeout
        self._auto_reconnect = auto_reconnect
        self._conn = ExTdxConnection(self._host, port, timeout, mac_ex_mode=True)

    @classmethod
    def from_best_host(
        cls,
        hosts: list[str] | None = None,
        port: int = _DEFAULT_PORT,
        timeout: float = 15.0,
        ping_timeout: float = 5.0,
        auto_reconnect: bool = True,
    ) -> "MacExClient":
        """测量所有 MAC 扩展行情服务器延迟，选最低延迟建立连接。"""
        candidates = hosts or get_mac_ex_hosts()
        ranked = ping_ex_all(candidates, port, ping_timeout)
        best = ranked[0][0] if ranked else candidates[0]
        save_best_mac_ex_host(best)
        return cls(best, port, timeout, auto_reconnect)

    @staticmethod
    def ping_all(
        hosts: list[str] | None = None,
        port: int = _DEFAULT_PORT,
        timeout: float = 5.0,
    ) -> list[tuple[str, float]]:
        return ping_ex_all(hosts or get_mac_ex_hosts(), port, timeout)

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._conn.connect()
        self._login()

    def close(self) -> None:
        self._conn.close()

    def disconnect(self) -> None:
        self.close()

    def ensure_connected(self) -> None:
        """验证连接存活，断线则自动重建。"""
        try:
            self._execute(GetExInstrumentCountCmd())
        except TdxConnectionError:
            self._conn.close()
            self._conn = ExTdxConnection(self._host, self._port, self._timeout, mac_ex_mode=True)
            self._conn.connect()
            self._login()

    def __enter__(self) -> "MacExClient":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    def _login(self) -> None:
        """执行 MAC EX 登录命令。"""
        self._conn.execute(MacExLoginCmd())

    def _execute(self, cmd: "BaseCommand[_T]") -> _T:
        """执行命令；断线时指数退避重试，同主机耗尽则跨主机故障转移。

        每次重连后必须重新 ``_login()``（MAC 协议扩展行情特有）。登录握手期的
        ``TdxConnectionError`` 与业务请求一样计入退避重试；``TdxCommandError``
        （登录被拒等确定性失败）不重试，直接抛出。跨主机故障转移阶段同样遵循
        ``connect + login`` 纳入重试的语义。

        健康分联动与 A 股 client 一致（成功记 success、连接失败记 failure）。
        """
        try:
            result = self._conn.execute(cmd)
        except TdxConnectionError:
            if not self._auto_reconnect:
                raise
            record_failure(self._host)
            last_exc: TdxConnectionError | None = None
            for delay in _RETRY_DELAYS:
                time.sleep(delay)
                self._conn.close()
                self._conn = ExTdxConnection(
                    self._host, self._port, self._timeout, mac_ex_mode=True
                )
                # connect + login 纳入重试：登录握手期连接再次断开属可重试语义。
                try:
                    self._conn.connect()
                    self._login()
                    result = self._conn.execute(cmd)
                    record_success(self._host)
                    return result
                except TdxConnectionError as e:
                    last_exc = e
                    record_failure(self._host)
            # 第二阶段：跨主机故障转移——测速切到另一台 MAC 扩展行情服务器
            new_host = select_best_host_sync(
                get_mac_ex_hosts(),
                ping_ex_all,
                save_best_mac_ex_host,
                self._port,
                5.0,
                self._host,
            )
            if new_host is not None:
                self._host = new_host
                self._conn.close()
                self._conn = ExTdxConnection(
                    self._host, self._port, self._timeout, mac_ex_mode=True
                )
                try:
                    self._conn.connect()
                    self._login()
                    result = self._conn.execute(cmd)
                    record_success(self._host)
                    return result
                except TdxConnectionError as e:
                    last_exc = e
                    record_failure(self._host)
            raise last_exc  # type: ignore[misc]
        else:
            record_success(self._host)
            return result

    # ------------------------------------------------------------------ #
    # 商品列表
    # ------------------------------------------------------------------ #

    def goods_count(self, market: int | None = None) -> int:
        """获取商品总数。market=None 时返回全市场总数，否则返回指定市场的数量。"""
        if market is None:
            return self._execute(GetExInstrumentCountCmd())
        # 需要二分查找定位市场边界来计数
        offset = self._find_market_offset(market)
        if offset < 0:
            return 0
        total = self._execute(GetExInstrumentCountCmd())
        # 从 offset 开始扫描计数
        n = 0
        page = 1000
        pos = offset
        while pos < total:
            batch = self._execute(GetExInstrumentInfoCmd(start=pos, count=page))
            if not batch:
                break
            for item in batch:
                if item.market == market:
                    n += 1
                elif item.market > market:
                    return n
            pos += page
        return n

    def goods_list(self, market: int, start: int = 0, count: int = 600) -> pd.DataFrame:
        """获取扩展市场商品列表（期货合约/港股/美股等）。

        通过 EX 协议的 GetInstrumentInfo 命令获取，按 market 过滤。

        Parameters
        ----------
        market : int
            ExMarket 枚举值，如 ExMarket.HK_MAIN_BOARD。
        start : int
            市场内起始偏移。
        count : int
            请求数量。
        """
        offset = self._find_market_offset(market)
        if offset < 0:
            return pd.DataFrame()
        total = self._execute(GetExInstrumentCountCmd())
        page_size = 1000
        collected: list[Any] = []
        skipped = 0
        pos = offset
        while pos < total and len(collected) < count:
            batch = self._execute(GetExInstrumentInfoCmd(start=pos, count=page_size))
            if not batch:
                break
            for item in batch:
                if item.market == market:
                    if skipped < start:
                        skipped += 1
                    else:
                        collected.append(item)
                        if len(collected) >= count:
                            break
                elif item.market > market:
                    break
            else:
                pos += page_size
                continue
            break
        return _to_df(collected)

    def _find_market_offset(self, market: int) -> int:
        """二分查找定位指定市场在全局商品列表中的起始偏移。"""
        total = self._execute(GetExInstrumentCountCmd())
        if total == 0:
            return -1
        lo, hi = 0, total
        while lo < hi:
            mid = (lo + hi) // 2
            items = self._execute(GetExInstrumentInfoCmd(start=mid, count=1))
            if not items:
                hi = mid
                continue
            m = items[0].market
            if m < market:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # ------------------------------------------------------------------ #
    # 行情
    # ------------------------------------------------------------------ #

    def goods_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: Any = None,
    ) -> pd.DataFrame:
        """批量获取扩展市场自定义字段报价。

        Parameters
        ----------
        stocks : list[tuple[int, str]]
            [(ExMarketcode, code), ...] 列表，最多 80 只。
        fields : Fields | None
            字段选择，默认 PresetField.COMMON。
        """
        cmd = SymbolQuotesCmd(stocks, fields)
        result: list[MacQuoteField] = self._execute(cmd)
        return _quotes_to_df(result)

    def goods_quotes_list(
        self,
        market: int,
        start: int = 0,
        count: int = 100,
        sort_type: SortType = SortType.CODE,
        sort_order: SortOrder = SortOrder.NONE,
    ) -> pd.DataFrame:
        """获取扩展市场排序报价列表（通过 GoodsList + Quotes 组合）。

        先获取商品列表，再批量查询报价。

        Parameters
        ----------
        market : int
            ExMarket 枚举值。
        start : int
            起始偏移。
        count : int
            返回条数（最大 80，受报价批量限制）。
        sort_type : SortType
            排序字段（暂未实现排序，预留接口）。
        sort_order : SortOrder
            排序方向（暂未实现排序，预留接口）。
        """
        page_size = min(count, 80)
        items_df = self.goods_list(market, start=start, count=page_size)
        if items_df.empty:
            return pd.DataFrame()
        stocks: list[tuple[int, str]] = []
        for _, row in items_df.iterrows():
            stocks.append((market, row["code"]))
        cmd = SymbolQuotesCmd(stocks)
        result: list[MacQuoteField] = self._execute(cmd)
        return _quotes_to_df(result)

    def goods_kline(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        start: int = 0,
        count: int = 800,
        adjust: Adjust = Adjust.NONE,
    ) -> pd.DataFrame:
        """获取扩展市场 K 线数据（支持复权）。

        Parameters
        ----------
        market : int
            ExMarket 枚举值。
        code : str
            证券代码。
        period : Period
            K 线周期。
        start : int
            起始偏移（0=最新）。
        count : int
            返回条数。
        adjust : Adjust
            复权方式（NONE/QFQ/HFQ）。
        """
        cmd = SymbolBarCmd(
            market=market,
            code=code,
            period=period,
            start=start,
            count=count,
            fq=adjust,
        )
        result = self._execute(cmd)
        return _to_df(result)

    # ------------------------------------------------------------------ #
    # 分时
    # ------------------------------------------------------------------ #

    def goods_tick_chart(
        self,
        market: int,
        code: str,
        query_date: int | date | None = None,
    ) -> pd.DataFrame:
        """获取单日分时图。

        Parameters
        ----------
        market : int
            ExMarket 枚举值。
        code : str
            证券代码。
        query_date : int | date | None
            查询日期：date 对象或 YYYYMMDD 整数，None 表示今天。
        """
        cmd = SymbolTickChartCmd(
            market=market, code=code, query_date=_coerce_query_date(query_date)
        )
        result = self._execute(cmd)
        return _to_df(result)

    def goods_chart_sampling(
        self,
        market: int,
        code: str,
    ) -> pd.DataFrame:
        """获取分时缩略采样价格点（约 240 个点）。

        Parameters
        ----------
        market : int
            ExMarket 枚举值。
        code : str
            证券代码。
        """
        cmd = ChartSamplingCmd(market=market, code=code)
        prices: list[float] = self._execute(cmd)
        if not prices:
            return pd.DataFrame()
        return pd.DataFrame({"price": prices})

    # ------------------------------------------------------------------ #
    # 成交
    # ------------------------------------------------------------------ #

    def goods_transaction(
        self,
        market: int,
        code: str,
        query_date: int | date | None = None,
        start: int = 0,
        count: int = 2000,
    ) -> pd.DataFrame:
        """获取逐笔成交数据。

        Parameters
        ----------
        market : int
            ExMarket 枚举值。
        code : str
            证券代码。
        query_date : date | None
            查询日期，None 表示今天。
        start : int
            起始偏移。**注意：通达信逐笔协议为倒序**——``start=0`` 指向最新一笔
            （收盘方向），``start`` 越大越早。A 股 0x122F 与港股 ex 协议语义一致。
        count : int
            返回条数。港股单日成交常达数万笔（如 02715 约 1.3 万笔/日），默认
            ``count=2000`` 只取最近 2000 笔，会集中在尾盘时段。若需全天全部成交，
            请改用 :meth:`goods_transaction_all`。

        Note
        ----
        港股股票类市场（HK_MAIN_BOARD/HK_GEM/HK_INDEX/HK_FUND/HK_STOCK_GGT/HK_DARK_POOL，
        见 :data:`easy_tdx.ex._hk_transaction.HK_STOCK_MARKETS`）走 ex 扩展行情协议
        （当日 0x23FC / 历史 0x2406），返回价格单位为港元（浮点）。其余扩展市场
        （美股 / 期货等）走 MAC 协议 0x122F。原因：0x122F 的数据源未接入港股，
        对港股请求会返回空（issue #14）。不确定市场归属时，可先用
        :meth:`goods_kline` 探测哪个 market 能取到 K 线。
        """
        if is_hk_stock_market(market):
            result = _fetch_hk_transactions_sync(
                self._execute, market, code, _coerce_query_date(query_date), start, count
            )
            return _to_df(result)
        cmd = SymbolTransactionCmd(
            market=market,
            code=code,
            query_date=_coerce_query_date(query_date),
            start=start,
            count=count,
        )
        result = self._execute(cmd)
        return _to_df(result)

    def goods_transaction_all(
        self,
        market: int,
        code: str,
        query_date: date | None = None,
    ) -> pd.DataFrame:
        """获取港股某日**全部**逐笔成交（仅港股股票类市场，自动翻页取全天）。

        与 :meth:`goods_transaction` 的区别：不受 ``count`` 上限约束，自动翻页直至
        末页，返回当日所有逐笔成交（港股单日常 1~5 万笔）。返回顺序仍为协议原生
        倒序（最新在前）；如需正序展示，调用方自行 ``df.iloc[::-1]`` 反转。

        Parameters
        ----------
        market : int
            ExMarket 枚举值（须为港股股票类市场，见
            :data:`easy_tdx.ex._hk_transaction.HK_STOCK_MARKETS`）。
        code : str
            证券代码。
        query_date : date | None
            查询日期，None 表示今天。

        Raises
        ------
        ValueError
            ``market`` 不属于港股股票类市场时抛出（本方法专为港股设计；其他扩展
            市场请用 :meth:`goods_transaction`）。
        """
        if not is_hk_stock_market(market):
            raise ValueError(
                f"goods_transaction_all 仅支持港股股票类市场（HK_STOCK_MARKETS），"
                f"收到 market={market}；其他市场请用 goods_transaction。"
            )
        result = _fetch_all_hk_transactions_sync(self._execute, market, code, query_date)
        return _to_df(result)


# ============================================================
# 异步客户端
# ============================================================


class AsyncMacExClient(AsyncHeartbeatMixin):
    """异步 MAC 协议扩展市场客户端（asyncio，端口 7727）。

    使用示例::

        async with AsyncMacExClient() as c:
            df = await c.goods_kline(ExMarket.CFFEX_FUTURES, "IFL0", Period.DAILY)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int = _DEFAULT_PORT,
        timeout: float = 15.0,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 60.0,
    ) -> None:
        self._host = host if host is not None else get_best_mac_ex_host()
        self._port = port
        self._timeout = timeout
        self._auto_reconnect = auto_reconnect
        self._heartbeat_interval = heartbeat_interval
        self._conn = AsyncExTdxConnection(self._host, port, timeout, mac_ex_mode=True)
        self._execute_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None

    @classmethod
    def from_best_host(
        cls,
        hosts: list[str] | None = None,
        port: int = _DEFAULT_PORT,
        timeout: float = 15.0,
        ping_timeout: float = 5.0,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 60.0,
    ) -> "AsyncMacExClient":
        candidates = hosts or get_mac_ex_hosts()
        ranked = ping_ex_all(candidates, port, ping_timeout)
        best = ranked[0][0] if ranked else candidates[0]
        save_best_mac_ex_host(best)
        return cls(best, port, timeout, auto_reconnect, heartbeat_interval)

    @staticmethod
    def ping_all(
        hosts: list[str] | None = None,
        port: int = _DEFAULT_PORT,
        timeout: float = 5.0,
    ) -> list[tuple[str, float]]:
        return ping_ex_all(hosts or get_mac_ex_hosts(), port, timeout)

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        await self._conn.connect()
        await self._login()
        self._start_heartbeat()

    async def close(self) -> None:
        await self._stop_heartbeat()
        await self._conn.close()

    async def __aenter__(self) -> "AsyncMacExClient":
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    def _heartbeat_cmd(self) -> Awaitable[object]:
        """心跳使用的轻量请求（get_instrument_count，复用 _execute 重连）。"""
        return self._execute(GetExInstrumentCountCmd())

    async def _login(self) -> None:
        """执行 MAC EX 登录命令。"""
        await self._conn.execute(MacExLoginCmd())

    async def _execute(self, cmd: "BaseCommand[_T]") -> _T:
        """执行命令；断线时指数退避重试，同主机耗尽则跨主机故障转移。

        每次重连后必须重新 ``_login()``（MAC 协议扩展行情特有）。登录握手期的
        ``TdxConnectionError`` 与业务请求一样计入退避重试；``TdxCommandError``
        （登录被拒等确定性失败）不重试，直接抛出。

        健康分联动与 sync 版对称。
        """
        async with self._execute_lock:
            try:
                result = await self._conn.execute(cmd)
            except TdxConnectionError:
                if not self._auto_reconnect:
                    raise
                record_failure(self._host)
                last_exc: TdxConnectionError | None = None
                for delay in _RETRY_DELAYS:
                    await asyncio.sleep(delay)
                    await self._conn.close()
                    self._conn = AsyncExTdxConnection(
                        self._host, self._port, self._timeout, mac_ex_mode=True
                    )
                    # connect + login 纳入重试：登录握手期连接再次断开属可重试语义。
                    try:
                        await self._conn.connect()
                        await self._login()
                        result = await self._conn.execute(cmd)
                        record_success(self._host)
                        return result
                    except TdxConnectionError as e:
                        last_exc = e
                        record_failure(self._host)
                # 第二阶段：跨主机故障转移
                new_host = await select_best_host_async(
                    get_mac_ex_hosts(),
                    ping_ex_all,
                    save_best_mac_ex_host,
                    self._port,
                    5.0,
                    self._host,
                )
                if new_host is not None:
                    self._host = new_host
                    await self._conn.close()
                    self._conn = AsyncExTdxConnection(
                        self._host, self._port, self._timeout, mac_ex_mode=True
                    )
                    try:
                        await self._conn.connect()
                        await self._login()
                        result = await self._conn.execute(cmd)
                        record_success(self._host)
                        return result
                    except TdxConnectionError as e:
                        last_exc = e
                        record_failure(self._host)
                raise last_exc  # type: ignore[misc]
            else:
                record_success(self._host)
                return result

    # ------------------------------------------------------------------ #
    # 商品列表
    # ------------------------------------------------------------------ #

    async def goods_count(self, market: int | None = None) -> int:
        """获取商品总数。market=None 时返回全市场总数，否则返回指定市场的数量。"""
        if market is None:
            return await self._execute(GetExInstrumentCountCmd())
        offset = await self._find_market_offset(market)
        if offset < 0:
            return 0
        total = await self._execute(GetExInstrumentCountCmd())
        n = 0
        page = 1000
        pos = offset
        while pos < total:
            batch = await self._execute(GetExInstrumentInfoCmd(start=pos, count=page))
            if not batch:
                break
            for item in batch:
                if item.market == market:
                    n += 1
                elif item.market > market:
                    return n
            pos += page
        return n

    async def goods_list(self, market: int, start: int = 0, count: int = 600) -> pd.DataFrame:
        """获取扩展市场商品列表（期货合约/港股/美股等）。"""
        offset = await self._find_market_offset(market)
        if offset < 0:
            return pd.DataFrame()
        total = await self._execute(GetExInstrumentCountCmd())
        page_size = 1000
        collected: list[Any] = []
        skipped = 0
        pos = offset
        while pos < total and len(collected) < count:
            batch = await self._execute(GetExInstrumentInfoCmd(start=pos, count=page_size))
            if not batch:
                break
            for item in batch:
                if item.market == market:
                    if skipped < start:
                        skipped += 1
                    else:
                        collected.append(item)
                        if len(collected) >= count:
                            break
                elif item.market > market:
                    break
            else:
                pos += page_size
                continue
            break
        return _to_df(collected)

    async def _find_market_offset(self, market: int) -> int:
        """二分查找定位指定市场在全局商品列表中的起始偏移。"""
        total = await self._execute(GetExInstrumentCountCmd())
        if total == 0:
            return -1
        lo, hi = 0, total
        while lo < hi:
            mid = (lo + hi) // 2
            items = await self._execute(GetExInstrumentInfoCmd(start=mid, count=1))
            if not items:
                hi = mid
                continue
            m = items[0].market
            if m < market:
                lo = mid + 1
            else:
                hi = mid
        return lo

    # ------------------------------------------------------------------ #
    # 行情
    # ------------------------------------------------------------------ #

    async def goods_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: Any = None,
    ) -> pd.DataFrame:
        cmd = SymbolQuotesCmd(stocks, fields)
        result: list[MacQuoteField] = await self._execute(cmd)
        return _quotes_to_df(result)

    async def goods_quotes_list(
        self,
        market: int,
        start: int = 0,
        count: int = 100,
        sort_type: SortType = SortType.CODE,
        sort_order: SortOrder = SortOrder.NONE,
    ) -> pd.DataFrame:
        page_size = min(count, 80)
        items_df = await self.goods_list(market, start=start, count=page_size)
        if items_df.empty:
            return pd.DataFrame()
        stocks: list[tuple[int, str]] = [(market, row["code"]) for _, row in items_df.iterrows()]
        cmd = SymbolQuotesCmd(stocks)
        result: list[MacQuoteField] = await self._execute(cmd)
        return _quotes_to_df(result)

    # ------------------------------------------------------------------ #
    # K 线
    # ------------------------------------------------------------------ #

    async def goods_kline(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        start: int = 0,
        count: int = 800,
        adjust: Adjust = Adjust.NONE,
    ) -> pd.DataFrame:
        cmd = SymbolBarCmd(
            market=market,
            code=code,
            period=period,
            start=start,
            count=count,
            fq=adjust,
        )
        result = await self._execute(cmd)
        return _to_df(result)

    # ------------------------------------------------------------------ #
    # 分时
    # ------------------------------------------------------------------ #

    async def goods_tick_chart(
        self,
        market: int,
        code: str,
        query_date: int | date | None = None,
    ) -> pd.DataFrame:
        cmd = SymbolTickChartCmd(
            market=market, code=code, query_date=_coerce_query_date(query_date)
        )
        result = await self._execute(cmd)
        return _to_df(result)

    async def goods_chart_sampling(
        self,
        market: int,
        code: str,
    ) -> pd.DataFrame:
        cmd = ChartSamplingCmd(market=market, code=code)
        prices: list[float] = await self._execute(cmd)
        if not prices:
            return pd.DataFrame()
        return pd.DataFrame({"price": prices})

    # ------------------------------------------------------------------ #
    # 成交
    # ------------------------------------------------------------------ #

    async def goods_transaction(
        self,
        market: int,
        code: str,
        query_date: int | date | None = None,
        start: int = 0,
        count: int = 2000,
    ) -> pd.DataFrame:
        """获取逐笔成交数据（异步）。

        路由与 ``start`` 倒序语义见同步版 :meth:`goods_transaction`。
        """
        if is_hk_stock_market(market):
            result = await _fetch_hk_transactions_async(
                self._execute, market, code, _coerce_query_date(query_date), start, count
            )
            return _to_df(result)
        cmd = SymbolTransactionCmd(
            market=market,
            code=code,
            query_date=_coerce_query_date(query_date),
            start=start,
            count=count,
        )
        result = await self._execute(cmd)
        return _to_df(result)

    async def goods_transaction_all(
        self,
        market: int,
        code: str,
        query_date: date | None = None,
    ) -> pd.DataFrame:
        """获取港股某日全部逐笔成交（异步）。语义见同步版 :meth:`goods_transaction_all`。"""
        if not is_hk_stock_market(market):
            raise ValueError(
                f"goods_transaction_all 仅支持港股股票类市场（HK_STOCK_MARKETS），"
                f"收到 market={market}；其他市场请用 goods_transaction。"
            )
        result = await _fetch_all_hk_transactions_async(self._execute, market, code, query_date)
        return _to_df(result)
