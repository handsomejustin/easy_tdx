"""新浪财经财报三表 —— 独立于 TDX 协议的 HTTP 数据源。

零额外依赖（标准库 urllib），无需连接 TDX 服务器即可使用。

支持三表：
- ``lrb`` 利润表
- ``fzb`` 资产负债表
- ``llb`` 现金流量表

用法::

    from easy_tdx.sina import SinaClient

    client = SinaClient()
    # 利润表（默认 8 期）
    df = client.get_financial_report("600519", report_type="lrb")
    # → DataFrame，每行一期，列 = [报告期, 营业总收入, 营业总收入_同比, ...]
"""

from __future__ import annotations

from .client import SinaClient
from .models import ReportType, SinaError, normalize_report_type, report_type_name

__all__ = [
    "SinaClient",
    "ReportType",
    "SinaError",
    "normalize_report_type",
    "report_type_name",
]
