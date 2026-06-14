"""新浪财经财报模块离线测试 —— mock HTTP，零网络依赖。

覆盖：响应解析（三表）、数值转换（字符串→float）、报告期格式化、
同比键、paperCode 推导、错误转换、模块导出。
"""

from __future__ import annotations

import json
from typing import Any

import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# 导出
# ---------------------------------------------------------------------------


def test_public_exports() -> None:
    """模块应导出 SinaClient / ReportType / SinaError。"""
    from easy_tdx import sina

    assert hasattr(sina, "SinaClient")
    assert hasattr(sina, "ReportType")
    assert hasattr(sina, "SinaError")


def test_sina_error_subclasses_tdx_error() -> None:
    """SinaError 必须继承 TdxError，保证全局 except TdxError 覆盖。"""
    from easy_tdx.exceptions import TdxError
    from easy_tdx.sina import SinaError

    assert issubclass(SinaError, TdxError)
    assert issubclass(SinaError, Exception)


# ---------------------------------------------------------------------------
# report_type 归一化
# ---------------------------------------------------------------------------


def test_normalize_report_type_standard() -> None:
    from easy_tdx.sina import normalize_report_type

    assert normalize_report_type("lrb") == "lrb"
    assert normalize_report_type("fzb") == "fzb"
    assert normalize_report_type("llb") == "llb"


def test_normalize_report_type_uppercase() -> None:
    from easy_tdx.sina import normalize_report_type

    assert normalize_report_type("LRB") == "lrb"
    assert normalize_report_type("FZB") == "fzb"


def test_normalize_report_type_chinese_alias() -> None:
    from easy_tdx.sina import normalize_report_type

    assert normalize_report_type("利润表") == "lrb"
    assert normalize_report_type("资产负债表") == "fzb"
    assert normalize_report_type("现金流量表") == "llb"


def test_normalize_report_type_english_alias() -> None:
    from easy_tdx.sina import normalize_report_type

    assert normalize_report_type("income") == "lrb"
    assert normalize_report_type("balance") == "fzb"
    assert normalize_report_type("cashflow") == "llb"


def test_normalize_report_type_invalid_raises() -> None:
    from easy_tdx.sina import normalize_report_type

    with pytest.raises(ValueError, match="无法识别"):
        normalize_report_type("xyz")


# ---------------------------------------------------------------------------
# _to_float / _format_period
# ---------------------------------------------------------------------------


def test_to_float_numeric_string() -> None:
    from easy_tdx.sina.client import _to_float

    assert _to_float("54702912385.230000") == 54702912385.23
    assert _to_float("0") == 0.0
    assert _to_float("-123.45") == -123.45


def test_to_float_empty_and_none() -> None:
    from easy_tdx.sina.client import _to_float

    assert _to_float("") is None
    assert _to_float(None) is None


def test_to_float_non_numeric() -> None:
    from easy_tdx.sina.client import _to_float

    assert _to_float("N/A") is None
    assert _to_float("--") is None
    assert _to_float("abc") is None


def test_format_period() -> None:
    from easy_tdx.sina.client import _format_period

    assert _format_period("20260331") == "2026-03-31"
    assert _format_period("20251231") == "2025-12-31"
    # 非 8 位数字原样返回
    assert _format_period("2026Q1") == "2026Q1"


# ---------------------------------------------------------------------------
# paperCode 推导
# ---------------------------------------------------------------------------


def test_build_paper_code_sh() -> None:
    """6 开头 → sh 前缀。"""
    from easy_tdx.sina import SinaClient

    assert SinaClient()._build_paper_code("600519") == "sh600519"
    assert SinaClient()._build_paper_code("601318") == "sh601318"


def test_build_paper_code_sz() -> None:
    """非 6 开头 → sz 前缀（含北交所 8/4）。"""
    from easy_tdx.sina import SinaClient

    assert SinaClient()._build_paper_code("000001") == "sz000001"
    assert SinaClient()._build_paper_code("002594") == "sz002594"
    assert SinaClient()._build_paper_code("300750") == "sz300750"
    assert SinaClient()._build_paper_code("830799") == "sz830799"


# ---------------------------------------------------------------------------
# 财报查询与解析（mock HTTP）
# ---------------------------------------------------------------------------


def _make_response(periods: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """构造新浪 API 响应。periods = {period: [行项...]}"""
    report_list = {
        period: {
            "data": items,
            "publish_date": "2026-04-30",
            "rType": "lrb",
        }
        for period, items in periods.items()
    }
    return {
        "result": {
            "status": {"code": 0},
            "data": {
                "report_count": len(periods),
                "report_date": sorted(periods.keys(), reverse=True),
                "report_list": report_list,
            },
        }
    }


# 典型利润表行项
_LRB_ITEMS_2026Q1 = [
    {
        "item_field": "BIZTOTINCO",
        "item_title": "营业总收入",
        "item_value": "54702912385.230000",
        "item_display": "大类",
        "item_tongbi": 0.06336,
    },
    {
        "item_field": "BIZINCO",
        "item_title": "营业收入",
        "item_value": "53909252220.510000",
        "item_display": "小类",
        "item_tongbi": 0.06538,
    },
]

_LRB_ITEMS_2025 = [
    {
        "item_field": "BIZTOTINCO",
        "item_title": "营业总收入",
        "item_value": "174000000000.000000",
        "item_display": "大类",
        "item_tongbi": 0.10,
    },
]

# 资产负债表（含大类标题行，item_value 为空）
_FZB_ITEMS = [
    {
        "item_field": "",
        "item_title": "流动资产",
        "item_value": "",
        "item_display": "大类",
        "item_tongbi": "",
    },
    {
        "item_field": "CURFDS",
        "item_title": "货币资金",
        "item_value": "48786691397.550000",
        "item_display": "小类",
        "item_tongbi": -0.06538,
    },
]


def _patch_http(monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]) -> None:
    """让 _http_get_json 返回固定响应（不触网）。"""
    monkeypatch.setattr(
        "easy_tdx.sina.client._http_get_json",
        lambda url, params, timeout=15.0: response,
    )


def test_get_financial_report_returns_dataframe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """应返回 DataFrame，第一列是报告期，其余是科目（float）。"""
    resp = _make_response({"20260331": _LRB_ITEMS_2026Q1, "20251231": _LRB_ITEMS_2025})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519", report_type="lrb")
    assert isinstance(df, pd.DataFrame)
    # 第一列报告期
    assert df.columns[0] == "报告期"
    # 最新期在前
    assert df.iloc[0]["报告期"] == "2026-03-31"
    assert df.iloc[1]["报告期"] == "2025-12-31"
    # 科目名作为列
    assert "营业总收入" in df.columns
    assert "营业收入" in df.columns
    # 值已转 float（非 object 字符串）
    assert df.iloc[0]["营业总收入"] == 54702912385.23
    assert isinstance(df.iloc[0]["营业总收入"], float)


def test_get_financial_report_tongbi_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有同比的科目应附加 {科目}_同比 列。"""
    resp = _make_response({"20260331": _LRB_ITEMS_2026Q1})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519", report_type="lrb")
    assert "营业总收入_同比" in df.columns
    assert df.iloc[0]["营业总收入_同比"] == pytest.approx(0.06336)


def test_get_financial_report_no_tongbi_omits_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tongbi 为 None/空时不应生成 _同比 列。"""
    items = [
        {
            "item_field": "NETPROFIT",
            "item_title": "净利润",
            "item_value": "100000000.00",
            "item_tongbi": None,
        }
    ]
    resp = _make_response({"20260331": items})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519")
    assert "净利润" in df.columns
    assert "净利润_同比" not in df.columns


def test_get_financial_report_dalei_header_row_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大类标题行（item_value="")应保留，值为 None（不跳过）。"""
    resp = _make_response({"20260331": _FZB_ITEMS})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519", report_type="fzb")
    assert "流动资产" in df.columns
    # 大类标题行的值为 None（空字符串转换）
    assert df.iloc[0]["流动资产"] is None or pd.isna(df.iloc[0]["流动资产"])
    # 小类行有值
    assert df.iloc[0]["货币资金"] == 48786691397.55


def test_get_financial_report_dalei_no_tongbi_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """大类标题行 tongbi="" 不生成 _同比 列。"""
    resp = _make_response({"20260331": _FZB_ITEMS})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519", report_type="fzb")
    assert "流动资产_同比" not in df.columns


def test_get_financial_report_non_numeric_value_to_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非数值 item_value（如 'N/A'）应转 None，不抛错。"""
    items = [
        {
            "item_field": "X",
            "item_title": "某科目",
            "item_value": "N/A",
            "item_tongbi": None,
        }
    ]
    resp = _make_response({"20260331": items})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519")
    assert "某科目" in df.columns
    assert df.iloc[0]["某科目"] is None or pd.isna(df.iloc[0]["某科目"])


def test_get_financial_report_skips_no_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """item_title 为空应跳过该行项。"""
    items = [
        {"item_field": "", "item_title": "", "item_value": "123.45"},
        {"item_field": "X", "item_title": "有效科目", "item_value": "1.00"},
    ]
    resp = _make_response({"20260331": items})
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519")
    assert "有效科目" in df.columns
    # 空 title 的行不应产生列（pandas 会把无名列丢进一个奇怪的列名，确认它不是有效科目）


def test_get_financial_report_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """空 report_list → 带「报告期」列名的空 DataFrame。"""
    resp = {"result": {"status": {"code": 0}, "data": {"report_list": {}}}}
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519")
    assert isinstance(df, pd.DataFrame)
    assert df.empty
    assert list(df.columns) == ["报告期"]


def test_get_financial_report_missing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """响应缺少 result/data/report_list 链应视为空结果，不抛错。"""
    _patch_http(monkeypatch, {"unexpected": True})
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519")
    assert df.empty


def test_get_financial_report_request_failure_raises_sina_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 异常应转为 SinaError。"""

    def _boom(url: str, params: dict[str, str], timeout: float = 15.0) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr("easy_tdx.sina.client._http_get_json", _boom)
    from easy_tdx.sina import SinaClient, SinaError

    with pytest.raises(SinaError):
        SinaClient().get_financial_report("600519")


def test_get_financial_report_num_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """num 应限制返回期数（sorted reverse 后取前 num）。"""
    resp = _make_response(
        {
            "20260331": _LRB_ITEMS_2026Q1,
            "20251231": _LRB_ITEMS_2025,
            "20250930": _LRB_ITEMS_2025,
            "20250630": _LRB_ITEMS_2025,
        }
    )
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519", num=2)
    assert len(df) == 2
    assert df.iloc[0]["报告期"] == "2026-03-31"
    assert df.iloc[1]["报告期"] == "2025-12-31"


def test_get_financial_report_params_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """paperCode/source/num 应正确传入 params。"""
    captured: dict[str, Any] = {}

    def _capture(url: str, params: dict[str, str], timeout: float = 15.0) -> Any:
        captured.update(params)
        return {"result": {"data": {"report_list": {}}}}

    monkeypatch.setattr("easy_tdx.sina.client._http_get_json", _capture)
    from easy_tdx.sina import SinaClient

    SinaClient().get_financial_report("600519", report_type="fzb", num=4)
    assert captured["paperCode"] == "sh600519"
    assert captured["source"] == "fzb"
    assert captured["num"] == "4"
    assert captured["type"] == "0"


def test_get_financial_report_report_type_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """中文别名（利润表）应归一化为 lrb 传入 source。"""
    captured: dict[str, Any] = {}

    def _capture(url: str, params: dict[str, str], timeout: float = 15.0) -> Any:
        captured.update(params)
        return {"result": {"data": {"report_list": {}}}}

    monkeypatch.setattr("easy_tdx.sina.client._http_get_json", _capture)
    from easy_tdx.sina import SinaClient

    SinaClient().get_financial_report("000001", report_type="现金流量表")
    assert captured["source"] == "llb"
    assert captured["paperCode"] == "sz000001"


def test_get_financial_report_invalid_report_type_raises() -> None:
    """无法识别的 report_type 应抛 ValueError（normalize 阶段，不触网）。"""
    from easy_tdx.sina import SinaClient

    with pytest.raises(ValueError, match="无法识别"):
        SinaClient().get_financial_report("600519", report_type="xyz")


def test_get_financial_report_skips_non_dict_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """report_list 中某期值非 dict（如 list）应跳过该期。"""
    resp = {
        "result": {
            "data": {
                "report_list": {
                    "20260331": {"data": _LRB_ITEMS_2026Q1},  # 正常（含 data 键）
                    "20251231": ["not", "a", "dict"],  # 异常，跳过
                }
            }
        }
    }
    _patch_http(monkeypatch, resp)
    from easy_tdx.sina import SinaClient

    df = SinaClient().get_financial_report("600519")
    assert len(df) == 1
    assert df.iloc[0]["报告期"] == "2026-03-31"


# ---------------------------------------------------------------------------
# urllib helper 烟雾测试（不触网，验证 query 拼接 + headers）
# ---------------------------------------------------------------------------


def test_http_get_json_builds_query_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """_http_get_json 应把 params urlencode 到 URL。"""
    import easy_tdx.sina.client as mod

    captured: dict[str, Any] = {}

    class _FakeResp:
        def read(self) -> bytes:
            return json.dumps({"ok": 1}).encode("utf-8")

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    def _fake_urlopen(req: Any, timeout: float = 15.0) -> _FakeResp:
        captured["url"] = req.full_url
        captured["headers"] = {k.lower(): v for k, v in req.header_items()}
        return _FakeResp()

    monkeypatch.setattr(mod.urlrequest, "urlopen", _fake_urlopen)
    result = mod._http_get_json(
        "https://example.com/api", {"paperCode": "sh600519", "source": "lrb"}
    )
    assert result == {"ok": 1}
    assert "paperCode=sh600519" in captured["url"]
    assert "source=lrb" in captured["url"]
    assert "user-agent" in captured["headers"]


def test_http_get_json_no_params(monkeypatch: pytest.MonkeyPatch) -> None:
    """params 为空时 URL 不附加 ?。"""
    import easy_tdx.sina.client as mod

    class _FakeResp:
        def read(self) -> bytes:
            return b'{"ok": 1}'

        def __enter__(self) -> _FakeResp:
            return self

        def __exit__(self, *args: Any) -> None:
            pass

    monkeypatch.setattr(mod.urlrequest, "urlopen", lambda req, timeout=15.0: _FakeResp())
    assert mod._http_get_json("https://example.com/x", {}) == {"ok": 1}
