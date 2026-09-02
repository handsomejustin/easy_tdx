"""实时数据推送模块。

提供事件驱动的行情推送框架，基于 asyncio 实现。

核心组件：
- :class:`EventBus`: 事件总线，发布/订阅行情事件
- :class:`RealtimeStrategy`: 实时策略基类
- :class:`MarketEvent`: 行情事件数据结构
- :class:`RealtimeDataFeed`: 轮询数据源，把 ``get_stock_quotes`` 快照喂给 EventBus

.. note::

    通达信协议没有服务端推送，本模块的「实时」是 **轮询快照近似**（默认约 3 秒
    延迟）。``EventBus`` 自身不会产生数据，必须配合 :class:`RealtimeDataFeed`
    （或自行实现 ``bus.publish`` 的数据源）才能驱动 ``RealtimeStrategy``。
"""

from easy_tdx.realtime.engine import (
    EventBus,
    EventHandler,
    EventType,
    MarketEvent,
    RealtimeStrategy,
)
from easy_tdx.realtime.feed import RealtimeDataFeed
from easy_tdx.realtime.session import SESSION_WINDOWS, is_trading_time, session_info

__all__ = [
    "EventBus",
    "EventHandler",
    "EventType",
    "MarketEvent",
    "RealtimeDataFeed",
    "RealtimeStrategy",
    "SESSION_WINDOWS",
    "is_trading_time",
    "session_info",
]
