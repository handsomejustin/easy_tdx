"""交易时段判断单元测试（realtime/session.py，v1.29）。

覆盖：窗口边界（09:15/11:30:30/13:00/15:05）、午休、周末、
盘前盘后、session_info 响应结构。
"""

from __future__ import annotations

from datetime import datetime

from easy_tdx.realtime.session import SESSION_WINDOWS, is_trading_time, session_info


def _dt(s: str) -> datetime:
    # 2026-09-02 是周三（盘中日）
    return datetime.strptime(f"2026-09-02 {s}", "%Y-%m-%d %H:%M:%S")


class TestIsTradingTime:
    def test_weekday_morning_session(self):
        assert is_trading_time(_dt("09:15:00"))  # 集合竞价起
        assert is_trading_time(_dt("10:30:00"))
        assert is_trading_time(_dt("11:30:30"))  # 窗口含端

    def test_lunch_break_excluded(self):
        assert not is_trading_time(_dt("11:31:00"))
        assert not is_trading_time(_dt("12:30:00"))
        assert not is_trading_time(_dt("12:59:59"))

    def test_afternoon_session(self):
        assert is_trading_time(_dt("13:00:00"))
        assert is_trading_time(_dt("14:30:00"))
        assert is_trading_time(_dt("15:05:00"))  # 收盘竞价缓冲端点
        assert not is_trading_time(_dt("15:05:01"))

    def test_pre_and_post_market(self):
        assert not is_trading_time(_dt("09:14:59"))
        assert not is_trading_time(_dt("08:00:00"))
        assert not is_trading_time(_dt("22:00:00"))

    def test_weekend_rejected(self):
        # 2026-09-05 周六 / 2026-09-06 周日，取盘中时间也应为 False
        assert not is_trading_time(datetime(2026, 9, 5, 10, 0))
        assert not is_trading_time(datetime(2026, 9, 6, 14, 0))


class TestSessionInfo:
    def test_shape(self):
        info = session_info(_dt("10:00:00"))
        assert info["is_trading_time"] is True
        assert info["weekday"] == 2  # 周三
        assert len(info["sessions"]) == len(SESSION_WINDOWS)
        assert info["session_desc"] == "09:15~11:30, 13:00~15:05"
        assert "T" in info["server_time"]  # isoformat

    def test_closed(self):
        info = session_info(datetime(2026, 9, 5, 10, 0))  # 周六
        assert info["is_trading_time"] is False
