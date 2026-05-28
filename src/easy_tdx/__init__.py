"""easy_tdx — 通达信 TCP 协议 A 股行情数据客户端。

快速开始::

    from easy_tdx import TdxClient, Market, KlineCategory

    with TdxClient("180.153.18.170") as c:
        count = c.get_security_count(Market.SH)
        bars  = c.get_security_bars(Market.SH, "600000", KlineCategory.DAY, 0, 5)

asyncio 版本::

    import asyncio
    from easy_tdx import AsyncTdxClient, Market, KlineCategory

    async def main():
        async with AsyncTdxClient("180.153.18.170") as c:
            bars = await c.get_security_bars(Market.SH, "600000", KlineCategory.DAY, 0, 5)

    asyncio.run(main())
"""

from .client import AsyncTdxClient, TdxClient
from .config import save_best_ex_host, save_best_host
from .ex.client import AsyncExTdxClient, ExTdxClient
from .ex.mac_client import AsyncMacExClient, MacExClient
from .ex.models import KNOWN_EX_HOSTS
from .exceptions import TdxCommandError, TdxConnectionError, TdxDecodeError, TdxError
from .mac.client import AsyncMacClient, MacClient
from .mac.enums import (
    Adjust,
    BoardType,
    Category,
    ExMarket,
    FilterType,
    Period,
    SortOrder,
    SortType,
)
from .models import (
    XDXR_CATEGORY_NAMES,
    CompanyInfoCategory,
    FinanceInfo,
    FinancialFileInfo,
    FinancialRecord,
    KlineCategory,
    Market,
    MinuteBar,
    SecurityBar,
    SecurityInfo,
    SecurityQuote,
    TransactionRecord,
    XdxrRecord,
)
from .transport.sync import CALC_HOSTS, KNOWN_HOSTS, MAC_HOSTS, ping_all, ping_mac_all
from .unified import AsyncUnifiedTdxClient, UnifiedTdxClient

__all__ = [
    # 客户端
    "TdxClient",
    "AsyncTdxClient",
    "MacClient",
    "AsyncMacClient",
    "MacExClient",
    "AsyncMacExClient",
    "UnifiedTdxClient",
    "AsyncUnifiedTdxClient",
    # 枚举
    "Market",
    "KlineCategory",
    "Adjust",
    "BoardType",
    "Category",
    "ExMarket",
    "FilterType",
    "Period",
    "SortOrder",
    "SortType",
    # 数据模型
    "SecurityBar",
    "SecurityQuote",
    "SecurityInfo",
    "MinuteBar",
    "TransactionRecord",
    "XdxrRecord",
    "XDXR_CATEGORY_NAMES",
    "FinanceInfo",
    "CompanyInfoCategory",
    "FinancialFileInfo",
    "FinancialRecord",
    # 异常
    "TdxError",
    "TdxConnectionError",
    "TdxDecodeError",
    "TdxCommandError",
    # 扩展行情
    "ExTdxClient",
    "AsyncExTdxClient",
    "KNOWN_EX_HOSTS",
    # 工具
    "ping_all",
    "ping_mac_all",
    "KNOWN_HOSTS",
    "CALC_HOSTS",
    "MAC_HOSTS",
    "save_best_host",
    "save_best_ex_host",
]

__version__ = "1.4.0"
