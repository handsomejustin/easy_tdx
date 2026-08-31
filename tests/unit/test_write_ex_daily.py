"""离线扩展市场日线写入测试（纯离线，无网络）。"""

from __future__ import annotations

import struct
from pathlib import Path

from easy_tdx.offline.ex_daily_bar import _EX_DAILY_FMT, ExDailyBar, read_ex_daily_bars
from easy_tdx.offline.write_ex_daily import (
    append_ex_daily_bars,
    encode_ex_daily_bar,
    get_last_ex_bar_date,
    sync_ex_daily_bars,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_ex_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    open_: float = 3500.0,
    high: float = 3550.0,
    low: float = 3480.0,
    close: float = 3520.0,
    amount: float = 123456.0,
    vol: int = 98765,
    settlement: float = 3510.0,
) -> ExDailyBar:
    return ExDailyBar(
        open=open_,
        close=close,
        high=high,
        low=low,
        amount=amount,
        vol=vol,
        settlement=settlement,
        year=year,
        month=month,
        day=day,
    )


def _make_raw_ex_bar(
    year: int = 2026,
    month: int = 6,
    day: int = 6,
    open_: float = 3500.0,
    high: float = 3550.0,
    low: float = 3480.0,
    close: float = 3520.0,
    amount: float = 123456.0,
    vol: int = 98765,
    settlement: float = 3510.0,
) -> bytes:
    date_int = year * 10000 + month * 100 + day
    return _EX_DAILY_FMT.pack(date_int, open_, high, low, close, amount, vol, settlement)


# ---------------------------------------------------------------------------
# encode_ex_daily_bar
# ---------------------------------------------------------------------------


class TestEncodeExDailyBar:
    def test_output_length(self) -> None:
        bar = _make_ex_bar()
        result = encode_ex_daily_bar(bar)
        assert len(result) == 32

    def test_date_encoding(self) -> None:
        bar = _make_ex_bar(year=2025, month=12, day=25)
        result = encode_ex_daily_bar(bar)
        date_int = struct.unpack_from("<I", result, 0)[0]
        assert date_int == 20251225

    def test_float_prices_preserved(self) -> None:
        bar = _make_ex_bar(open_=3500.5, high=3560.25, low=3479.75, close=3520.0)
        result = encode_ex_daily_bar(bar)
        op, hi, lo, cl = struct.unpack_from("<ffff", result, 4)
        assert abs(op - 3500.5) < 0.01
        assert abs(hi - 3560.25) < 0.01
        assert abs(lo - 3479.75) < 0.01
        assert abs(cl - 3520.0) < 0.01

    def test_settlement_encoding(self) -> None:
        bar = _make_ex_bar(settlement=3510.5)
        result = encode_ex_daily_bar(bar)
        (sett,) = struct.unpack_from("<f", result, 28)
        assert abs(sett - 3510.5) < 0.01


# ---------------------------------------------------------------------------
# round-trip
# ---------------------------------------------------------------------------


class TestExRoundTrip:
    def test_single_bar_round_trip(self, tmp_path: Path) -> None:
        bar = _make_ex_bar(open_=3500.0, close=3520.0, amount=123456.0, vol=98765)
        encoded = encode_ex_daily_bar(bar)

        filepath = tmp_path / "29#A1801.day"
        filepath.write_bytes(encoded)

        bars = read_ex_daily_bars(filepath)
        assert len(bars) == 1
        b = bars[0]
        assert b.year == 2026 and b.month == 6 and b.day == 6
        assert abs(b.open - 3500.0) < 0.01
        assert abs(b.close - 3520.0) < 0.01
        assert abs(b.amount - 123456.0) < 0.01
        assert b.vol == 98765

    def test_multiple_bars_round_trip(self, tmp_path: Path) -> None:
        bars_in = [
            _make_ex_bar(year=2026, month=6, day=4, open_=3400.0),
            _make_ex_bar(year=2026, month=6, day=5, open_=3450.0),
            _make_ex_bar(year=2026, month=6, day=6, open_=3500.0),
        ]
        encoded = b"".join(encode_ex_daily_bar(b) for b in bars_in)

        filepath = tmp_path / "29#A1801.day"
        filepath.write_bytes(encoded)

        bars_out = read_ex_daily_bars(filepath)
        assert len(bars_out) == 3
        assert bars_out[0].day == 4
        assert bars_out[2].day == 6


# ---------------------------------------------------------------------------
# get_last_ex_bar_date
# ---------------------------------------------------------------------------


class TestGetLastExBarDate:
    def test_returns_last_date(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.day"
        filepath.write_bytes(_make_raw_ex_bar(year=2026, month=6, day=5))
        assert get_last_ex_bar_date(filepath) == 20260605

    def test_returns_none_for_empty(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.day"
        filepath.write_bytes(b"")
        assert get_last_ex_bar_date(filepath) is None


# ---------------------------------------------------------------------------
# append & sync
# ---------------------------------------------------------------------------


class TestAppendExDailyBars:
    def test_append_to_existing(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.day"
        filepath.write_bytes(_make_raw_ex_bar(year=2026, month=6, day=5))

        new_bar = _make_ex_bar(year=2026, month=6, day=6)
        written = append_ex_daily_bars(filepath, [new_bar])
        assert written == 1

        bars = read_ex_daily_bars(filepath)
        assert len(bars) == 2

    def test_skips_duplicate(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.day"
        filepath.write_bytes(_make_raw_ex_bar(year=2026, month=6, day=6))

        new_bar = _make_ex_bar(year=2026, month=6, day=6)
        written = append_ex_daily_bars(filepath, [new_bar])
        assert written == 0

    def test_sync_filters_correctly(self, tmp_path: Path) -> None:
        filepath = tmp_path / "test.day"
        filepath.write_bytes(_make_raw_ex_bar(year=2026, month=6, day=5))

        server_bars = [
            _make_ex_bar(year=2026, month=6, day=4),
            _make_ex_bar(year=2026, month=6, day=5),
            _make_ex_bar(year=2026, month=6, day=6),
        ]
        written = sync_ex_daily_bars(filepath, server_bars)
        assert written == 1

        bars = read_ex_daily_bars(filepath)
        assert len(bars) == 2


# ---------------------------------------------------------------------------
# 真实样本回归（issue #57）：槽位语义
# ---------------------------------------------------------------------------

# 47#IF300（扩展市场沪深300 指数）2023-09-11 的真实记录。
# 与标准市场 sh000300.day 同日对照：vol=105358016（手）、amount=186871758848.0（元）完全一致，
# 证明第 6 槽是 float32 成交额，第 7 槽是 uint32 成交量。
_REAL_IF300_20230911 = bytes.fromhex(
    "ffb2340148c969451fc56c45856b6945a4786b45b3092e52c0a2470600000000"
)


class TestRealSampleSlots:
    def test_amount_is_float32_turnover(self, tmp_path: Path) -> None:
        filepath = tmp_path / "47#IF300.day"
        filepath.write_bytes(_REAL_IF300_20230911)

        bars = read_ex_daily_bars(filepath)
        assert len(bars) == 1
        b = bars[0]
        assert (b.year, b.month, b.day) == (2023, 9, 11)
        assert b.amount == 186871758848.0
        assert b.vol == 105358016
        assert abs(b.close - 3767.54) < 0.01
        # amount 与 vol 不得串槽（回归：旧实现 amount=vol）
        assert b.amount != b.vol

    def test_large_amount_does_not_overflow(self, tmp_path: Path) -> None:
        # 真实成交额动辄超 uint32 上限，第 6 槽必须按 float32 编码
        bar = _make_ex_bar(amount=186871758848.0)
        encoded = encode_ex_daily_bar(bar)
        filepath = tmp_path / "47#IF300.day"
        filepath.write_bytes(encoded)

        (b,) = read_ex_daily_bars(filepath)
        assert b.amount == 186871758848.0
