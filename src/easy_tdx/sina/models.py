"""新浪财经数据模型。"""

from __future__ import annotations

from typing import Literal

from easy_tdx.exceptions import TdxError

# 财报三表类型（新浪 API 的 source 参数值）
ReportType = Literal["lrb", "fzb", "llb"]

# 中文别名 → API source 值（CLI/Web 层方便用户）
_REPORT_TYPE_ALIASES: dict[str, str] = {
    "lrb": "lrb",
    "利润表": "lrb",
    "income": "lrb",
    "fzb": "fzb",
    "资产负债表": "fzb",
    "balance": "fzb",
    "llb": "llb",
    "现金流量表": "llb",
    "cashflow": "llb",
}

_REPORT_TYPE_NAMES: dict[str, str] = {
    "lrb": "利润表",
    "fzb": "资产负债表",
    "llb": "现金流量表",
}


def normalize_report_type(s: str) -> str:
    """归一化 report_type 输入：接受 lrb/fzb/llb 及中文/英文别名，返回标准三值之一。

    Raises:
        ValueError: 无法识别的输入。
    """
    key = s.strip().lower() if s.isascii() else s.strip()
    if key in _REPORT_TYPE_ALIASES:
        return _REPORT_TYPE_ALIASES[key]
    raise ValueError(
        f"无法识别的报表类型: {s!r}"
        "（支持 lrb/利润表/income、fzb/资产负债表/balance、llb/现金流量表/cashflow）"
    )


def report_type_name(report_type: str) -> str:
    """报表类型的中文名（用于展示）。"""
    return _REPORT_TYPE_NAMES.get(report_type, report_type)


class SinaError(TdxError):
    """新浪财经数据请求或解析失败。"""
