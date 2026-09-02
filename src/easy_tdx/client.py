"""高层行情 API：TdxClient（同步）和 AsyncTdxClient（asyncio）。"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, TypeVar
from zoneinfo import ZoneInfo

import pandas as pd

from ._df import (
    _add_minute_datetime,
    _apply_bar_time_align_df,
    _category_to_minutes,
    _merge_bar_datetime,
    _merge_txn_datetime,
    _to_df,
)
from ._health import record_failure, record_success
from ._reconnect import (
    _RETRY_DELAYS,
    AsyncHeartbeatMixin,
    find_working_host_async,
    find_working_host_sync,
    select_best_host_async,
    select_best_host_sync,
)
from .codec.block import parse_block_dat
from .codec.financial import parse_financial_dat, parse_financial_file_list
from .codec.industry import parse_tdxhy_cfg
from .codec.price_rules import compute_price_limits, get_no_limit_window_days
from .commands.base import BaseCommand
from .commands.block_info import GetBlockInfoCmd, GetBlockInfoMetaCmd
from .commands.company_info import GetCompanyInfoCategoryCmd, GetCompanyInfoContentCmd
from .commands.finance_info import GetFinanceInfoCmd
from .commands.minute_time import GetHistoryMinuteTimeDataCmd
from .commands.report_file import GetReportFileCmd
from .commands.security_bars import GetIndexBarsCmd, GetSecurityBarsCmd
from .commands.security_count import GetSecurityCountCmd
from .commands.security_list import GetSecurityListCmd
from .commands.security_quotes import GetSecurityQuotesCmd
from .commands.transaction import GetHistoryTransactionDataCmd, GetTransactionDataCmd
from .commands.xdxr_info import GetXdxrInfoCmd
from .config import (
    get_best_host,
    get_calc_hosts,
    get_known_hosts,
    get_port,
    get_timeout,
    save_best_host,
)
from .exceptions import TdxConnectionError
from .models.bar import SecurityBar
from .models.enums import KlineCategory, Market
from .models.finance import (
    FinancialFileInfo,
    FinancialRecord,
)
from .models.quote import SecurityQuote
from .models.security import SecurityInfo
from .models.stats import FundFlow, HistoricalFundFlow, MarketStat
from .models.timeseries import TransactionRecord
from .transport.async_ import AsyncTdxConnection
from .transport.sync import TdxConnection, ping_all

_T = TypeVar("_T")
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_DAILY_PLUS = frozenset(
    {
        KlineCategory.DAY,
        KlineCategory.WEEK,
        KlineCategory.MONTH,
        KlineCategory.YEAR,
        KlineCategory.YEAR_ALT,
    }
)


def _today_in_shanghai() -> int:
    return int(datetime.now(_SHANGHAI_TZ).strftime("%Y%m%d"))


def _fund_flow_df_with_net(df: pd.DataFrame) -> pd.DataFrame:
    """为资金流 DataFrame 物化主力净额列。

    ``HistoricalFundFlow.main_net_inflow`` / ``FundFlow.main_net_inflow`` 是
    dataclass property，``_to_df`` 的 asdict 会静默丢弃（Issue #52：用户
    "取不到主力净额"的直接原因），这里显式物化为 ``main_net_inflow`` 列
    （单位：元，正=净流入）。放在 date 列之后（无 date 时放首列）。
    """
    if df.empty or "super_in" not in df.columns:
        return df
    out = df.copy()
    pos = 1 if "date" in out.columns else 0
    out.insert(
        pos,
        "main_net_inflow",
        (out["super_in"] + out["large_in"]) - (out["super_out"] + out["large_out"]),
    )
    return out


def _record_signature(
    record: TransactionRecord,
) -> tuple[int, int, float, int, int, int]:
    return (
        record.hour,
        record.minute,
        record.price,
        record.vol,
        record.buyorsell,
        record.unknown_last,
    )


def _page_signature(
    records: list[TransactionRecord],
) -> tuple[tuple[int, int, float, int, int, int], tuple[int, int, float, int, int, int]]:
    return (_record_signature(records[0]), _record_signature(records[-1]))


def _classify_fund_flow(records: list[TransactionRecord]) -> FundFlow:
    stats = {
        "super_in": 0.0,
        "large_in": 0.0,
        "medium_in": 0.0,
        "small_in": 0.0,
        "super_out": 0.0,
        "large_out": 0.0,
        "medium_out": 0.0,
        "small_out": 0.0,
    }

    for record in records:
        amount = record.price * record.vol * 100.0
        direction = "in" if record.buyorsell == 0 else "out" if record.buyorsell == 1 else None
        if not direction:
            continue

        if amount > 1_000_000:
            stats[f"super_{direction}"] += amount
        elif amount > 200_000:
            stats[f"large_{direction}"] += amount
        elif amount > 40_000:
            stats[f"medium_{direction}"] += amount
        else:
            stats[f"small_{direction}"] += amount

    return FundFlow(**stats)


def _date_from_bar(bar: SecurityBar) -> int:
    return bar.year * 10000 + bar.month * 100 + bar.day


def _historical_fund_flow_from_records(
    date: int, records: list[TransactionRecord]
) -> HistoricalFundFlow:
    flow = _classify_fund_flow(records)
    year = date // 10000
    month = (date // 100) % 100
    day = date % 100
    return HistoricalFundFlow(
        year=year,
        month=month,
        day=day,
        super_in=flow.super_in,
        super_out=flow.super_out,
        large_in=flow.large_in,
        large_out=flow.large_out,
        medium_in=flow.medium_in,
        medium_out=flow.medium_out,
        small_in=flow.small_in,
        small_out=flow.small_out,
    )


# ============================================================
# 同步客户端
# ============================================================

_CACHE_DIR = Path.home() / ".easy_tdx" / "cache"
_CACHE_MAX_AGE = 86400  # 1 天


def _serialize_stocks(stocks: list[SecurityInfo]) -> list[dict[str, Any]]:
    return [{k: v for k, v in asdict(s).items() if k != "_raw"} for s in stocks]


def _deserialize_stocks(data: list[dict[str, Any]]) -> list[SecurityInfo]:
    return [SecurityInfo(**{**d, "market": Market(d["market"])}) for d in data]


def _load_cache() -> list[SecurityInfo] | None:
    path = _CACHE_DIR / "security_list_all.json"
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text("utf-8"))
        updated = datetime.fromisoformat(raw["updated"])
        # 统一用 aware datetime 比较（审计 #18）：旧缓存可能写的是 naive datetime，
        # 此处 localize 到上海时区，避免跨时区机器（如 CI 的 UTC 与本地 +8）误判过期。
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=_SHANGHAI_TZ)
        if (datetime.now(_SHANGHAI_TZ) - updated).total_seconds() > _CACHE_MAX_AGE:
            return None
        return _deserialize_stocks(raw["data"])
    except Exception:
        return None


def _save_cache(stocks: list[SecurityInfo]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "updated": datetime.now(_SHANGHAI_TZ).isoformat(),
        "count": len(stocks),
        "data": _serialize_stocks(stocks),
    }
    (_CACHE_DIR / "security_list_all.json").write_text(
        json.dumps(data, ensure_ascii=False), "utf-8"
    )


class TdxClient:
    """同步通达信行情客户端，支持 IP 优选与断线自动重连。

    使用示例::

        # 单台服务器
        with TdxClient("180.153.18.170") as c:
            bars = c.get_security_bars(Market.SH, "600000", KlineCategory.DAY, 0, 100)

        # 自动从候选列表中选延迟最低的服务器
        with TdxClient.from_best_host() as c:
            count = c.get_security_count(Market.SH)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 15.0,
    ) -> None:
        self._host = host if host is not None else get_best_host()
        self._port = port if port is not None else get_port()
        self._timeout = timeout if timeout is not None else get_timeout()
        self._auto_reconnect = auto_reconnect
        self._heartbeat_interval = heartbeat_interval
        self._conn = TdxConnection(host, port, timeout)

    # ------------------------------------------------------------------ #
    # 工厂方法：自动优选最低延迟服务器
    # ------------------------------------------------------------------ #

    @classmethod
    def from_best_host(
        cls,
        hosts: list[str] | None = None,
        port: int | None = None,
        timeout: float | None = None,
        ping_timeout: float = 5.0,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 15.0,
    ) -> "TdxClient":
        """测量 hosts 中所有服务器延迟，选最低延迟的建立连接。

        自动将最佳主机保存到 config.json，后续连接默认使用该主机。
        若所有服务器均不可达，回退到 hosts[0]。
        """
        if hosts is None:
            hosts = get_known_hosts()
        if port is None:
            port = get_port()
        if timeout is None:
            timeout = get_timeout()
        ranked = ping_all(hosts, port, ping_timeout)
        best = ranked[0][0] if ranked else hosts[0]
        save_best_host(best)
        return cls(best, port, timeout, auto_reconnect, heartbeat_interval)

    @staticmethod
    def ping_all(
        hosts: list[str] | None = None,
        port: int | None = None,
        timeout: float = 5.0,
    ) -> list[tuple[str, float]]:
        """测量多台服务器延迟，返回按延迟排序的 (host, seconds) 列表。"""
        if hosts is None:
            hosts = get_known_hosts()
        if port is None:
            port = get_port()
        return ping_all(hosts, port, timeout)

    # ------------------------------------------------------------------ #
    # 连接管理
    # ------------------------------------------------------------------ #

    def connect(self) -> None:
        self._conn.connect()
        if self._heartbeat_interval > 0:
            self._conn.start_heartbeat(self._heartbeat_interval)

    def close(self) -> None:
        self._conn.stop_heartbeat()
        self._conn.close()

    def disconnect(self) -> None:
        """Alias for close()."""
        self.close()

    def ensure_connected(self) -> None:
        """验证连接存活，断线则自动重建。"""
        try:
            self._execute(GetSecurityCountCmd(Market.SH))
        except TdxConnectionError:
            self._reconnect()

    def _reconnect(self, host: str | None = None) -> None:
        """关闭当前连接并重建（默认连 self._host；传入 host 则切换主机）。

        统一收敛所有"重建 TdxConnection + 起心跳"的副本：``_execute`` 同主机
        重试、``_execute`` 跨主机故障转移、``ensure_connected``、
        ``get_market_stat`` 空数据重试都走这里，保证 4 处重建逻辑一致。
        """
        target = host if host is not None else self._host
        if host is not None:
            self._host = host
        self._conn.stop_heartbeat()
        self._conn.close()
        self._conn = TdxConnection(target, self._port, self._timeout)
        self._conn.connect()
        if self._heartbeat_interval > 0:
            self._conn.start_heartbeat(self._heartbeat_interval)

    def __enter__(self) -> "TdxClient":
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
    # 内部执行：含自动重连 + 跨主机故障转移
    # ------------------------------------------------------------------ #

    def _execute(self, cmd: "BaseCommand[_T]") -> _T:
        """执行命令；断线时指数退避重试，同主机耗尽则跨主机故障转移。

        两阶段韧性：
            1. 同主机重试（``_RETRY_DELAYS``，4 次指数退避）——应对瞬时抖动。
            2. 跨主机故障转移——同主机重试仍失败时，重新测速选延迟最低的另
               一台服务器再试一轮。服务器连不上时用户无需手动 ``ping``。
        ``auto_reconnect=False`` 时两阶段都不触发，直接抛出原异常。

        健康分联动：成功路径记 ``record_success``（恢复 score），连接失败
        记 ``record_failure``（降权），让频繁断连的服务器在后续故障转移中
        自动靠后。
        """
        try:
            result = self._conn.execute(cmd)
        except TdxConnectionError:
            if not self._auto_reconnect:
                raise
            # 连接失败：当前主机降权
            record_failure(self._host)
            last_exc: TdxConnectionError | None = None
            for delay in _RETRY_DELAYS:
                time.sleep(delay)
                self._reconnect()
                try:
                    result = self._conn.execute(cmd)
                    record_success(self._host)
                    return result
                except TdxConnectionError as e:
                    last_exc = e
                    record_failure(self._host)
            # 第二阶段：跨主机故障转移——重新测速切到另一台服务器再试一次
            new_host = select_best_host_sync(
                get_known_hosts(),
                ping_all,
                save_best_host,
                self._port,
                5.0,
                self._host,
            )
            if new_host is not None:
                self._reconnect(new_host)
                try:
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
    # 市场信息
    # ------------------------------------------------------------------ #

    def get_security_count(self, market: Market) -> int:
        """获取市场证券总数。"""
        return self._execute(GetSecurityCountCmd(market))

    def get_security_list(self, market: Market, start: int) -> pd.DataFrame:
        """获取证券列表（每页约1000条，按 start 分页）。"""
        return _to_df(self._execute(GetSecurityListCmd(market, start)))

    def get_security_list_all(self, pages: int | str = "all") -> pd.DataFrame:
        """获取沪深 A 股完整证券列表，并自动挂载行业信息。

        Args:
            pages: 拉取页数。每个市场每页 1000 条。
                   "all" 拉取全部（默认，结果会缓存到本地文件）。
                   整数 N 表示每个市场只拉前 N 页，不缓存。

        注意：
            `Market.BJ` 的证券列表请求长期存在服务器超时问题，当前版本暂不纳入此方法。
        """
        log = logging.getLogger(__name__)

        if pages == "all":
            cached = _load_cache()
            if cached is not None:
                log.info("从缓存加载沪深 A 股列表，共 %d 只", len(cached))
                return _to_df(cached)

        # 计算每个市场的最大起始偏移
        def _max_start(count: int) -> int:
            if pages == "all":
                return count
            return min(count, int(pages) * 1000)

        # 尝试获取行业配置
        industry_map: dict[str, tuple[str, str]] = {}
        try:
            cfg_data = self.get_report_file("tdxhy.cfg")
            if cfg_data:
                industry_map = parse_tdxhy_cfg(cfg_data)
                log.info("行业配置已加载，共 %d 条映射", len(industry_map))
        except Exception:
            log.warning("无法获取 tdxhy.cfg，行业字段将为空")

        all_stocks: list[SecurityInfo] = []
        for market in [Market.SH, Market.SZ]:
            count = self.get_security_count(market)
            limit = _max_start(count)
            total_pages = (limit + 999) // 1000
            for page_idx, start in enumerate(range(0, limit, 1000)):
                try:
                    stocks = self._execute(GetSecurityListCmd(market, start))
                except Exception:
                    log.warning(
                        "%s 第 %d/%d 页获取失败，跳过", market.name, page_idx + 1, total_pages
                    )
                    continue
                log.info(
                    "%s 第 %d/%d 页: %d 条", market.name, page_idx + 1, total_pages, len(stocks)
                )
                for s in stocks:
                    is_a_share = (market == Market.SH and s.code.startswith(("60", "68"))) or (
                        market == Market.SZ and s.code.startswith(("00", "30"))
                    )
                    if is_a_share:
                        if s.code in industry_map:
                            s.industry_tdx, s.industry_sw = industry_map[s.code]
                        all_stocks.append(s)

        log.info("沪深 A 股总数: %d", len(all_stocks))

        if pages == "all":
            _save_cache(all_stocks)

        return _to_df(all_stocks)

    def get_security_quotes(self, stocks: list[tuple[Market, str]]) -> pd.DataFrame:
        """批量获取实时五档行情（最多80只/次）。"""
        return _to_df(self._execute(GetSecurityQuotesCmd(stocks)))

    def get_price_limits(
        self, market: Market, code: str, name: str, pre_close: float
    ) -> tuple[float | None, float | None]:
        """按当前交易状态计算涨跌停价。

        对上市初期不设涨跌幅限制的标的，会先用日 K 线条数估算已上市交易天数。
        """
        listed_days: int | None = None
        no_limit_window_days = get_no_limit_window_days(market, code, name)
        if no_limit_window_days > 0:
            try:
                bars = self._execute(
                    GetSecurityBarsCmd(market, code, KlineCategory.DAY, 0, no_limit_window_days + 1)
                )
                listed_days = len(bars)
            except Exception:
                listed_days = None

        return compute_price_limits(
            market,
            code,
            name,
            pre_close,
            listed_days=listed_days,
        )

    # ------------------------------------------------------------------ #
    # K 线
    # ------------------------------------------------------------------ #

    def get_security_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
        *,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """获取 K 线数据（最多800条/次，按 start 分页）。

        Args:
            bar_time: 时间戳语义。 ``"start"``（默认）= bar 开始时间（通达信原始，
                上午最后一根 5min 标 11:25、下午第一根标 13:00）；``"end"`` = bar 右端点
                （= 开始 + 周期时长，与 Tushare/同花顺对齐，上午最后一根标 11:30）。
                仅对分钟级周期生效；日线及以上不受影响。

        vol 单位：分钟线/日线为成交量(股)；周/月/季/年线服务端原样返回的是
        真实成交量/100，解析层已 ×100 还原为股。
        """
        cmd = GetSecurityBarsCmd(market, code, category, start, count)
        bars = self._execute(cmd)
        # 空数据故障转移：服务器连通但返回空/截断（部分服务器对所有证券返回空 body
        # 且不报错），按延迟顺序逐台实测找首台有效数据的服务器。与 get_market_stat
        # 同源逻辑。注意：真·无历史数据（如新股）所有服务器都返回空，此时换台仍为空，
        # 直接返回空 DataFrame 而非 raise——避免把"该股票本就没数据"误报为故障。
        if not bars and self._auto_reconnect:
            bars = self._find_host_returning_data(cmd)
        df = _to_df(bars)
        delta = _category_to_minutes(int(category))
        is_intraday = delta is not None
        df = _apply_bar_time_align_df(
            df,
            is_intraday=is_intraday,
            delta_minutes=delta,
            bar_time=bar_time,
            has_time_columns=True,
        )
        return _merge_bar_datetime(df, not is_intraday)

    def get_index_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
        *,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """获取指数 K 线数据。

        Args:
            bar_time: 见 :meth:`get_security_bars`，分钟级周期时间戳可对齐 Tushare 右端点。

        vol 单位：日线与周/月/季/年线为成交量(手)（周及以上周期服务端原样
        返回真实成交量/100，解析层已 ×100 还原）；**分钟线协议不提供成交量**
        （报文中该字段实为成交额/100，与 amount 冗余），vol 为 NaN——请勿将
        其当作成交量使用，Web API 中序列化为 ``null``。
        """
        cmd = GetIndexBarsCmd(market, code, category, start, count)
        bars = self._execute(cmd)
        # 空数据故障转移：指数/板块指数（880xxx 等）并非所有服务器都提供，服务端
        # 截断返回 0 条是已知现象（日志"指数K线响应在第1/800条处被截断"）。
        # 按延迟顺序逐台实测换台，避免上层拿到空数据。全失败则返回空 DataFrame。
        if not bars and self._auto_reconnect:
            bars = self._find_host_returning_data(cmd)
        df = _to_df(bars)
        delta = _category_to_minutes(int(category))
        is_intraday = delta is not None
        df = _apply_bar_time_align_df(
            df,
            is_intraday=is_intraday,
            delta_minutes=delta,
            bar_time=bar_time,
            has_time_columns=True,
        )
        return _merge_bar_datetime(df, not is_intraday)

    # ------------------------------------------------------------------ #
    # 分时
    # ------------------------------------------------------------------ #

    def get_minute_time_data(self, market: Market, code: str) -> pd.DataFrame:
        """获取今日分时数据（240条，走历史分时接口）。"""
        today = _today_in_shanghai()
        bars = self._execute(GetHistoryMinuteTimeDataCmd(market, code, today))
        return _add_minute_datetime(_to_df(bars), today)

    def get_history_minute_time_data(self, market: Market, code: str, date: int) -> pd.DataFrame:
        """获取历史某日分时数据（date: YYYYMMDD）。"""
        bars = self._execute(GetHistoryMinuteTimeDataCmd(market, code, date))
        return _add_minute_datetime(_to_df(bars), date)

    # ------------------------------------------------------------------ #
    # 逐笔成交
    # ------------------------------------------------------------------ #

    def get_transaction_data(
        self, market: Market, code: str, start: int, count: int = 800
    ) -> pd.DataFrame:
        """获取当日逐笔成交（分页）。"""
        df = _to_df(self._execute(GetTransactionDataCmd(market, code, start, count)))
        return _merge_txn_datetime(df, _today_in_shanghai())

    def get_history_transaction_data(
        self, market: Market, code: str, date: int, start: int, count: int = 800
    ) -> pd.DataFrame:
        """获取历史逐笔成交（date: YYYYMMDD，分页）。"""
        df = _to_df(self._execute(GetHistoryTransactionDataCmd(market, code, date, start, count)))
        return _merge_txn_datetime(df, date)

    # ------------------------------------------------------------------ #
    # 财务 / 公司
    # ------------------------------------------------------------------ #

    def get_xdxr_info(self, market: Market, code: str) -> pd.DataFrame:
        """获取除权除息历史记录。"""
        return _to_df(self._execute(GetXdxrInfoCmd(market, code)))

    def get_finance_info(self, market: Market, code: str) -> pd.DataFrame:
        """获取最新财务数据。"""
        return _to_df(self._execute(GetFinanceInfoCmd(market, code)))

    def get_company_info_category(self, market: Market, code: str) -> pd.DataFrame:
        """获取公司信息文件目录。"""
        return _to_df(self._execute(GetCompanyInfoCategoryCmd(market, code)))

    def get_company_info_content(
        self, market: Market, code: str, filename: str, offset: int, length: int
    ) -> str:
        """读取公司信息文本。"""
        return self._execute(GetCompanyInfoContentCmd(market, code, filename, offset, length))

    def get_block_info(self, filename: str) -> pd.DataFrame:
        """获取并解析板块文件（行业、概念、风格等）。

        常用文件名：
          'block_zs.dat'  - 行业/指数板块
          'block_gn.dat'  - 概念板块
          'block_fg.dat'  - 风格板块
        """
        size, _hash = self._execute(GetBlockInfoMetaCmd(filename))
        full_data = bytearray()
        pos = 0
        chunk_size = 30000
        while pos < size:
            chunk = self._execute(GetBlockInfoCmd(filename, pos, chunk_size))
            if not chunk:
                break
            full_data.extend(chunk)
            pos += len(chunk)
        return _to_df(parse_block_dat(bytes(full_data), filename))

    def get_report_file(self, filename: str) -> bytes:
        """从服务器拉取大文件（如 'base_info.zip'）。"""
        full_data = bytearray()
        pos = 0
        chunk_size = 30000
        while True:
            chunk = self._execute(GetReportFileCmd(filename, pos, chunk_size))
            if not chunk:
                break
            full_data.extend(chunk)
            pos += len(chunk)
            if len(chunk) < chunk_size:
                break
        return bytes(full_data)

    @staticmethod
    def _download_from_host(
        host: str, filename: str, port: int = 7709, timeout: float = 15.0
    ) -> bytes:
        """从指定服务器创建临时连接并下载文件。"""
        conn = TdxConnection(host, port, timeout)
        try:
            conn.connect()
            full_data = bytearray()
            pos = 0
            chunk_size = 30000
            while True:
                chunk = conn.execute(GetReportFileCmd(filename, pos, chunk_size))
                if not chunk:
                    break
                full_data.extend(chunk)
                pos += len(chunk)
                if len(chunk) < chunk_size:
                    break
            return bytes(full_data)
        finally:
            conn.close()

    def get_financial_file_list(self, host: str | None = None) -> pd.DataFrame:
        """获取可用的历史专业财报文件列表。

        连接到计算服务器，下载 tdxfin/gpcw.txt 并解析。
        """
        if host is None:
            host = get_calc_hosts()[0]
        data = self._download_from_host(host, "tdxfin/gpcw.txt")
        raw_list = parse_financial_file_list(data)
        return _to_df([FinancialFileInfo(filename=f, hash=h, filesize=s) for f, h, s in raw_list])

    def get_financial_file(self, filename: str, host: str | None = None) -> bytes:
        """从计算服务器下载财报 zip 文件。

        Args:
            filename: 如 'tdxfin/gpcw20260331.zip'
        """
        if host is None:
            host = get_calc_hosts()[0]
        return self._download_from_host(host, filename)

    def get_financial_records(self, filename: str, host: str | None = None) -> pd.DataFrame:
        """下载财报 zip 并解析为每只股票的记录列表。

        Args:
            filename: 如 'tdxfin/gpcw20260331.zip'
        """
        if host is None:
            host = get_calc_hosts()[0]
        import io
        import re
        import zipfile

        zip_data = self.get_financial_file(filename, host)
        if not zip_data:
            return pd.DataFrame()

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            dat_names = [n for n in zf.namelist() if n.endswith(".dat")]
            if not dat_names:
                return pd.DataFrame()
            dat_data = zf.read(dat_names[0])

        m = re.search(r"(\d{8})", filename)
        report_date = int(m.group(1)) if m else 0

        raw_records = parse_financial_dat(dat_data, report_date)
        records: list[FinancialRecord] = []
        for code, market_byte, rdate, fields in raw_records:
            market = Market.SH if market_byte == 1 else Market.SZ
            records.append(
                FinancialRecord(code=code, market=market, report_date=rdate, fields=fields)
            )
        return _to_df(records)

    def get_market_stat(self) -> pd.DataFrame:
        """获取 A 股全市场涨跌统计概况（基于 880005/880001/880006 统计指数）。

        通达信这三个"统计指数"的计数类字段（涨/跌/平/总数/涨停/跌停家数）
        返回的是真实家数的 1/10，需统一 ×10 还原。成交额/量/市值字段不受影响。
        `suspended_count` 由 `total - up - down - neutral` 推得，用于保证计数守恒。

        空数据容错：880005/880001/880006 并非所有服务器都提供，会返回空 quotes。
        此时不只切换到延迟最低的一台（它可能也不提供），而是按延迟顺序逐台实测，
        找到第一台返回有效数据的服务器，避免用户手动 ``easy-tdx ping``。
        """
        # 通达信中 880005 是全市场行情统计，880001 是总市值指数，880006 是涨跌停统计
        _cmd = GetSecurityQuotesCmd(
            [(Market.SH, "880005"), (Market.SH, "880001"), (Market.SH, "880006")]
        )
        quotes = self._execute(_cmd)
        if not quotes and self._auto_reconnect:
            quotes = self._find_host_returning_quotes(_cmd)
        if not quotes:
            raise RuntimeError("无法获取市场统计数据")
        q = quotes[0]
        # 计数字段协议返回值为真实家数 / 10，这里 ×10 还原（见 docstring）
        up = round(q.price * 10)
        down = round(q.open * 10)
        neutral = round(q.low * 10)
        total = round(q.high * 10)
        market_cap = quotes[1].price * 1e10 if len(quotes) > 1 else 0.0
        limit_down = round(quotes[2].open * 10) if len(quotes) > 2 else 0
        limit_up = round(quotes[2].price * 10) if len(quotes) > 2 else 0
        return _to_df(
            MarketStat(
                up_count=up,
                down_count=down,
                neutral_count=neutral,
                suspended_count=max(0, total - up - down - neutral),
                total_count=total,
                total_amount=q.amount,
                total_volume=q.vol,
                total_market_cap=market_cap,
                limit_up_count=limit_up,
                limit_down_count=limit_down,
            )
        )

    def _find_host_returning_data(self, cmd: "BaseCommand[_T]") -> _T:
        """空数据故障转移：测速后按延迟顺序逐台实测，返回首台有效数据的结果。

        泛化版：支持任意返回 ``list``/序列的命令（quotes、K 线 bars 等）。
        统计指数（880005 等）、指数 K 线等并非所有服务器都提供，延迟最低的不
        一定返回数据，故需逐台实际查询。最多尝试 ``_WORKING_HOST_MAX_ATTEMPTS``
        台（见 ``_reconnect``）。找到后 client 停在该 host；全失败返回空值
        （由 ``bool()`` 判空）。

        Note:
            命令返回值必须可被 ``bool()`` 判空（list / DataFrame 均满足）。
        """
        bad_host = self._host
        ranked = ping_all(get_known_hosts(), self._port, 5.0)

        def _try(host: str) -> bool:
            # 切换到候选 host 并实测；非空即视为该 host 可用
            self._reconnect(host)
            return bool(self._execute(cmd))

        new_host = find_working_host_sync(ranked, _try, save_best_host, bad_host)
        if new_host is None:
            # 全部候选都不可用，回退到原 host（保持状态可预测）
            if self._host != bad_host:
                self._reconnect(bad_host)
            return []  # type: ignore[return-value]
        # _try 已把 client 切到 new_host 并执行过 cmd，重新取一次拿结果
        return self._execute(cmd)

    def _find_host_returning_quotes(
        self, cmd: "BaseCommand[list[SecurityQuote]]"
    ) -> list[SecurityQuote]:
        """空数据故障转移（quotes 专用薄封装）。

        保留独立方法以兼容既有 ``get_market_stat`` 调用与外部测试；实际委托
        给泛化版 :meth:`_find_host_returning_data`。
        """
        return self._find_host_returning_data(cmd)

    def _collect_transaction_records(
        self,
        fetch_page: Callable[[int, int], list[TransactionRecord]],
        page_size: int,
        max_start: int = 10000,
    ) -> list[TransactionRecord]:
        all_recs: list[TransactionRecord] = []
        seen_sig: set[tuple[int, int, float, int, int, int]] = set()
        seen_page_sigs: set[
            tuple[
                tuple[int, int, float, int, int, int],
                tuple[int, int, float, int, int, int],
            ]
        ] = set()
        start = 0

        while start < max_start:
            recs = fetch_page(start, page_size)
            if not recs:
                break

            page_sig = _page_signature(recs)
            if page_sig in seen_page_sigs:
                break
            seen_page_sigs.add(page_sig)

            new_count = 0
            for record in recs:
                sig = _record_signature(record)
                if sig not in seen_sig:
                    seen_sig.add(sig)
                    all_recs.append(record)
                    new_count += 1

            if new_count == 0:
                break

            start += len(recs)
            if len(recs) < 100:
                break

        return all_recs

    def get_fund_flow(self, market: Market, code: str) -> pd.DataFrame:
        """获取个股当日资金流向分布（基于 L1 逐笔数据统计）。

        返回列含 ``main_net_inflow``（主力净流入，单位元）。

        口径限制（Issue #55）：分档基于 0x0fb5 逐笔接口返回的"单笔成交额"，
        而该接口的记录是交易所真实逐笔**聚合**后的（实测 000001.SZ 单日
        约 17:1），且分档看的是成交额、不是挂单额。高价股单笔普遍被聚合
        推过 100 万/20 万阈值，小单档可不足成交额 1%、主力档常占 95%+——
        ``main_net_inflow`` 实质更接近"当日主动买卖总失衡"，与东财/同花顺
        基于 L2 逐笔委托挂单额的"主力净流入"**不可比**，勿混用于同一张
        表或同一个因子。
        """
        records = self._collect_transaction_records(
            lambda start, page_size: self._execute(
                GetTransactionDataCmd(market, code, start, page_size)
            ),
            2000,
        )
        return _fund_flow_df_with_net(_to_df(_classify_fund_flow(records)))

    def _fetch_fund_flow_records(
        self, market: Market, code: str, start: int, count: int
    ) -> list[HistoricalFundFlow]:
        """在当前 host 上获取资金流记录（日 K 线取日期 + 逐笔成交重算）。

        通达信标准行情服务器没有"历史资金流向"专用指令：曾经的 Category 22
        直连请求实测在全部已知服务器上仅返回 2 字节空包（Issue #52），已移除。
        资金流一律由逐笔成交重算：历史日期走历史逐笔接口；当日成交在历史逐笔
        接口里要收盘清算后才有，当日 bar 盘中改走当日实时逐笔接口——此前当日
        行恒为全 0，用户"取不到最新主力净额"的直接原因（Issue #52）。
        返回空列表代表该 host 无 K 线数据（或解析失败）。
        """
        bars = self._execute(GetSecurityBarsCmd(market, code, KlineCategory.DAY, start, count))
        today = _today_in_shanghai()
        results: list[HistoricalFundFlow] = []
        for bar in bars:
            date = _date_from_bar(bar)

            # 用闭包工厂立即绑定 date（审计 #10），避免 lambda 延迟绑定循环变量。
            def _fetch_page(
                page_start: int, page_size: int, _d: int = date
            ) -> list[TransactionRecord]:
                cmd: BaseCommand[list[TransactionRecord]]
                if _d == today:
                    cmd = GetTransactionDataCmd(market, code, page_start, page_size)
                else:
                    cmd = GetHistoryTransactionDataCmd(market, code, _d, page_start, page_size)
                return self._execute(cmd)

            records = self._collect_transaction_records(_fetch_page, 800)
            results.append(_historical_fund_flow_from_records(date, records))
        return results

    def get_history_fund_flow(
        self, market: Market, code: str, start: int, count: int
    ) -> pd.DataFrame:
        """获取个股历史日线资金流向序列。

        实现："日 K 线取日期 + 逐笔成交重算资金流"。通达信标准服务器无
        资金流专用指令（Category 22 实测全空，见 Issue #52）；当日 bar 盘中
        走当日实时逐笔接口，收盘清算后走历史逐笔接口。

        返回列含 ``main_net_inflow``（主力净流入 = 超大单+大单净额，单位元）。

        空数据故障转移（v1.20.5，Issue #41）：当前 host 无 K 线数据时，
        按延迟顺序逐台实测找首台返回有效数据的服务器。部分服务器对常见标的也会
        返回 ret_count 撒谎的空 body（日志"K线响应为空（声称 800 条...）"），
        此前直接返回空 DataFrame，用户拿不到数据；现复用 K 线故障转移的同源逻辑。
        注意：真·无历史数据（如新股）所有服务器都返回空，此时换台仍为空，直接
        返回空 DataFrame 而非 raise——避免把"该股票本就没数据"误报为故障。

        口径限制（Issue #55）：分档基于 0x0fb5 逐笔接口返回的"单笔成交额"，
        而该接口的记录是交易所真实逐笔**聚合**后的（实测 000001.SZ 单日
        约 17:1），且分档看的是成交额、不是挂单额。高价股单笔普遍被聚合
        推过 100 万/20 万阈值，小单档可不足成交额 1%、主力档常占 95%+——
        ``main_net_inflow`` 实质更接近"当日主动买卖总失衡"，与东财/同花顺
        基于 L2 逐笔委托挂单额的"主力净流入"**不可比**，勿混用于同一张
        表或同一个因子（实证两口径选股信号重合度仅约 14%）。
        """
        results = self._fetch_fund_flow_records(market, code, start, count)
        # 空数据故障转移：与 get_security_bars / get_index_bars 同源逻辑。
        if not results and self._auto_reconnect:
            results = self._fund_flow_failover(market, code, start, count)
        return _fund_flow_df_with_net(_to_df(results))

    def _fund_flow_failover(
        self, market: Market, code: str, start: int, count: int
    ) -> list[HistoricalFundFlow]:
        """资金流空数据故障转移：逐台实测找首台返回有效数据的服务器。

        与 ``_find_host_returning_data`` 区别：资金流获取涉及多命令（K 线 +
        逐笔），无法用单个 cmd 复用泛化版；这里以内联 ``_try`` 在每台候选上跑完
        整 ``_fetch_fund_flow_records``，返回首台非空结果。全失败返回空列表。
        """
        bad_host = self._host
        ranked = ping_all(get_known_hosts(), self._port, 5.0)

        def _try(host: str) -> bool:
            self._reconnect(host)
            return bool(self._fetch_fund_flow_records(market, code, start, count))

        new_host = find_working_host_sync(ranked, _try, save_best_host, bad_host)
        if new_host is None:
            # 全部候选都不可用，回退到原 host（保持状态可预测）
            if self._host != bad_host:
                self._reconnect(bad_host)
            return []
        # _try 已切到 new_host 并跑过一次，重新取一次拿结果
        return self._fetch_fund_flow_records(market, code, start, count)


# ============================================================
# 异步客户端
# ============================================================


class AsyncTdxClient(AsyncHeartbeatMixin):
    """异步通达信行情客户端（asyncio）。

    使用示例::

        async with AsyncTdxClient("180.153.18.170") as c:
            bars = await c.get_security_bars(Market.SH, "600000", KlineCategory.DAY, 0, 100)

    注意：
        单个 AsyncTdxClient 仅维护一条 TCP 连接；并发调用会在连接内串行执行。
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        timeout: float | None = None,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 60.0,
    ) -> None:
        self._host = host if host is not None else get_best_host()
        self._port = port if port is not None else get_port()
        self._timeout = timeout if timeout is not None else get_timeout()
        self._auto_reconnect = auto_reconnect
        self._heartbeat_interval = heartbeat_interval
        self._conn = AsyncTdxConnection(self._host, self._port, self._timeout)
        self._execute_lock = asyncio.Lock()
        self._heartbeat_task: asyncio.Task[None] | None = None

    @classmethod
    def from_best_host(
        cls,
        hosts: list[str] | None = None,
        port: int | None = None,
        timeout: float | None = None,
        ping_timeout: float = 5.0,
        auto_reconnect: bool = True,
        heartbeat_interval: float = 60.0,
    ) -> "AsyncTdxClient":
        """测量 hosts 中所有服务器延迟，选最低延迟的建立连接。

        自动将最佳主机保存到 config.json。
        """
        if hosts is None:
            hosts = get_known_hosts()
        if port is None:
            port = get_port()
        if timeout is None:
            timeout = get_timeout()
        ranked = ping_all(hosts, port, ping_timeout)
        best = ranked[0][0] if ranked else hosts[0]
        save_best_host(best)
        return cls(best, port, timeout, auto_reconnect, heartbeat_interval)

    @staticmethod
    def ping_all(
        hosts: list[str] | None = None,
        port: int | None = None,
        timeout: float = 5.0,
    ) -> list[tuple[str, float]]:
        """测量多台服务器延迟，返回按延迟排序的 (host, seconds) 列表。"""
        if hosts is None:
            hosts = get_known_hosts()
        if port is None:
            port = get_port()
        return ping_all(hosts, port, timeout)

    async def connect(self) -> None:
        await self._conn.connect()
        self._start_heartbeat()

    async def close(self) -> None:
        await self._stop_heartbeat()
        await self._conn.close()

    async def reconnect_to(self, host: str) -> None:
        """热切换到新 host：关旧连接 → 换 host → 建新连接。

        用于 web UI 的"服务器设置"页面——用户点选一个 host 后，无需重启
        服务即可切换。复用 ``_execute_lock`` 保证切换期间没有并发行情请求
        撞到半开的连接。切换失败抛异常（旧连接已 close，client 处于断开
        状态，调用方应捕获并提示用户选别的 host）。
        """
        async with self._execute_lock:
            await self._stop_heartbeat()
            await self._conn.close()
            self._host = host
            self._conn = AsyncTdxConnection(host, self._port, self._timeout)
            await self._conn.connect()
            self._start_heartbeat()

    async def __aenter__(self) -> "AsyncTdxClient":
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
        """心跳使用的轻量请求（get_security_count，复用 _execute 重连）。"""
        return self.get_security_count(Market.SH)

    async def _areconnect(self, host: str | None = None) -> None:
        """关闭当前连接并重建（默认连 self._host；传入 host 则切换主机）。

        async 版的统一重建入口，与 sync ``_reconnect`` 对称，供 ``_execute``
        同主机重试、跨主机故障转移、``get_market_stat`` 空数据重试复用。
        """
        target = host if host is not None else self._host
        if host is not None:
            self._host = host
        await self._stop_heartbeat()
        await self._conn.close()
        self._conn = AsyncTdxConnection(target, self._port, self._timeout)
        await self._conn.connect()
        self._start_heartbeat()

    async def _execute(self, cmd: "BaseCommand[_T]") -> _T:
        """执行命令；断线时指数退避重试，同主机耗尽则跨主机故障转移。

        两阶段韧性与 sync 版对称：先同主机重试（``_RETRY_DELAYS``），再跨主机
        故障转移（重新测速切到另一台服务器）。整个流程在 ``_execute_lock`` 内
        串行，避免并发请求触发多次故障转移抖动。``auto_reconnect=False`` 时
        两阶段都不触发。
        """
        async with self._execute_lock:
            try:
                result = await self._conn.execute(cmd)
            except TdxConnectionError:
                if not self._auto_reconnect:
                    raise
                # 连接失败：当前主机降权
                record_failure(self._host)
                last_exc: TdxConnectionError | None = None
                for delay in _RETRY_DELAYS:
                    await asyncio.sleep(delay)
                    await self._areconnect()
                    try:
                        result = await self._conn.execute(cmd)
                        record_success(self._host)
                        return result
                    except TdxConnectionError as e:
                        last_exc = e
                        record_failure(self._host)
                # 第二阶段：跨主机故障转移
                new_host = await select_best_host_async(
                    get_known_hosts(),
                    ping_all,
                    save_best_host,
                    self._port,
                    5.0,
                    self._host,
                )
                if new_host is not None:
                    await self._areconnect(new_host)
                    try:
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

    async def get_security_count(self, market: Market) -> int:
        return await self._execute(GetSecurityCountCmd(market))

    async def get_security_list(self, market: Market, start: int) -> pd.DataFrame:
        return _to_df(await self._execute(GetSecurityListCmd(market, start)))

    async def get_security_list_all(self, pages: int | str = "all") -> pd.DataFrame:
        """获取沪深 A 股完整证券列表，并自动挂载行业信息。

        Args:
            pages: 拉取页数。每个市场每页 1000 条。
                   "all" 拉取全部（默认，结果会缓存到本地文件）。
                   整数 N 表示每个市场只拉前 N 页，不缓存。

        注意：
            `Market.BJ` 的证券列表请求长期存在服务器超时问题，当前版本暂不纳入此方法。
        """
        log = logging.getLogger(__name__)

        if pages == "all":
            cached = _load_cache()
            if cached is not None:
                log.info("从缓存加载沪深 A 股列表，共 %d 只", len(cached))
                return _to_df(cached)

        def _max_start(count: int) -> int:
            if pages == "all":
                return count
            return min(count, int(pages) * 1000)

        industry_map: dict[str, tuple[str, str]] = {}
        try:
            cfg_data = await self.get_report_file("tdxhy.cfg")
            if cfg_data:
                industry_map = parse_tdxhy_cfg(cfg_data)
                log.info("行业配置已加载，共 %d 条映射", len(industry_map))
        except Exception:
            log.warning("无法获取 tdxhy.cfg，行业字段将为空")

        all_stocks: list[SecurityInfo] = []
        for market in [Market.SH, Market.SZ]:
            count = await self.get_security_count(market)
            limit = _max_start(count)
            total_pages = (limit + 999) // 1000
            for page_idx, start in enumerate(range(0, limit, 1000)):
                try:
                    stocks = await self._execute(GetSecurityListCmd(market, start))
                except Exception:
                    log.warning(
                        "%s 第 %d/%d 页获取失败，跳过", market.name, page_idx + 1, total_pages
                    )
                    continue
                log.info(
                    "%s 第 %d/%d 页: %d 条", market.name, page_idx + 1, total_pages, len(stocks)
                )
                for s in stocks:
                    is_a_share = (market == Market.SH and s.code.startswith(("60", "68"))) or (
                        market == Market.SZ and s.code.startswith(("00", "30"))
                    )
                    if is_a_share:
                        if s.code in industry_map:
                            s.industry_tdx, s.industry_sw = industry_map[s.code]
                        all_stocks.append(s)

        log.info("沪深 A 股总数: %d", len(all_stocks))
        if pages == "all":
            _save_cache(all_stocks)
        return _to_df(all_stocks)

    async def get_security_quotes(self, stocks: list[tuple[Market, str]]) -> pd.DataFrame:
        return _to_df(await self._execute(GetSecurityQuotesCmd(stocks)))

    async def get_price_limits(
        self, market: Market, code: str, name: str, pre_close: float
    ) -> tuple[float | None, float | None]:
        """按当前交易状态计算涨跌停价。"""
        listed_days: int | None = None
        no_limit_window_days = get_no_limit_window_days(market, code, name)
        if no_limit_window_days > 0:
            try:
                bars = await self._execute(
                    GetSecurityBarsCmd(market, code, KlineCategory.DAY, 0, no_limit_window_days + 1)
                )
                listed_days = len(bars)
            except Exception:
                listed_days = None

        return compute_price_limits(
            market,
            code,
            name,
            pre_close,
            listed_days=listed_days,
        )

    async def get_security_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
        *,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """获取 K 线数据。``bar_time`` 见同步版 :meth:`get_security_bars`。"""
        cmd = GetSecurityBarsCmd(market, code, category, start, count)
        bars = await self._execute(cmd)
        # 空数据故障转移（与 sync 版对称）：服务器连通但返回空/截断时逐台换台。
        if not bars and self._auto_reconnect:
            bars = await self._find_host_returning_data(cmd)
        df = _to_df(bars)
        delta = _category_to_minutes(int(category))
        is_intraday = delta is not None
        df = _apply_bar_time_align_df(
            df,
            is_intraday=is_intraday,
            delta_minutes=delta,
            bar_time=bar_time,
            has_time_columns=True,
        )
        return _merge_bar_datetime(df, not is_intraday)

    async def get_index_bars(
        self,
        market: Market,
        code: str,
        category: KlineCategory,
        start: int,
        count: int = 800,
        *,
        bar_time: str = "start",
    ) -> pd.DataFrame:
        """获取指数 K 线数据。``bar_time`` 见同步版 :meth:`get_index_bars`。"""
        cmd = GetIndexBarsCmd(market, code, category, start, count)
        bars = await self._execute(cmd)
        # 空数据故障转移（与 sync 版对称）：指数 K 线截断/空时逐台换台。
        if not bars and self._auto_reconnect:
            bars = await self._find_host_returning_data(cmd)
        df = _to_df(bars)
        delta = _category_to_minutes(int(category))
        is_intraday = delta is not None
        df = _apply_bar_time_align_df(
            df,
            is_intraday=is_intraday,
            delta_minutes=delta,
            bar_time=bar_time,
            has_time_columns=True,
        )
        return _merge_bar_datetime(df, not is_intraday)

    async def get_minute_time_data(self, market: Market, code: str) -> pd.DataFrame:
        today = _today_in_shanghai()
        bars = await self._execute(GetHistoryMinuteTimeDataCmd(market, code, today))
        return _add_minute_datetime(_to_df(bars), today)

    async def get_history_minute_time_data(
        self, market: Market, code: str, date: int
    ) -> pd.DataFrame:
        bars = await self._execute(GetHistoryMinuteTimeDataCmd(market, code, date))
        return _add_minute_datetime(_to_df(bars), date)

    async def get_transaction_data(
        self, market: Market, code: str, start: int, count: int = 800
    ) -> pd.DataFrame:
        df = _to_df(await self._execute(GetTransactionDataCmd(market, code, start, count)))
        return _merge_txn_datetime(df, _today_in_shanghai())

    async def get_history_transaction_data(
        self, market: Market, code: str, date: int, start: int, count: int = 800
    ) -> pd.DataFrame:
        df = _to_df(
            await self._execute(GetHistoryTransactionDataCmd(market, code, date, start, count))
        )
        return _merge_txn_datetime(df, date)

    async def get_xdxr_info(self, market: Market, code: str) -> pd.DataFrame:
        return _to_df(await self._execute(GetXdxrInfoCmd(market, code)))

    async def get_finance_info(self, market: Market, code: str) -> pd.DataFrame:
        return _to_df(await self._execute(GetFinanceInfoCmd(market, code)))

    async def get_company_info_category(self, market: Market, code: str) -> pd.DataFrame:
        return _to_df(await self._execute(GetCompanyInfoCategoryCmd(market, code)))

    async def get_company_info_content(
        self, market: Market, code: str, filename: str, offset: int, length: int
    ) -> str:
        return await self._execute(GetCompanyInfoContentCmd(market, code, filename, offset, length))

    async def get_block_info(self, filename: str) -> pd.DataFrame:
        """获取并解析板块文件（行业、概念、风格等）。"""
        size, _hash = await self._execute(GetBlockInfoMetaCmd(filename))
        full_data = bytearray()
        pos = 0
        chunk_size = 30000
        while pos < size:
            chunk = await self._execute(GetBlockInfoCmd(filename, pos, chunk_size))
            if not chunk:
                break
            full_data.extend(chunk)
            pos += len(chunk)
        return _to_df(parse_block_dat(bytes(full_data), filename))

    async def get_report_file(self, filename: str) -> bytes:
        """从服务器拉取大文件。"""
        full_data = bytearray()
        pos = 0
        chunk_size = 30000
        while True:
            chunk = await self._execute(GetReportFileCmd(filename, pos, chunk_size))
            if not chunk:
                break
            full_data.extend(chunk)
            pos += len(chunk)
            if len(chunk) < chunk_size:
                break
        return bytes(full_data)

    @staticmethod
    async def _async_download_from_host(
        host: str, filename: str, port: int = 7709, timeout: float = 15.0
    ) -> bytes:
        """从指定服务器创建临时异步连接并下载文件。"""
        conn = AsyncTdxConnection(host, port, timeout)
        try:
            await conn.connect()
            full_data = bytearray()
            pos = 0
            chunk_size = 30000
            while True:
                chunk = await conn.execute(GetReportFileCmd(filename, pos, chunk_size))
                if not chunk:
                    break
                full_data.extend(chunk)
                pos += len(chunk)
                if len(chunk) < chunk_size:
                    break
            return bytes(full_data)
        finally:
            await conn.close()

    async def get_financial_file_list(self, host: str | None = None) -> pd.DataFrame:
        """获取可用的历史专业财报文件列表（异步）。"""
        if host is None:
            host = get_calc_hosts()[0]
        data = await self._async_download_from_host(host, "tdxfin/gpcw.txt")
        raw_list = parse_financial_file_list(data)
        return _to_df([FinancialFileInfo(filename=f, hash=h, filesize=s) for f, h, s in raw_list])

    async def get_financial_file(self, filename: str, host: str | None = None) -> bytes:
        """从计算服务器下载财报 zip 文件（异步）。"""
        if host is None:
            host = get_calc_hosts()[0]
        return await self._async_download_from_host(host, filename)

    async def get_financial_records(self, filename: str, host: str | None = None) -> pd.DataFrame:
        """下载财报 zip 并解析为记录列表（异步）。"""
        if host is None:
            host = get_calc_hosts()[0]
        import io
        import re
        import zipfile

        zip_data = await self.get_financial_file(filename, host)
        if not zip_data:
            return pd.DataFrame()

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            dat_names = [n for n in zf.namelist() if n.endswith(".dat")]
            if not dat_names:
                return pd.DataFrame()
            dat_data = zf.read(dat_names[0])

        m = re.search(r"(\d{8})", filename)
        report_date = int(m.group(1)) if m else 0

        raw_records = parse_financial_dat(dat_data, report_date)
        records: list[FinancialRecord] = []
        for code, market_byte, rdate, fields in raw_records:
            market = Market.SH if market_byte == 1 else Market.SZ
            records.append(
                FinancialRecord(code=code, market=market, report_date=rdate, fields=fields)
            )
        return _to_df(records)

    async def get_market_stat(self) -> pd.DataFrame:
        """获取 A 股全市场涨跌统计概况（基于 880005/880001/880006 统计指数）。

        通达信这三个"统计指数"的计数类字段（涨/跌/平/总数/涨停/跌停家数）
        返回的是真实家数的 1/10，需统一 ×10 还原。成交额/量/市值字段不受影响。
        `suspended_count` 由 `total - up - down - neutral` 推得，用于保证计数守恒。

        空数据容错：与 sync 版对称——空 quotes 时按延迟顺序逐台实测，找到首台
        返回有效数据的服务器。
        """
        # 通达信中 880005 是全市场行情统计，880001 是总市值指数，880006 是涨跌停统计
        _cmd = GetSecurityQuotesCmd(
            [(Market.SH, "880005"), (Market.SH, "880001"), (Market.SH, "880006")]
        )
        quotes = await self._execute(_cmd)
        if not quotes and self._auto_reconnect:
            quotes = await self._find_host_returning_quotes(_cmd)
        if not quotes:
            raise RuntimeError("无法获取市场统计数据")
        q = quotes[0]
        # 计数字段协议返回值为真实家数 / 10，这里 ×10 还原（见 docstring）
        up = round(q.price * 10)
        down = round(q.open * 10)
        neutral = round(q.low * 10)
        total = round(q.high * 10)
        market_cap = quotes[1].price * 1e10 if len(quotes) > 1 else 0.0
        limit_down = round(quotes[2].open * 10) if len(quotes) > 2 else 0
        limit_up = round(quotes[2].price * 10) if len(quotes) > 2 else 0
        return _to_df(
            MarketStat(
                up_count=up,
                down_count=down,
                neutral_count=neutral,
                suspended_count=max(0, total - up - down - neutral),
                total_count=total,
                total_amount=q.amount,
                total_volume=q.vol,
                total_market_cap=market_cap,
                limit_up_count=limit_up,
                limit_down_count=limit_down,
            )
        )

    async def _find_host_returning_data(self, cmd: "BaseCommand[_T]") -> _T:
        """空数据故障转移（async）：与 sync ``_find_host_returning_data`` 对称。

        泛化版，支持任意可 ``bool()`` 判空的命令返回值（quotes / K 线 bars）。
        """
        bad_host = self._host
        ranked = await asyncio.to_thread(ping_all, get_known_hosts(), self._port, 5.0)

        async def _try(host: str) -> bool:
            await self._areconnect(host)
            # mypy 对 async 闭包内泛型参数的推断会宽化为 BaseCommand[object]
            # （sync 同模式可正确推断），此处为已知 mypy 限制，非真实类型错误。
            return bool(await self._execute(cmd))  # type: ignore[arg-type]

        new_host = await find_working_host_async(ranked, _try, save_best_host, bad_host)
        if new_host is None:
            if self._host != bad_host:
                await self._areconnect(bad_host)
            return []  # type: ignore[return-value]
        return await self._execute(cmd)

    async def _find_host_returning_quotes(
        self, cmd: "BaseCommand[list[SecurityQuote]]"
    ) -> list[SecurityQuote]:
        """空数据故障转移（async quotes 专用薄封装）。"""
        return await self._find_host_returning_data(cmd)

    async def _collect_transaction_records(
        self,
        fetch_page: Callable[[int, int], Awaitable[list[TransactionRecord]]],
        page_size: int,
        max_start: int = 10000,
    ) -> list[TransactionRecord]:
        all_recs: list[TransactionRecord] = []
        seen_sig: set[tuple[int, int, float, int, int, int]] = set()
        seen_page_sigs: set[
            tuple[
                tuple[int, int, float, int, int, int],
                tuple[int, int, float, int, int, int],
            ]
        ] = set()
        start = 0

        while start < max_start:
            recs = await fetch_page(start, page_size)
            if not recs:
                break

            page_sig = _page_signature(recs)
            if page_sig in seen_page_sigs:
                break
            seen_page_sigs.add(page_sig)

            new_count = 0
            for record in recs:
                sig = _record_signature(record)
                if sig not in seen_sig:
                    seen_sig.add(sig)
                    all_recs.append(record)
                    new_count += 1

            if new_count == 0:
                break

            start += len(recs)
            if len(recs) < 100:
                break

        return all_recs

    async def get_fund_flow(self, market: Market, code: str) -> pd.DataFrame:
        """获取个股当日资金流向分布（基于 L1 逐笔数据统计，async）。

        返回列含 ``main_net_inflow``（主力净流入，单位元）。
        口径限制同同步版（Issue #55）：0x0fb5 逐笔为聚合记录、按成交额而非
        挂单额分档，值更接近"主动买卖总失衡"，与东财/同花顺不可比。
        """
        records = await self._collect_transaction_records(
            lambda start, page_size: self._execute(
                GetTransactionDataCmd(market, code, start, page_size)
            ),
            2000,
        )
        return _fund_flow_df_with_net(_to_df(_classify_fund_flow(records)))

    async def _fetch_fund_flow_records(
        self, market: Market, code: str, start: int, count: int
    ) -> list[HistoricalFundFlow]:
        """在当前 host 上获取资金流记录（日 K 线取日期 + 逐笔成交重算，async）。

        同步版说明：无 Category 22 直连（实测全空，Issue #52）；当日 bar 盘中
        走当日实时逐笔接口，收盘清算后走历史逐笔接口。
        返回空列表代表该 host 无 K 线数据（或解析失败）。
        """
        bars = await self._execute(
            GetSecurityBarsCmd(market, code, KlineCategory.DAY, start, count)
        )
        today = _today_in_shanghai()
        results: list[HistoricalFundFlow] = []
        for bar in bars:
            date = _date_from_bar(bar)

            # 用闭包工厂立即绑定 date（审计 #10），避免 lambda 延迟绑定循环变量。
            async def _fetch_page(
                page_start: int, page_size: int, _d: int = date
            ) -> list[TransactionRecord]:
                cmd: BaseCommand[list[TransactionRecord]]
                if _d == today:
                    cmd = GetTransactionDataCmd(market, code, page_start, page_size)
                else:
                    cmd = GetHistoryTransactionDataCmd(market, code, _d, page_start, page_size)
                return await self._execute(cmd)

            records = await self._collect_transaction_records(_fetch_page, 800)
            results.append(_historical_fund_flow_from_records(date, records))
        return results

    async def get_history_fund_flow(
        self, market: Market, code: str, start: int, count: int
    ) -> pd.DataFrame:
        """获取个股历史日线资金流向序列。

        实现："日 K 线取日期 + 逐笔成交重算资金流"；当日 bar 盘中走当日实时
        逐笔接口。返回列含 ``main_net_inflow``（主力净流入，单位元）。

        口径限制同同步版（Issue #55）：0x0fb5 逐笔为聚合记录、按成交额而非
        挂单额分档，值更接近"主动买卖总失衡"，与东财/同花顺不可比。

        空数据故障转移（v1.20.5，Issue #41）：当前 host 无 K 线数据时，
        按延迟顺序逐台实测找首台返回有效数据的服务器。
        """
        results = await self._fetch_fund_flow_records(market, code, start, count)
        if not results and self._auto_reconnect:
            results = await self._fund_flow_failover(market, code, start, count)
        return _fund_flow_df_with_net(_to_df(results))

    async def _fund_flow_failover(
        self, market: Market, code: str, start: int, count: int
    ) -> list[HistoricalFundFlow]:
        """资金流空数据故障转移（async）：逐台实测找首台返回有效数据的服务器。

        与 ``_find_host_returning_data`` 区别：资金流获取涉及多命令（K 线 +
        逐笔），无法用单个 cmd 复用泛化版；这里以内联 ``_try`` 在每台候选上
        跑完整 ``_fetch_fund_flow_records``。
        """
        bad_host = self._host
        ranked = await asyncio.to_thread(ping_all, get_known_hosts(), self._port, 5.0)

        async def _try(host: str) -> bool:
            await self._areconnect(host)
            return bool(await self._fetch_fund_flow_records(market, code, start, count))

        new_host = await find_working_host_async(ranked, _try, save_best_host, bad_host)
        if new_host is None:
            if self._host != bad_host:
                await self._areconnect(bad_host)
            return []
        return await self._fetch_fund_flow_records(market, code, start, count)
