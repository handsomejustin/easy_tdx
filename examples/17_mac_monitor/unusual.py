"""演示：市场异动数据。

通过 MacClient 的 get_unusual() 获取全市场的异动股票数据。

参数:
    market  -- 市场代码（Market.SH / Market.SZ）
    start   -- 起始偏移（默认 0）
    count   -- 单次请求数量（协议上限 600，超出会被截断为 600）

UnusualItem dataclass 字段:
    index         int     异动序号
    market        int     市场代码
    code          str     证券代码
    name          str     证券名称
    time          time    异动时间
    desc          str     异动描述（如 "盘中强势"、"竞价拉升"、"急速下跌"）
    value         str     异动数值（如 "5.82%"、"10.05%/64310手"）
    unusual_type  int     异动类型代码（见下表）

异动类型代码表（0x1237，2026-09-01 实测锚定，可用 easy_tdx.UNUSUAL_TYPE_NAMES 映射）:
    0x03  主力买入/卖出          0x10  大单托盘
    0x04  加速拉升               0x11  大单压盘
    0x05  加速下跌               0x12  大单锁盘
    0x06  低位反弹               0x13  竞价试盘（试买/试卖，09:15~09:20 触发）
    0x07  高位回落               0x14  涨跌停（逼近/封板/封大减/打开）
    0x08  撑杆跳高               0x15  竞价/尾盘异动（拉升/下跌/平稳，09:25 与 15:00 双时刻触发）
    0x09  平台跳水               0x16  盘中强势/弱势（v1 为 1~3 级强弱等级）
    0x0A  单笔冲涨/冲跌          0x1D  急速拉升
    0x0B  区间放量涨/跌/平       0x1E  急速下跌
    0x0C  区间缩量

返回 DataFrame 列说明:
    index         int      异动序号
    market        int      市场代码
    code          str      证券代码
    name          str      证券名称
    time          object   异动时间（HH:MM:SS 格式）
    desc          str      异动描述
    value         str      异动数值
    unusual_type  int      异动类型代码

说明:
    通达信 MAC 协议 0x1237 单次最多返回 600 条异动数据。
    若要拉取全市场全部异动（盘中可能数千条），需要用 start 参数翻页，
    每次累加 600，直到某页返回不足 600 条即为尾页。
"""

import pandas as pd

from easy_tdx import MacClient, Market

PAGE = 600  # 协议单次返回上限，不要改大（会被截断）

with MacClient.from_best_host() as c:
    frames = []
    start = 0
    while True:
        df = c.get_unusual(Market.SH, start=start, count=PAGE)
        if df.empty:
            break
        frames.append(df)
        if len(df) < PAGE:  # 不足一页 = 已到尾
            break
        start += PAGE

    if frames:
        full = pd.concat(frames, ignore_index=True)
        print(f"共获取 {len(full)} 条异动（{len(frames)} 页）")
        print(full.to_string(index=False))
    else:
        print("暂无异动数据。")

# 示例输出:
#  共获取 12871 条异动（22 页）
#   index  market  code   name       time          desc       value  unusual_type
#       1       1  600551  时代出版  09:25:00     竞价下跌      -1.21%/40254手      21
#       2       1  600551  时代出版  09:25:00     盘中强势       5.82%              22
#       3       1  600295  鄂尔多斯  09:25:00     竞价拉升       2.88%/533手        21
#       4       1  605365  立达信    09:35:08     急速拉升       1.62%              29
#       ...
