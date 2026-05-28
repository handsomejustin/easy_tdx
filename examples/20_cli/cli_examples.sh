#!/bin/bash
# easy-tdx CLI 使用示例大全
# 所有命令均不实际执行，仅供展示用法和注释输出。
#
# 通用参数说明:
#   --table          以表格形式输出（默认 JSON）
#   --output PATH    将结果写入文件（支持 .csv / .xlsx / .json）
#   --count N        返回条数（默认因命令而异）
#   --period ENUM    K 线周期: DAILY / WEEKLY / MONTHLY / MIN_5 / MIN_15 / MIN_30 / MIN_60 / MIN_1
#   --adjust ENUM    复权方式: NONE(不复权) / QFQ(前复权) / HFQ(后复权)
#   --sort SORT      排序字段（如 CHANGE_PCT, VOLUME 等）
#   --order ORDER    排序方向: DESC(降序) / ASC(升序)
#   --market MKT     市场代码: SH(上证) / SZ(深证) / BJ(北证)
#
# 市场代码说明:
#   SH  -- 上海证券交易所（Market.SH = 1）
#   SZ  -- 深圳证券交易所（Market.SZ = 0）
#   BJ  -- 北京证券交易所（Market.BJ = 12）
#
# 扩展市场代码说明（ex 子命令使用）:
#   HK_MAIN_BOARD    -- 香港主板 (31)     US_STOCK       -- 美国股票 (74)
#   CFFEX_FUTURES    -- 中金所期货 (47)   ZZ_FUTURES     -- 郑州商品 (28)
#   DL_FUTURES       -- 大连商品 (29)     SH_FUTURES     -- 上海期货 (30)
#   HK_GEM           -- 香港创业板 (48)

echo "=== 1. 服务器测速 ==="
# 测试所有已知行情服务器的延迟。
# --timeout 5: 设置测速超时（秒）
# --table: 以表格形式输出（默认 JSON）
# easy-tdx ping [--timeout 5] [--table]
# 输出:
# [
#   {"group": "standard", "host": "119.147.212.81", "latency_ms": 12.3},
#   {"group": "standard", "host": "112.74.214.43", "latency_ms": 18.7},
#   {"group": "standard", "host": "221.231.141.60", "latency_ms": 25.1},
#   {"group": "mac", "host": "112.74.214.43", "latency_ms": 19.5},
#   {"group": "mac", "host": "119.147.212.81", "latency_ms": 13.8}
# ]

echo "=== 2. 查看版本 ==="
# easy-tdx version
# 输出:
# easy-tdx 1.0.0

echo "=== 3. 获取K线（平安银行）==="
# 获取 K 线数据。SZ 表示深证，000001 为平安银行。
# 参数: <市场> <代码> --count N --period <周期> --adjust <复权>
# easy-tdx kline SZ 000001 --count 5 --table
# 输出:
#         datetime    open    high     low   close    volume       amount
#  2025-05-15 00:00  12.35   12.50   12.30   12.45  45678900   567890000
#  2025-05-16 00:00  12.45   12.58   12.40   12.52  38901200   487650000
#  2025-05-19 00:00  12.50   12.65   12.48   12.60  42345600   534567000
#  2025-05-20 00:00  12.60   12.68   12.52   12.55  35678900   448760000
#  2025-05-21 00:00  12.55   12.70   12.50   12.68  40123400   508765000

echo "=== 4. 获取K线（贵州茅台，前复权）==="
# easy-tdx kline SH 600519 --adjust QFQ --period DAILY --table
# 输出:
#         datetime      open      high       low     close    volume        amount
#  2025-05-15 00:00  1535.00  1548.00  1528.00  1542.00    345678  532456000000
#  2025-05-16 00:00  1542.00  1556.00  1535.00  1548.50    312345  483456000000
#  2025-05-19 00:00  1548.00  1560.00  1540.00  1555.00    378901  588765000000
#  2025-05-20 00:00  1555.00  1562.00  1545.00  1548.00    298765  462345000000
#  2025-05-21 00:00  1548.00  1558.00  1542.00  1552.50    323456  501234000000

echo "=== 5. 获取实时报价（多只）==="
# 批量获取实时报价。多只股票用逗号分隔，格式为 "市场 代码"。
# 参数: "市场 代码,市场 代码,..." --table
# 最多 80 只/次。
# 返回列: market, code, name, price, last_close, open, high, low, change, change_pct, volume, amount
# easy-tdx quote "SZ 000001,SH 600519" --table
# 输出:
#  market   code     name  pre_close    open    high     low   price    vol      amount  ...
#      0  000001  平安银行     12.55   12.58   12.72   12.55   12.68  38901200  492345000  ...
#      1  600519  贵州茅台   1548.00  1552.00  1560.00  1545.00  1555.00    298765  464567000000  ...

echo "=== 6. 获取市场分类报价列表 ==="
# 获取市场分类排序报价。A=全部A股, SH=上证A, SZ=深证A, KCB=科创板, CYB=创业板。
# 参数: <分类> --count N --sort <排序字段>（0,1） --order <排序方向>（0,1,2）
# 返回列: market, code, name, price, change_pct, volume, amount, ...
# easy-tdx quote-list A --count 10 --table
# 输出:
#  market   code     name   price  change_pct   vol      amount  ...
#      0  300XXX  某某科技   25.80      +20.00   123456   318765000  ...
#      0  301XXX  某某电子   18.50      +15.32    98765   182765000  ...
#      1  688XXX  某某芯片   42.30      +12.56    67890   287456000  ...
#      0  002XXX  某某新材   33.60      +10.04   156789   527234000  ...
#      0  300XXX  某某医药   56.20       +8.75    45678   256789000  ...
#  ...（共10条）

echo "=== 7. 获取分时图 ==="
# 获取当日分时走势。返回约 330 条分钟级数据。
# 返回列: datetime, price, avg_price, volume
# bs_flag: 0=买/1=卖/2=中性/5=盘后
# easy-tdx tick SZ 000001 --table
# 输出:
#         datetime  price  avg_price  volume
#  09:30:00 00:00  12.58      12.58       0
#  09:31:00 00:00  12.60      12.59    5600
#  09:32:00 00:00  12.62      12.60    3400
#  09:33:00 00:00  12.58      12.60    2800
#  09:34:00 00:00  12.55      12.59    4100
#  ...（共约330条）

echo "=== 8. 获取多日分时图 ==="
# 获取多日分时走势。--days N 指定天数（最多 5 天）。
# 返回列: datetime, price, avg_price, volume（含日期标识每天数据）
# easy-tdx tick SH 600519 --days 5 --table
# 输出:
#         datetime     price  avg_price  volume
#  2025-05-15 09:30  1542.00    1542.00       0
#  2025-05-15 09:31  1543.50    1542.75     120
#  2025-05-15 09:32  1545.00    1543.50      85
#  ...
#  2025-05-21 09:30  1548.00    1548.00       0
#  2025-05-21 09:31  1550.00    1549.00      95
#  ...（共约1650条，5天）

echo "=== 9. 获取逐笔成交 ==="
# 获取逐笔成交明细。--count N 指定返回条数。
# 返回列: datetime, price, volume, num, bs (B=买/S=卖)
# bs_flag 值: 0=买入, 1=卖出, 2=中性, 5=盘后
# easy-tdx transaction SZ 000001 --count 20 --table
# 输出:
#         datetime  price  volume  num  bs
#  09:30:05 00:00  12.58     100    1   B
#  09:30:05 00:00  12.58     200    1   B
#  09:30:06 00:00  12.59     300    1   B
#  09:30:06 00:00  12.57     500    1   S
#  09:30:07 00:00  12.58     100    1   B
#  ...（共20条）

echo "=== 10. 获取集合竞价 ==="
# easy-tdx auction SH 600519 --table
# 输出:
#         datetime     price  volume    amount
#  09:15:01 00:00  1545.00    1234  1906530
#  09:15:06 00:00  1548.00    2345  3630060
#  09:15:11 00:00  1550.00    3456  5356800
#  09:15:16 00:00  1548.50    2567  3976479
#  09:15:21 00:00  1549.00    1890  2927610
#  09:25:00 00:00  1550.00    5678  8800900

echo "=== 11. 获取板块列表 ==="
# 获取板块列表。--type 指定板块类型: HY(行业), GN(概念), FG(风格), DQ(地区), ALL(全部)。
# 返回列: code, name, price, rise_speed, pre_close, symbol_code, symbol_name, ...
# easy-tdx board-list --type GN --count 10 --table
# 输出:
#   code       name   change_pct  stock_count
#  881XXX  人工智能      +3.25         128
#  881XXX  芯片概念      +2.87          96
#  881XXX  新能源车      +2.45         152
#  881XXX  锂电池        +2.12         110
#  881XXX  光伏概念      +1.98          87
#  881XXX  军工电子      +1.76          73
#  881XXX  医药电商      +1.54          45
#  881XXX  白酒概念      +1.32          32
#  881XXX  数字经济      +1.15          68
#  881XXX  机器人        +0.98          54

echo "=== 12. 获取板块成分股 ==="
# 获取板块成分股报价。参数为板块代码（如 881001）。
# --sort CHANGE_PCT --order DESC 按涨幅降序。
# 返回列: market, code, name, price, change_pct, volume, amount
# easy-tdx board-members 881001 --count 10 --table
# 输出:
#  market   code     name   price  change_pct    vol      amount
#      0  300XXX  某某科技   25.80      +10.02   45678   117890000
#      1  688XXX  某某芯片   42.30       +8.56   23456    99234000
#      0  002XXX  某某软件   18.90       +6.78   67890   128345000
#      0  000XXX  某某信息   33.50       +5.43   12345    41356000
#      0  300XXX  某某电子   56.20       +4.32   34567   194345000
#  ...（共10条）

echo "=== 13. 查询个股所属板块 ==="
# 查询指定股票所属的所有板块（行业、概念、风格等）。
# 返回列: board_type(0=行业/3=概念/4=风格), board_code, board_name, close, pre_close
# easy-tdx belong-board SZ 000001 --table
# 输出:
#   code       name  type
#  881XXX      银行    HY
#  881XXX    深证成指    GN
#  881XXX    融资融券    GN
#  881XXX    沪深300    GN
#  881XXX   MSCI概念    GN
#  881XXX    标普道琼斯  GN

echo "=== 14. 获取个股资金流向 ==="
# 获取个股多日资金流向。包含主力/大单/中单/小单的流入流出净额。
# 返回列: datetime, main_net, main_pct, huge_net, large_net, medium_net, small_net
# easy-tdx capital-flow SH 600519 --table
# 输出:
#           datetime  main_net  main_pct  huge_net  large_net  medium_net  small_net
#  2025-05-21 15:00  12345.6      1.25  23456.7   -11111.1    -5678.9   -6666.7
# 2025-05-20 15:00  -8765.4     -0.89  12345.6   -21111.0     4321.0    4444.4
# 2025-05-19 15:00   5432.1      0.55   6789.0    -1356.9    -1234.5   -4197.6

echo "=== 15. 获取市场异动 ==="
# 获取全市场异动数据。包含快速拉升、大幅下跌、大笔成交等异动类型。
# 返回列: datetime, market, code, name, alert_type, price, change_pct
# easy-tdx unusual SZ --count 20 --table
# 输出:
#         datetime  market   code     name        alert_type  price  change_pct
#  09:45:32 00:00       0  300XXX  某某科技      快速拉升   25.80       +8.56
#  09:52:18 00:00       0  002XXX  某某新材      大笔买入   33.60       +5.32
#  10:05:44 00:00       0  000XXX  某某医药      封涨停板   18.90      +10.00
#  10:12:07 00:00       0  300XXX  某某电子      快速下跌   12.45       -7.21
#  10:23:55 00:00       0  002XXX  某某食品      大笔卖出   45.60       -3.45
#  ...（共20条）

echo "=== 16. 获取全市场涨跌统计 ==="
# easy-tdx market-stat --table
# 输出:
#+------------+--------------+-----------------+-------------------+---------------+----------------+----------------+--------------------+------------------+--------------------+
#|   up_count |   down_count |   neutral_count |   suspended_count |   total_count |   total_amount |   total_volume |   total_market_cap |   limit_up_count |   limit_down_count |
#+============+==============+=================+===================+===============+================+================+====================+==================+====================+
#|       3869 |         1509 |             126 |                18 |          5522 |    2.92468e+12 |    1.35881e+09 |         1.1915e+14 |              136 |                 18 |
#+------------+--------------+-----------------+-------------------+---------------+----------------+----------------+--------------------+------------------+--------------------+

echo "=== 17. 获取服务器交易时段信息 ==="
# easy-tdx server-info --table
# 输出:
#  name           start    end        status
#  早盘集合竞价    09:15    09:25      closed
#  早盘连续竞价    09:30    11:30      open
#  午盘连续竞价    13:00    15:00      open
#  盘后固定价格    15:05    15:30      closed

echo "=== 18. 获取个股简要特征快照 ==="
# 获取个股简要特征快照。包含活跃度、内外盘、换手率、均价等。
# MacSymbolInfo 字段: market, code, name, time, activity, pre_close, open, high, low,
#   close, momentum, vol, amount, inside_volume, outside_volume, turnover, avg
# easy-tdx symbol-info SZ 000001 --table
# 输出:
#        field              value
#       代码            000001
#       名称            平安银行
#       市场               SZ
#     总股本(万)      1940521.84
#     流通股(万)      1940521.84
#     总市值(亿)      24509.37
#     流通市值(亿)    24509.37

echo "=== 19. 列出扩展市场代码 ==="
# 列出所有可用的 ExMarket 枚举值和名称。
# 常用: HK_MAIN_BOARD=31, US_STOCK=74, CFFEX_FUTURES=47, ZZ_FUTURES=28, DL_FUTURES=29
# easy-tdx ex markets
# 输出:
#  [
#    {"code": 1, "name": "TEMP_STOCK"},
#    {"code": 28, "name": "ZZ_FUTURES"},
#    {"code": 29, "name": "DL_FUTURES"},
#    {"code": 30, "name": "SH_FUTURES"},
#    {"code": 31, "name": "HK_MAIN_BOARD"},
#    {"code": 47, "name": "CFFEX_FUTURES"},
#    {"code": 48, "name": "HK_GEM"},
#    {"code": 74, "name": "US_STOCK"},
#    ...
#  ]

echo "=== 20. 获取扩展市场K线（港股腾讯）==="
# 获取扩展市场 K 线。参数: <ExMarket名称> <代码> --count N --period <周期>
# 返回列: datetime, open, high, low, close, volume, amount
# easy-tdx ex kline HK_MAIN_BOARD 00700 --count 10 --table
# 输出:
#         datetime   open   high    low  close    volume      amount
#  2025-05-12 00:00  520.0  528.0  518.5  525.0  16543000  8676540000
#  2025-05-13 00:00  525.0  530.0  522.0  523.5  14321000  7498760000
#  2025-05-14 00:00  523.5  527.0  520.0  525.5  13456000  7076540000
#  2025-05-15 00:00  525.0  530.0  522.5  528.0  15234000  8011230000
#  2025-05-16 00:00  528.0  532.0  525.5  530.5  12345000  6543210000
#  2025-05-19 00:00  531.0  535.0  529.0  533.0  14567000  7765430000
#  2025-05-20 00:00  533.0  536.0  530.0  531.5  11234000  5987650000
#  2025-05-21 00:00  532.0  537.0  530.5  535.0  13456000  7187650000
#  ...（共10条）

echo "=== 21. 获取扩展市场报价（美股苹果）==="
# 获取单只扩展市场股票报价。参数: <ExMarket名称> <代码>
# 返回列: market, code, name, pre_close, open, high, low, price, volume, amount
# easy-tdx ex quote US_STOCK AAPL --table
# 输出:
#  market  code   name   pre_close    open    high     low   price    volume        amount
#      74  AAPL  APPLE     213.75  214.00  218.00  213.50  217.50  49876000  10789650000

echo "=== 22. 获取扩展市场商品列表（港股主板）==="
# 获取扩展市场商品列表。参数: <ExMarket名称> --count N
# 返回列: code(证券代码), name(证券名称), market(市场代码)
# easy-tdx ex quote-list HK_MAIN_BOARD --count 10 --table
# 输出:
#        code           name  market
#      00001         长和      31
#      00002         中电控股    31
#      00003         香港中华煤气  31
#      00004         九龙仓集团   31
#      00005         汇丰控股    31
#      00006         电能实业    31
#      00007         高鑫零售    31
#      00008         新鸿基地产   31
#      00009         载通       31
#      00010         恒隆地产    31

echo "=== 23. 获取扩展市场分时图（港股腾讯）==="
# 获取扩展市场当日分时走势。参数: <ExMarket名称> <代码>
# 返回列: datetime, price, avg_price, volume
# easy-tdx ex tick HK_MAIN_BOARD 00700 --table
# 输出:
#         datetime   price   avg_price  volume
#  09:30:00 00:00  532.00      532.00       0
#  09:31:00 00:00  532.50      532.25    5600
#  09:32:00 00:00  533.00      532.50    3400
#  09:33:00 00:00  533.50      532.75    2800
#  09:34:00 00:00  532.80      532.56    4100
#  09:35:00 00:00  533.20      532.84    3500
#  ...（共约330条）

echo "=== 24. 列出可用技术指标 ==="
# 列出所有支持的技术指标名称、输入需求和输出列。
# easy-tdx indicator-list --table
# 输出:
#  name    description                     inputs                  outputs                       default_params
#  MACD    MACD 指数平滑异同移动平均线     ['close']               ['MACD_DIF', 'MACD_DEA', ...]  {'SHORT': 12, 'LONG': 26, 'M': 9}
#  KDJ     KDJ 随机指标                    ['close', 'high', ...]  ['KDJ_K', 'KDJ_D', 'KDJ_J']   {'N': 9, 'M1': 3, 'M2': 3}
#  RSI     RSI 相对强弱指标                ['close']               ['RSI']                       {'N': 24}
#  BOLL    BOLL 布林带                     ['close']               ['BOLL_UPPER', 'BOLL_MID'...]  {'N': 20, 'P': 2}
#  ...（共30个指标）

echo "=== 25. 计算单个技术指标（MACD）==="
# 计算单只股票的技术指标。默认前复权（QFQ），返回最近 30 条。
# 参数: <指标名> -m <市场> -c <代码> --count N --table
# 返回列: datetime, open, high, low, close, vol, amount + 指标列
# easy-tdx indicator MACD -m SH -c 600519 --table
# 输出:
#  datetime              open     high      low    close    vol       amount  MACD_DIF  MACD_DEA  MACD_HIST
#  2025-05-06 00:00:00  1498.00  1518.00  1492.00  1510.00  16540  2500000000     -4.56     -2.94      -3.24
#  2025-05-07 00:00:00  1505.00  1516.00  1490.00  1498.00  14280  2150000000     -3.12     -3.18       0.11
#  2025-05-08 00:00:00  1492.00  1510.00  1485.00  1505.00  15670  2350000000     -2.45     -3.03       1.16
#  2025-05-09 00:00:00  1498.00  1516.00  1490.00  1498.00  14280  2150000000     -1.89     -2.80       1.82
#  2025-05-12 00:00:00  1505.00  1516.00  1490.00  1498.00  14280  2150000000     -1.78     -2.60       1.64
#  ...（默认30条）

echo "=== 26. 同时计算多个指标 ==="
# 用逗号分隔多个指标名称（不区分大小写）。
# easy-tdx indicator MACD,KDJ,RSI,BOLL -m SH -c 600519 --count 5 --table
# 输出:
#  datetime            close  MACD_DIF  MACD_DEA  MACD_HIST  KDJ_K  KDJ_D   KDJ_J   RSI  BOLL_UPPER  BOLL_MID  BOLL_LOWER
#  2025-05-09 00:00  1505.00    -1.89     -2.80      1.82  45.23  52.34   31.01  55.6    1530.45   1500.12    1469.79
#  2025-05-12 00:00  1498.00    -1.78     -2.60      1.64  38.56  48.89   17.90  48.2    1528.90   1498.56    1468.22
#  2025-05-13 00:00  1510.00    -0.89     -2.26      2.74  62.34  52.17   82.68  56.8    1527.34   1497.00    1466.66
#  2025-05-14 00:00  1509.00    -0.12     -1.83      3.42  58.12  53.56   67.24  52.3    1525.78   1495.44    1465.10
#  2025-05-15 00:00  1521.00     1.23     -1.22      4.90  78.45  59.74  115.87  65.1    1524.22   1493.88    1463.54

echo "=== 27. 自定义指标参数 ==="
# 通过 --params 覆盖默认参数。格式: KEY=VALUE 或 INDICATOR.KEY=VALUE
# 修改 MACD 短周期为 10，长周期为 22
# easy-tdx indicator MACD -m SH -c 600519 --params SHORT=10,LONG=22 --table
#
# 同时计算 MACD 和 KDJ，分别为它们设置不同参数:
# easy-tdx indicator MACD,KDJ -m SH -c 600519 --params MACD.SHORT=10,KDJ.N=14 --table

echo "=== 28. 仅输出指标值（不含 OHLCV）==="
# 加 --no-ohlcv 隐藏原始 K 线列，仅显示时间 + 指标值。
# easy-tdx indicator RSI -m SZ -c 000001 --no-ohlcv --count 5 --table
# 输出:
#  datetime               RSI
#  2025-05-09 00:00:00  52.34
#  2025-05-12 00:00:00  48.67
#  2025-05-13 00:00:00  56.12
#  2025-05-14 00:00:00  51.89
#  2025-05-15 00:00:00  63.45

echo "=== 29. 分钟 K 线技术指标 ==="
# 使用 --period 指定分钟周期，与 K 线命令相同。
# easy-tdx indicator MACD -m SH -c 600519 --period 5MIN --count 10 --table
# 输出:
#  datetime            close  MACD_DIF  MACD_DEA  MACD_HIST
#  2025-05-15 14:10  1520.50     0.34     0.28      0.12
#  2025-05-15 14:15  1518.20     0.21     0.27     -0.11
#  2025-05-15 14:20  1519.80     0.18     0.25     -0.15
#  2025-05-15 14:25  1521.00     0.23     0.25     -0.04
#  ...（共10条）

echo "=== 30. 常用指标快速参考 ==="
# MACD:  easy-tdx indicator MACD -m SH -c 600519 --table
# KDJ:   easy-tdx indicator KDJ -m SZ -c 000001 --table
# RSI:   easy-tdx indicator RSI -m SH -c 600519 --table
# BOLL:  easy-tdx indicator BOLL -m SH -c 600519 --table
# DMI:   easy-tdx indicator DMI -m SH -c 600519 --table
# ATR:   easy-tdx indicator ATR -m SH -c 600519 --table
# WR:    easy-tdx indicator WR -m SH -c 600519 --table
# CCI:   easy-tdx indicator CCI -m SH -c 600519 --table
# BIAS:  easy-tdx indicator BIAS -m SZ -c 000001 --table
# OBV:   easy-tdx indicator OBV -m SZ -c 000001 --table
