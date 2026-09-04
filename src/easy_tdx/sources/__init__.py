"""备选数据源（自动兜底）。

- :mod:`easy_tdx.sources.baostock`：baostock EOD 兜底源（TDX 全部路径失败时
  的最后一级回退，仅日线及以上）。
- :class:`AutoKlineClient`：TDX 优先、备选源兜底的组合客户端，供
  ``WarehouseSyncer`` 等只认 ``get_stock_kline`` 协议的组件使用。
"""

from __future__ import annotations

from typing import Any

import pandas as pd

__all__ = ["AutoKlineClient"]


class AutoKlineClient:
    """TDX 优先、备选源兜底的组合 K 线客户端。

    满足 ``get_stock_kline(market:int, code, **kwargs)`` 协议：primary 出错
    **或返回空**时自动转 fallback；fallback 的结果（或异常）直接透传——
    异常信息通常带安装提示（如 baostock 未安装），便于上层定位。

    Example::

        client = AutoKlineClient(mac_client, BaostockClient())
        syncer = WarehouseSyncer(client, warehouse)
    """

    def __init__(self, primary: Any, fallback: Any) -> None:
        self._primary = primary
        self._fallback = fallback

    def get_stock_kline(self, market: int, code: str, **kwargs: Any) -> pd.DataFrame:
        try:
            df = self._primary.get_stock_kline(market, code, **kwargs)
            if df is not None and len(df) > 0:
                return df
        except Exception:  # noqa: BLE001 — 主源失败是兜底触发的正常路径
            pass
        return self._fallback.get_stock_kline(market, code, **kwargs)
