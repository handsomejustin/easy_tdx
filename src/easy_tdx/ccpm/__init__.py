"""中金所成交持仓排名（ccpm）——官网每日成交/持仓前 20 名会员数据。

独立于 TDX 协议的 HTTP 数据源（中金所官网），无需连接行情服务器。

用法::

    from easy_tdx.ccpm import CcpmClient

    client = CcpmClient()
    df = client.get_rank("IF", "2026-09-02")  # 指定交易日
    df = client.latest_rank("IF")             # 自动回溯最近有数据的交易日
"""

from .client import WIDE_COLUMNS, CcpmClient, normalize_date, parse_xml
from .models import (
    PRODUCT_CODES,
    PRODUCTS,
    CcpmError,
    CcpmNoDataError,
    ProductMeta,
    list_products,
    normalize_product,
)

__all__ = [
    "CcpmClient",
    "CcpmError",
    "CcpmNoDataError",
    "PRODUCTS",
    "PRODUCT_CODES",
    "ProductMeta",
    "WIDE_COLUMNS",
    "list_products",
    "normalize_date",
    "normalize_product",
    "parse_xml",
]
