"""新浪财经财报三表客户端。

独立于 TDX 协议的 HTTP 数据源（标准库 urllib，零额外依赖）。
公开方法返回 ``pd.DataFrame``，遵循项目 ``get_*`` 约定。

新浪财报接口 ``CompanyFinanceService.getFinanceReport2022`` 返回结构::

    result.data.report_list = { "20260331": { "data": [行项...] }, ... }
                                  ↑ 报告期(YYYYMMDD) 为键，倒序排列

每行项含 ``item_title``（科目名）/ ``item_value``（字符串数值）/ ``item_tongbi``
（同比比例，如 0.06336 = +6.3%）/ ``item_display``（大类/小类）。

参考脚本的 bug：``item_value`` 是字符串（如 "54702912385.230000"），
直接存入 DataFrame 导致列是 object 类型无法数值计算。本实现转 float，
空字符串/非数值转 None（保留行，因为大类标题行有价值）。
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib import parse
from urllib import request as urlrequest

import pandas as pd

from .models import ReportType, SinaError, normalize_report_type

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_API_URL = "https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022"


def _http_get_json(url: str, params: dict[str, str], timeout: float = 15.0) -> Any:
    """GET JSON，自动 urlencode query 参数（stdlib urllib，monkeypatch 点）。"""
    full = f"{url}?{parse.urlencode(params)}" if params else url
    req = urlrequest.Request(full, headers={"User-Agent": _UA})
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _to_float(v: Any) -> float | None:
    """item_value 字符串转 float，空/非数值返回 None。"""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _format_period(period: str) -> str:
    """``20260331`` → ``2026-03-31``。"""
    if len(period) == 8 and period.isdigit():
        return f"{period[:4]}-{period[4:6]}-{period[6:8]}"
    return period


class SinaClient:
    """新浪财经财报检索客户端（无状态 HTTP，无需 connect/close）。

    用法::

        from easy_tdx.sina import SinaClient

        client = SinaClient()
        # 利润表（默认 8 期，最新在前）
        df = client.get_financial_report("600519", report_type="lrb")
        # → DataFrame，每行一期，列 = [报告期, 营业总收入, 营业总收入_同比, ...]
    """

    def __init__(self, *, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def _build_paper_code(self, code: str) -> str:
        """6 位代码 → 新浪 paperCode（sh/sz 前缀）。"""
        prefix = "sh" if code.startswith("6") else "sz"
        return f"{prefix}{code}"

    def get_financial_report(
        self,
        code: str,
        report_type: ReportType | str = "lrb",
        *,
        num: int = 8,
    ) -> pd.DataFrame:
        """获取财报三表数据。

        Args:
            code: 6 位股票代码（不含市场前缀），如 ``600519``。
            report_type: 报表类型，标准值 ``lrb``（利润表）/ ``fzb``（资产负债表）/
                ``llb``（现金流量表），也接受中文/英文别名（如 ``利润表``/``income``）。
            num: 取最近 N 期（默认 8）。

        Returns:
            ``DataFrame``，每行一期报告（最新在前）。

            - 第一列 ``报告期``（``YYYY-MM-DD`` 格式）
            - 其余列为科目名（如 ``营业总收入``），值为 float
            - 有同比数据的科目附加 ``{科目}_同比`` 列（float 比例值，如 0.06336 = +6.3%）

            大类标题行（如 ``流动资产``）的 ``item_value`` 为 None（保留行以反映报表结构）。
            无结果时返回空 DataFrame（含 ``报告期`` 列名）。
        """
        rt = normalize_report_type(str(report_type))
        rows = self._query(code, rt, num=num)
        if not rows:
            return pd.DataFrame(columns=["报告期"])
        return pd.DataFrame(rows)

    def _query(self, code: str, report_type: str, *, num: int) -> list[dict[str, Any]]:
        """调用新浪 API，解析为「按报告期」的行列表。

        整个 HTTP + 解析过程统一捕获异常并转为 ``SinaError``。
        """
        paper_code = self._build_paper_code(code)
        params = {
            "paperCode": paper_code,
            "source": report_type,
            "type": "0",
            "page": "1",
            "num": str(num),
        }
        try:
            d = _http_get_json(_API_URL, params, timeout=self.timeout)
            report_list = (
                d.get("result", {}).get("data", {}).get("report_list", {})
                if isinstance(d, dict)
                else {}
            )
            if not report_list:
                return []

            rows: list[dict[str, Any]] = []
            # 按报告期倒序，取最近 num 期
            for period in sorted(report_list.keys(), reverse=True)[:num]:
                obj = report_list[period]
                if not isinstance(obj, dict):
                    continue
                rec: dict[str, Any] = {"报告期": _format_period(period)}
                for it in obj.get("data", []) or []:
                    if not isinstance(it, dict):
                        continue
                    title = it.get("item_title", "")
                    if not title:
                        continue
                    # item_value 字符串转 float（空/非数值 → None，保留行）
                    rec[title] = _to_float(it.get("item_value"))
                    tongbi = it.get("item_tongbi")
                    if tongbi not in (None, ""):
                        tb = _to_float(tongbi)
                        if tb is not None:
                            rec[f"{title}_同比"] = tb
                rows.append(rec)
            return rows
        except SinaError:
            raise
        except Exception as e:  # noqa: BLE001 — HTTP/JSON/解析统一转领域异常
            raise SinaError(f"新浪财报查询失败: {e}") from e
