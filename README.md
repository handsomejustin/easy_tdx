# easy-tdx

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/easy-tdx.svg)](https://pypi.org/project/easy-tdx/)

通达信 TCP 行情协议客户端。支持 A 股、港股、美股、期货全市场；内置 `easy-tdx` CLI 工具，默认 JSON 输出，天然适配 Claude Code、OpenClaw、Hermes 等 AI Agent 工具链。提供同步 + asyncio 双接口；strict mypy 通过；每一层编解码都有离线 fixture 测试覆盖。

## 安装

```bash
pip install easy-tdx
```

安装后自动注册 `easy-tdx` CLI 命令：

```bash
easy-tdx --help
```

开发模式：

```bash
pip install -e ".[dev]"
```

## CLI 参考

`easy-tdx` 默认输出 JSON（一行一条记录），`--table` 切换表格，`--output csv` 输出 CSV。

### 基础

```bash
easy-tdx ping                    # 服务器测速
easy-tdx version                 # 版本号
```

### 行情

```bash
# K 线
easy-tdx kline SZ 000001 --count 30 --table
easy-tdx kline SH 600519 --period 5MIN --adjust QFQ

# 实时报价
easy-tdx quote "SZ 000001,SH 600519" --table

# 市场分类报价（按涨幅排序）
easy-tdx quote-list A --count 20 --table
easy-tdx quote-list KCB --sort TOTAL_AMOUNT --order ASC
easy-tdx quote-list CYB --count 50
```

### 分时 / 成交

```bash
easy-tdx tick SZ 000001 --table
easy-tdx tick SH 600519 --days 5
easy-tdx tick SZ 000001 --date 20250115

easy-tdx transaction SZ 000001 --count 100 --table
easy-tdx transaction SH 600519 --date 20250115
```

### 板块

```bash
easy-tdx board-list --type GN --table
easy-tdx board-list --type HY --count 200
easy-tdx board-members 881001 --table
easy-tdx belong-board SZ 000001 --table
easy-tdx board-summary 881001 --table          # 板块汇总（成交额/主力净流入/涨跌家数）
easy-tdx board-summary 881001 --members --table # 含成分股明细
easy-tdx board-ranking --type HY --top 10 --table   # 行业板块排行
easy-tdx board-ranking --type GN --sort-by amount    # 概念板块按成交额排行
```

### 资金 / 监控

```bash
easy-tdx capital-flow SH 600519 --table
easy-tdx auction SZ 000001 --table
easy-tdx unusual SH --count 100 --table
easy-tdx market-stat --table
easy-tdx server-info --table
easy-tdx symbol-info SZ 000001 --table
```

### 技术指标

```bash
easy-tdx indicator-list --table                       # 列出所有可用指标
easy-tdx indicator MACD -m SH -c 600519 --table       # MACD
easy-tdx indicator KDJ -m SZ -c 000001 --table        # KDJ
easy-tdx indicator RSI -m SH -c 600519 --table        # RSI
easy-tdx indicator BOLL -m SH -c 600519 --table       # BOLL 布林带
easy-tdx indicator DMI -m SH -c 600519 --table        # DMI 动向指标
easy-tdx indicator ATR -m SH -c 600519 --table        # ATR 真实波幅
easy-tdx indicator WR -m SH -c 600519 --table         # WR 威廉指标
easy-tdx indicator CCI -m SH -c 600519 --table        # CCI 顺势指标
easy-tdx indicator BIAS -m SZ -c 000001 --table       # BIAS 乖离率
easy-tdx indicator OBV -m SZ -c 000001 --table        # OBV 能量潮

# 多指标同时计算
easy-tdx indicator MACD,KDJ,RSI,BOLL -m SH -c 600519 --count 10 --table

# 自定义参数
easy-tdx indicator MACD -m SH -c 600519 --params SHORT=10,LONG=22

# 分钟线指标
easy-tdx indicator MACD -m SH -c 600519 --period 5MIN --count 50

# 仅输出指标值（不含 OHLCV）
easy-tdx indicator RSI -m SZ -c 000001 --no-ohlcv
```

支持 30 个指标：MACD, KDJ, RSI, BOLL, DMI, ATR, WR, CCI, BIAS, OBV, VR, EMV, MFI, BRAR, ASI, TRIX, DPO, MTM, ROC, EXPMA, BBI, PSY, DFMA, CR, KTN, XSII, MASS, TAQ。

### 财务

```bash
easy-tdx f10 SH 600519              # F10 公司信息
easy-tdx fund-flow SH 600519        # 历史资金流向
```

### 扩展市场（港股/美股/期货）

```bash
easy-tdx ex markets                                       # 列出可用市场
easy-tdx ex kline HK_MAIN_BOARD 00700 --count 30 --table  # 港股 K 线
easy-tdx ex kline US_STOCK AAPL --table                    # 美股 K 线
easy-tdx ex quote US_STOCK TSLA --table                    # 美股报价
easy-tdx ex quote-list HK_MAIN_BOARD --table               # 港股商品列表
easy-tdx ex tick HK_MAIN_BOARD 00700 --table               # 港股分时
```

## CLI 命令汇总

| 命令 | 说明 |
|------|------|
| `ping` | 服务器延迟测速 |
| `version` | 版本号 |
| `kline` | K 线（日/周/月/分钟，支持复权） |
| `quote` | 实时报价（单只/批量） |
| `quote-list` | 市场分类排序报价（A/SH/SZ/KCB/CYB） |
| `tick` | 分时图（单日/多日/历史） |
| `transaction` | 逐笔成交 |
| `board-list` | 板块列表（行业/概念/风格） |
| `board-members` | 板块成分股报价 |
| `board-summary` | 板块汇总（成交额、主力净流入、涨跌家数） |
| `board-ranking` | 板块涨跌幅排行榜（行业/概念排行） |
| `belong-board` | 个股所属板块 |
| `capital-flow` | 资金流向 |
| `auction` | 集合竞价 |
| `unusual` | 市场异动 |
| `market-stat` | 全市场涨跌统计 |
| `server-info` | 服务器交易时段 |
| `symbol-info` | 个股特征快照 |
| `indicator` | 技术指标计算（30 个：MACD/KDJ/RSI/BOLL/DMI/ATR...） |
| `indicator-list` | 列出可用技术指标 |
| `f10` | F10 公司信息 |
| `fund-flow` | 历史资金流向 |
| `ex kline` | 扩展市场 K 线 |
| `ex quote` | 扩展市场报价 |
| `ex quote-list` | 扩展市场商品列表 |
| `ex tick` | 扩展市场分时 |
| `ex markets` | 列出可用扩展市场 |

## Python API

### 连接管理

所有客户端支持 `from_best_host()` 自动选最低延迟服务器：

```python
from easy_tdx import MacClient

with MacClient.from_best_host() as c:
    df = c.get_stock_kline(...)
```

| 客户端 | 端口 | 覆盖范围 |
|--------|------|----------|
| `MacClient` / `AsyncMacClient` | 7709 | A 股行情（MAC 协议，推荐） |
| `MacExClient` / `AsyncMacExClient` | 7727 | 港股/美股/期货（MAC 协议） |
| `UnifiedTdxClient` / `AsyncUnifiedTdxClient` | 自动 | A 股 + 扩展市场统一入口 |
| `TdxClient` / `AsyncTdxClient` | 7709 | A 股行情（标准协议） |

### MAC 协议（推荐）

#### 报价

```python
from easy_tdx import MacClient, Market, Category, SortType, SortOrder

with MacClient.from_best_host() as c:
    # 批量报价（最多 80 只/次）
    df = c.get_stock_quotes([(Market.SH, "600519"), (Market.SZ, "000858")])

    # 市场分类排序报价
    df = c.get_stock_quotes_list(
        Category.A, count=20,
        sort_type=SortType.CHANGE_PCT,
        sort_order=SortOrder.DESC,
    )
```

返回列：`market, code, name` + 动态字段（`pre_close, open, high, low, close, vol, amount, turnover, vol_ratio` 等）。

#### K 线（支持复权）

```python
from easy_tdx import MacClient, Market, Period, Adjust

with MacClient.from_best_host() as c:
    # 日K前复权
    df = c.get_stock_kline(Market.SH, "600519", Period.DAILY, count=10, adjust=Adjust.QFQ)
    # 5分钟线
    df = c.get_stock_kline(Market.SZ, "000001", Period.MIN_5, count=100)
```

返回列：`datetime, open, close, high, low, vol, amount`。

#### 技术指标

自动获取 200+ 条历史数据预热 EMA，返回最后 `count` 条带指标的结果：

```python
from easy_tdx import MacClient, Market, Period, Adjust
from easy_tdx.indicator import compute_indicators, list_indicators

with MacClient.from_best_host() as c:
    # 便捷方法：获取 K 线 + 计算指标一步完成（默认前复权）
    df = c.get_stock_kline_with_indicators(
        Market.SH, "600519",
        indicators=["MACD", "KDJ", "RSI", "BOLL"],
        count=30,
    )
    # df 包含: datetime, open, close, high, low, vol, amount
    #         + MACD_DIF, MACD_DEA, MACD_HIST, KDJ_K, KDJ_D, KDJ_J, RSI,
    #           BOLL_UPPER, BOLL_MID, BOLL_LOWER

    # 自定义指标参数
    df = c.get_stock_kline_with_indicators(
        Market.SH, "600519",
        indicators=["MACD"],
        params={"MACD": {"SHORT": 10, "LONG": 22}},
    )

    # 独立使用：对已有 DataFrame 计算指标
    raw = c.get_stock_kline(Market.SH, "600519", Period.DAILY, count=200, adjust=Adjust.QFQ)
    result = compute_indicators(raw, ["ATR", "CCI", "WR"], tail=30)

    # 查看所有可用指标
    for info in list_indicators():
        print(info["name"], info["description"], info["outputs"])
```

支持 30 个技术指标：

| 指标 | 输入 | 输出列 |
|------|------|--------|
| MACD | close | MACD_DIF, MACD_DEA, MACD_HIST |
| KDJ | close, high, low | KDJ_K, KDJ_D, KDJ_J |
| RSI | close | RSI |
| BOLL | close | BOLL_UPPER, BOLL_MID, BOLL_LOWER |
| DMI | close, high, low | DMI_PDI, DMI_MDI, DMI_ADX, DMI_ADXR |
| ATR | close, high, low | ATR |
| WR | close, high, low | WR1, WR2 |
| CCI | close, high, low | CCI |
| BIAS | close | BIAS1, BIAS2, BIAS3 |
| OBV | close, vol | OBV |
| VR | close, vol | VR |
| EMV | high, low, vol | EMV, EMV_MA |
| MFI | close, high, low, vol | MFI |
| BRAR | open, close, high, low | AR, BR |
| ASI | open, close, high, low | ASI, ASI_MA |
| TRIX | close | TRIX, TRIX_MA |
| DPO | close | DPO, DPO_MA |
| MTM | close | MTM, MTM_MA |
| ROC | close | ROC, ROC_MA |
| EXPMA | close | EXPMA_12, EXPMA_50 |
| BBI | close | BBI |
| PSY | close | PSY, PSY_MA |
| DFMA | close | DFMA_DIF, DFMA_DMA |
| CR | close, high, low | CR |
| KTN | close, high, low | KTN_UPPER, KTN_MID, KTN_LOWER |
| XSII | close, high, low | XSII_TD1, XSII_TD2, XSII_TD3, XSII_TD4 |
| MASS | high, low | MASS, MASS_MA |
| TAQ | high, low | TAQ_UP, TAQ_MID, TAQ_DOWN |

#### 分时

```python
with MacClient.from_best_host() as c:
    df = c.get_tick_chart(Market.SH, "600519")          # 单日分时
    df = c.get_tick_charts(Market.SH, "600519", days=3)  # 多日分时（最多5天）
    df = c.get_chart_sampling(Market.SH, "600519")       # 240点缩略采样
```

#### 逐笔成交

```python
with MacClient.from_best_host() as c:
    df = c.get_transactions(Market.SH, "600519", count=100)
    df = c.get_transactions(Market.SH, "600519", count=100, date=20250115)
```

#### 板块

```python
from easy_tdx import BoardType

with MacClient.from_best_host() as c:
    df = c.get_board_list(BoardType.GN)                       # 概念板块
    df = c.get_board_members("881001", sort_type=SortType.CHANGE_PCT)
    df = c.get_belong_board(Market.SZ, "000001")              # 个股所属板块

    # 板块汇总：成交额、主力净流入、涨跌家数
    summary = c.get_board_summary("881001")
    # summary = {
    #     "member_count": 82,
    #     "amount": 5823456000.0,        # 板块总成交额（元）
    #     "vol": 412356789,              # 板块总成交量（股）
    #     "main_net_amount": -123456.0,  # 当日主力净流入
    #     "main_net_3d": -567890.0,      # 近3日主力净流入
    #     "main_net_5d": -234567.0,      # 近5日主力净流入
    #     "up_count": 45,
    #     "down_count": 37,
    #     "members": DataFrame(...),     # 成分股明细
    # }

    # 板块涨跌幅排行榜
    df = c.get_board_ranking(BoardType.HY, top_n=10, sort_by="change_pct")
    df = c.get_board_ranking(BoardType.GN, top_n=20, sort_by="main_net_amount")
    # 返回列：code, name, change_pct, amount, vol, main_net_amount, up_count, down_count, member_count
```

#### 资金流向

```python
with MacClient.from_best_host() as c:
    df = c.get_capital_flow(Market.SH, "600519")
```

返回列：`date, main_in, main_out, main_net, small_in/out/net, mid_in/out/net, large_in/out/net`。

#### 监控

```python
with MacClient.from_best_host() as c:
    df = c.get_auction(Market.SH, "600519")     # 集合竞价
    df = c.get_unusual(Market.SH)               # 市场异动
    df = c.get_symbol_info(Market.SZ, "000001") # 个股特征快照
    df = c.get_server_info()                     # 服务器交易时段
```

### 扩展市场

```python
from easy_tdx import MacExClient, ExMarket, Period

with MacExClient.from_best_host() as c:
    count = c.goods_count(ExMarket.HK_MAIN_BOARD)
    df = c.goods_list(ExMarket.HK_MAIN_BOARD, start=0, count=50)
    df = c.goods_kline(ExMarket.US_STOCK, "AAPL", Period.DAILY, count=10)
    df = c.goods_quotes([(ExMarket.HK_MAIN_BOARD, "00700")])
    df = c.goods_tick_chart(ExMarket.HK_MAIN_BOARD, "00700")
    df = c.goods_transaction(ExMarket.HK_MAIN_BOARD, "00700", count=100)
```

### 统一客户端

```python
from easy_tdx import UnifiedTdxClient, ExMarket, Market, Period

with UnifiedTdxClient() as client:
    # A 股 -- 自动路由到 MacClient
    df = client.get_stock_kline(Market.SH, "600519", Period.DAILY, count=5)
    df = client.get_stock_quotes([(Market.SH, "600519")])
    df = client.get_board_list()

    # 扩展市场 -- 自动路由到 MacExClient
    df = client.goods_kline(ExMarket.HK_MAIN_BOARD, "00700", Period.DAILY, count=5)
```

### 标准协议

```python
from easy_tdx import TdxClient, Market, KlineCategory

with TdxClient.from_best_host() as c:
    count = c.get_security_count(Market.SH)
    stocks = c.get_security_list(Market.SH, start=0)
    quotes = c.get_security_quotes([(Market.SH, "600000"), (Market.SZ, "000001")])
    bars = c.get_security_bars(Market.SZ, "002176", KlineCategory.DAY, 0, 100)
    minute = c.get_minute_time_data(Market.SH, "600000")
    trades = c.get_transaction_data(Market.SH, "600000", 0, 20)
    flow = c.get_fund_flow(Market.SH, "600519")
    blocks = c.get_block_info("block_gn.dat")
    xdxr = c.get_xdxr_info(Market.SH, "600519")
    stat = c.get_market_stat()
```

`AsyncTdxClient` 提供对应的 `async def` 方法，接口一一对应。

### SecurityQuote 字段说明

`get_security_quotes()` 返回的 DataFrame 包含以下特殊字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `trading_status` | int | 交易状态标志。`0x8020`(32800) = 停牌，其余值表示正常交易或集合竞价 |
| `open_amount` | float | 集合竞价成交金额（元）。仅个股有效，指数该字段无意义 |
| `server_time` | str | 服务器时间，格式 `HH:MM:SS.mmm` |
| `unknown_2` | int | 指数: 集合竞价成交金额/100；个股: 舍入残差≈0 |
| `unknown_3` | int | 个股: 集合竞价成交金额/100；指数: 负值/无意义 |
| `unknown_5-8` | int | 保留字段，恒为 0 |

检测停牌：

```python
df = c.get_security_quotes([(Market.SH, "600000")])
is_suspended = df.iloc[0]["trading_status"] == 0x8020
```

### 离线数据读取

无需网络，从本地通达信安装目录直接读取：

```python
from easy_tdx.offline import detect_tdx_home, read_daily_bars, find_daily_bar_file
from easy_tdx import Market

home = detect_tdx_home()
filepath = find_daily_bar_file(Market.SH, "600000")
bars = read_daily_bars(filepath)
```

支持：日线、分钟线、扩展市场日线、板块、股本变迁、历史财务数据。

## 枚举参考

### Period（K 线周期）

| 值 | 名称 | 说明 |
|----|------|------|
| 7 | `MIN_1` | 1 分钟 |
| 0 | `MIN_5` | 5 分钟 |
| 1 | `MIN_15` | 15 分钟 |
| 2 | `MIN_30` | 30 分钟 |
| 3 | `MIN_60` | 60 分钟 |
| 4 | `DAILY` | 日线 |
| 5 | `WEEKLY` | 周线 |
| 6 | `MONTHLY` | 月线 |
| 10 | `QUARTERLY` | 季线 |
| 11 | `YEARLY` | 年线 |

### Adjust（复权类型）

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | `NONE` | 不复权 |
| 1 | `QFQ` | 前复权 |
| 2 | `HFQ` | 后复权 |

### Category（市场分类）

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | `SH` | 上证 A 股 |
| 2 | `SZ` | 深证 A 股 |
| 6 | `A` | 全部 A 股 |
| 7 | `B` | B 股 |
| 8 | `KCB` | 科创板 |
| 12 | `BJ` | 北证 A 股 |
| 14 | `CYB` | 创业板 |

### BoardType（板块类型）

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | `HY` | 行业一级 |
| 1 | `HY2` | 行业二级 |
| 3 | `GN` | 概念 |
| 4 | `FG` | 风格 |
| 5 | `DQ` | 地区 |
| 255 | `ALL` | 全部 |

### SortType（排序字段）

| 名称 | 说明 |
|------|------|
| `CODE` | 代码 |
| `PRICE` | 现价 |
| `CHANGE_PCT` | 涨幅% |
| `VOLUME` | 成交量 |
| `TOTAL_AMOUNT` | 成交额 |
| `TURNOVER_RATE` | 换手% |
| `MAIN_NET_AMOUNT` | 主力净额 |

### ExMarket（扩展市场）

| 值 | 名称 | 说明 |
|----|------|------|
| 28 | `ZZ_FUTURES` | 郑州商品 |
| 29 | `DL_FUTURES` | 大连商品 |
| 30 | `SH_FUTURES` | 上海期货 |
| 31 | `HK_MAIN_BOARD` | 香港主板 |
| 47 | `CFFEX_FUTURES` | 中金所期货 |
| 48 | `HK_GEM` | 香港创业板 |
| 74 | `US_STOCK` | 美国股票 |

### Market（市场）

| 值 | 名称 | 说明 |
|----|------|------|
| 0 | `SZ` | 深圳 |
| 1 | `SH` | 上海 |
| 2 | `BJ` | 北京 |

## 完整 API 列表

### MacClient / AsyncMacClient

| 方法 | 说明 |
|------|------|
| `get_stock_quotes(stocks, fields)` | 批量实时报价 |
| `get_stock_quotes_list(category, ...)` | 市场分类排序报价 |
| `get_stock_kline(market, code, period, ...)` | K 线（支持复权） |
| `get_stock_kline_with_indicators(market, code, indicators, ...)` | K 线 + 技术指标 |
| `get_tick_chart(market, code, date)` | 单日分时图 |
| `get_tick_charts(market, code, days)` | 多日分时图 |
| `get_chart_sampling(market, code)` | 分时缩略采样 |
| `get_transactions(market, code, ...)` | 逐笔成交 |
| `get_symbol_info(market, code)` | 个股特征快照 |
| `get_board_list(board_type, ...)` | 板块列表 |
| `get_board_members(board_symbol, ...)` | 板块成分股报价 |
| `get_board_summary(board_symbol, ...)` | 板块汇总（成交额、主力净流入、涨跌家数） |
| `get_board_ranking(board_type, top_n, sort_by, ...)` | 板块涨跌幅排行榜（行业/概念排行） |
| `get_belong_board(market, code)` | 个股所属板块 |
| `get_capital_flow(market, code)` | 资金流向 |
| `get_auction(market, code)` | 集合竞价 |
| `get_unusual(market, ...)` | 市场异动 |
| `get_server_info()` | 服务器交易时段 |
| `get_kline_offset(offset, count)` | K 线偏移信息 |
| `get_goods_list(market, ...)` | 扩展市场商品列表 |

### MacExClient / AsyncMacExClient

| 方法 | 说明 |
|------|------|
| `goods_count(market)` | 商品总数 |
| `goods_list(market, start, count)` | 商品列表 |
| `goods_quotes(stocks, fields)` | 批量报价 |
| `goods_quotes_list(market, ...)` | 市场分类报价列表 |
| `goods_kline(market, code, period, ...)` | K 线（支持复权） |
| `goods_tick_chart(market, code, ...)` | 分时图 |
| `goods_chart_sampling(market, code)` | 分时缩略采样 |
| `goods_transaction(market, code, ...)` | 逐笔成交 |

### TdxClient / AsyncTdxClient

| 方法 | 说明 |
|------|------|
| `get_security_count(market)` | 市场证券总数 |
| `get_security_list(market, start)` | 证券列表（分页） |
| `get_security_list_all()` | 沪深 A 股完整列表（含行业） |
| `get_security_quotes(stocks)` | 批量五档行情 |
| `get_security_bars(market, code, ...)` | 个股 K 线 |
| `get_index_bars(market, code, ...)` | 指数 K 线 |
| `get_minute_time_data(market, code)` | 今日分时 |
| `get_history_minute_time_data(market, code, date)` | 历史分时 |
| `get_transaction_data(market, code, ...)` | 当日逐笔成交 |
| `get_history_transaction_data(...)` | 历史逐笔成交 |
| `get_fund_flow(market, code)` | 当日资金流向 |
| `get_history_fund_flow(market, code, ...)` | 历史资金流向 |
| `get_xdxr_info(market, code)` | 除权除息历史 |
| `get_finance_info(market, code)` | 最新财务数据 |
| `get_company_info_category(market, code)` | 公司信息目录 |
| `get_company_info_content(...)` | 公司信息文本 |
| `get_block_info(filename)` | 板块信息 |
| `get_report_file(filename)` | 下载服务器文件 |
| `get_market_stat()` | 全市场涨跌统计 |
| `get_price_limits(market, code, name, pre_close)` | 涨跌停价 |

## 架构

```
src/easy_tdx/
├── client.py          # TdxClient / AsyncTdxClient（标准协议）
├── unified.py         # UnifiedTdxClient（统一入口）
├── config.py          # 服务器地址、端口、超时配置
├── indicator.py       # 技术指标计算（30 个，基于 MyTT）
├── MyTT.py            # 麦语言技术指标算法库
├── mac/
│   ├── client.py      # MacClient / AsyncMacClient（MAC 协议）
│   ├── enums.py       # Period, Adjust, Category, ExMarket, SortType, ...
│   ├── models.py      # MacBar, MacQuoteField, MacTick, BoardInfo, ...
│   └── commands/      # MAC 命令（build_request + parse_response，无 IO）
├── ex/
│   ├── client.py      # ExTdxClient / AsyncExTdxClient（标准协议扩展市场）
│   ├── mac_client.py  # MacExClient / AsyncMacExClient（MAC 协议扩展市场）
│   └── transport/     # ExTdxConnection（端口 7727）
├── transport/
│   ├── sync.py        # TdxConnection + ping_host / ping_all
│   └── async_.py      # AsyncTdxConnection（asyncio）
├── commands/          # 标准协议命令（无 IO）
├── codec/             # price / volume / datetime / frame / bitmap 编解码
├── models/            # 纯 dataclass，无业务逻辑
├── offline/           # 离线数据读取模块
└── cli/               # easy-tdx CLI（click）
```

commands 层不依赖 transport，可独立单测。

## 开发

```bash
python -m pytest tests/unit/ -v                             # 单元测试（无需网络）
XMTDX_LIVE=1 python -m pytest tests/integration/ -v        # 集成测试
mypy src/                                                    # 类型检查
ruff check src/ tests/                                       # lint
ruff format --check src/ tests/                              # format check
```

## 致谢

- [pytdx](https://github.com/rainx/pytdx) -- 离线数据读取模块借鉴自 pytdx 项目，感谢 rainx 及所有贡献者
- [xmtdx](https://github.com/minionszyw/xmtdx) -- 本项目初始原型
- [mootdx](https://github.com/mootdx/mootdx) -- 工程化封装参考
- [MyTT](https://github.com/mpquant/MyTT) -- 麦语言技术指标算法库，技术指标计算基于此实现

详见 [NOTICE](NOTICE) 和 [LICENSE](LICENSE)。

## Changelog

### 1.4.0 (2026-05-28)

**技术指标计算** — 集成 [MyTT](https://github.com/mpquant/MyTT) 麦语言指标库，支持 30 个常用技术指标，一步获取 K 线 + 指标值。

- 新增 `indicator.py` 核心模块：注册表驱动的指标调度，`compute_indicators()` 纯计算无 IO
- 新增 `MacClient.get_stock_kline_with_indicators()` / `AsyncMacClient` 同名方法
- 新增 `UnifiedTdxClient.get_stock_kline_with_indicators()` / `AsyncUnifiedTdxClient` 同名方法
- 新增 CLI 命令 `easy-tdx indicator` 和 `easy-tdx indicator-list`
- 自动获取 200+ 条历史数据预热 EMA，用户只需指定返回条数
- 支持的指标：MACD, KDJ, RSI, BOLL, DMI, ATR, WR, CCI, BIAS, OBV, VR, EMV, MFI, BRAR, ASI, TRIX, DPO, MTM, ROC, EXPMA, BBI, PSY, DFMA, CR, KTN, XSII, MASS, TAQ

### 1.3.1 (2025-05-15)

- 新增 `board-summary` 和 `board-ranking` CLI 命令
- 新增 `get_board_summary()` 板块汇总（成交额、主力净流入、涨跌家数）
- 新增 `get_board_ranking()` 板块涨跌幅排行榜

### 1.3.0 (2025-05-12)

- 新增 MAC 协议客户端 `MacClient` / `AsyncMacClient`（端口 7709）
- 新增扩展市场客户端 `MacExClient` / `AsyncMacExClient`（端口 7727）
- 新增统一客户端 `UnifiedTdxClient` 自动路由 A 股 / 扩展市场
- 新增板块、资金流向、集合竞价、异动、个股特征等数据接口
- 新增 `easy-tdx` CLI 工具，默认 JSON 输出

### 1.2.1 (2025-04-20)

- 离线数据读取模块（日线、分钟线、板块、财务）
- 除权除息、股本变迁读取

### 1.0.0 (2025-03-01)

- 首个正式版本
- TdxClient / AsyncTdxClient 标准协议客户端
- K 线、实时报价、分时、逐笔成交、财务数据
