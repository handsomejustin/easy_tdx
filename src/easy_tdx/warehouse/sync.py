"""仓库增量同步器（v1.26 新增）。

从 MAC 客户端拉取行情补入 :class:`~easy_tdx.warehouse.store.KlineWarehouse`：

- **首同步全量**：仓库无该标的数据时按 ``max_bars``（默认 8000 根）拉取；
- **增量补缺**：已有数据时只拉最近 ``tail_bars``（默认 15 根）覆盖——
  覆盖同日 bar（收盘价修正 / provisional 转正），不动更早历史；
- 同步前自动 :meth:`promote_provisional`（过期临时行转正）。

客户端只需具备 ``get_stock_kline(market:int, code, period, start, count,
adjust)`` 签名（``MacClient`` / ``AsyncMacClient`` 均可，本同步器只用同步
调用——CLI 在主线程使用；serve 的 async 环境请在后台线程调用）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from easy_tdx.warehouse.store import MARKET_TO_TDX, KlineWarehouse

logger = logging.getLogger(__name__)

__all__ = ["WarehouseSyncer", "SyncSummary"]


class SyncSummary(dict[str, Any]):
    """批次同步结果（dict 语义，键见 :meth:`WarehouseSyncer.sync`）。"""


def _period_name(period: str) -> str:
    """归一化周期名为仓库 period 键（与客户端 Period 枚举名对齐）。"""
    return period.upper()


class WarehouseSyncer:
    """把客户端行情增量同步进仓库。

    Example::
        with get_mac_client() as client:
            syncer = WarehouseSyncer(client, warehouse)
            summary = syncer.sync(["SH:600519", "SZ:000001"])
            print(summary["added"], summary["updated"])
    """

    def __init__(
        self,
        client: Any,
        warehouse: KlineWarehouse,
        max_bars: int = 8000,
        tail_bars: int = 15,
        adjust: str = "QFQ",
    ) -> None:
        """Initialize.

        Args:
            client: 行情客户端（需有 ``get_stock_kline``）。
            warehouse: 目标仓库。
            max_bars: 首同步（仓库为空时）的最大拉取根数。
            tail_bars: 增量同步拉取的尾部根数（覆盖近几日的修正）。
            adjust: 复权方式（默认 ``"QFQ"`` 前复权——回测/筛选口径；
                注意仓库按 period+adjust 隐含统一，混存不同复权口径需
                分开仓库文件）。
        """
        self._client = client
        self._wh = warehouse
        self._max_bars = max(int(max_bars), 800)
        self._tail_bars = max(int(tail_bars), 5)
        self._adjust = adjust

    def sync_symbol(
        self,
        market: str,
        code: str,
        period: str = "DAILY",
    ) -> dict[str, Any]:
        """同步单个标的，返回 ``{symbol, added, updated, skipped, error}``。"""
        symbol = f"{market}:{code}"
        try:
            existing_last = self._wh.last_datetime(market, code, period)
            count = self._tail_bars if existing_last is not None else self._max_bars
            df = self._client.get_stock_kline(
                MARKET_TO_TDX[market.upper()],
                code,
                period=period,
                start=0,
                count=count,
                adjust=self._adjust,
            )
            if df is None or len(df) == 0:
                return {"symbol": symbol, "added": 0, "updated": 0, "skipped": 1, "error": None}
            added, updated = self._wh.upsert_bars(market, code, df, period=period)
            return {
                "symbol": symbol,
                "added": added,
                "updated": updated,
                "skipped": 0,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 — 单标失败不中断批次
            logger.warning("仓库同步 %s 失败：%s", symbol, exc)
            return {"symbol": symbol, "added": 0, "updated": 0, "skipped": 1, "error": str(exc)}

    def sync(
        self,
        symbols: list[str] | list[tuple[str, str]],
        period: str = "DAILY",
        progress: Callable[[int, int, str], None] | None = None,
    ) -> SyncSummary:
        """批量同步，返回汇总。

        Args:
            symbols: ``["SH:600519", ...]`` 或 ``[("SH", "600519"), ...]``。
            period: K 线周期（默认日线）。
            progress: 进度回调 ``progress(done, total, symbol)``。

        Returns:
            ``{"total", "ok", "added", "updated", "skipped", "failed", "details"}``。
        """
        self._wh.promote_provisional()
        p = _period_name(period)

        parsed: list[tuple[str, str]] = []
        for s in symbols:
            if isinstance(s, str):
                mkt, cde = s.split(":", 1)
                parsed.append((mkt.strip().upper(), cde.strip()))
            else:
                parsed.append((s[0].upper(), s[1]))

        details: list[dict[str, Any]] = []
        added = updated = skipped = failed = 0
        for i, (mkt, cde) in enumerate(parsed, 1):
            if progress is not None:
                progress(i, len(parsed), f"{mkt}:{cde}")
            r = self.sync_symbol(mkt, cde, p)
            details.append(r)
            added += r["added"]
            updated += r["updated"]
            if r["error"]:
                failed += 1
            elif r["skipped"]:
                skipped += 1
        return SyncSummary(
            {
                "total": len(parsed),
                "ok": len(parsed) - failed - skipped,
                "added": added,
                "updated": updated,
                "skipped": skipped,
                "failed": failed,
                "details": details,
            }
        )
