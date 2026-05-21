# easy-tdx

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

通达信（tdx）是中国使用最广泛的券商行情终端之一，其私有 TCP 协议长期缺乏官方 SDK。[pytdx](https://github.com/rainx/pytdx) 率先完成了协议逆向与离线数据读取，为整个生态奠定了基础；[mootdx](https://github.com/mootdx/mootdx) 在此之上做了工程化封装，让更多开发者得以使用；[xmtdx](https://github.com/minionszyw/xmtdx) 进一步探索了现代 Python 接口设计。

easy-tdx 站在这些项目的肩膀上，从协议层重新实现：LEB128 价格编解码、自定义浮点成交量、帧解压缩与握手——每一层都有对应的离线 fixture 测试。commands 层不含 IO，与 transport 完全解耦；同步 + asyncio 双接口；strict mypy 通过；零运行时依赖；每条记录保留原始字节。覆盖标准行情、扩展市场（期货/港股/外盘）、离线本地数据读取、专业财务数据全场景。

感谢 rainx、mootdx 社区及 minionszyw 的开创性工作——没有他们，就不会有这个项目。

详见 [NOTICE](NOTICE) 和 [LICENSE](LICENSE) 文件。

## 特性

- **零依赖**：纯标准库，Python >= 3.10
- **同步 + asyncio 双接口**：`TdxClient` / `AsyncTdxClient`，commands 层不含任何 IO
- **完整类型注解**：strict `mypy` + `ruff` 通过
- **高可用传输**：同步/异步均支持 `ping_all()`、`from_best_host()`、断线自动重连
- **修复 pytdx 已知 bug**（见下文）
- **保留原始字节**：每条数据记录含 `_raw: bytes`，未知字段以 `unknown_N` 命名而非丢弃
- **保活心跳机制**：`AsyncTdxClient` 自动发送心跳包，确保长连接生产环境稳定性
- **扩展行情**：`ExTdxClient` / `AsyncExTdxClient` 支持期货、港股、外盘等扩展市场（端口 7727）
- **离线数据读取**：从本地通达信安装目录直接读取日线、分钟线、财务、板块、股本变迁等数据，无需网络
- **专业财务数据**：通过计算服务器下载历史财报 ZIP 文件并解析

## 安装

```bash
pip install -e .                  # 开发模式
pip install -e ".[dev]"           # 含测试/类型检查工具
pip install -e ".[pandas]"        # 含 pandas（可选）
```

## 快速开始

### 连接与基本查询

```python
from easy_tdx import TdxClient, Market, KlineCategory

# 手动指定服务器
with TdxClient("180.153.18.170") as c:
    count = c.get_security_count(Market.SH)
    print(f"沪市证券总数: {count}")

# 自动优选最低延迟服务器
with TdxClient.from_best_host() as c:
    df = c.get_security_bars(Market.SH, "600000", KlineCategory.DAY, 0, 5)
    print(df.to_string(index=False))
    #        date   open  close   high    low         vol       amount
    # 2025-01-02  10.25  10.12  10.25  10.08  108154752.0 1.078280e+09
```

### asyncio

```python
import asyncio
from easy_tdx import AsyncTdxClient, Market, KlineCategory

async def main():
    async with AsyncTdxClient.from_best_host() as c:
        df = await c.get_security_bars(
            Market.SH, "600000", KlineCategory.DAY, 0, 5
        )
        print(df.to_string(index=False))

asyncio.run(main())
```

### 服务器测速

```python
from easy_tdx import TdxClient

# 测速并排序
results = TdxClient.ping_all()
for host, latency in results:
    print(f"{host}  {latency * 1000:.0f} ms")
```

## API 参考

### 连接管理

| 方法 | 说明 |
|------|------|
| `TdxClient(host, port=7709, timeout=15.0)` | 指定服务器创建客户端 |
| `TdxClient.from_best_host(ping_timeout=5.0)` | 自动选延迟最低的服务器 |
| `TdxClient.ping_all(timeout=5.0)` | 并发测速，返回 `[(host, seconds), ...]` |
| `AsyncTdxClient` / `AsyncTdxClient.from_best_host()` | 异步版，接口一一对应 |

内置服务器列表 `KNOWN_HOSTS`（8 台）和计算服务器 `CALC_HOSTS`（1 台）。

### 市场信息

```python
with TdxClient.from_best_host() as c:
    # 市场证券总数
    count = c.get_security_count(Market.SH)

    # 证券列表（分页，每页约 1000 条）
    stocks = c.get_security_list(Market.SH, start=0)
    # stocks[0].code / .name / .pre_close / .industry_tdx / .industry_sw

    # 沪深 A 股完整列表（自动挂载行业信息，本地缓存 1 天）
    all_stocks = c.get_security_list_all()

    # 批量实时五档行情（最多 80 只/次）
    quotes = c.get_security_quotes([
        (Market.SH, "600000"),   # 浦发银行
        (Market.SH, "600519"),   # 贵州茅台
        (Market.SZ, "000001"),   # 平安银行
        (Market.SZ, "000858"),   # 五粮液
    ])
    # quotes[0].price / .pre_close / .open / .high / .low / .bid1..bid5 / .ask1..ask5

    # 全市场涨跌统计
    stat = c.get_market_stat()
    # stat.up_count / .down_count / .neutral_count / .total_amount / .total_market_cap
```

### K 线数据

```python
from easy_tdx import Market, KlineCategory

with TdxClient.from_best_host() as c:
    # 个股 K 线
    bars = c.get_security_bars(Market.SZ, "002176", KlineCategory.DAY, 0, 100)

    # 指数 K 线（常用指数代码：上证 "999999"，深成 "399001"，创业板 "399006"）
    bars = c.get_index_bars(Market.SH, "999999", KlineCategory.DAY, 0, 10)
```

K 线类别：

```
KlineCategory.MIN_1  MIN_5  MIN_15  MIN_30  MIN_60
KlineCategory.DAY    WEEK   MONTH   YEAR
```

K 线字段：`date`（日线及以上）或 `datetime`（分钟线） `open` `close` `high` `low` `vol` `amount`

### 分时数据

```python
with TdxClient.from_best_host() as c:
    # 今日分时（240 条）
    bars = c.get_minute_time_data(Market.SH, "600000")

    # 历史某日分时，date 为 YYYYMMDD 格式整数
    bars = c.get_history_minute_time_data(Market.SH, "600000", 20250110)
```

分时字段：`datetime` `price` `vol`

### 逐笔成交

```python
with TdxClient.from_best_host() as c:
    # 当日逐笔成交（分页）
    records = c.get_transaction_data(Market.SH, "600000", 0, 20)

    # 历史逐笔成交
    records = c.get_history_transaction_data(Market.SH, "600000", 20250110, 0, 20)
```

成交字段：`datetime` `price` `vol` `buyorsell`（0=买, 1=卖, 2=中性, 8=集合竞价）

### 财务与公司信息

```python
from easy_tdx import XDXR_CATEGORY_NAMES

with TdxClient.from_best_host() as c:
    # 除权除息历史
    records = c.get_xdxr_info(Market.SH, "600519")
    # records[0].fenhong / .songzhuangu / .peigujia / .peigu

    # 最新财务数据
    info = c.get_finance_info(Market.SH, "600519")
    # info.zong_guben / .liutong_guben / .jing_lirun / .zhuying_shouru / ...

    # 涨跌停价计算
    quotes = c.get_security_quotes([(Market.SH, "600519")])
    limit_up, limit_down = c.get_price_limits(
        Market.SH, "600519", "贵州茅台", quotes[0].pre_close
    )

    # 公司信息目录
    categories = c.get_company_info_category(Market.SH, "600519")
    for cat in categories:
        print(cat.name, cat.filename, cat.start, cat.length)

    # 公司信息内容
    content = c.get_company_info_content(
        Market.SH, "600519", cat.filename, cat.start, cat.length
    )
```

### 板块信息

```python
with TdxClient.from_best_host() as c:
    # 行业/指数板块
    blocks = c.get_block_info("block_zs.dat")
    # 概念板块
    blocks = c.get_block_info("block_gn.dat")
    # 风格板块
    blocks = c.get_block_info("block_fg.dat")
    # blocks[0].name / .category / .count / .codes
```

### 资金流向

```python
with TdxClient.from_best_host() as c:
    # 当日资金流向（超大/大/中/小单）
    flow = c.get_fund_flow(Market.SH, "600519")
    # flow.super_in / .super_out / .large_in / .large_out / .main_net_inflow

    # 历史日线资金流向序列
    flows = c.get_history_fund_flow(Market.SH, "600519", 0, 10)
    # flows[0].date / .super_in / .main_net_inflow
```

### 文件下载

```python
from easy_tdx import CALC_HOSTS

with TdxClient.from_best_host() as c:
    # 行情服务器可用的文件
    data = c.get_report_file("tdxhy.cfg")       # 行业映射配置
    data = c.get_report_file("block_gn.dat")     # 概念板块

    # 计算服务器：专业财务数据
    with TdxClient(CALC_HOSTS[0]) as calc:
        file_list = calc.get_financial_file_list()
        # file_list[0].filename / .filesize / .hash

        zip_data = calc.get_financial_file("tdxfin/gpcw20260331.zip")
        records = calc.get_financial_records("tdxfin/gpcw20260331.zip")
        # records[0].market / .code / .report_date / .fields
```

### 扩展行情（期货、港股、外盘）

```python
from easy_tdx import ExTdxClient

# 扩展行情服务器端口 7727
with ExTdxClient() as c:
    markets = c.get_markets()                    # 可用市场列表
    count = c.get_instrument_count()             # 品种总数
    instruments = c.get_instrument_info(0, 50)   # 品种信息（分页）
    quote = c.get_instrument_quote(market, code) # 单品种行情

    # K 线（支持日期范围查询）
    bars = c.get_instrument_bars(market, code, category, start, count)
    bars = c.get_history_instrument_bars_range(market, code, date_start, date_end)

    # 分时 / 逐笔
    minute = c.get_minute_time_data(market, code)
    trades = c.get_transaction_data(market, code, start, count)
```

`AsyncExTdxClient` 提供与同步版对应的 `async def` 方法。

## 离线数据读取

从本地通达信安装目录直接读取数据文件，无需网络连接。离线模块的路径检测优先级：

1. `TDX_HOME` 环境变量
2. 平台常见路径猜测（Windows: `C:\new_jyplug`、`C:\new_tdx` 等）

```python
# Windows
set TDX_HOME=C:\new_jyplug

# Linux/macOS
export TDX_HOME=/opt/new_tdx
```

### 日线 K 线

```python
from easy_tdx.offline import detect_tdx_home, read_daily_bars, find_daily_bar_file
from easy_tdx import Market

home = detect_tdx_home()

# 通过 市场+代码 自动定位文件
filepath = find_daily_bar_file(Market.SH, "600000")
bars = read_daily_bars(filepath)

for bar in bars[-10:]:
    print(f"{bar.year}-{bar.month:02d}-{bar.day:02d} "
          f"开:{bar.open:.2f} 收:{bar.close:.2f} 量:{bar.vol:.0f}")
```

文件位于 `vipdoc/{sh,sz}/lday/`，如 `sh600000.day`。自动识别证券类型（A 股/B 股/指数/基金/债券）并应用对应的价格和成交量系数。

### 分钟 K 线

```python
from easy_tdx.offline import (
    read_5min_bars, read_lc_min_bars,
    find_5min_bar_file, find_lc1_bar_file, find_lc5_bar_file,
)
from easy_tdx import Market

# .5 文件（OHLC 为整数 / 100）
filepath = find_5min_bar_file(Market.SH, "600000")
bars = read_5min_bars(filepath)

# .lc1 文件（1 分钟线，OHLC 为浮点数）
filepath = find_lc1_bar_file(Market.SH, "600000")
bars = read_lc_min_bars(filepath)

# .lc5 文件（5 分钟线，OHLC 为浮点数）
filepath = find_lc5_bar_file(Market.SZ, "002176")
bars = read_lc_min_bars(filepath)
```

文件位于 `vipdoc/{sh,sz}/fzline/`，如 `sh600000.5`、`sh600000.lc1`、`sh600000.lc5`。

### 扩展市场日线

```python
from easy_tdx.offline import read_ex_daily_bars

# 期货、港股、外盘等扩展市场数据
# 文件位于 vipdoc/ds/lday/，如 29#A1801.day
bars = read_ex_daily_bars(r"C:\new_jyplug\vipdoc\ds\lday\38#2_CPI.day")
# bar.open / .high / .low / .close / .settlement / .vol
```

### 板块数据

```python
from easy_tdx.offline import read_block_dat, read_customer_blocks

# 系统板块（本地 .dat 文件）
blocks = read_block_dat(r"C:\new_jyplug\vipdoc\block_zs.dat")
# blocks[0].name / .category / .count / .codes

# 自定义板块（blocknew 目录）
blocks = read_customer_blocks(r"C:\new_jyplug\T0002\blocknew")
# blocks[0].blockname / .codes
```

支持本地 .dat 文件离线读取，本地不存在时可通过 `TdxClient.get_block_info()` 在线获取。

### 股本变迁

```python
from easy_tdx.offline import read_gbbq

records = read_gbbq(r"C:\new_jyplug\T0002\hq_cache\gbbq")
# records[0].market / .code / .datetime / .category / .hongli_panqianliutong / ...
```

gbbq 文件使用 XOR 加密存储，读取时自动解密。

### 历史财务数据

```python
from easy_tdx.offline import read_history_financial

# 支持 .dat 和 .zip 文件（.zip 自动解压）
records = read_history_financial(r"C:\new_jyplug\vipdoc\fin\gpcw20260331.zip")
# records[0].code / .market / .report_date / .fields
```

文件可通过 `TdxClient.get_financial_file_list()` 查询可用文件，再用 `get_financial_file()` 下载到本地。

### 路径检测

```python
from easy_tdx.offline import detect_tdx_home, resolve_vipdoc

# 自动检测通达信安装目录
home = detect_tdx_home()

# 解析 vipdoc 数据目录
vipdoc = resolve_vipdoc()
```

vipdoc 目录结构：

```
vipdoc/
├── sh/lday/      上海日线      sh600000.day
├── sh/fzline/    上海分钟线    sh600000.5 / .lc1 / .lc5
├── sz/lday/      深圳日线      sz000001.day
├── sz/fzline/    深圳分钟线    sz000001.5 / .lc1 / .lc5
├── ds/lday/      扩展市场      29#A1801.day
└── fin/          历史财务      gpcw*.dat / gpcw*.zip
```

## 完整 API 列表

### TdxClient / AsyncTdxClient

| 方法 | 说明 |
|------|------|
| `get_security_count(market)` | 市场证券总数 |
| `get_security_list(market, start)` | 证券列表（每页约 1000 条） |
| `get_security_list_all()` | 沪深 A 股完整列表（含行业映射，本地缓存 1 天） |
| `get_security_quotes([(market, code), ...])` | 批量实时五档行情（最多 80 只/次） |
| `get_price_limits(market, code, name, pre_close)` | 计算涨跌停价 |
| `get_security_bars(market, code, category, start, count)` | 个股 K 线 |
| `get_index_bars(market, code, category, start, count)` | 指数 K 线 |
| `get_minute_time_data(market, code)` | 今日分时（240 条） |
| `get_history_minute_time_data(market, code, date)` | 历史分时 |
| `get_transaction_data(market, code, start, count)` | 当日逐笔成交 |
| `get_history_transaction_data(market, code, date, start, count)` | 历史逐笔成交 |
| `get_fund_flow(market, code)` | 当日资金流向 |
| `get_history_fund_flow(market, code, start, count)` | 历史日线资金流向 |
| `get_xdxr_info(market, code)` | 除权除息历史 |
| `get_finance_info(market, code)` | 最新财务数据 |
| `get_company_info_category(market, code)` | 公司信息目录 |
| `get_company_info_content(market, code, filename, offset, length)` | 公司信息文本 |
| `get_block_info(filename)` | 板块信息 |
| `get_report_file(filename)` | 下载服务器文件 |
| `get_market_stat()` | 全市场涨跌统计 |
| `get_financial_file_list()` | 计算服务器财务文件列表 |
| `get_financial_file(filename)` | 下载财务文件 |
| `get_financial_records(filename)` | 下载并解析财务记录 |

### ExTdxClient / AsyncExTdxClient

| 方法 | 说明 |
|------|------|
| `get_markets()` | 可用市场列表 |
| `get_instrument_count()` | 品种总数 |
| `get_instrument_info(start, count)` | 品种信息（分页） |
| `get_instrument_quote(market, code)` | 单品种行情 |
| `get_instrument_quote_list(market, start, count)` | 批量行情 |
| `get_instrument_bars(market, code, category, start, count)` | 品种 K 线 |
| `get_history_instrument_bars_range(market, code, start, end)` | 日期范围 K 线 |
| `get_minute_time_data(market, code)` | 分时数据 |
| `get_history_minute_time_data(market, code, date)` | 历史分时 |
| `get_transaction_data(market, code, start, count)` | 逐笔成交 |
| `get_history_transaction_data(market, code, date, start, count)` | 历史逐笔 |

### easy_tdx.offline

| 函数 | 说明 |
|------|------|
| `detect_tdx_home()` | 检测通达信安装目录 |
| `resolve_vipdoc(path)` | 解析 vipdoc 数据目录 |
| `read_daily_bars(filepath)` | 读取日线 .day 文件 |
| `find_daily_bar_file(market, code)` | 定位日线文件路径 |
| `read_5min_bars(filepath)` | 读取 .5 分钟线文件 |
| `read_lc_min_bars(filepath)` | 读取 .lc1/.lc5 分钟线文件 |
| `find_5min_bar_file(market, code)` | 定位 .5 文件路径 |
| `find_lc1_bar_file(market, code)` | 定位 .lc1 文件路径 |
| `find_lc5_bar_file(market, code)` | 定位 .lc5 文件路径 |
| `read_ex_daily_bars(filepath)` | 读取扩展市场日线 |
| `read_block_dat(filepath)` | 读取系统板块 .dat 文件 |
| `read_customer_blocks(block_dir)` | 读取自定义板块目录 |
| `read_gbbq(filepath)` | 读取股本变迁文件 |
| `read_history_financial(filepath)` | 读取历史财务数据 |

## 数据模型

所有 dataclass 字段均有类型注解。每条记录附带 `_raw: bytes`（原始协议字节）。

### SecurityBar（K 线）

```
date（日线及以上）或 datetime（分钟线）
open  close  high  low  vol  amount
```

### SecurityQuote（实时行情）

```
market  code  price  pre_close  open  high  low
vol  cur_vol  amount  s_vol  b_vol
bid1..bid5  bid_vol1..bid_vol5
ask1..ask5  ask_vol1..ask_vol5
server_time
_raw
```

`limit_up` / `limit_down` 默认为 `None`，涨跌停价应通过 `get_price_limits()` 计算。

### SecurityInfo（证券列表）

```
market  code  name  volunit  decimal_point  pre_close
industry_tdx  industry_sw
```

### MinuteBar（分时）

```
datetime  price  vol
```

### TransactionRecord（逐笔成交）

```
datetime  price  vol  buyorsell
```

### XdxrRecord（除权除息）

```
date  market  code  category  name
fenhong  peigujia  songzhuangu  peigu  suogu
xingquanjia  fenshu
panqian_liutong  panhou_liutong      # 万股
qian_zongguben  hou_zongguben        # 万股
_raw
```

`category == 1` 时为现金分红/送转/配股，`fenhong / songzhuangu / peigu` 已归一化为每股口径。

### 复权公式

仅使用 `category == 1` 的 xdxr 记录：

```text
factor = (pre_close - cash + rights * rights_price) / (1 + bonus + rights)
```

其中 `cash = fenhong`，`bonus = songzhuangu`，`rights = peigu`，`rights_price = peigujia`，`pre_close` 为事件前一日未复权收盘价。

- 前复权：事件日前的历史价格连续乘以各次 `factor`
- 后复权：事件日后的价格连续除以各次 `factor`

### FundFlow（资金流向）

```
super_in/out  large_in/out  medium_in/out  small_in/out
main_net_inflow  total_net_inflow
```

### FinanceInfo（财务）

流通股本、总股本、各省份/行业代码、资产负债表及利润表主要科目（30 个 float 字段）。

### CompanyInfoCategory（公司信息目录）

```
name  filename  start  length
```

### TdxBlock（板块信息）

```
name  category  count  codes
```

## 已知限制

- `get_security_list(Market.BJ, start)` 当前不能稳定获取（服务器端问题），`get_security_list_all()` 暂不纳入 BJ
- `limit_up` / `limit_down` 在 `SecurityQuote` 中默认为 `None`，涨跌停价应通过 `get_price_limits()` 计算

## 修复的 pytdx Bug

| # | 位置 | 问题 | 修复 |
|---|------|------|------|
| 1 | `xdxr_info` | 循环内始终读 `body[:7]`，所有记录字段相同 | 改为从当前 `pos` 读取，pos 正确推进 |
| 2 | `security_list` | GBK 解码截断时 crash | `decode('gbk', errors='replace')` |
| 3 | `security_list` | `pre_close` 误当作整数价格 `/100` | 恢复为通达信自定义浮点解码 |
| 4 | `transaction` | 最后一个字段被 `_` 丢弃 | 保留为 `unknown_last` |
| 5 | `minute_time` | `reversed1` 字段被丢弃 | 保留为 `unknown_1` |
| 6 | `xdxr_info` | 股本字段用 `float(uint32)` 直解，差约 374 倍 | 改用 `_decode_volume`，单位万股，与 `FinanceInfo` 完全吻合 |
| 7 | `security_quotes` | 涨停/跌停价映射错误或缺失 | 停止使用不可信协议位，改由业务规则计算 |

## 架构

```
src/easy_tdx/
├── client.py          # TdxClient / AsyncTdxClient（高层 API）
├── ex/
│   ├── client.py      # ExTdxClient / AsyncExTdxClient（扩展行情）
│   └── models.py      # 扩展行情数据模型
├── offline/           # 离线数据读取模块
│   ├── paths.py       # 路径检测与解析
│   ├── daily_bar.py   # 日线读取
│   ├── min_bar.py     # 分钟线读取
│   ├── ex_daily_bar.py # 扩展市场日线
│   ├── block.py       # 板块数据读取
│   ├── gbbq.py        # 股本变迁（XOR 解密）
│   ├── history_financial.py # 历史财务数据
│   └── finders.py     # 文件路径定位
├── transport/
│   ├── sync.py        # TdxConnection（socket）+ ping_host / ping_all
│   └── async_.py      # AsyncTdxConnection（asyncio）
├── commands/          # 每条命令：build_request() + parse_response()，无 IO
├── codec/             # price / volume / datetime / frame 编解码
└── models/            # 纯 dataclass，无业务逻辑
```

commands 层不依赖 transport，可独立单测。transport 层负责 TCP、握手、帧解压、分发。offline 层直接读取本地二进制文件，不依赖 transport。

## 协议说明

通达信使用私有二进制 TCP 协议：

- **帧格式**：16 字节响应头（含 zipsize / unzipsize），body 按需 zlib 解压
- **价格编码**：变长有符号整数（类 LEB128，bit8=继续，bit7=符号，首字节低 6 位 + 后续低 7 位）
- **成交量编码**：4 字节自定义浮点（字节 3 = 指数，字节 0-2 = 精度），不可用于价格字段
- **握手**：连接后必须顺序发送 3 条 setup 命令，响应丢弃
- **价格存储**：整数 x 100，差分编码（相邻 tick 存 delta）

## 开发

```bash
# 单元测试（无需网络）
python -m pytest tests/unit/

# 集成测试（需要网络，默认跳过）
XMTDX_LIVE=1 python -m pytest tests/integration/

# 类型检查
mypy src/

# lint + format
ruff check src/ tests/
ruff format --check src/ tests/
```

## 致谢

- [pytdx](https://github.com/rainx/pytdx) — 离线数据读取模块（日线、分钟线、板块、股本变迁、历史财务的文件格式解析方法）借鉴自 pytdx 项目，感谢 rainx 及所有贡献者
- [xmtdx](https://github.com/minionszyw/xmtdx) — 本项目的初始原型，感谢 minionszyw 的工作
- 通达信协议分析离不开开源社区的逆向工程成果
