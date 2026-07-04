# easy-tdx

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/easy-tdx.svg)](https://pypi.org/project/easy-tdx/)
[![GitHub Repo stars](https://img.shields.io/github/stars/handsomejustin/easy-tdx?style=social)](https://github.com/handsomejustin/easy-tdx)
[![GitHub last commit](https://img.shields.io/github/last-commit/handsomejustin/easy-tdx)](https://github.com/handsomejustin/easy-tdx)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://www.mypy-lang.org/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/handsomejustin/easy_tdx)

<img src="./docs/top_img.png" alt="头部宣传图" />
量化基金花百万买的毫秒级行情通道，散户连一根日线都要手动截图——这不是技术差距，这是数据霸凌。

easy-tdx 要做的事很简单：**把机构的数据锁砸开，扔到每个普通人桌面。**

它是一个完全免费、无需注册、无需 API Key、纯开源的行**情核武器**。  
一行命令，A股、港股、美股、期货——K线、报价、资金流向、板块轮动、分时明细、逐笔成交，**毫秒级拉满**。

**34个技术指标**（MACD、KDJ、RSI、BOLL……连”捉妖大师”和”30日乖离率信号”都给你算好）开箱即用。
**缠论分析**（笔、中枢、买卖点、背驰）一键出结果——你不再需要手画分型、猜线段。
**内置回测引擎**——写个策略文件，一行命令跑回测，18 个经典策略自带，多因子组合、策略选股扫描，批量对比哪个最赚钱一目了然。

**回测可视化 Web UI**（v1.17 新增）——Vue3 + ECharts 单页应用，浏览器里选标的、挑策略、调参数，K 线买卖点、净值回撤、19 项绩效指标一目了然。支持组合回测、参数网格寻优、多策略结果对比，**还能把好策略存进策略库（SQLite 持久化），勾选多个策略做资金分仓组合回测看综合表现**，全程零代码。

**数据评级系统**（v1.17.14 新增）——回测结果顶部直接显示 **S/A/B/C/D 五档评级徽章**，1 秒判断「这个品种适不适合经常参与」。评级**不看收益率**（避免被近期大涨误导），只看风险调整后的持有体验：卡玛比率、最大回撤、胜率、利润因子、夏普、波动率六维加权 + 一票否决（系统亏损/深回撤/低胜率直接低评）。京东方那种「收益 126% 但胜率 35%、回撤 41%」的案例会评 **D 档**——明确告诉普通人「别碰，套牢后回本极难」。三个入口（单标的/组合/寻优）都有评级，长线低频策略不会被冤枉（交易少时只降权胜率维度，不否决整个评级）。

装上就能跑。**Python API + CLI + Web API 三通道**，输出 JSON 天然喂给 AI Agent：Claude Code、OpenClaw、Hermes 直接吃。`easy-tdx serve` 一键起 REST 服务，浏览器打开就是交互式 API 文档。

**你不懂 TCP 协议？不用。**
**你不会写量化框架？不用。**
**你想回测验证策略？自带引擎，不用。**
**你不想给任何平台付一分钱？完全不用。**

`pip install easy-tdx`，30秒后——你屏幕上的数据，和机构看到的**是同一份**。

---

**为什么做这个？**

金融数据的获取门槛，从来不该是散户亏钱的理由。  
当量化基金用程序化交易像割草一样收割市场时，普通人至少应该**有权利拿一样的武器**。

这不是一个帮你“赚钱”的工具。  
这是让你**不再裸奔**的工具。

**MIT 协议，代码全开源。**  
随便用，随便改，随便分发。  
**数据面前，人人平等。**

📖 **详细用法请查看 [GitHub Wiki](https://github.com/handsomejustin/easy_tdx/wiki)**

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

# 开发 Web API 模式（含 FastAPI + Uvicorn）
pip install -e ".[web]"
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

# 板块 N 日涨跌幅排行（默认全部，支持指定日期）
easy-tdx board-change-ranking --table                      # 行业 20 日涨跌幅排行
easy-tdx board-change-ranking --type GN --days 10 --table  # 概念 10 日涨跌幅排行
easy-tdx board-change-ranking --type HY --date 20250530 --days 20 --table
easy-tdx board-change-ranking --type HY --top 10 --asc     # 行业跌幅前10
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

### 公告检索（巨潮资讯网）

```bash
easy-tdx announcement 688017                          # 默认 30 条，JSON 输出
easy-tdx announcement 601088 --count 10 --page 2      # 翻页
easy-tdx announcement 000001 --table                  # 表格输出（不截断 url）

# 下载最新 5 条公告的 PDF 到 ./pdfs 目录
easy-tdx announcement 601088 --count 5 --download 5 --download-dir ./pdfs
```

> 独立数据源（巨潮资讯网），无需连接 TDX 行情服务器即可使用。
> 返回的 ``url`` 含 4 参数可直接打开，``pdf_url`` 为 PDF 直链。

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
easy-tdx indicator BIAS_SIGNAL -m SH -c 600519 --table # 30日乖离率信号
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

### 缠论分析

基于缠论理论的技术分析，计算管道：`K 线合并 → 分型识别 → 笔 → 中枢 → 线段 → 买卖点 → 背驰`。默认输出 JSON，加 `--table` 输出可读表格。

```bash
easy-tdx chanlun SZ 000001 --table
easy-tdx chanlun SH 600519 --adjust QFQ --table
easy-tdx chanlun SZ 000001 --period 30MIN

# 多级别联立：分析日线最后一笔在 30 分钟级别中的走势结构
easy-tdx chanlun SZ 000001 --multi-level 30MIN --table
easy-tdx chanlun SH 600519 --multi-level 5MIN
```

#### 输出示例

以 `easy-tdx chanlun SH 601088 --table` 为例，输出分五个部分：

**概要统计**

```
标的: 601088  周期: DAILY
原始K线: 800  缠论K线: 589
分型: 275  笔: 131  中枢: 21  线段: 40
买卖点: 125  背驰: 73
```

| 字段 | 含义 |
|------|------|
| 原始 K 线 | 从服务端获取的原始 K 线条数 |
| 缠论 K 线 | 经过包含处理（合并）后的 K 线条数，数量一定 ≤ 原始 K 线 |
| 分型 | 识别出的顶分型 + 底分型总数 |
| 笔 | 相邻两个异向分型之间的连线（涨跌方向交替） |
| 中枢 | 至少 3 笔重叠区域形成的密集成交区间 |
| 线段 | 由笔构成的更大级别走势单位 |
| 买卖点 | 一二三类买卖点信号总数 |
| 背驰 | 力度衰减信号总数（笔背驰 / 盘整背驰 / 趋势背驰） |

**笔**

```
[0] ↑ 2023-02-17 → 2023-02-23 h=28.46 l=26.76 ✓
[1] ↓ 2023-02-23 → 2023-02-28 h=28.46 l=27.8 ✓
[2] ↑ 2023-02-28 → 2023-03-09 h=29.77 l=27.8 ✓
```

笔是缠论的基本走势单位。每条笔连接一个顶分型和一个底分型，方向严格交替（↑↓↑↓…）。`✓` 表示已确认（后续出现了反向笔），`…` 表示仍在进行中。

- `↑`：向上笔，起点是底分型（低点），终点是顶分型（高点）
- `↓`：向下笔，起点是顶分型（高点），终点是底分型（低点）
- `h`/`l`：该笔范围内的最高价 / 最低价

**中枢**

```
[0] zg=28.46 zd=28.11 gg=32.56 dd=26.76 lines=11 ✓
[1] zg=31.2  zd=30.45 gg=32.56 dd=27.9  lines=3  ✓
```

中枢是至少 3 笔重叠形成的密集成交区间，代表多空博弈的平衡区域。`✓` 表示已脱离，`…` 表示价格仍在中枢区间内震荡。

| 字段 | 含义 |
|------|------|
| `zg` | 中枢上沿（区间内最高的低点）— 支撑/压力的关键分界 |
| `zd` | 中枢下沿（区间内最低的高点） |
| `gg` | 中枢区间内的最高价 |
| `dd` | 中枢区间内的最低价 |
| `lines` | 构成该中枢的笔数，笔数越多代表震荡越充分 |

中枢的意义：价格在中枢内震荡 → 突破中枢上沿看涨，跌破下沿看跌。`zg`/`zd` 是实战中最常用的参考价位。

**线段**

```
[0] ↑ 2023-02-17 → 2023-03-09 h=29.77 l=26.76
[1] ↓ 2023-02-28 → 2023-03-29 h=29.77 l=27.18
```

线段是比笔更大的走势单位，由多笔重叠组合而成。线段的方向不严格交替，可能出现连续同向（如连续多段向上），代表更高一级的趋势方向。实战中通常在线段级别判断大方向，在笔级别找买卖点。

**买卖点**

```
1buy:  中枢下方力度衰减，一类买点 (l=27.30 < zd=46.72)
2buy:  回调不创新低，二类买点 (l=27.33)
3buy:  回调不破中枢上沿，三类买点 (l=27.80 > zg=27.58)
1sell: 中枢上方力度衰减，一类卖点 (h=50.38 > zg=46.97)
2sell: 反弹不创新高，二类卖点 (h=29.32)
3sell: 反弹不破中枢下沿，三类卖点 (h=28.46 < zd=46.72)
```

缠论定义三类买点和三类卖点：

| 类型 | 买点含义 | 卖点含义 |
|------|----------|----------|
| 一类 | 下跌趋势末端，力度衰减后的第一个低点（抄底） | 上涨趋势末端，力度衰减后的第一个高点（逃顶） |
| 二类 | 一类买点后的回调不创新低（确认反转） | 一类卖点后的反弹不创新高（确认反转） |
| 三类 | 回调不进入中枢上沿（趋势确认，中枢上方买） | 反弹不进入中枢下沿（趋势确认，中枢下方卖） |

括号内的条件是该信号的触发依据，如 `l=27.80 > zg=27.58` 表示回调低点 27.80 高于中枢上沿 27.58，所以是三类买点。

**背驰**

```
[✓] bi: 笔背驰: 笔[4] 力度=1.32 < 笔[2] 力度=1.97
[✓] pz: 盘整背驰: 中枢[11] 内末笔力度=2.49 < 首笔力度=6.64
[✓] qs: 趋势背驰(上): 中枢[1] 离开力度=3.32 < 中枢[0] 离开力度=4.45
```

背驰是力度衰减信号，表明当前走势动力正在减弱，可能即将反转。力度通过 MACD 面积计算，数值越小力度越弱。

| 类型 | 含义 |
|------|------|
| `bi`（笔背驰） | 同向相邻两笔比较，后一笔力度 < 前一笔 → 该方向动力减弱 |
| `pz`（盘整背驰） | 同一中枢内，末笔力度 < 首笔 → 中枢内动力衰减，即将突破 |
| `qs`（趋势背驰） | 两个同向中枢之间比较，后一中枢离开力度 < 前一中枢 → 趋势可能终结 |

`[✓]` 表示确认背驰。趋势背驰(上)代表上涨趋势可能结束，趋势背驰(下)代表下跌趋势可能结束。

### 回测引擎

内置向量回测引擎，加载 Python 策略文件即可跑回测。策略继承 `Strategy` 基类，在 `init()` 注册指标，在 `next()` 逐 bar 生成买卖信号，引擎完成订单模拟、持仓跟踪和绩效分析。

**单策略回测：**

```bash
easy-tdx backtest SZ 300308 --strategy-file strategies/expma_cross.py --count 2000 --cash 1000000 --adjust QFQ --table
# 推荐加上 --slippage 0.01 模拟真实滑点（元/股），使回测更贴近实盘

# 缠论自动桥接：引擎自动计算缠论分析并注入策略 self.chanlun
easy-tdx backtest SZ 000001 --strategy-file strategies/chanlun_strategy.py --chanlun-level DAILY --table
```

输出示例：

```
=== 回测绩效概要 ===
总收益率: 1413.51%
年化收益: 40.85%
最大回撤: 76.75%
夏普比率: 0.88
胜率: 20.8%
交易次数: 24
```

> ⚠️ **回测 ≠ 实盘**。以上收益率为历史数据回测结果，包含幸存者偏差和过拟合风险，
> 不构成投资建议。实际交易需考虑滑点、流动性、涨跌停无法成交等因素。
> 请在充分理解策略逻辑后谨慎使用。

**全策略批量对比（CLI）：**

`easy-tdx run-all` 一行命令跑完 `strategies/` 下所有策略并排名：

```bash
easy-tdx run-all SZ 300308 --count 2000 --cash 1000000 --adjust QFQ

# 多因子组合回测
easy-tdx run-all SZ 300308 --combo 2 --combo-mode MAJORITY

# 加 --show 自动弹出最佳策略的资金曲线 vs 股价对比图
easy-tdx run-all SZ 300308 --count 2000 --cash 1000000 --adjust QFQ --show

# 自定义策略目录
easy-tdx run-all SZ 300308 --strategies-dir my_strategies/
```

也可使用项目自带的 `run_all_strategies.py` 脚本（功能相同）：

```bash
python -X utf8 run_all_strategies.py SZ 300308 --count 2000 --cash 1000000 --adjust QFQ

# 加 --show 自动弹出最佳策略的资金曲线 vs 股价对比图
python -X utf8 run_all_strategies.py SZ 300308 --count 2000 --cash 1000000 --adjust QFQ --show
```

**多因子组合回测：**

自动遍历所有 2 因子 / 3 因子组合，找到最优搭配：

```bash
# 自动寻找最佳 2 因子和 3 因子组合（MAJORITY 模式）
python -X utf8 run_all_strategies.py SZ 300308 --combo 2 --combo 3 --combo-mode majority

# CLI 方式
easy-tdx run-all SZ 300308 --combo 2 --combo 3 --combo-mode majority
```

CLI 指定策略文件组合：

```bash
easy-tdx backtest SZ 000001 \
  --combo-strategies strategies/macd_cross.py,strategies/rsi_reversal.py,strategies/bollinger_breakout.py \
  --combo-mode majority --table
```

Python API：

```python
from easy_tdx.backtest import CombinationRunner

runner = CombinationRunner(
    strategy_classes=[MACDStrategy, RSIStrategy, BollingerStrategy],
    df=df, cash=100000,
)
results = runner.screen(combo_sizes=(2, 3), mode="MAJORITY")
for r in results[:5]:
    print(f"{r.name}: 收益={r.result.performance['total_return']:.2%}")
```

信号合并模式：

| 模式 | 买入条件 | 卖出条件 | 特点 |
|------|---------|---------|------|
| `AND` | 所有因子都看多 | 所有因子都看空 | 极保守，交易少但精确 |
| `MAJORITY` | 过半因子看多 | 过半因子看空 | 平衡，推荐默认 |
| `OR` | 任一因子看多 | 任一因子看空 | 激进，信号多噪声大 |

`--show` 会用 matplotlib 弹出一个双轴对比窗口：左轴蓝色线是归一化股价，右轴红色线是最佳策略的资金曲线，绿三角=买入、黄三角=卖出，标题显示股票名称和关键绩效指标。需要 `pip install matplotlib`。

**多标的组合回测（portfolio）：**

`easy-tdx portfolio` 对多只股票同时回测，共享资金池，按均等比例分配，汇总组合整体绩效：

```bash
# 两只股票组合回测
easy-tdx portfolio --stocks SZ:000001,SH:600519 --strategy-file strategies/ma_cross.py --table

# 自定义资金和周期
easy-tdx portfolio --stocks SZ:000001,SH:600519,SH:600036 \
  --strategy-file strategies/expma_cross.py --cash 500000 --period DAILY --count 1000 --table

# 搭配缠论桥接
easy-tdx portfolio --stocks SZ:000001,SH:600519 \
  --strategy-file strategies/chanlun_strategy.py --chanlun-level DAILY --table
```

输出示例：

```
=== 组合回测绩效概要 ===
标的数量: 3
总资金: 200,000
组合收益率: 28.50%
组合年化: 28.50%

── 各标的详情 ──
  SZ000001: 收益=35.20% 夏普=0.92 回撤=15.30% 分配=33% 交易=12
  SH600519: 收益=18.40% 夏普=0.68 回撤=8.50%  分配=33% 交易=8
  SH600036: 收益=31.90% 夏普=0.85 回撤=12.10% 分配=33% 交易=15
```

| 参数 | 说明 |
|------|------|
| `--stocks` | 股票列表：逗号分隔的 `市场:代码`（如 `SZ:000001,SH:600519`） |
| `--cash` | 总资金（默认 20 万） |
| `--allocation` | 资金分配方式（目前支持 `equal` 均等分配） |
| `--chanlun-level` | 自动计算缠论分析并注入策略（如 DAILY/30MIN） |

**回测可视化 Web UI（v1.17 新增）：**

<img src="./docs/web-ui-page-1.png" alt="Web UI 截图 1" />

<img src="./docs/web-ui-page-2.png" alt="Web UI 截图 2" />

<img src="./docs/web-ui-page-3.png" alt="Web UI 截图 3" />

不想写命令行？用浏览器。`easy-tdx serve` 启动后端，`web-ui/` 目录跑前端，浏览器打开就是完整的回测可视化界面。

**前置条件：**

```bash
# 后端需安装 web 可选依赖（FastAPI + Uvicorn）
pip install -e ".[web]"

# 前端需 Node.js 18+（首次运行需装依赖）
cd web-ui && npm install
```

**启动（两个终端）：**

```bash
# 终端 1：启动后端 API 服务（提供行情数据 + 回测计算）
easy-tdx serve --port 8000

# 终端 2：启动前端开发服务器（web-ui/ 目录）
cd web-ui && npm run dev
# 浏览器打开 http://localhost:5173
```

> 前端开发服务器通过 Vite proxy 把 `/api` 请求转发到后端 `127.0.0.1:8000`，无需处理跨域。后端行情连接失败时回测路由仍可用（用内联数据），但取行情功能需要后端连通通达信服务器。

打开浏览器后，顶部导航栏有五个页面：

**1. 单标的回测**（首页 `/`）

左侧配置面板从上到下填写，右侧自动出图：

- **取行情**：选市场（深/沪/北），填 6 位代码，选周期（日线/周线/分钟线），设日期范围（默认最近 3 年），点「取行情」。超过 800 根会自动翻页拼接
- **选策略**：下拉选 18 个内置策略之一（双均线交叉、MACD、布林带、RSI、KDJ、唐安奇通道、CCI 等），选中后参数表单自动出现，按推荐范围调参
- **资金与成本**：初始资金、佣金率、滑点、成交模式（默认 next_open 下一根开盘成交）
- 点「开始回测」，右侧依次出：K 线主图（红三角=买入、绿钉=卖出）、净值曲线与回撤双轴图、19 项绩效指标表（总收益/夏普/最大回撤/胜率/盈亏比等）、成交记录明细
- 结果区右上角有「💾 保存策略」按钮，把当前策略 + 标的 + 成绩快照存进策略库，下次直接载入或参与组合回测

**2. 组合回测**（`/portfolio`）

- 添加多只标的（如 SZ:000001、SH:600519），选策略和日期范围
- 点「开始组合回测」，右侧出：组合整体绩效（加权收益率）、组合净值曲线（各标的按日期对齐求和）、各标的净值归一化叠加对比图、各标的绩效横向对比表
- 同样有「保存策略」按钮，可把整个组合配置存进策略库

**3. 参数寻优**（`/optimize`）

- 先取行情（同单标的），选策略
- 勾选 1-2 个想寻优的参数，填入取值列表（逗号分隔，如 fast 填 `5,10,20,30`），页面实时显示网格点数（上限 200）
- 点「开始寻优」，右侧出：最优结果摘要、参数热力图（2 参数时，颜色映射收益率）、所有网格点排名表
- 排名表每行有「查看」按钮，点击跳转单标的回测页，自动填充该参数组合跑完整回测

**4. 结果对比**（`/compare`）

- 左侧列出最近 20 个已完成的回测任务（含单标的和组合）
- 勾选 2-4 个，右侧出：归一化净值叠加图（初始=1，看相对走势）、8 项核心指标横向对比表（总收益/夏普/最大回撤/胜率/盈亏比/交易数/年化/波动率）

**5. 策略库**（`/strategies`，v1.17.11 新增）

- 保存你觉得不错的策略，下次直接载入或重跑。数据存在本地 SQLite 单文件（`~/.easy_tdx/strategies.db`，重启不丢）
- 每张卡片展示策略名、标的、保存时的成绩快照（总收益/夏普/回撤）、标签、备注、创建时间
- **载入**：点「载入」跳转对应回测页（单标的/组合），自动回填标的、日期、策略参数，可直接重跑
- **多策略组合回测**：勾选多个单标的策略（卡片左上角复选框），点顶部「组合回测(N)」——每个策略各拿 1/N 资金、各跑在它保存时的原标的上（取最新行情），净值曲线按日期对齐求和，看综合表现。结果区展示：组合净值曲线、19 项完整绩效指标（与单标的同口径）、各策略绩效对比表、净值叠加图、各策略当前持仓表（回测结束时谁还套着票）

> ⚠️ **任务不持久化**：回测结果存在后端进程内存，重启 `easy-tdx serve` 后清空。对比页只能选当前运行期间产生的任务。**策略库除外**——保存到策略库的策略持久存在 SQLite，重启不丢。

技术栈：Vue 3 + Vite + TypeScript + Pinia + ECharts（按需引入，构建产物约 800KB）。前端代码在 `web-ui/` 目录，独立 `package.json`，不依赖 Python 环境。



```
发现 9 个策略文件
标的: SZ 300308 | K线: 2000 | 资金: 1,000,000 | 复权: QFQ
================================================================================

>> 运行策略: bias_reversal ... 完成 (2.4s)
>> 运行策略: bollinger_breakout ... 完成 (0.6s)
>> 运行策略: expma_cross ... 完成 (0.6s)
>> 运行策略: kdj_golden ... 完成 (0.1s)
>> 运行策略: ma_cross ... 完成 (1.4s)
>> 运行策略: macd_cross ... 完成 (2.1s)
>> 运行策略: rsi_reversal ... 完成 (0.2s)
>> 运行策略: turtle_breakout ... 完成 (0.1s)
>> 运行策略: volume_price ... 完成 (6.3s)

================================================================================
[*] 策略绩效排名 (按总收益率降序)
================================================================================
  排名  策略                           总收益率       年化收益       最大回撤       夏普       胜率     交易次数      盈亏比
----------------------------------------------------------------------------------------------------
 *1* 1  expma_cross             1413.51%    40.85%    76.75%     0.88   20.8%       24     6.45
 *2* 2  ma_cross                1258.07%    38.94%    58.01%     0.87   38.2%       55     2.21
 *3* 3  turtle_breakout          905.07%    33.76%    48.30%     0.83   75.0%        4    10.14
     4  bias_reversal            504.94%    25.47%    42.25%     0.70   66.3%       95     2.08
     5  macd_cross               387.67%    22.11%    61.08%     0.60   40.0%       85     2.20
     6  volume_price             247.72%    17.01%    65.73%     0.50   43.3%      254     1.40
     7  bollinger_breakout       169.65%    13.32%    49.71%     0.44   66.7%       24     1.93
     8  rsi_reversal              95.89%     8.85%    56.51%     0.33   57.1%        7     2.48
     9  kdj_golden                89.10%     8.36%    61.86%     0.32   66.7%        3    10.49
```

综合评分（夏普 × 0.4 + 收益/回撤 × 0.3 + 胜率 × 0.3）：

```
 *1* 1  turtle_breakout             23.04     0.83       0.70   75.0%
 *2* 2  bias_reversal               20.35     0.70       0.60   66.3%
 *3* 3  bollinger_breakout          20.26     0.44       0.27   66.7%
```

换一个标的再跑：

```bash
# 贵州茅台
python -X utf8 run_all_strategies.py SH 600519 --count 2000 --cash 1000000 --adjust QFQ
```

#### `--show` 可视化效果

<p align="center">
  <img src="strategies/demo/1.png" width="700"><br>
  <sub>SH601088 中国神华 — bollinger_breakout 策略 | 收益 1281.8%</sub>
</p>

<p align="center">
  <img src="strategies/demo/2.png" width="700"><br>
  <sub>SH600522 中天科技 — kdj_golden 策略 | 收益 568.6%</sub>
</p>

<p align="center">
  <img src="strategies/demo/3.png" width="700"><br>
  <sub>SH601179 中国西电 — expma_cross 策略 | 收益 168.0%</sub>
</p>

<p align="center">
  <img src="strategies/demo/4.png" width="700"><br>
  <sub>SH600519 贵州茅台 — bollinger_breakout 策略 | 收益 187.0%</sub>
</p>

> **⚠️ Demo 展示，不作为操作依据。** 历史回测收益不代表未来表现，策略参数未经过样本外验证。

#### 自带策略示例

`strategies/` 目录下有 16 个开箱即用的策略文件，可直接用于 `--strategy-file`：

| 文件 | 策略 | 类型 | 适合行情 |
|------|------|------|----------|
| `ma_cross.py` | 双均线交叉（MA5/MA20） | 趋势跟踪 | 单边趋势 |
| `expma_cross.py` | EMA12/EMA50 交叉 | 趋势跟踪 | 单边趋势（比 MA 更灵敏） |
| `macd_cross.py` | MACD 金叉死叉 | 趋势跟踪 | 中长线趋势 |
| `bollinger_breakout.py` | 布林带突破 | 震荡反转 | 横盘震荡 |
| `rsi_reversal.py` | RSI 超买超卖 | 反转 | 震荡市 |
| `kdj_golden.py` | KDJ 低位金叉/高位死叉 | 反转 | 短线震荡 |
| `turtle_breakout.py` | 海龟交易法（唐安奇通道） | 趋势突破 | 牛市启动 |
| `bias_reversal.py` | 乖离率反转 | 反转 | 震荡回归 |
| `volume_price.py` | 量价配合 | 综合判断 | 放量突破 |
| `zhuoyao_momentum.py` | 捉妖大师多周期共振 | 趋势跟踪 | 多周期共振强势股 |
| `dmi_trend.py` | DMI/ADX 趋势强度跟踪 | 趋势跟踪 | 单边趋势（过滤震荡） |
| `cci_breakout.py` | CCI ±100 区间突破 | 区间突破 | 震荡转趋势 |
| `mfi_volume.py` | MFI 量价反转 | 量价反转 | 震荡市（带量能确认） |
| `trix_cross.py` | TRIX 三重平滑趋势交叉 | 趋势跟踪 | 中长线（抗噪音） |
| `mtm_momentum.py` | MTM 动量零线穿越 | 动量 | 趋势拐点 |
| `obv_trend.py` | OBV 能量潮趋势 | 量价趋势 | 资金持续流入的上升趋势 |

编写自定义策略只需继承 `Strategy` 基类：

```python
from easy_tdx.backtest import Strategy
from easy_tdx import MyTT


class MyStrategy(Strategy):
    def init(self):
        self.ma = self.I(MyTT.MA, self.data.close, 10)

    def next(self):
        if self.data.close[0] > self.ma[self._bar_index]:
            self.buy(size=0)     # size=0 表示全仓
        elif self.position["size"] > 0:
            self.sell(size=0)    # size=0 表示清仓
```

完整 API 参考：[docs/backtest_usage.md](docs/backtest_usage.md)

### 量化因子与组合管理

新增三大模块：**因子引擎**（19 个内置因子 + 自定义扩展）、**因子分析**（IC/分层/衰减）、**组合管理**（4 种优化器 + 再平衡引擎）。加上**高级回测增强**：可插拔滑点模型（方根冲击/成交量比例）、执行仿真（TWAP/VWAP/限价单）、归因分析（Brinson + 因子归因）。

```python
from easy_tdx.factor import FactorEngine, FactorAnalyzer, preprocess
from easy_tdx.portfolio import RebalanceEngine, FactorWeightedOptimizer
from easy_tdx.backtest import BacktestEngine
from easy_tdx.backtest.slippage import SquareRootSlippage
from easy_tdx.backtest.execution import TWAPExecution

# 因子研究
engine = FactorEngine()
factor_data = engine.compute_cross_section(data, ["momentum_20d", "rsi_14"])
clean = preprocess(factor_data, ["momentum_20d", "rsi_14"])
forward_returns = engine.compute_forward_returns(data, period=5)
report = FactorAnalyzer(clean, forward_returns).full_report("momentum_20d")
print(f"IC均值={report.mean_ic:.4f} ICIR={report.icir:.4f}")

# 组合回测
result = RebalanceEngine(
    FactorWeightedOptimizer(), factor_name="momentum_20d", n_stocks=50, cash=1_000_000,
).run(data, start_date=20230101, end_date=20240101)
print(f"年化={result.performance['annual_return']:.2%}")

# 高级回测（滑点 + 执行仿真）
engine = BacktestEngine(
    MyStrategy, cash=1_000_000,
    slippage_model=SquareRootSlippage(impact_coeff=0.1),
    execution_model=TWAPExecution(n_bars=3),
)
```

详细用法和完整工作流示例：**[docs/quantitative-guide.md](docs/quantitative-guide.md)**

### 策略选股扫描（screen）

把策略翻转成选股器：给定一个策略，扫描全市场找出今天触发买入信号的股票，再对这些信号做历史回测排名。**纯离线数据**，读取本地通达信 `.day` 文件，全市场约 30-60 秒。

两步走工作流：

**第一步：信号扫描（scan）**

```bash
# 扫描沪深全 A，找出 RSI 超卖触发的股票
easy-tdx screen scan --strategy strategies/rsi_reversal.py --output signals.json

# 缩小范围
easy-tdx screen scan --strategy strategies/macd_cross.py --universe sz --output signals.json

# 从自定义股票列表扫描
easy-tdx screen scan --strategy strategies/bollinger_breakout.py --universe my_stocks.txt --output signals.json

# 并发扫描（推荐 4-8 进程，速度提升 4-8 倍）
easy-tdx screen scan --strategy strategies/rsi_reversal.py --workers 4 --output signals.json

# 增量扫描（缓存未修改的 .day 文件，跳过重复计算）
easy-tdx screen scan --strategy strategies/rsi_reversal.py --cache scan_cache.json --output signals.json
```

输出示例（JSON）：

```json
{
  "scan_time": "2026-06-10T18:30:00",
  "strategy": "RSIStrategy",
  "total_scanned": 4832,
  "total_signals": 37,
  "signals": [
    {"code": "000001", "market": "SZ", "signal_date": 20260610, "last_close": 12.35},
    {"code": "600519", "market": "SH", "signal_date": 20260610, "last_close": 1800.0}
  ]
}
```

**第二步：回测排名（rank）**

```bash
# 按夏普比率排名（默认）
easy-tdx screen rank --from signals.json --sort sharpe --top 20 --table

# 按最大回撤排名（越小越好，用 --sort-reverse）
easy-tdx screen rank --from signals.json --sort max_drawdown --sort-reverse --table

# 管道模式：一步到位
easy-tdx screen scan --strategy strategies/rsi_reversal.py | easy-tdx screen rank --from - --table

# 补齐股票名称（需要网络）
easy-tdx screen rank --from signals.json --sort sharpe --top 10 --table --names
```

输出示例（`--table`）：

```
[*] 信号排名 (按 sharpe 降序, 共 37 只)
══════════════════════════════════════════════════════════════════════════
排名  代码       名称      总收益率  年化收益  最大回撤  夏普   胜率   交易
 *1   SZ300308  中际旭创   45.23%   18.72%   12.35%   1.85  62.5%    16
 *2   SH600519  贵州茅台   38.10%   15.90%    8.21%   1.62  58.3%    12
```

| 参数 | 说明 |
|------|------|
| `--universe` | `all`（默认，沪深全 A）/ `sh` / `sz` / 文件路径（每行 "市场 代码"） |
| `--vipdoc` | 离线数据目录（默认自动检测通达信安装路径） |
| `--workers` | 并发进程数：`0` 串行（默认）/ `2+` ProcessPoolExecutor 并发（推荐 4-8） |
| `--cache` | 增量扫描缓存文件路径（JSON，mtime 未变的文件自动跳过） |
| `--sort` | 排序指标：`sharpe`（默认）/ `total_return` / `max_drawdown` / `win_rate` 等 |
| `--sort-reverse` | 升序（用于回撤等越小越好的指标） |
| `--names` | 在线补齐股票名称（默认关闭，只查排名中的几十只） |
| `--count` | rank 使用最近 N 条 K 线（0=全部，默认 0） |

#### 强势股排名（strength）

按 **5 / 20 / 60 日涨幅加权**合成强势分，从全市场选出"最近最强"的股票。**纯离线数据**，读取本地通达信 `.day` 文件，全市场约 30-60 秒（并发可压到 10 秒内）。

**三种预设模式：**

| 模式 | 性格 | 权重 (w5/w20/w60) | 波动率惩罚 | 适合 |
|------|------|-------------------|-----------|------|
| `steady`（默认） | 中长期稳健 | 0.2 / 0.3 / 0.5 | ✅ 除以 vol_20 | 选"稳着涨"的票，妖股被高波动压低 |
| `breakout` | 近期妖股爆发 | 0.6 / 0.3 / 0.1 | ❌ 纯加权涨幅 | 选"短期最猛"的票，妖股本身就是高波动 |
| `balanced` | 三周期均衡 | 等权 + vol 调整 | ✅ 除以 vol_20 | 不确定时的安全默认 |

> 💡 **为什么 breakout 不除波动率？** 妖股本质高波动，除以 vol 会把它压下去，与"找妖股"目标矛盾。steady 除以 vol 是为了奖励"稳着涨"的票（vol 小，score 放大）。

```bash
# 中长期稳健强势 Top 50（默认 steady 模式）
easy-tdx screen strength --preset steady --top 50 --table

# 近期妖股爆发 Top 20（补齐股票名称）
easy-tdx screen strength --preset breakout --top 20 --names --table

# 三周期均衡
easy-tdx screen strength --preset balanced --top 30 --table

# 自定义权重（自动归一化，5:3:2 = 0.5:0.3:0.2）
easy-tdx screen strength --w5 0.5 --w20 0.3 --w60 0.2 --top 30 --table

# 并发扫描（推荐 4-8 进程）
easy-tdx screen strength --preset steady --top 100 --workers 4 --table

# 过滤低流动性（最近 5 日日均成交额 ≥ 5000 万）
easy-tdx screen strength --preset breakout --top 30 --min-amount 50000000 --table

# 缩小范围 + 输出到文件
easy-tdx screen strength --universe sz --top 30 --output sz_strength.json
```

输出示例（`--table`）：

```
[*] 强势股排名 [steady] 共 50 只
    数据截止: 2026-06-24 | 中长期稳健强势：权重偏 60 日，波动率惩罚，选出稳着涨的票
════════════════════════════════════════════════════════════════════════════════
排名  代码       名称     现价       5日     20日     60日   波动率   强势分
 *1   SZ300308  中际旭创     85.20    8.12%   15.34%   30.21%  0.0180     9.52
 *2   SH600519  贵州茅台  1800.00    3.25%    5.10%   10.05%  0.0120     6.21
```

输出示例（JSON）：

```json
{
  "scan_time": "2026-06-25T10:30:00",
  "preset": "steady",
  "preset_desc": "中长期稳健强势：权重偏 60 日，波动率惩罚...",
  "data_date": 20260624,
  "total_ranked": 50,
  "ranking": [
    {"rank": 1, "code": "300308", "market": "SZ", "name": "中际旭创",
     "last_close": 85.20, "last_date": 20260624,
     "ret_5": 0.0812, "ret_20": 0.1534, "ret_60": 0.3021,
     "vol_20": 0.0180, "strength": 9.52}
  ]
}
```

| 参数 | 说明 |
|------|------|
| `--preset` | 预设模式：`steady`（默认）/ `breakout` / `balanced` |
| `--w5` `--w20` `--w60` | 自定义三周期权重（覆盖预设，自动归一化） |
| `--vol-adjusted` / `--no-vol-adjusted` | 波动率惩罚开关（覆盖预设） |
| `--top` | 返回前 N 名（默认 50） |
| `--universe` | `all`（默认）/ `sh` / `sz` / 文件路径 |
| `--min-listed-days` | 最小上市天数（默认 65，保证能算 60 日涨幅） |
| `--min-amount` | 最近 5 日日均成交额下限（元，默认 0 不过滤） |
| `--workers` | 并发进程数：`0` 串行 / `4+` 并发（推荐 4-8） |
| `--names` | 在线补齐股票名称（默认关闭） |
| `--output` | 输出 JSON 文件（默认 stdout） |

> ⚠️ **数据时效**：strength 依赖本地 `.day` 文件。输出中的 `data_date` / `last_date` 字段标注数据截止日，请先用 `easy-tdx offline sync` 同步最新数据。

### 捉妖大师（重点）

捉妖大师是多周期涨幅共振指标，通过 20/60/120 日涨幅及指数平滑判断短中长线趋势是否同向，用于筛选趋势刚启动的强势股。

```bash
easy-tdx indicator ZHUOYAO -m SH -c 600519 --count 30 --table

# 自定义周期参数
easy-tdx indicator ZHUOYAO -m SZ -c 000001 --params N1=90,N2=45,N3=15

# 结合其他指标一起看
easy-tdx indicator ZHUOYAO,MACD,KDJ -m SH -c 600519 --count 20 --table
```

输出列说明：

| 列名 | 含义 |
|------|------|
| `ZY_LONG` | 长线 — 120 日涨幅的 10 日指数平滑 |
| `ZY_MID` | 中线 — 60 日涨幅(%) |
| `ZY_SHORT` | 短线 — 20 日涨幅(%) |
| `ZY_TREND` | 趋势 — 中线的 10 日指数平滑 |

**核心信号：** 四线全部 > 0 且短线 > 中线 > 长线 = 短中长趋势完全一致向上，是强势股特征。详见 [捉妖大师指标详解](docs/indicator-zhuoyao.md)。

### 30日乖离率信号（重点）

30日乖离率信号指标，在标准乖离率（BIAS）基础上叠加短/长信号线，通过三者位置关系判断趋势方向和转折点。源自通达信经典指标。

```bash
easy-tdx indicator BIAS_SIGNAL -m SH -c 600519 --count 60 --table

# 自定义周期参数
easy-tdx indicator BIAS_SIGNAL -m SZ -c 000001 --params P=5,M=20

# 结合其他指标一起看
easy-tdx indicator BIAS_SIGNAL,MACD,KDJ -m SH -c 600519 --count 30 --table
```

输出列说明：

| 列名 | 含义 |
|------|------|
| `BS_X` | M日乖离率 — 当前价格偏离30日均线的百分比 |
| `BS_SMA` | 短周期信号线 — 乖离率的 P 日均线，过滤短期噪音 |
| `BS_LMA` | 长周期信号线 — 乖离率的 M 日均线，捕捉中期趋势方向 |

**核心信号：** X > S_SMA 且 X_LMA 上升 = 多头确认（通达信红色）；S_SMA > X 或 X_LMA 下降 = 空头预警（通达信绿色）。多空判断非对称设计——多头需两个条件同时满足，空头只需其一，偏向保守预警。详见 [30日乖离率信号指标详解](docs/indicator-bias-signal.md)。

```python
# Python API 用法
from easy_tdx import MacClient, Market

with MacClient.from_best_host() as c:
    df = c.get_stock_kline_with_indicators(
        Market.SH, "600519",
        indicators=["BIAS_SIGNAL"],
        count=60,
    )
    # df 包含: datetime, open, close, high, low, vol, amount
    #         + BS_X, BS_SMA, BS_LMA
```

支持 34 个指标：MACD, KDJ, RSI, BOLL, DMI, ATR, WR, CCI, BIAS, BIAS_SIGNAL, OBV, VR, EMV, MFI, BRAR, ASI, TRIX, DPO, MTM, ROC, EXPMA, BBI, PSY, DFMA, CR, KTN, XSII, MASS, TAQ, ZHUOYAO, SAR, VWAP, AROON, FK。

```python
# Python API 用法
from easy_tdx import MacClient, Market

with MacClient.from_best_host() as c:
    df = c.get_stock_kline_with_indicators(
        Market.SH, "600519",
        indicators=["ZHUOYAO"],
        count=30,
    )
    # df 包含: datetime, open, close, high, low, vol, amount
    #         + ZY_LONG, ZY_MID, ZY_SHORT, ZY_TREND
```

支持 34 个指标：MACD, KDJ, RSI, BOLL, DMI, ATR, WR, CCI, BIAS, BIAS_SIGNAL, OBV, VR, EMV, MFI, BRAR, ASI, TRIX, DPO, MTM, ROC, EXPMA, BBI, PSY, DFMA, CR, KTN, XSII, MASS, TAQ, ZHUOYAO, SAR, VWAP, AROON, FK。

### 财务

```bash
easy-tdx f10 600519                          # 茅台利润表，最近 8 期（默认 lrb）
easy-tdx f10 600519 --type fzb --num 4       # 资产负债表，最近 4 期
easy-tdx f10 000001 --type llb --table       # 平安现金流量表，表格输出
```

> 新浪财经数据源，``--type`` 支持 ``lrb``（利润表）/``fzb``（资产负债表）/``llb``（现金流量表）。
> 独立于 TDX 行情服务器，``item_value`` 已转 float 可直接数值计算，同比附 ``{科目}_同比`` 列。

### 通达信原生 F10 与最新财务快照

走通达信协议（与 Web 层 ``/finance`` ``/company/*`` 端点同源），覆盖 ``f10``（新浪三表）之外的 F10 全文板块。完整示例见 [examples/06_finance/](./examples/06_finance/README.md)。

```bash
easy-tdx finance-info SH 600519 --table                          # 最新财务快照（30+ 项单期指标）
easy-tdx company-info SH 600519                                  # F10 板块目录（最新提示/公司概况/...）
easy-tdx company-info SH 600519 "公司概况"                        # 读板块完整正文（自动解析+读全，无需 offset/length）
easy-tdx company-info SH 600519 600519.txt                       # 也可直接传文件名（此时用 --offset/--length）
```

- ``finance-info``：最新一期财务快照，含股本结构、资产负债、利润、现金流、每股指标（37 字段）。与 ``f10`` 互补——前者是单期快照，后者是多期三表。
- ``company-info``：**一个命令两种用法**——无板块名参数列 F10 板块目录，有板块名参数读正文。目录含 16 个板块（最新提示、公司概况、财务分析、股东研究、股本结构、资本运作、业内点评、行业分析、公司大事、研究报告、经营分析、主力追踪、分红扩股、高层治理、龙虎榜单、关联个股）。
- 读正文时传板块名即可自动读取完整内容（按目录 length 分块循环，大板块如「公司大事」也能一次读全）；``--offset``/``--length`` 仅在传文件名时生效。通达信多服务器目录版本不一致时自动重试命中。


### 扩展市场（港股/美股/期货）

```bash
easy-tdx ex markets                                       # 列出可用市场
easy-tdx ex kline HK_MAIN_BOARD 00700 --count 30 --table  # 港股 K 线
easy-tdx ex kline US_STOCK AAPL --table                    # 美股 K 线
easy-tdx ex quote US_STOCK TSLA --table                    # 美股报价
easy-tdx ex quote-list HK_MAIN_BOARD --table               # 港股商品列表
easy-tdx ex tick HK_MAIN_BOARD 00700 --table               # 港股分时
```

### 离线数据（读取 + 写入同步）

从本地通达信安装目录直接读取数据文件，无需网络连接：

```bash
easy-tdx offline home                                # 检测通达信安装目录
easy-tdx offline daily SH 600000 --count 10 --table  # A 股日线
easy-tdx offline min SZ 000001 --type lc5 --table    # 分钟线（5min/lc1/lc5）
easy-tdx offline ex-files --table                    # 列出扩展市场可用文件
easy-tdx offline ex-daily 38#2_CPI --count 5 --table # 扩展市场日线（期货/港股/外盘）
easy-tdx offline gbbq C:\new_jyplug\T0002\hq_cache\gbbq --table        # 股本变迁
easy-tdx offline financial C:\new_jyplug\vipdoc\fin\gpcw20260331.dat    # 历史财务
easy-tdx offline blocks C:\new_jyplug\T0002\blocknew --table            # 自定义板块
```

从服务端获取最新日线并写入本地 .day 文件，替代通达信内置下载功能：

```bash
# 同步单只股票日线（自动增量/全量）
easy-tdx offline sync-daily SZ 000001
easy-tdx offline sync-daily SH 600519 --vipdoc C:\new_jyplug\vipdoc

# 一键同步沪深全市场（每天一条命令）
easy-tdx offline sync-all
```

> 建议在通达信关闭时执行 sync 命令，避免文件被锁定。空文件自动全量下载，已有数据只做增量追加。

## Web API

将 easy-tdx 暴露为 REST + WebSocket 服务，供前端、其他语言或远程调用。无需额外注册，零配置启动。

### 安装

```bash
# 标准安装
pip install easy-tdx[web]

# 开发模式（从源码安装，支持热重载）
pip install -e ".[web]"
```

### 快速启动

```bash
# 启动 Web API 服务器（自动连接最优 TDX 服务器）
easy-tdx serve

# 启动后浏览器打开 http://127.0.0.1:8000/docs 查看完整 API 文档（Swagger UI）
# 也可以访问 http://127.0.0.1:8000/redoc 查看 ReDoc 格式文档

# 指定端口和 TDX 服务器
easy-tdx serve --port 8080 --tdx-host 119.147.212.81

# 开发模式（代码修改后自动重载）
easy-tdx serve --reload
```

> 💡 启动后访问 **http://127.0.0.1:8000/docs** 可以看到完整的交互式 API 文档，支持在线调试每个接口。

### REST API 示例

```bash
# ── 基础行情 ──
# 获取深圳市场证券数量
curl "http://localhost:8000/api/v1/security/count?market=SZ"

# 获取股票K线
curl "http://localhost:8000/api/v1/bars?market=SZ&code=000001&category=DAY&count=100"

# 批量获取实时行情
curl -X POST "http://localhost:8000/api/v1/quotes" \
  -H "Content-Type: application/json" \
  -d '{"stocks": [{"market": "SZ", "code": "000001"}, {"market": "SH", "code": "600000"}]}'

# 市场统计
curl "http://localhost:8000/api/v1/market/stat"

# 全市场强势股排名（基于本地 vipdoc 数据，扫描约 30-60 秒）
# steady = 中长期稳健 / breakout = 近期妖股 / balanced = 均衡
curl "http://localhost:8000/api/v1/market/strength?preset=breakout&top_n=20"

# 自定义权重 + 过滤低流动性（日均成交额 ≥ 5000 万）
curl "http://localhost:8000/api/v1/market/strength?w5=0.5&w20=0.3&w60=0.2&min_amount=50000000&top_n=30"

# 板块信息（标准协议）
curl "http://localhost:8000/api/v1/block?filename=block_gn.dat"

# ── 板块分析（MAC 协议）──
# 行业板块列表
curl "http://localhost:8000/api/v1/board-mac/list?board_type=HY&count=50"

# 板块成分股（按涨幅排序）
curl "http://localhost:8000/api/v1/board-mac/members?board_symbol=881001&count=20"

# 个股所属板块
curl "http://localhost:8000/api/v1/board-mac/belong?market=SZ&code=000001"

# 板块摘要（含主力净流入、涨跌家数）
curl "http://localhost:8000/api/v1/board-mac/summary?board_symbol=881001"

# 行业板块涨幅排名 Top 10
curl "http://localhost:8000/api/v1/board-mac/ranking?board_type=HY&top_n=10"

# 板块 20 日涨幅排行
curl "http://localhost:8000/api/v1/board-mac/change-ranking?board_type=HY&days=20&top_n=10"

# ── 资金 / 信息 ──
# 个股资金流向（主力/散户净流入）
curl "http://localhost:8000/api/v1/mac/capital-flow?market=SH&code=600519"

# 个股基本信息快照
curl "http://localhost:8000/api/v1/mac/symbol-info?market=SZ&code=000001"

# 服务器交易时段信息
curl "http://localhost:8000/api/v1/mac/server-info"

# ── 公告检索（巨潮资讯网，独立数据源）──
# 检索公司公告（无需 TDX 行情服务器）
curl "http://localhost:8000/api/v1/announcements?code=688017&count=30&page=1"
# 返回每条含 url（4 参数可直点打开）和 pdf_url（PDF 直链）：
# {"data": [{"title":"...","type":"...","date":"...","url":".../detail?stockCode=...","pdf_url":"http://static.cninfo.com.cn/.../xxx.PDF",...}], "count": 30}

# ── 财报三表（新浪财经，独立数据源）──
# 利润表（type: lrb/fzb/llb）
curl "http://localhost:8000/api/v1/sina/financial-report?code=600519&type=lrb&num=8"
# 返回每行一期（最新在前），列为科目名（float）+ {科目}_同比（如有）：

# ── 排行 / 竞价 / 异动 ──
# 全 A 涨幅排行前 20
curl "http://localhost:8000/api/v1/mac/quote-list?category=A&count=20&sort_type=CHANGE_PCT"

# 集合竞价数据
curl "http://localhost:8000/api/v1/mac/auction?market=SZ&code=000001"

# 市场异动行情
curl "http://localhost:8000/api/v1/mac/unusual?market=SH&count=50"

# ── 扩展市场（期货/港股/美股）──
# 港股 K 线
curl "http://localhost:8000/api/v1/ex/bars?market=HK_MAIN_BOARD&code=00700&category=DAY&count=30"

# 美股实时报价
curl "http://localhost:8000/api/v1/ex/quote?market=US_STOCK&code=AAPL"

# ── 技术指标 ──
# 列出所有可用指标
curl "http://localhost:8000/api/v1/indicator/list"

# 计算 MACD + KDJ 指标
curl -X POST "http://localhost:8000/api/v1/indicator/compute" \
  -H "Content-Type: application/json" \
  -d '{"data": [{"open":10,"close":10.5,"high":11,"low":9.5,"vol":1000}], "indicators": ["MACD", "KDJ"]}'

# ── 缠论分析 ──
curl -X POST "http://localhost:8000/api/v1/chanlun/analyze" \
  -H "Content-Type: application/json" \
  -d '{"market": "SZ", "code": "000001", "category": "DAY", "count": 200}'
```

### WebSocket 实时行情

```javascript
// JavaScript 示例
const ws = new WebSocket("ws://localhost:8000/ws/realtime/SZ000001");

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log(data);  // {type: "tick", market: "SZ", code: "000001", price: 10.5, ...}
};

// 动态订阅更多标的
ws.send(JSON.stringify({action: "subscribe", symbol: "SH600000"}));
```

### API 文档

启动服务后访问：
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### 编程 API

```python
from easy_tdx.web import create_app
import uvicorn

app = create_app(host="119.147.212.81", port=7709)
uvicorn.run(app, host="0.0.0.0", port=8000)
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
| `board-change-ranking` | 板块 N 日涨跌幅排行（支持指定截止日期） |
| `belong-board` | 个股所属板块 |
| `capital-flow` | 资金流向 |
| `auction` | 集合竞价 |
| `unusual` | 市场异动 |
| `market-stat` | 全市场涨跌统计 |
| `server-info` | 服务器交易时段 |
| `symbol-info` | 个股特征快照 |
| `indicator` | 技术指标计算（34 个：MACD/KDJ/RSI/BOLL/DMI/ATR...） |
| `indicator-list` | 列出可用技术指标 |
| `backtest` | 回测引擎（加载策略文件，输出绩效报告） |
| `portfolio` | 多标的组合回测（共享资金池，均等分配，汇总绩效） |
| `factor list` | 列出所有内置因子 |
| `factor analyze` | 因子分析（IC/分层/衰减） |
| `pfactor backtest` | 组合因子选股回测 |
| `run-all` | 批量运行所有策略并排名（绩效排名 + 综合评分 + 可选图表） |
| `screen scan` | 策略选股扫描（纯离线，全市场信号扫描） |
| `screen rank` | 扫描结果回测排名（按夏普/回撤等指标排序） |
| `serve` | 启动 Web API 服务器（REST + WebSocket，需 `easy-tdx[web]`） |
| `f10` | 财报三表（新浪：利润表/资产负债表/现金流量表） |
| `finance-info` | 最新财务快照（通达信协议，30+ 项单期指标） |
| `company-info` | F10 公司信息（无板块名列目录 / 有板块名读正文） |
| `fund-flow` | 历史资金流向 |
| `ex kline` | 扩展市场 K 线 |
| `ex quote` | 扩展市场报价 |
| `ex quote-list` | 扩展市场商品列表 |
| `ex tick` | 扩展市场分时 |
| `ex markets` | 列出可用扩展市场 |
| `offline home` | 检测通达信安装目录 |
| `offline daily` | A 股日线（本地 .day 文件） |
| `offline sync-daily` | 从服务端同步单只股票日线到本地 .day 文件 |
| `offline sync-all` | 一键同步沪深全市场日线（扫描本地 .day 文件） |
| `offline min` | 分钟线（本地 .5/.lc1/.lc5 文件） |
| `offline ex-files` | 列出扩展市场可用文件 |
| `offline ex-daily` | 扩展市场日线（期货/港股/外盘） |
| `offline gbbq` | 股本变迁数据 |
| `offline financial` | 历史财务数据 |
| `offline blocks` | 自定义板块数据 |

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

支持 34 个技术指标：

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
| ZHUOYAO | close | ZY_LONG, ZY_MID, ZY_SHORT, ZY_TREND |
| BIAS_SIGNAL | close | BS_X, BS_SMA, BS_LMA |
| SAR | high, low | SAR（抛物线转向/动态止损位） |
| VWAP | close, high, low, vol | VWAP（N日滚动成交量加权均价） |
| AROON | high, low | AROON_UP, AROON_DOWN, AROON_OSC |
| FK | close | FK（EMA(2) 突破斜率外推 EMA(42)） |

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

    # 板块 N 日涨跌幅排行（支持指定截止日期，默认全部）
    df = c.get_board_change_ranking(BoardType.HY, days=20)
    df = c.get_board_change_ranking(BoardType.GN, target_date=20250530, days=10, top_n=15)
    # 返回列：code, name, close_end, close_start, change_pct
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
from datetime import date

from easy_tdx import MacExClient, ExMarket, Period

with MacExClient.from_best_host() as c:
    count = c.goods_count(ExMarket.HK_MAIN_BOARD)
    df = c.goods_list(ExMarket.HK_MAIN_BOARD, start=0, count=50)
    df = c.goods_kline(ExMarket.US_STOCK, "AAPL", Period.DAILY, count=10)
    df = c.goods_quotes([(ExMarket.HK_MAIN_BOARD, "00700")])
    df = c.goods_tick_chart(ExMarket.HK_MAIN_BOARD, "00700")
    df = c.goods_transaction(ExMarket.HK_MAIN_BOARD, "00700", count=100)
    df = c.goods_transaction_all(ExMarket.HK_MAIN_BOARD, "00700", date(2026, 7, 3))  # 港股当日全部逐笔
```

> **逐笔成交排序**：通达信协议为**倒序**——`start=0` 指向最新一笔（收盘方向），`count=2000` 默认只取最近 2000 笔。港股单日成交常达数万笔（如 02715 约 1.3 万笔/日），若需当日全部成交，用 `goods_transaction_all`（仅港股股票类市场，自动按 1800/页翻页取全天，安全上限 9 万条；返回协议原生倒序，需正序展示自行 `df.iloc[::-1]`）。

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

### 离线数据写入同步

从服务端获取最新数据并追加写入本地通达信数据文件：

```python
from easy_tdx.offline import (
    encode_daily_bar, append_daily_bars, get_last_bar_date,
    encode_5min_bar, append_5min_bars,
    encode_lc_min_bar, append_lc_min_bars,
)
from easy_tdx import Market
from easy_tdx.client import TdxClient

# 追加日线到 .day 文件（自动跳过重复日期）
from easy_tdx.offline import sync_daily_bars_from_security_bars

# 手动编码单条记录
bar_bytes = encode_daily_bar(bar, price_coeff=0.01, vol_coeff=0.01)

# 获取文件末尾日期
last_date = get_last_bar_date("C:/new_jyplug/vipdoc/sh/lday/sh600000.day")
```

v1.5.0 起可通过 CLI 直接使用：

```bash
easy-tdx offline daily SH 600000 --count 10 --table
easy-tdx offline ex-files --table
easy-tdx offline ex-daily 29#A1801 --table
```

### 缠论分析

基于缠论理论的技术分析模块，接收 easy_tdx 的 K 线 DataFrame，输出笔、中枢、线段、买卖点、背驰等分析结果：

```python
from easy_tdx.chanlun import ChanlunAnalyser, ChanlunConfig

# 使用 easy_tdx 获取 K 线数据
with TdxClient() as client:
    df = client.get_security_bars(Market.SH, "600519", KlineCategory.DAY, 0, 800)

# 缠论分析
analyser = ChanlunAnalyser("SH600519", "DAILY")
result = analyser.process_klines(df)

# 获取结果
print(f"笔数: {len(result.bis)}")
print(f"中枢数: {len(result.zss)}")
print(f"线段数: {len(result.xds)}")
print(f"买卖点: {[m.msg for m in result.mmds]}")
print(f"背驰: {[b.msg for b in result.bcs]}")

# JSON 兼容字典输出
print(result.to_dict())
```

### 公告检索（巨潮资讯网）

独立数据源（巨潮资讯网 cninfo），无需连接 TDX 行情服务器即可检索公司公告。
标准库 urllib 实现，零额外依赖。

```python
from easy_tdx.cninfo import CninfoClient

client = CninfoClient()

# 检索公告（默认 30 条，最新在前）
df = client.get_announcements("688017")
# → DataFrame[title, type, date, url, code, org_id, announcement_id, announcement_time, pdf_url]

# 翻页 + 自定义数量
df = client.get_announcements("601088", count=10, page=2)

# 返回示例（url 含 4 参数可直点打开，pdf_url 为 PDF 直链）：
#   title                       type     date        url                                              pdf_url
# 0 关于召开2025年年度股东大会... 股东大会 2025-06-14 .../detail?stockCode=688017&announcementId=... http://static.cninfo.com.cn/.../xxx.PDF
# 1 2024年年度报告              PDF      2025-03-28 .../detail?stockCode=688017&announcementId=... http://static.cninfo.com.cn/.../yyy.PDF
```

> - ``type`` 优先取 cninfo 的 ``announcementTypeName``；该字段对很多公告为 null
>   （数据源限制），此时回退到 ``adjunctType``（如 "PDF"），再为空给空字符串。
> - ``url`` 必须含 4 参数（``stockCode``/``announcementId``/``orgId``/``announcementTime``）
>   才能打开，少参数会 404。
> - orgId 解析沿用 #19 修复：动态拉取官方映射表，查不到回退硬编码规则，
>   保证 601xxx 等非标 orgId 段也能正常查询。

#### 下载公告 PDF

```python
# 下载最新一条公告的 PDF 到当前目录
df = client.get_announcements("601088", count=5)
path = client.download_pdf(df.iloc[0])  # 接受 Announcement 或 DataFrame 的一行
print(path)  # /abs/path/20260605_1225351400.PDF

# 批量下载
for _, row in df.iterrows():
    try:
        path = client.download_pdf(row, dest_dir="./pdfs")
    except Exception as e:
        print(f"跳过（无附件或失败）: {e}")
```

### 财报三表（新浪财经）

独立数据源（新浪财经），无需连接 TDX 行情服务器即可获取利润表/资产负债表/现金流量表。
标准库 urllib 实现，零额外依赖。

```python
from easy_tdx.sina import SinaClient

client = SinaClient()

# 利润表（默认 8 期，最新在前）
df = client.get_financial_report("600519", report_type="lrb")
# → DataFrame，每行一期，列 = [报告期, 营业总收入, 营业总收入_同比, ...]

# 资产负债表 / 现金流量表（report_type 也接受中文别名：利润表/资产负债表/现金流量表）
df = client.get_financial_report("600519", report_type="fzb", num=4)
df = client.get_financial_report("600519", report_type="llb", num=4)

# 返回示例（item_value 已转 float，可直接数值计算）：
#         报告期      营业总收入  营业总收入_同比       营业收入  营业收入_同比
# 0  2026-03-31  54702912385.23        0.06336  53909252220.51        0.06538
# 1  2025-12-31 174000000000.00        0.10000            NaN            NaN
```

> - ``item_value`` 是字符串（新浪原始格式），本实现转 float；空/非数值转 None
> - 有同比的科目附加 ``{科目}_同比`` 列（float 比例，如 0.06336 = +6.3%）
> - 大类标题行（如 ``流动资产``，原 ``item_value=""``）保留为 None，反映报表结构

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
| `get_board_change_ranking(board_type, target_date, days, ...)` | 板块 N 日涨跌幅排行 |
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
├── indicator.py       # 技术指标计算（34 个，基于 MyTT）
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
├── chanlun/           # 缠论技术分析（K线合并/分型/笔/线段/中枢/买卖点/背驰）
├── factor/            # 因子引擎（Factor ABC/19内置因子/截面计算/因子分析/预处理管道）
├── portfolio/         # 组合管理（4优化器/风险模型/再平衡引擎）
├── backtest/          # 回测引擎（Strategy基类/向量化引擎/多因子组合/滑点模型/执行仿真/归因分析）
├── screen/            # 策略选股扫描（scan信号扫描/rank回测排名/并发扫描/增量缓存）
├── realtime/          # 实时数据推送框架（EventBus/事件驱动/asyncio）
├── web/               # Web API（FastAPI REST + WebSocket）
├── models/            # 纯 dataclass，无业务逻辑
├── offline/           # 离线数据读写模块（读取 + 写入同步）
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

## 更新日志

完整版本变更记录请查看 [CHANGELOG.md](CHANGELOG.md)。

## 免责声明

本工具仅供学习和技术研究使用，不构成任何投资建议。使用者应自行承担投资决策的全部风险。
作者不对因使用本工具导致的任何直接或间接损失负责。
