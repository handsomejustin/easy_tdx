"""统一通达信客户端 -- 自动路由 A 股 / 扩展市场。"""

from __future__ import annotations

from types import TracebackType
from typing import Any

import pandas as pd

from .ex.mac_client import AsyncMacExClient, MacExClient
from .mac.client import AsyncMacClient, MacClient
from .mac.enums import (
    Adjust,
    BoardType,
    Category,
    FilterType,
    Period,
    SortOrder,
    SortType,
)


class UnifiedTdxClient:
    """统一通达信行情客户端。

    自动路由：A 股方法代理到 MacClient，扩展市场方法代理到 MacExClient。
    MacClient 在 connect()/__enter__ 时立即连接；MacExClient 延迟到首次使用。

    用法::

        with UnifiedTdxClient() as client:
            df = client.get_stock_kline(0, "600000", Period.DAILY, count=10)
            df2 = client.goods_kline(ExMarket.US_STOCK, "TSLA", Period.DAILY, count=10)
    """

    def __init__(
        self,
        heartbeat_interval: float = 15.0,
        timeout: float = 15.0,
    ) -> None:
        self._heartbeat_interval = heartbeat_interval
        self._timeout = timeout
        self._mac: MacClient | None = None
        self._mac_ex: MacExClient | None = None

    def connect(self) -> None:
        self._ensure_mac()

    def close(self) -> None:
        if self._mac is not None:
            self._mac.close()
            self._mac = None
        if self._mac_ex is not None:
            self._mac_ex.close()
            self._mac_ex = None

    def disconnect(self) -> None:
        self.close()

    def __enter__(self) -> UnifiedTdxClient:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # 内部路由
    # ------------------------------------------------------------------ #

    def _ensure_mac(self) -> MacClient:
        if self._mac is None:
            self._mac = MacClient.from_best_host(
                heartbeat_interval=self._heartbeat_interval,
                timeout=self._timeout,
            )
            self._mac.connect()
        return self._mac

    def _ensure_mac_ex(self) -> MacExClient:
        if self._mac_ex is None:
            self._mac_ex = MacExClient.from_best_host(timeout=self._timeout)
            self._mac_ex.connect()
        return self._mac_ex

    # ------------------------------------------------------------------ #
    # A 股方法 (proxy to MacClient)
    # ------------------------------------------------------------------ #

    def get_stock_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: object = None,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_stock_quotes(stocks, fields)

    def get_stock_quotes_list(
        self,
        category: Category,
        start: int = 0,
        count: int = 80,
        sort_type: SortType = SortType.CHANGE_PCT,
        sort_order: SortOrder = SortOrder.DESC,
        exclude_flags: list[FilterType] | None = None,
        fields: object = None,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_stock_quotes_list(
            category, start, count, sort_type, sort_order, exclude_flags, fields
        )

    def get_stock_kline(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        start: int = 0,
        count: int = 800,
        times: int = 1,
        adjust: Adjust = Adjust.NONE,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_stock_kline(market, code, period, start, count, times, adjust)

    def get_stock_kline_with_indicators(
        self,
        market: int,
        code: str,
        indicators: list[str],
        period: Period = Period.DAILY,
        count: int = 30,
        adjust: Adjust = Adjust.QFQ,
        params: dict[str, dict[str, int | float]] | None = None,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_stock_kline_with_indicators(
            market, code, indicators, period, count, adjust, params,
        )

    def get_tick_chart(
        self,
        market: int,
        code: str,
        date: int | None = None,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_tick_chart(market, code, date)

    def get_tick_charts(
        self,
        market: int,
        code: str,
        date: int | None = None,
        days: int = 5,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_tick_charts(market, code, date, days)

    def get_chart_sampling(self, market: int, code: str) -> pd.DataFrame:
        return self._ensure_mac().get_chart_sampling(market, code)

    def get_transactions(
        self,
        market: int,
        code: str,
        count: int = 2000,
        start: int = 0,
        date: int | None = None,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_transactions(market, code, count, start, date)

    def get_symbol_info(self, market: int, code: str) -> pd.DataFrame:
        return self._ensure_mac().get_symbol_info(market, code)

    def get_board_list(
        self,
        board_type: BoardType = BoardType.ALL,
        count: int = 10000,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_board_list(board_type, count)

    def get_board_members(
        self,
        board_symbol: str,
        count: int = 100000,
        sort_type: SortType = SortType.CHANGE_PCT,
        sort_order: SortOrder = SortOrder.DESC,
        fields: object = None,
        exclude_flags: list[FilterType] | None = None,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_board_members(
            board_symbol, count, sort_type, sort_order, fields, exclude_flags
        )

    def get_belong_board(self, market: int, code: str) -> pd.DataFrame:
        return self._ensure_mac().get_belong_board(market, code)

    def get_capital_flow(self, market: int, code: str) -> pd.DataFrame:
        return self._ensure_mac().get_capital_flow(market, code)

    def get_auction(self, market: int, code: str) -> pd.DataFrame:
        return self._ensure_mac().get_auction(market, code)

    def get_unusual(
        self,
        market: int,
        start: int = 0,
        count: int = 0,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_unusual(market, start, count)

    def get_server_info(self) -> pd.DataFrame:
        return self._ensure_mac().get_server_info()

    def get_kline_offset(
        self,
        offset: int = 0,
        count: int = 128000,
    ) -> pd.DataFrame:
        return self._ensure_mac().get_kline_offset(offset, count)

    def get_file_meta(self, filename: str) -> pd.DataFrame:
        return self._ensure_mac().get_file_meta(filename)

    def download_file_chunk(
        self,
        filename: str,
        index: int,
        offset: int,
        size: int,
    ) -> bytes:
        return self._ensure_mac().download_file_chunk(filename, index, offset, size)

    def download_file(
        self,
        filename: str,
        filesize: int = 0,
    ) -> bytearray:
        return self._ensure_mac().download_file(filename, filesize)

    def get_goods_list(
        self,
        market: int,
        start: int = 0,
        count: int = 600,
    ) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_list(market, start, count)

    # ------------------------------------------------------------------ #
    # 扩展市场方法 (proxy to MacExClient)
    # ------------------------------------------------------------------ #

    def goods_count(self, market: int) -> int:
        return self._ensure_mac_ex().goods_count(market)

    def goods_list(self, market: int, start: int = 0, count: int = 600) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_list(market, start, count)

    def goods_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: Any = None,
    ) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_quotes(stocks, fields)

    def goods_quotes_list(
        self,
        market: int,
        start: int = 0,
        count: int = 100,
        sort_type: SortType = SortType.CODE,
        sort_order: SortOrder = SortOrder.NONE,
    ) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_quotes_list(market, start, count, sort_type, sort_order)

    def goods_kline(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        start: int = 0,
        count: int = 800,
        adjust: Adjust = Adjust.NONE,
    ) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_kline(market, code, period, start, count, adjust)

    def goods_tick_chart(
        self,
        market: int,
        code: str,
        query_date: object = None,
    ) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_tick_chart(market, code, query_date)  # type: ignore[arg-type]

    def goods_chart_sampling(self, market: int, code: str) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_chart_sampling(market, code)

    def goods_transaction(
        self,
        market: int,
        code: str,
        query_date: object = None,
        start: int = 0,
        count: int = 2000,
    ) -> pd.DataFrame:
        return self._ensure_mac_ex().goods_transaction(market, code, query_date, start, count)  # type: ignore[arg-type]


class AsyncUnifiedTdxClient:
    """异步统一通达信行情客户端。

    用法::

        async with AsyncUnifiedTdxClient() as client:
            df = await client.get_stock_kline(0, "600000", Period.DAILY, count=10)
            df2 = await client.goods_kline(ExMarket.US_STOCK, "TSLA", Period.DAILY, count=10)
    """

    def __init__(
        self,
        heartbeat_interval: float = 15.0,
        timeout: float = 15.0,
    ) -> None:
        self._heartbeat_interval = heartbeat_interval
        self._timeout = timeout
        self._mac: AsyncMacClient | None = None
        self._mac_ex: AsyncMacExClient | None = None

    async def connect(self) -> None:
        await self._ensure_mac()

    async def close(self) -> None:
        if self._mac is not None:
            await self._mac.close()
            self._mac = None
        if self._mac_ex is not None:
            await self._mac_ex.close()
            self._mac_ex = None

    async def disconnect(self) -> None:
        await self.close()

    async def __aenter__(self) -> AsyncUnifiedTdxClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------ #
    # 内部路由
    # ------------------------------------------------------------------ #

    async def _ensure_mac(self) -> AsyncMacClient:
        if self._mac is None:
            self._mac = AsyncMacClient.from_best_host(
                heartbeat_interval=self._heartbeat_interval,
                timeout=self._timeout,
            )
            await self._mac.connect()
        return self._mac

    async def _ensure_mac_ex(self) -> AsyncMacExClient:
        if self._mac_ex is None:
            self._mac_ex = AsyncMacExClient.from_best_host(timeout=self._timeout)
            await self._mac_ex.connect()
        return self._mac_ex

    # ------------------------------------------------------------------ #
    # A 股方法 (proxy to AsyncMacClient)
    # ------------------------------------------------------------------ #

    async def get_stock_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: object = None,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_stock_quotes(stocks, fields)

    async def get_stock_quotes_list(
        self,
        category: Category,
        start: int = 0,
        count: int = 80,
        sort_type: SortType = SortType.CHANGE_PCT,
        sort_order: SortOrder = SortOrder.DESC,
        exclude_flags: list[FilterType] | None = None,
        fields: object = None,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_stock_quotes_list(
            category, start, count, sort_type, sort_order, exclude_flags, fields
        )

    async def get_stock_kline(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        start: int = 0,
        count: int = 800,
        times: int = 1,
        adjust: Adjust = Adjust.NONE,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_stock_kline(market, code, period, start, count, times, adjust)

    async def get_stock_kline_with_indicators(
        self,
        market: int,
        code: str,
        indicators: list[str],
        period: Period = Period.DAILY,
        count: int = 30,
        adjust: Adjust = Adjust.QFQ,
        params: dict[str, dict[str, int | float]] | None = None,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_stock_kline_with_indicators(
            market, code, indicators, period, count, adjust, params,
        )

    async def get_tick_chart(
        self,
        market: int,
        code: str,
        date: int | None = None,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_tick_chart(market, code, date)

    async def get_tick_charts(
        self,
        market: int,
        code: str,
        date: int | None = None,
        days: int = 5,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_tick_charts(market, code, date, days)

    async def get_chart_sampling(self, market: int, code: str) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_chart_sampling(market, code)

    async def get_transactions(
        self,
        market: int,
        code: str,
        count: int = 2000,
        start: int = 0,
        date: int | None = None,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_transactions(market, code, count, start, date)

    async def get_symbol_info(self, market: int, code: str) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_symbol_info(market, code)

    async def get_board_list(
        self,
        board_type: BoardType = BoardType.ALL,
        count: int = 10000,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_board_list(board_type, count)

    async def get_board_members(
        self,
        board_symbol: str,
        count: int = 100000,
        sort_type: SortType = SortType.CHANGE_PCT,
        sort_order: SortOrder = SortOrder.DESC,
        fields: object = None,
        exclude_flags: list[FilterType] | None = None,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_board_members(
            board_symbol, count, sort_type, sort_order, fields, exclude_flags
        )

    async def get_belong_board(self, market: int, code: str) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_belong_board(market, code)

    async def get_capital_flow(self, market: int, code: str) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_capital_flow(market, code)

    async def get_auction(self, market: int, code: str) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_auction(market, code)

    async def get_unusual(
        self,
        market: int,
        start: int = 0,
        count: int = 0,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_unusual(market, start, count)

    async def get_server_info(self) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_server_info()

    async def get_kline_offset(
        self,
        offset: int = 0,
        count: int = 128000,
    ) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_kline_offset(offset, count)

    async def get_file_meta(self, filename: str) -> pd.DataFrame:
        mac = await self._ensure_mac()
        return await mac.get_file_meta(filename)

    async def download_file_chunk(
        self,
        filename: str,
        index: int,
        offset: int,
        size: int,
    ) -> bytes:
        mac = await self._ensure_mac()
        return await mac.download_file_chunk(filename, index, offset, size)

    async def download_file(
        self,
        filename: str,
        filesize: int = 0,
    ) -> bytearray:
        mac = await self._ensure_mac()
        return await mac.download_file(filename, filesize)

    async def get_goods_list(
        self,
        market: int,
        start: int = 0,
        count: int = 600,
    ) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_list(market, start, count)

    # ------------------------------------------------------------------ #
    # 扩展市场方法 (proxy to AsyncMacExClient)
    # ------------------------------------------------------------------ #

    async def goods_count(self, market: int) -> int:
        ex = await self._ensure_mac_ex()
        return await ex.goods_count(market)

    async def goods_list(self, market: int, start: int = 0, count: int = 600) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_list(market, start, count)

    async def goods_quotes(
        self,
        stocks: list[tuple[int, str]],
        fields: Any = None,
    ) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_quotes(stocks, fields)

    async def goods_quotes_list(
        self,
        market: int,
        start: int = 0,
        count: int = 100,
        sort_type: SortType = SortType.CODE,
        sort_order: SortOrder = SortOrder.NONE,
    ) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_quotes_list(market, start, count, sort_type, sort_order)

    async def goods_kline(
        self,
        market: int,
        code: str,
        period: Period = Period.DAILY,
        start: int = 0,
        count: int = 800,
        adjust: Adjust = Adjust.NONE,
    ) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_kline(market, code, period, start, count, adjust)

    async def goods_tick_chart(
        self,
        market: int,
        code: str,
        query_date: object = None,
    ) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_tick_chart(market, code, query_date)  # type: ignore[arg-type]

    async def goods_chart_sampling(self, market: int, code: str) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_chart_sampling(market, code)

    async def goods_transaction(
        self,
        market: int,
        code: str,
        query_date: object = None,
        start: int = 0,
        count: int = 2000,
    ) -> pd.DataFrame:
        ex = await self._ensure_mac_ex()
        return await ex.goods_transaction(market, code, query_date, start, count)  # type: ignore[arg-type]
