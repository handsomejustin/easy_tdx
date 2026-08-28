"""ex 分时/成交查询日期类型的回归测试。

issue 修复：'easy-tdx ex tick US_STOCK TSLA --date 20260827' 曾因 CLI 传入
'int'（YYYYMMDD）而 goods_tick_chart 只接受 datetime.date，直接抛
AttributeError: 'int' object has no attribute 'year'（cmd_ex.py 里还遗留
type: ignore[arg-type]）。

修复方式：MacExClient / AsyncMacExClient 的 goods_tick_chart /
goods_transaction 统一接受 int（YYYYMMDD）/ date / None，内部经
_coerce_query_date 归一为 date，与 A 股 MacClient.get_tick_chart 的
YYYYMMDD 整数语义保持一致。
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest
from click.testing import CliRunner

from easy_tdx.ex.mac_client import MacExClient, _coerce_query_date

# ---------------------------------------------------------------------------
# 1. _coerce_query_date 纯函数
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected",
    [
        (20260827, date(2026, 8, 27)),
        (20250101, date(2025, 1, 1)),
        (20260103, date(2026, 1, 3)),  # 月份/日期前导零按整数解析
        (date(2026, 8, 27), date(2026, 8, 27)),  # date 原样透传
        (None, None),
    ],
)
def test_coerce_query_date(raw: int | date | None, expected: date | None) -> None:
    assert _coerce_query_date(raw) == expected


# ---------------------------------------------------------------------------
# 2. MacExClient 同步客户端
# ---------------------------------------------------------------------------


def _fake_sync_client(captured: list) -> MacExClient:
    """构造不联网的 MacExClient（仅替换 _execute，记录命令）。"""

    def fake_execute(cmd):
        captured.append(cmd)
        return []

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]
    return client


def test_goods_tick_chart_int_date() -> None:
    """int YYYYMMDD 应被转换为 date 后传给 SymbolTickChartCmd。"""
    from easy_tdx.mac.models import MacTickChart

    captured: list = []

    def fake_execute(cmd):
        captured.append(cmd)
        return MacTickChart(
            market=74,
            code="TSLA",
            name="Tesla",
            pre_close=0.0,
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            vol=0,
            amount=0.0,
            turnover=0.0,
            avg=0.0,
            charts=[],
        )

    client = object.__new__(MacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = client.goods_tick_chart(74, "TSLA", query_date=20260827)

    assert len(captured) == 1
    assert captured[0]._ymd == 20260827  # 归一为 date 后再编码为 YYYYMMDD
    assert len(df) == 1 and df.iloc[0]["code"] == "TSLA"  # 正常转 DataFrame


def test_goods_tick_chart_date_and_none() -> None:
    """date 对象与 None 保持原语义（不回归）。"""
    captured: list = []
    client = _fake_sync_client(captured)

    client.goods_tick_chart(74, "TSLA", query_date=date(2026, 8, 27))
    assert captured[-1]._ymd == 20260827

    client.goods_tick_chart(74, "TSLA")
    assert captured[-1]._ymd == 0  # None → 今天（协议 0）


def test_goods_transaction_int_date_non_hk() -> None:
    """非港股市场（美股 74）：int 日期应转换后传给 SymbolTransactionCmd（0x122F）。"""
    captured: list = []
    client = _fake_sync_client(captured)

    client.goods_transaction(74, "TSLA", query_date=20260827, count=10)

    assert len(captured) == 1
    assert captured[0]._ymd == 20260827


def test_goods_transaction_int_date_hk() -> None:
    """港股市场（31）：int 日期应转换后走 ex 历史逐笔协议（GetExHistoryTransactionDataCmd）。"""
    from easy_tdx.ex.commands.get_transaction import GetExHistoryTransactionDataCmd

    captured: list = []
    client = _fake_sync_client(captured)

    client.goods_transaction(31, "00700", query_date=20260827, count=100)

    assert captured
    assert all(isinstance(c, GetExHistoryTransactionDataCmd) for c in captured)
    assert captured[0].date == 20260827


# ---------------------------------------------------------------------------
# 3. AsyncMacExClient 异步客户端
# ---------------------------------------------------------------------------


async def test_async_goods_tick_chart_int_date() -> None:
    """异步版同样接受 int YYYYMMDD。"""
    from easy_tdx.ex.mac_client import AsyncMacExClient
    from easy_tdx.mac.models import MacTickChart

    captured: list = []

    async def fake_execute(cmd):
        captured.append(cmd)
        return MacTickChart(
            market=74,
            code="TSLA",
            name="Tesla",
            pre_close=0.0,
            open=0.0,
            high=0.0,
            low=0.0,
            close=0.0,
            vol=0,
            amount=0.0,
            turnover=0.0,
            avg=0.0,
            charts=[],
        )

    client = object.__new__(AsyncMacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    df = await client.goods_tick_chart(74, "TSLA", query_date=20260827)

    assert len(captured) == 1
    assert captured[0]._ymd == 20260827
    assert len(df) == 1 and df.iloc[0]["code"] == "TSLA"


async def test_async_goods_transaction_int_date() -> None:
    """异步逐笔成交：非港股市场 int 日期转换。"""
    from easy_tdx.ex.mac_client import AsyncMacExClient

    captured: list = []

    async def fake_execute(cmd):
        captured.append(cmd)
        return []

    client = object.__new__(AsyncMacExClient)
    client._execute = fake_execute  # type: ignore[method-assign]

    await client.goods_transaction(74, "TSLA", query_date=20260827, count=10)

    assert len(captured) == 1
    assert captured[0]._ymd == 20260827


# ---------------------------------------------------------------------------
# 4. CLI 回归：easy-tdx ex tick --date
# ---------------------------------------------------------------------------


class _FakeMacExClient:
    """假客户端：记录 goods_tick_chart 收到的 query_date。"""

    def __init__(self, received: dict) -> None:
        self._received = received

    def goods_tick_chart(self, market: int, code: str, query_date=None) -> pd.DataFrame:
        self._received["query_date"] = query_date
        return pd.DataFrame([{"market": market, "code": code}])

    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass


class _FakeCtx:
    def __init__(self, received: dict) -> None:
        self._received = received

    def __enter__(self) -> _FakeMacExClient:
        return _FakeMacExClient(self._received)

    def __exit__(self, *args) -> bool:
        return False


def _patch_conn(monkeypatch: pytest.MonkeyPatch, received: dict) -> None:
    import easy_tdx.cli.conn as conn_mod

    monkeypatch.setattr(conn_mod, "get_mac_ex_client", lambda: _FakeCtx(received))


def test_cli_ex_tick_with_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """回归：--date 20260827 不再抛 AttributeError。

    CLI 层透传 YYYYMMDD 整数，由 MacExClient.goods_tick_chart 内部归一为
    date（与 A 股 MacClient.get_tick_chart 模式一致）；转换正确性由上面
    的客户端级测试覆盖。
    """
    from easy_tdx.cli.cmd_ex import ex

    received: dict = {}
    _patch_conn(monkeypatch, received)

    runner = CliRunner()
    result = runner.invoke(ex, ["tick", "US_STOCK", "TSLA", "--date", "20260827"])

    assert result.exit_code == 0, result.output
    assert received["query_date"] == 20260827


def test_cli_ex_tick_without_date(monkeypatch: pytest.MonkeyPatch) -> None:
    """不带 --date 时默认 None（今天），不回归。"""
    from easy_tdx.cli.cmd_ex import ex

    received: dict = {}
    _patch_conn(monkeypatch, received)

    runner = CliRunner()
    result = runner.invoke(ex, ["tick", "US_STOCK", "TSLA"])

    assert result.exit_code == 0, result.output
    assert received["query_date"] is None
