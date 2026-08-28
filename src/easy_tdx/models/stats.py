"""验证市场概况模型。"""

from dataclasses import dataclass


@dataclass
class MarketStat:
    """全市场涨跌统计概况。"""

    up_count: int  # 上涨家数
    down_count: int  # 下跌家数
    neutral_count: int  # 平盘家数
    suspended_count: int  # 由 total-(up+down+neutral) 得到的残差项，近似表示停牌/未参与统计家数
    total_count: int  # 总计（包含停牌）
    total_amount: float  # 总成交额
    total_volume: float  # 总成交量
    total_market_cap: float  # 总市值（亿元），来自 880001 收盘价，÷100 得万亿
    limit_up_count: int  # 涨停家数，来自 880006 close
    limit_down_count: int  # 跌停家数，来自 880006 open


@dataclass
class FundFlow:
    """个股资金流向统计（基于逐笔成交重算）。

    口径（Issue #55）：按 0x0fb5 逐笔接口的"单笔成交额"分档——该接口
    返回的是聚合记录（非交易所真实逐笔，也非挂单额），故 ``main_net_inflow``
    更接近"主动买卖总失衡"，与东财/同花顺的"主力净流入"不可比。
    """

    # 流入项 (Buy)
    super_in: float  # 超大单流入 (>100万)
    large_in: float  # 大单流入 (>20万 且 <=100万)
    medium_in: float  # 中单流入 (>4万 且 <=20万)
    small_in: float  # 小单流入 (<=4万)

    # 流出项 (Sell)
    super_out: float
    large_out: float
    medium_out: float
    small_out: float

    @property
    def main_net_inflow(self) -> float:
        """主力净流入 (超大单 + 大单)。"""
        return (self.super_in + self.large_in) - (self.super_out + self.large_out)

    @property
    def total_net_inflow(self) -> float:
        """全单净流入。"""
        return (self.super_in + self.large_in + self.medium_in + self.small_in) - (
            self.super_out + self.large_out + self.medium_out + self.small_out
        )


@dataclass
class HistoricalFundFlow:
    """历史日线资金流向条目。

    口径同 ``FundFlow``（Issue #55）：按聚合后单笔成交额分档，与东财/
    同花顺"主力净流入"不可比。
    """

    year: int
    month: int
    day: int

    # 金额项 (单位：元)
    super_in: float
    super_out: float
    large_in: float
    large_out: float
    medium_in: float
    medium_out: float
    small_in: float
    small_out: float

    @property
    def main_net_inflow(self) -> float:
        """当日主力净流入。"""
        return (self.super_in + self.large_in) - (self.super_out + self.large_out)
