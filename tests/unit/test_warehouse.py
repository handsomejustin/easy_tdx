"""本地 K 线仓库测试（DuckDB store + 增量 sync + provisional 状态机 + 健康自检）。"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

pytest.importorskip("duckdb")

from easy_tdx.warehouse.store import KlineWarehouse  # noqa: E402
from easy_tdx.warehouse.sync import WarehouseSyncer  # noqa: E402


@pytest.fixture()
def wh(tmp_path):
    warehouse = KlineWarehouse(tmp_path / "test.duckdb")
    yield warehouse
    warehouse.close()


def _bars(n: int = 10, start: str = "2024-01-01", base: float = 10.0) -> pd.DataFrame:
    dates = pd.date_range(start, periods=n, freq="B")
    close = base + np.linspace(0, 1, n)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "vol": 1000.0,
            "amount": close * 1000,
        }
    )


class _FakeClient:
    """返回预置 K 线的假客户端（duck-typed get_stock_kline）。"""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df
        self.calls: list[dict] = []

    def get_stock_kline(self, market, code, period="DAILY", start=0, count=800, adjust="NONE"):
        self.calls.append({"market": market, "count": count, "adjust": adjust})
        return self._df.iloc[max(0, len(self._df) - count) :].reset_index(drop=True)


# ── store：写入 / 查询 ───────────────────────────────────────────────────────


def test_upsert_and_query_roundtrip(wh):
    df = _bars(10)
    added, updated = wh.upsert_bars("SH", "600519", df)
    assert (added, updated) == (10, 0)

    out = wh.query("SH", "600519")
    assert len(out) == 10
    assert list(out.columns)[:5] == ["market", "code", "period", "datetime", "open"]
    assert out["market"].iloc[0] == "SH"
    # 升序
    dts = pd.to_datetime(out["datetime"])
    assert dts.is_monotonic_increasing


def test_upsert_same_bars_updates_not_duplicates(wh):
    df = _bars(10)
    wh.upsert_bars("SH", "600519", df)
    # 同一批再写 → 全部 update，无重复行
    added, updated = wh.upsert_bars("SH", "600519", df)
    assert (added, updated) == (0, 10)
    assert len(wh.query("SH", "600519")) == 10


def test_query_count_takes_latest(wh):
    full = _bars(50)
    wh.upsert_bars("SZ", "000001", full)
    out = wh.query("SZ", "000001", count=10)
    assert len(out) == 10
    # 是最近 10 根（时间仍升序，且末根 = 全量末根）
    last_full = pd.Timestamp(full["datetime"].iloc[-1]).normalize()
    assert pd.Timestamp(out["datetime"].iloc[-1]) == last_full


def test_query_date_range_filter(wh):
    wh.upsert_bars("SZ", "000001", _bars(50))
    out = wh.query("SZ", "000001", start="2024-01-15", end="2024-01-25")
    dts = pd.to_datetime(out["datetime"]).dt.date.astype(str)
    assert (dts >= "2024-01-15").all() and (dts <= "2024-01-25").all()


def test_last_datetime_and_symbols(wh):
    assert wh.last_datetime("SH", "600519") is None
    wh.upsert_bars("SH", "600519", _bars(10))
    wh.upsert_bars("SZ", "000001", _bars(5))
    assert wh.last_datetime("SH", "600519") == pd.Timestamp("2024-01-12")
    syms = wh.symbols()
    assert len(syms) == 2
    assert set(syms["code"]) == {"600519", "000001"}


def test_delete_symbol(wh):
    wh.upsert_bars("SH", "600519", _bars(10))
    assert wh.delete_symbol("SH", "600519") == 10
    assert len(wh.query("SH", "600519")) == 0


def test_missing_optional_columns_filled(wh):
    df = _bars(5).drop(columns=["amount"])
    wh.upsert_bars("SH", "600519", df)
    out = wh.query("SH", "600519")
    assert out["amount"].isna().all()


# ── provisional 状态机 ───────────────────────────────────────────────────────


def test_today_bars_before_close_marked_provisional(wh, monkeypatch):
    """当日 bar 在 15:05 前落盘 → provisional（逐行判定），默认查询忽略。"""
    import datetime as _dt

    import easy_tdx.warehouse.store as store_mod

    today = pd.Timestamp.today().normalize()
    dates = pd.date_range(today - pd.Timedelta(days=10), periods=11, freq="D")
    df = pd.DataFrame(
        {
            "datetime": dates,
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "vol": 100.0,
            "amount": 1000.0,
        }
    )

    class _FixedDT(_dt.datetime):
        @classmethod
        def now(cls, tz=None):  # 固定在当日 10:00（盘中）
            return _dt.datetime(today.year, today.month, today.day, 10, 0)

    monkeypatch.setattr(store_mod, "datetime", _FixedDT)

    added, _ = wh.upsert_bars("SH", "600519", df)
    assert added == 11
    all_rows = wh.query("SH", "600519", include_provisional=True)
    completed = wh.query("SH", "600519")
    assert len(all_rows) == 11
    assert len(completed) == 10  # 仅当日 bar 是 provisional
    # 显式 include_provisional 时当日可见且标记正确
    today_rows = all_rows[all_rows["status"] == "provisional"]
    assert len(today_rows) == 1
    assert pd.Timestamp(today_rows["datetime"].iloc[0]).date() == today.date()


def test_promote_provisional(wh):
    """过期的 provisional 行（日期 < 今天）转正。"""

    old = pd.DataFrame(
        {
            "datetime": pd.date_range("2024-01-01", periods=3),
            "open": 10.0,
            "high": 10.1,
            "low": 9.9,
            "close": 10.0,
            "vol": 100.0,
            "amount": 1000.0,
        }
    )
    wh.upsert_bars("SH", "600519", old, status="provisional")
    assert len(wh.query("SH", "600519")) == 0  # provisional 默认不可见
    n = wh.promote_provisional()
    assert n >= 3
    assert len(wh.query("SH", "600519")) == 3  # 转正后可见


# ── 健康自检 ─────────────────────────────────────────────────────────────────


def test_health_check_detects_gap_and_stale(wh):
    # 构造缺口：跳过 2 周
    df1 = _bars(5, start="2024-01-01")
    df2 = _bars(5, start="2024-03-01")
    wh.upsert_bars("SH", "600519", pd.concat([df1, df2], ignore_index=True))
    report = wh.health_check()
    assert report["symbols_checked"] == 1
    kinds = [i["kind"] for i in report["issues"]]
    assert "gap" in kinds  # 1 月→3 月的缺口
    assert report["summary"]["stale_symbols"]  # 2024 年数据 → 明显过期


def test_health_check_price_jump(wh):
    """除权式跳空被检出（kind=price_jump）。"""
    closes = [10.0] * 10 + [7.0] * 10
    dates = pd.date_range("2024-01-01", periods=20, freq="B")
    df = pd.DataFrame(
        {
            "datetime": dates,
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "vol": 100.0,
            "amount": 1000.0,
        }
    )
    wh.upsert_bars("SH", "600519", df)
    report = wh.health_check(market="SH", code="600519")
    assert any(i["kind"] == "price_jump" for i in report["issues"])


def test_health_check_clean_series_no_issues(wh):
    """连续无跳空数据（工作日）→ 无 gap/price_jump 问题。"""
    wh.upsert_bars("SZ", "000001", _bars(30))
    report = wh.health_check(market="SZ", code="000001")
    assert report["issues"] == []


# ── 增量同步 ─────────────────────────────────────────────────────────────────


def test_sync_initial_full_then_incremental(tmp_path):
    warehouse = KlineWarehouse(tmp_path / "s.duckdb")
    try:
        full = _bars(100)
        client = _FakeClient(full)
        syncer = WarehouseSyncer(client, warehouse, max_bars=800, tail_bars=15)

        s1 = syncer.sync(["SH:600519"])
        assert s1["added"] == 100 and s1["failed"] == 0
        # 首同步请求了全量（count=800）
        assert client.calls[-1]["count"] == 800

        s2 = syncer.sync([("SH", "600519")])
        assert s2["added"] == 0 and s2["updated"] == 15  # 增量只补尾部 15 根
        assert client.calls[-1]["count"] == 15
        assert len(warehouse.query("SH", "600519")) == 100  # 无重复
    finally:
        warehouse.close()


def test_sync_new_bars_appended(tmp_path):
    warehouse = KlineWarehouse(tmp_path / "s2.duckdb")
    try:
        client = _FakeClient(_bars(50))
        syncer = WarehouseSyncer(client, warehouse, tail_bars=20)
        syncer.sync(["SZ:000001"])

        # 行情前滚 5 根：新 bar 接在原末根之后
        end = pd.Timestamp(client._df["datetime"].iloc[-1])
        client._df = pd.concat(
            [client._df, _bars(5, start=str(end + pd.Timedelta(days=1)))], ignore_index=True
        )
        s2 = syncer.sync(["SZ:000001"])
        assert s2["added"] == 5
        assert len(warehouse.query("SZ", "000001")) == 55
    finally:
        warehouse.close()


def test_sync_failure_does_not_break_batch(tmp_path):
    warehouse = KlineWarehouse(tmp_path / "s3.duckdb")
    try:

        class _BadClient:
            def get_stock_kline(self, *a, **kw):
                raise ConnectionError("网络故障")

        syncer = WarehouseSyncer(_BadClient(), warehouse)
        s = syncer.sync(["SH:600519", "SZ:000001"])
        assert s["failed"] == 2
        assert all(d["error"] for d in s["details"])
    finally:
        warehouse.close()


def test_sync_progress_callback(tmp_path):
    warehouse = KlineWarehouse(tmp_path / "s4.duckdb")
    try:
        client = _FakeClient(_bars(20))
        seen: list[tuple[int, int, str]] = []

        def progress(done, total, sym):
            seen.append((done, total, sym))

        WarehouseSyncer(client, warehouse).sync(["SH:600519", "SZ:000001"], progress=progress)
        assert seen == [(1, 2, "SH:600519"), (2, 2, "SZ:000001")]
    finally:
        warehouse.close()


def test_missing_duckdb_helpful_error(tmp_path, monkeypatch):
    """duckdb 未安装时给出安装指引（模拟 ImportError）。"""
    import builtins

    real_import = builtins.__import__

    def _no_duckdb(name, *args, **kwargs):
        if name == "duckdb":
            raise ImportError("No module named 'duckdb'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_duckdb)
    with pytest.raises(ImportError, match=r"easy-tdx\[warehouse\]"):
        KlineWarehouse(tmp_path / "x.duckdb")
