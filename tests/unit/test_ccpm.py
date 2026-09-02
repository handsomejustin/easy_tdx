"""中金所成交持仓排名（ccpm）离线测试 —— mock HTTP，零网络依赖。

覆盖：XML 解析（长表→宽表对齐）、按日缓存读写、非交易日 302 语义、
日期/品种归一化、latest_rank 自动回溯、品种元数据完整性、
Web 路由（/ccpm/products、/ccpm/rank）与 CLI 命令。
"""

from __future__ import annotations

import json
from datetime import date

import pytest

# ---------------------------------------------------------------------------
# 测试夹具：最小 positionRank XML（1 个合约 × 3 类排名 × 前 2 名）
# ---------------------------------------------------------------------------

_SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<positionRank>
  <data Value="1" Text="IF2609">
    <instrumentid>IF2609</instrumentid><tradingday>20260902</tradingday>
    <datatypeid>0</datatypeid><rank>1</rank>
    <shortname>甲期货(代客)</shortname><volume>100</volume><varvolume>10</varvolume>
    <partyid>0001</partyid><productid>IF</productid>
  </data>
  <data Value="1" Text="IF2609">
    <instrumentid>IF2609</instrumentid><tradingday>20260902</tradingday>
    <datatypeid>0</datatypeid><rank>2</rank>
    <shortname>乙期货(代客)</shortname><volume>80</volume><varvolume>-5</varvolume>
    <partyid>0002</partyid><productid>IF</productid>
  </data>
  <data Value="1" Text="IF2609">
    <instrumentid>IF2609</instrumentid><tradingday>20260902</tradingday>
    <datatypeid>1</datatypeid><rank>1</rank>
    <shortname>丙期货(代客)</shortname><volume>220</volume><varvolume>-7</varvolume>
    <partyid>0003</partyid><productid>IF</productid>
  </data>
  <data Value="1" Text="IF2609">
    <instrumentid>IF2609</instrumentid><tradingday>20260902</tradingday>
    <datatypeid>1</datatypeid><rank>2</rank>
    <shortname>甲期货(代客)</shortname><volume>180</volume><varvolume>0</varvolume>
    <partyid>0001</partyid><productid>IF</productid>
  </data>
  <data Value="1" Text="IF2609">
    <instrumentid>IF2609</instrumentid><tradingday>20260902</tradingday>
    <datatypeid>2</datatypeid><rank>1</rank>
    <shortname>乙期货(代客)</shortname><volume>150</volume><varvolume>3</varvolume>
    <partyid>0002</partyid><productid>IF</productid>
  </data>
  <data Value="1" Text="IF2609">
    <instrumentid>IF2609</instrumentid><tradingday>20260902</tradingday>
    <datatypeid>2</datatypeid><rank>2</rank>
    <shortname>丙期货(代客)</shortname><volume>90</volume><varvolume>-2</varvolume>
    <partyid>0003</partyid><productid>IF</productid>
  </data>
</positionRank>
"""


@pytest.fixture()
def isolated_config(tmp_path, monkeypatch):
    """缓存目录隔离到 tmp_path（EASY_TDX_CONFIG_DIR 约定）。"""
    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path))
    return tmp_path


def _mock_fetch(monkeypatch, sample: str = _SAMPLE_XML):
    """把 _fetch_xml 替换为返回固定 XML，并记录调用 URL。"""
    from easy_tdx.ccpm import client as ccpm_client

    calls: list[str] = []

    def fake(url: str, timeout: float) -> str:
        calls.append(url)
        return sample

    monkeypatch.setattr(ccpm_client, "_fetch_xml", fake)
    return calls


# ---------------------------------------------------------------------------
# 领域异常与导出
# ---------------------------------------------------------------------------


def test_error_hierarchy() -> None:
    """CcpmError/CcpmNoDataError 必须继承 TdxError（全局 except 覆盖）。"""
    from easy_tdx.ccpm import CcpmError, CcpmNoDataError
    from easy_tdx.exceptions import TdxError

    assert issubclass(CcpmError, TdxError)
    assert issubclass(CcpmNoDataError, CcpmError)


def test_public_exports() -> None:
    from easy_tdx import ccpm

    for name in ("CcpmClient", "CcpmError", "CcpmNoDataError", "PRODUCTS", "list_products"):
        assert hasattr(ccpm, name)


# ---------------------------------------------------------------------------
# 品种元数据
# ---------------------------------------------------------------------------


def test_products_meta_complete() -> None:
    """8 个品种：股指 4 + 国债 4，字段非空，股指带指数代码。"""
    from easy_tdx.ccpm import PRODUCTS, list_products

    assert list(PRODUCTS) == ["IF", "IH", "IC", "IM", "TS", "TF", "T", "TL"]
    metas = list_products()
    assert len(metas) == 8
    for m in metas:
        for field in ("code", "name", "category", "underlying", "unit", "intro"):
            assert m[field], f"{m['code']} 缺少 {field}"
    assert sum(1 for m in metas if m["category"] == "股指期货") == 4
    assert sum(1 for m in metas if m["category"] == "国债期货") == 4
    # 股指期货必须给出对应指数代码，国债期货为空串
    assert PRODUCTS["IF"].underlying_code == "000300"
    assert PRODUCTS["TL"].underlying_code == ""


def test_normalize_product_case_insensitive() -> None:
    from easy_tdx.ccpm import normalize_product

    assert normalize_product("if").code == "IF"
    assert normalize_product(" Tl ").code == "TL"
    with pytest.raises(ValueError, match="未知品种"):
        normalize_product("XX")


# ---------------------------------------------------------------------------
# XML 解析：长表 → 宽表对齐
# ---------------------------------------------------------------------------


def test_parse_xml_wide_alignment() -> None:
    from easy_tdx.ccpm import WIDE_COLUMNS, parse_xml

    rows = parse_xml(_SAMPLE_XML)
    assert len(rows) == 2  # 1 合约 × rank 1..2
    assert set(rows[0]) == set(WIDE_COLUMNS)
    r1 = rows[0]
    assert r1["instrument"] == "IF2609"
    assert r1["trading_day"] == "20260902"
    assert r1["product"] == "IF"
    assert r1["rank"] == 1
    # 三类排名各自独立取自对应 datatypeid
    assert r1["vol_member"] == "甲期货(代客)" and r1["vol"] == 100 and r1["vol_chg"] == 10
    assert r1["long_member"] == "丙期货(代客)" and r1["long_pos"] == 220 and r1["long_chg"] == -7
    assert r1["short_member"] == "乙期货(代客)" and r1["short_pos"] == 150 and r1["short_chg"] == 3
    r2 = rows[1]
    assert r2["rank"] == 2 and r2["long_chg"] == 0 and r2["short_chg"] == -2


def test_parse_xml_missing_cell_fills_none() -> None:
    """某类型缺某排名时对应单元格为 None，不丢行、不错位。"""
    from easy_tdx.ccpm import parse_xml

    # 只有 datatypeid=0 的 rank1，其余类型缺失
    partial = _SAMPLE_XML.replace(
        "<datatypeid>1</datatypeid>", "<datatypeid>9</datatypeid>"
    ).replace("<datatypeid>2</datatypeid>", "<datatypeid>9</datatypeid>")
    rows = parse_xml(partial)
    assert rows
    assert rows[0]["vol"] == 100
    assert rows[0]["long_member"] is None and rows[0]["long_pos"] is None
    assert rows[0]["short_member"] is None and rows[0]["short_pos"] is None


def test_parse_xml_error_page_raises() -> None:
    from easy_tdx.ccpm import CcpmError, parse_xml

    with pytest.raises(CcpmError, match="XML 解析失败"):
        parse_xml("404 page，非 XML 内容")


# ---------------------------------------------------------------------------
# 日期归一化
# ---------------------------------------------------------------------------


def test_normalize_date_formats() -> None:
    from easy_tdx.ccpm import normalize_date

    assert normalize_date("2026-09-02") == date(2026, 9, 2)
    assert normalize_date("20260902") == date(2026, 9, 2)
    assert normalize_date(date(2026, 9, 2)) == date(2026, 9, 2)
    with pytest.raises(ValueError, match="日期格式"):
        normalize_date("2026/9/2")


# ---------------------------------------------------------------------------
# CcpmClient：抓取 + 按日缓存 + 无数据语义
# ---------------------------------------------------------------------------


def test_get_rank_fetch_and_columns(isolated_config, monkeypatch) -> None:
    from easy_tdx.ccpm import CcpmClient

    calls = _mock_fetch(monkeypatch)
    df = CcpmClient().get_rank("IF", "2026-09-02")
    assert len(df) == 2
    assert df["instrument"].tolist() == ["IF2609", "IF2609"]
    assert df["vol"].tolist() == [100, 80]
    # URL 按官网协议拼装：月份/日零填充，无 ?id= 缓存戳
    assert calls == ["http://www.cffex.com.cn/sj/ccpm/202609/02/IF.xml"]


def test_cache_hit_skips_network(isolated_config, monkeypatch) -> None:
    """第二次查询同 (日期, 品种) 应命中文件缓存，零网络。"""
    from easy_tdx.ccpm import CcpmClient
    from easy_tdx.ccpm import client as ccpm_client

    calls = _mock_fetch(monkeypatch)
    c = CcpmClient()
    c.get_rank("IF", "2026-09-02")
    assert len(calls) == 1

    # 网络层改为必炸：仍能取到数据 = 走了缓存
    monkeypatch.setattr(
        ccpm_client,
        "_fetch_xml",
        lambda url, timeout: (_ for _ in ()).throw(AssertionError("不应联网")),
    )
    df2 = c.get_rank("IF", "2026-09-02")
    assert len(df2) == 2

    # refresh=True 强制重新联网
    calls2 = _mock_fetch(monkeypatch)
    c.get_rank("IF", "2026-09-02", refresh=True)
    assert len(calls2) == 1


def test_no_data_error_from_redirect(isolated_config, monkeypatch) -> None:
    """官网非交易日 302 → error_404：走真实 _fetch_xml 的 302 翻译逻辑。"""
    from urllib.error import HTTPError

    from easy_tdx.ccpm import CcpmClient, CcpmNoDataError
    from easy_tdx.ccpm import client as ccpm_client

    def fake_open(req, timeout=None):  # noqa: ANN001, ANN202
        raise HTTPError(req.full_url, 302, "Found", None, None)  # type: ignore[arg-type]

    monkeypatch.setattr(ccpm_client._OPENER, "open", fake_open)
    with pytest.raises(CcpmNoDataError, match="非交易日"):
        CcpmClient().get_rank("IF", "2026-08-29")


def test_latest_rank_walks_back(isolated_config, monkeypatch) -> None:
    """自动回溯：今天无数据 → 往前一天命中。"""
    from easy_tdx.ccpm import CcpmClient, CcpmNoDataError
    from easy_tdx.ccpm import client as ccpm_client
    from easy_tdx.ccpm.client import _today_shanghai

    today = _today_shanghai()
    calls: list[str] = []

    def fake(url: str, timeout: float) -> str:
        calls.append(url)
        # 今天的 URL 抛无数据，昨天返回样例
        dd = f"{today.day:02d}"
        if f"/{dd}/IF.xml" in url:
            raise CcpmNoDataError("非交易日")
        return _SAMPLE_XML.replace("20260902", today.strftime("%Y%m%d")).replace(
            "IF2609", "IF" + today.strftime("%y%m")
        )

    monkeypatch.setattr(ccpm_client, "_fetch_xml", fake)
    df = CcpmClient().latest_rank("IF")
    assert len(df) == 2
    assert len(calls) == 2  # 今天一次 + 回退一天一次


def test_latest_rank_exhausted(isolated_config, monkeypatch) -> None:
    from easy_tdx.ccpm import CcpmClient, CcpmError, CcpmNoDataError
    from easy_tdx.ccpm import client as ccpm_client

    def always_no(url: str, timeout: float) -> str:
        raise CcpmNoDataError("非交易日")

    monkeypatch.setattr(ccpm_client, "_fetch_xml", always_no)
    with pytest.raises(CcpmError, match="未找到"):
        CcpmClient().latest_rank("IF", max_back=2)


# ---------------------------------------------------------------------------
# Web 路由
# ---------------------------------------------------------------------------


def _make_app():
    fastapi = pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from easy_tdx.web.routers.ccpm import router

    app = fastapi.FastAPI()
    app.include_router(router, prefix="/api/v1")
    return TestClient(app)


def test_route_products() -> None:
    tc = _make_app()
    r = tc.get("/api/v1/ccpm/products")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 8
    codes = [p["code"] for p in body["products"]]
    assert codes[0] == "IF" and "TL" in codes


def test_route_rank_ok(isolated_config, monkeypatch) -> None:
    _mock_fetch(monkeypatch)
    tc = _make_app()
    r = tc.get("/api/v1/ccpm/rank", params={"product": "IF", "date": "2026-09-02"})
    assert r.status_code == 200
    body = r.json()
    assert body["product"] == "IF" and body["product_name"] == "沪深300股指期货"
    assert body["trading_day"] == "20260902"
    assert body["count"] == 2 and body["data"][0]["instrument"] == "IF2609"


def test_route_rank_no_data_404(isolated_config, monkeypatch) -> None:
    from easy_tdx.ccpm import CcpmNoDataError
    from easy_tdx.ccpm import client as ccpm_client

    monkeypatch.setattr(
        ccpm_client,
        "_fetch_xml",
        lambda url, timeout: (_ for _ in ()).throw(CcpmNoDataError("非交易日")),
    )
    tc = _make_app()
    r = tc.get("/api/v1/ccpm/rank", params={"product": "IF", "date": "2026-08-29"})
    assert r.status_code == 404
    assert "非交易日" in r.json()["detail"]


def test_route_rank_invalid_product_422() -> None:
    tc = _make_app()
    r = tc.get("/api/v1/ccpm/rank", params={"product": "XX"})
    assert r.status_code == 422  # pattern 校验


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_ccpm_json(isolated_config, monkeypatch) -> None:
    pytest.importorskip("click")
    from click.testing import CliRunner

    from easy_tdx.cli.cmd_ccpm import ccpm as ccpm_cmd

    _mock_fetch(monkeypatch)
    result = CliRunner().invoke(ccpm_cmd, ["IF", "--date", "2026-09-02"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)  # print_output 的 JSON = records 数组
    assert len(payload) == 2
    assert payload[0]["instrument"] == "IF2609"


def test_cli_ccpm_table(isolated_config, monkeypatch) -> None:
    pytest.importorskip("click")
    from click.testing import CliRunner

    from easy_tdx.cli.cmd_ccpm import ccpm as ccpm_cmd

    _mock_fetch(monkeypatch)
    result = CliRunner().invoke(ccpm_cmd, ["IF", "--date", "2026-09-02", "--table"])
    assert result.exit_code == 0, result.output
    assert "合约" in result.output and "持买单·会员" in result.output


def test_cli_ccpm_no_data_exit_1(isolated_config, monkeypatch) -> None:
    pytest.importorskip("click")
    from click.testing import CliRunner

    from easy_tdx.ccpm import CcpmNoDataError
    from easy_tdx.ccpm import client as ccpm_client
    from easy_tdx.cli.cmd_ccpm import ccpm as ccpm_cmd

    monkeypatch.setattr(
        ccpm_client,
        "_fetch_xml",
        lambda url, timeout: (_ for _ in ()).throw(CcpmNoDataError("非交易日")),
    )
    result = CliRunner().invoke(ccpm_cmd, ["IF", "--date", "2026-08-29"])
    assert result.exit_code == 1
