"""easy_tdx.screen — 策略选股扫描器。

两步走工作流：
1. scan: 用策略扫描全市场，找出触发买入信号的股票（纯离线）
2. rank: 对扫描结果做历史回测排名

另外提供 strength: 全市场强势股排名（按 5/20/60 日涨幅加权排序）。

用法::

    # Step 1: 信号扫描
    easy-tdx screen scan --strategy strategies/rsi_reversal.py --output signals.json

    # Step 2: 回测排名
    easy-tdx screen rank --from signals.json --sort sharpe --top 20 --table

    # 强势股排名
    easy-tdx screen strength --preset steady --top 50 --table
"""

from easy_tdx.screen.scanner import ScanResult, SignalScanner  # noqa: F401
from easy_tdx.screen.strength import (  # noqa: F401
    STRENGTH_PRESETS,
    StrengthRanker,
    StrengthResult,
)
from easy_tdx.screen.universe import CORE_LEADERS, CORE_LEADERS_DESC  # noqa: F401

__all__ = [
    "SignalScanner",
    "ScanResult",
    "StrengthRanker",
    "StrengthResult",
    "STRENGTH_PRESETS",
    "CORE_LEADERS",
    "CORE_LEADERS_DESC",
]
