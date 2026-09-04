"""涨停生态（screen.limitup + /limitup-ecology 端点）单测。

用合成 .day 二进制文件验证：涨停/连板/炸板/跌停判定、20cm 创业板、
主板 5% 疑似 ST、汇总统计与排序；端点侧验证 DictResponse 包装与 60s 缓存。
"""

from __future__ import annotations

import pytest

from easy_tdx.offline.daily_bar import _DAILY_FMT


def _day(date: int, open_: float, high: float, low: float, close: float) -> bytes:
    """按 .day 真实格式打包一根日线（价格 ×100 存 uint，成交额 f32）。"""
    return _DAILY_FMT.pack(
        date,
        round(open_ * 100),
        round(high * 100),
        round(low * 100),
        round(close * 100),
        5_000_000.0,
        1_000_000,
        0,
    )


def _write_stock(
    vipdoc,
    exchange: str,
    code: str,
    closes: list[float],
    highs: list[float] | None = None,
    dates: list[int] | None = None,
) -> None:
    """写一只股票的 .day 文件；closes 逐日收盘，highs 缺省=每日收盘。"""
    lday = vipdoc / exchange / "lday"
    lday.mkdir(parents=True, exist_ok=True)
    highs = highs or closes
    dates = dates or [20260801 + i for i in range(len(closes))]
    data = b"".join(_day(d, c - 0.05, h, c - 0.10, c) for d, c, h in zip(dates, closes, highs))
    (lday / f"{exchange}{code}.day").write_bytes(data)


@pytest.fixture
def vipdoc(tmp_path):
    """合成市场（全部股票最后 bar 对齐 20260804，模拟真实"同一交易日"）。"""
    last4 = [20260801, 20260802, 20260803, 20260804]
    # 主板 3 连板：10.00 → 11.00 → 12.10 → 13.31（每根恰为 round(prev×1.1, 2)）
    _write_stock(tmp_path, "sh", "600100", [10.00, 11.00, 12.10, 13.31])
    # 创业板 2 连板（20cm）：20.00 → 24.00 → 28.80（首根铺垫同价）
    _write_stock(tmp_path, "sz", "300200", [20.00, 20.00, 24.00, 28.80], dates=last4)
    # 主板 5%（疑似 ST，前收 ≥3 才启用 ST 判定）：10.00 → 10.50
    _write_stock(tmp_path, "sh", "600300", [10.00, 10.00, 10.00, 10.50], dates=last4)
    # 炸板：前收 10.00，最高触 11.00，收 10.80（离开 5% 价位避免歧义）
    _write_stock(
        tmp_path,
        "sh",
        "600400",
        [10.00, 10.00, 10.00, 10.80],
        highs=[10.20, 10.20, 10.50, 11.00],
        dates=last4,
    )
    # 跌停：10.00 → 9.00
    _write_stock(tmp_path, "sz", "000500", [10.00, 10.00, 10.00, 9.00], dates=last4)
    # 平盘（无事件）
    _write_stock(tmp_path, "sh", "600600", [10.00, 10.00, 10.00, 10.20], dates=last4)
    # 陈旧文件：数据停在 20260703，当年的"3连板"不得进入今日生态
    _write_stock(
        tmp_path,
        "sh",
        "600700",
        [10.00, 11.00, 12.10],
        dates=[20260701, 20260702, 20260703],
    )
    # 低价 ST 护栏：前收 2.00（<3）恰收 +5%（2.10）不算涨停
    _write_stock(tmp_path, "sh", "600800", [2.00, 2.00, 2.00, 2.10], dates=last4)
    return tmp_path


def test_limitup_core_detection(vipdoc):
    from easy_tdx.screen.limitup import compute_limitup_ecology

    eco = compute_limitup_ecology(vipdoc)
    assert eco.data_date == 20260804
    assert eco.total == 8

    up = {e.code: e for e in eco.limit_up}
    assert set(up) == {"600100", "300200", "600300"}  # 600700 陈旧排除、600800 低价护栏

    board3 = up["600100"]
    assert board3.streak == 3
    assert board3.market == "SH"
    assert board3.pct == pytest.approx(10.0, abs=0.01)
    assert board3.st is False

    cyb = up["300200"]
    assert cyb.streak == 2  # 20cm 创业板
    assert cyb.pct == pytest.approx(20.0, abs=0.01)

    assert up["600300"].streak == 1
    assert up["600300"].st is True  # 主板 5% → 疑似 ST

    # 连板天梯排序：高度降序
    assert [e.streak for e in eco.limit_up] == [3, 2, 1]

    # 炸板与跌停
    assert [e.code for e in eco.blown] == ["600400"]
    assert eco.blown[0].pct == pytest.approx(8.0, abs=0.01)
    assert [e.code for e in eco.limit_down] == ["000500"]
    assert eco.limit_down[0].streak == 1

    s = eco.summary()
    assert s["limit_up_count"] == 3
    assert s["blown_count"] == 1
    assert s["limit_down_count"] == 1
    assert s["max_streak"] == 3
    assert s["first_board"] == 1  # 仅 600300 首板；600100 三板、300200 二板
    assert s["blown_rate"] == 25.0  # 3 封住 + 1 炸板


def test_limitup_empty_vipdoc(tmp_path):
    from easy_tdx.screen.limitup import compute_limitup_ecology

    eco = compute_limitup_ecology(tmp_path / "nonexistent")
    assert eco.total == 0
    assert eco.data_date == 0
    assert eco.summary()["limit_up_count"] == 0


def test_limitup_endpoint_and_cache(vipdoc, monkeypatch):
    """端点返回 DictResponse 包装；60s 内命中缓存（扫描只跑一次）。"""
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.screen import limitup as limitup_mod
    from easy_tdx.web.errors import register_exception_handlers
    from easy_tdx.web.routers import market as market_mod

    calls = {"n": 0}
    real = limitup_mod.compute_limitup_ecology

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(limitup_mod, "compute_limitup_ecology", counting)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(market_mod.router, prefix="/api/v1")
    app.state.tdx_client = object()

    with TestClient(app) as client:
        r1 = client.get("/api/v1/limitup-ecology", params={"vipdoc": str(vipdoc)})
        assert r1.status_code == 200
        d1 = r1.json()["data"]
        assert d1["summary"]["limit_up_count"] == 3
        assert d1["limit_up"][0]["code"] == "600100"

        r2 = client.get("/api/v1/limitup-ecology", params={"vipdoc": str(vipdoc)})
        assert r2.status_code == 200
        assert r2.json()["data"] == d1

    assert calls["n"] == 1  # 第二次命中缓存
