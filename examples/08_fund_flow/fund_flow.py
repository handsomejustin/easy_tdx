"""演示：获取个股当日资金流向（基于 L1 逐笔数据统计）。

使用 TdxClient 标准协议客户端，调用 get_fund_flow() 获取个股当日资金流向分布。
返回单行 DataFrame（FundFlow 模型），包含四级资金的流入/流出金额。

DataFrame 列说明:
  super_in      float   超大单流入（元）
  super_out     float   超大单流出（元）
  large_in      float   大单流入（元）
  large_out     float   大单流出（元）
  medium_in     float   中单流入（元）
  medium_out    float   中单流出（元）
  small_in      float   小单流入（元）
  small_out     float   小单流出（元）

资金级别划分（按单笔成交金额）:
  超大单: 单笔成交金额 > 100 万元
  大单:   单笔成交金额 > 20 万元 且 <= 100 万元
  中单:   单笔成交金额 > 4 万元  且 <= 20 万元
  小单:   单笔成交金额 <= 4 万元

衍生指标:
  主力净流入 = (超大单流入 + 大单流入) - (超大单流出 + 大单流出)
  全单净流入 = 所有级别流入之和 - 所有级别流出之和

数据特点:
  - 金额单位为元（本 demo 转换为亿元便于阅读）
  - 数据实时计算，非交易时段返回全零值
  - 基于 L1 逐笔成交数据统计，非交易所官方资金流向数据
  - 口径注意（Issue #55）: 0x0fb5 逐笔为聚合记录、按成交额（非挂单额）分档，
    高价股主力档常占 95%+，"主力净流入"更接近主动买卖总失衡，与东财/
    同花顺同名指标不可比，勿混用于同一张表或同一个因子
"""

import pandas as pd

from easy_tdx import Market, TdxClient

with TdxClient.from_best_host() as c:
    flow = c.get_fund_flow(Market.SH, "600519")
    # flow 是单行 DataFrame，转换为万元便于阅读
    in_cols = ["super_in", "large_in", "medium_in", "small_in"]
    out_cols = ["super_out", "large_out", "medium_out", "small_out"]
    df = pd.DataFrame(
        {
            "级别": ["超大单", "大单", "中单", "小单"],
            "流入(亿)": [flow[c].iloc[0] / 1e8 for c in in_cols],
            "流出(亿)": [flow[c].iloc[0] / 1e8 for c in out_cols],
        }
    )
    df["净流入(亿)"] = df["流入(亿)"] - df["流出(亿)"]
    print("贵州茅台 当日资金流向:")
    print(df.to_string(index=False))

# 运行结果:
# 贵州茅台 当日资金流向:
#   级别  流入(亿)  流出(亿)  净流入(亿)
# 超大单    3.52     2.18      1.34
#   大单    2.86     2.54      0.32
#   中单    4.12     3.98      0.14
#   小单    1.56     2.36     -0.80
