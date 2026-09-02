"""A 股交易时段判断（共享工具）。

已有的两处会话过滤各自私有、口径不一：

- :mod:`easy_tdx.realtime.feed` 的 ``_DEFAULT_SESSIONS``（09:15-11:30 / 13:00-15:00，
  WS 按需轮询用，收盘竞价不拉）；
- :mod:`easy_tdx.web.quote_streamer` 的 ``_is_trading_hours``（09:10-15:10 连续窗，
  SSE 快照轮询用，午休也降频拉收盘价快照）。

本模块提供第三个口径——**WebUI 仪表盘自动刷新用的"有效行情时段"**：
在 feed 的窗口基础上，早盘前移到 09:15（集合竞价有行情），尾盘后移到
15:05（收盘集合竞价 15:00-15:03 仍有成交），午休排除。前端在此时段内
做 15-30s 轮询，之外暂停自动刷新（手动刷新不受限）。

不改动上述两处既有语义，避免影响它们的测试与行为。
"""

from __future__ import annotations

from datetime import datetime, time, tzinfo
from typing import Any

__all__ = ["SESSION_WINDOWS", "SESSION_DESC", "is_trading_time", "session_info"]

#: 有效行情时段（本地时间）。窗口 = (start, end)，含两端。
#: - 早盘 09:15:00-11:30:30：09:15 起集合竞价可看，11:30:30 容纳尾单撮合散点；
#: - 午盘 13:00:00-15:05:00：15:00-15:03 为收盘集合竞价，留 2 分钟余量。
SESSION_WINDOWS: tuple[tuple[time, time], ...] = (
    (time(9, 15, 0), time(11, 30, 30)),
    (time(13, 0, 0), time(15, 5, 0)),
)

#: 展示用时段描述（前端状态栏 / API 响应）。
SESSION_DESC = "09:15~11:30, 13:00~15:05"


def is_trading_time(now: datetime | None = None, *, tz: tzinfo | None = None) -> bool:
    """判断当前是否处于 A 股有效行情时段（周一至周五，午休与深夜除外）。

    只做"星期 + 时分"判断，不含法定节假日日历——节假日全天处于闭市
    窗口外时前端轮询暂停是安全方向（误刷新无副作用，漏刷新才是问题，
    而节假日行情本就不动，手动刷新始终可用）。

    Args:
        now: 待判断时间，None = 取本地当前时间。
        tz: 未传 ``now`` 时使用的时区，None = 系统本地时区。

    Returns:
        True = 盘中（含集合竞价缓冲窗）。
    """
    t = now or datetime.now(tz=tz)
    if t.weekday() >= 5:  # 周六/周日
        return False
    for start, end in SESSION_WINDOWS:
        if start <= t.time() <= end:
            return True
    return False


def session_info(now: datetime | None = None, *, tz: tzinfo | None = None) -> dict[str, Any]:
    """构建 /market/session 响应体：时段判断 + 窗口描述 + 服务器时间。

    前端以本地判断为主（每 15s 重估），本接口用于校准服务器侧视角。
    """
    t = now or datetime.now(tz=tz)
    return {
        "is_trading_time": is_trading_time(t),
        "sessions": [
            {"start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")} for s, e in SESSION_WINDOWS
        ],
        "session_desc": SESSION_DESC,
        "server_time": t.isoformat(timespec="seconds"),
        "weekday": t.weekday(),
    }
