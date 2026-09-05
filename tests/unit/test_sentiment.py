"""市场情绪采样（store / sampler / 端点）与涨停历史回补单测。

sentiment_store 用 EASY_TDX_CONFIG_DIR 指向临时目录；limitup 历史复用
合成 .day 文件；端点侧验证 DictResponse 包装与缓存命中。
"""

from __future__ import annotations

import asyncio

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    """独立配置目录 + 全新单例的 SentimentStore。"""
    from easy_tdx.web import sentiment_store as ss

    monkeypatch.setenv("EASY_TDX_CONFIG_DIR", str(tmp_path / "cfg"))
    ss._store = None
    s = ss.get_sentiment_store()
    yield s
    ss._store = None


def _sample(date: int, minute: int, up=2000, down=2000, limit_up=50, limit_down=10, amount=8e11):
    from datetime import datetime

    return {
        "date": date,
        "minute": minute,
        "ts": int(datetime(2026, 9, 4).timestamp()),
        "up_count": up,
        "down_count": down,
        "neutral_count": 100,
        "total_count": up + down + 100,
        "limit_up_count": limit_up,
        "limit_down_count": limit_down,
        "total_amount": amount,
    }


def test_store_day_samples_and_idempotent(store):
    store.insert(_sample(20260904, 935))
    store.insert(_sample(20260904, 930))
    # 同 (date, minute) 覆盖不累积
    store.insert(_sample(20260904, 930, limit_up=77))

    rows = store.day_samples(20260904)
    assert [r["minute"] for r in rows] == [930, 935]  # 升序
    assert rows[0]["limit_up_count"] == 77  # 覆盖生效
    assert store.latest_date() == 20260904


def test_store_daily_history_close_snapshot_and_peak(store):
    # 收盘快照 = 当日最后一条采样；峰值 = 当日涨停最大值
    store.insert(_sample(20260903, 930, up=1500, limit_up=30, limit_down=40, amount=7e11))
    store.insert(
        _sample(20260903, 1500, up=2500, down=1500, limit_up=90, limit_down=5, amount=9e11)
    )
    store.insert(
        _sample(20260904, 930, up=1800, down=2200, limit_up=20, limit_down=60, amount=6e11)
    )

    days = store.daily_history(10)
    assert [d["date"] for d in days] == [20260903, 20260904]  # 升序

    d3 = days[0]
    assert d3["limit_up_peak"] == 90  # 日内峰值（930 点只有 30，1500 点 90）
    assert d3["limit_up_close"] == 90  # 收盘快照取当日最后一条
    assert d3["up_count"] == 2500
    assert d3["up_ratio"] == 62.5  # 2500 / (2500+1500)

    d4 = days[1]
    assert d4["limit_up_peak"] == 20
    assert d4["up_ratio"] == 45.0  # 1800 / 4000


def test_sampler_inserts_store_rows(store):
    import pandas as pd

    from easy_tdx.web.sentiment_sampler import SentimentSampler

    df = pd.DataFrame(
        [
            {
                "up_count": 2100,
                "down_count": 2300,
                "neutral_count": 120,
                "total_count": 4520,
                "limit_up_count": 44,
                "limit_down_count": 9,
                "total_amount": 8.5e11,
            }
        ]
    )

    class FakeClient:
        async def get_market_stat(self):
            return df

    sampler = SentimentSampler(FakeClient().get_market_stat, store=store, interval=1.0)
    asyncio.run(sampler._sample_once())

    rows = store.day_samples(store.latest_date())
    assert len(rows) == 1
    assert rows[0]["limit_up_count"] == 44
    assert rows[0]["total_amount"] == 8.5e11


@pytest.fixture
def vipdoc_factory(tmp_path):
    """按 {文件名: {dates, closes}} 合成 vipdoc 目录的工厂。"""
    from easy_tdx.offline.daily_bar import _DAILY_FMT

    def _day(date: int, close: float) -> bytes:
        return _DAILY_FMT.pack(
            date,
            round((close - 0.05) * 100),
            round(close * 100),
            round((close - 0.10) * 100),
            round(close * 100),
            5_000_000.0,
            1_000_000,
            0,
        )

    def factory(specs: dict[str, dict]) -> object:
        for filename, spec in specs.items():
            exchange = filename[:2]
            lday = tmp_path / exchange / "lday"
            lday.mkdir(parents=True, exist_ok=True)
            data = b"".join(_day(d, c) for d, c in zip(spec["dates"], spec["closes"]))
            (lday / f"{filename}.day").write_bytes(data)
        return tmp_path

    return factory


def test_limitup_history_counts(vipdoc_factory):
    from easy_tdx.screen.limitup import compute_limitup_history

    v = vipdoc_factory(
        # A 股票：0802、0803 连续两日涨停
        {
            "sh600100": {
                "dates": [20260801, 20260802, 20260803, 20260804],
                "closes": [10.00, 11.00, 12.10, 12.50],
            },
            # B 股票：0804 跌停
            "sz000200": {
                "dates": [20260801, 20260802, 20260803, 20260804],
                "closes": [10.00, 10.00, 10.00, 9.00],
            },
        }
    )
    rows = compute_limitup_history(v, days=10)
    by_date = {r["date"]: r for r in rows}
    assert by_date[20260802]["limit_up"] == 1
    assert by_date[20260803]["limit_up"] == 1
    assert by_date[20260804]["limit_down"] == 1
    assert by_date[20260804]["limit_up"] == 0
    # 升序
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates)


def test_limitup_history_endpoint_cache(vipdoc_factory, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from easy_tdx.screen import limitup as limitup_mod
    from easy_tdx.web.errors import register_exception_handlers
    from easy_tdx.web.routers import market as market_mod

    v = vipdoc_factory({"sh600100": {"dates": [20260801, 20260802], "closes": [10.0, 11.0]}})
    calls = {"n": 0}
    real = limitup_mod.compute_limitup_history

    def counting(*a, **kw):
        calls["n"] += 1
        return real(*a, **kw)

    monkeypatch.setattr(limitup_mod, "compute_limitup_history", counting)

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(market_mod.router, prefix="/api/v1")
    app.state.tdx_client = object()

    with TestClient(app) as client:
        r1 = client.get("/api/v1/market/limitup-history", params={"days": 10, "vipdoc": str(v)})
        assert r1.status_code == 200
        body = r1.json()["data"]
        # 仅 0802 有一天涨停（0801 无前收不计数）
        assert body["count"] == 1
        assert body["days"][0] == {"date": 20260802, "limit_up": 1, "limit_down": 0}
        client.get("/api/v1/market/limitup-history", params={"days": 10, "vipdoc": str(v)})
    assert calls["n"] == 1  # 缓存命中
