# easy-tdx

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/easy-tdx.svg)](https://pypi.org/project/easy-tdx/)
[![GitHub Repo stars](https://img.shields.io/github/stars/handsomejustin/easy-tdx?style=social)](https://github.com/handsomejustin/easy-tdx)
[![GitHub last commit](https://img.shields.io/github/last-commit/handsomejustin/easy-tdx)](https://github.com/handsomejustin/easy-tdx)
[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![Security: bandit](https://img.shields.io/badge/security-bandit-yellow.svg)](https://github.com/PyCQA/bandit)

量化基金花百万买的毫秒级行情通道，散户连一根日线都要手动截图——这不是技术差距，这是数据霸凌。

easy-tdx 要做的事很简单：**把机构的数据锁砸开，扔到每个普通人桌面。**

它是一个完全免费、无需注册、无需 API Key、纯开源的行**情核武器**。  
一行命令，A股、港股、美股、期货——K线、报价、资金流向、板块轮动、分时明细、逐笔成交，**毫秒级拉满**。

**34个技术指标**（MACD、KDJ、RSI、BOLL……连”捉妖大师”和”30日乖离率信号”都给你算好）开箱即用。
**缠论分析**（笔、中枢、买卖点、背驰）一键出结果——你不再需要手画分型、猜线段。
**内置回测引擎**——写个策略文件，一行命令跑回测，16 个经典策略自带，多因子组合、策略选股扫描，批量对比哪个最赚钱一目了然。

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
easy-tdx announcement 600519 --count 50 --page 2      # 翻页
easy-tdx announcement 000001 --table                  # 表格输出
```

> 独立数据源（巨潮资讯网），无需连接 TDX 行情服务器即可使用。

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

输出示例（以 SZ 300308 为例）：

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
# 返回：{"data": [{"title": "...", "type": "...", "date": "...", "url": "..."}], "count": 30}

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
| `f10` | F10 公司信息 |
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
# → DataFrame[title, type, date, url]

# 翻页 + 自定义数量
df = client.get_announcements("600519", count=50, page=2)

# 返回示例：
#                                              title      type        date                                                 url
# 0        关于召开2025年年度股东大会的通知    股东大会  2025-06-14  https://www.cninfo.com.cn/new/disclosure/detail?annoId=abc123
# 1                          2024年年度报告        定期报告  2025-03-28  https://www.cninfo.com.cn/new/disclosure/detail?annoId=def456
```

> orgId 解析沿用 #19 修复：动态拉取官方映射表，查不到回退硬编码规则，
> 保证 601xxx 等非标 orgId 段也能正常查询。

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

## Changelog

### 1.13.0 (2026-06-14)

**新增巨潮公告检索** — 三层接入（编程 API / CLI / Web API），独立数据源，无需连接 TDX 行情服务器。

- 新模块 `easy_tdx.cninfo`：`CninfoClient().get_announcements(code, count=, page=)` 返回 `DataFrame[title, type, date, url]`
- CLI：`easy-tdx announcement 688017 [--count N --page N --table]`
- Web：`GET /api/v1/announcements?code=&count=&page=`
- 标准库 urllib 实现，零新依赖
- 沿用 #19 修复的 orgId 动态映射 + 三段硬编码 fallback（保证 601xxx 段可查）

### 1.12.0 (2026-06-14)

**新增 4 个技术指标（30 → 34）** — 按"语义空白"补齐三类现有指标库缺失的维度：止损位、机构成本价、趋势启动时机。均为纯 numpy 实现，零新依赖。

**新增指标**：
- **SAR 抛物线转向**（`high, low` → `SAR`）：基于 Wilder 加速因子的动态止损位，填补 32 个指标里"止损位"语义的空白。可直接喂给 `BacktestEngine` 做动态 `stop_loss`。实现含反转检测、AF 加速/封顶、SAR 不穿越前两根 K 线极值的限制。
- **VWAP 成交量加权均价**（`close, high, low, vol` → `VWAP`）：N 日滚动机构基准成本价，填补"机构成本"维度空白。用典型价格 `(H+L+C)/3` 加权，含除零保护（零成交量返回 nan）。
- **AROON 阿隆指标**（`high, low` → `AROON_UP, AROON_DOWN, AROON_OSC`）：用"N 周期内新高/新低距今多少根"识别趋势启动时机，与现有 DMI（判断趋势强度但滞后）互补而非冗余。
- **FK 趋势指标**（`close` → `FK`）：清理孤儿函数——`MyTT.FK` 此前已实现但未在 `indicator.py` 注册，用户通过 CLI/API 无法调用。现正式注册暴露。语义为 EMA(2) 是否突破斜率外推 EMA(42)，本质是动量偏离检测。

**架构**：所有新指标沿用现有 `IndicatorSpec` 注册模式，`compute_indicators()` / `get_stock_kline_with_indicators()` / CLI `easy-tdx indicator` 自动可用，无需改动调度层。

**除零与边界保护**：
- SAR：一字板/停牌（高低价相同）不崩溃、不产生 inf；空输入返回空数组
- VWAP：零成交量返回 nan（不产生 inf）；前 N-1 根为 nan（rolling 窗口）
- AROON：输出严格落在 [0, 100] 区间

**类型存根**：`MyTT.pyi` 同步补充 SAR/VWAP/AROON/FK 四个函数签名，mypy strict 零错误。

**测试**：新增 `tests/unit/test_mytt.py`，22 个用例覆盖三个新指标 + FK 的数值正确性、单边行情行为、除零/空输入边界。注册层端到端覆盖复用 `test_indicator.py::test_all_registered_indicators_run`。

### 1.11.6 (2026-06-13)

**CI 类型与格式修复** — 修复 CI 流水线 mypy strict（13 errors）和 ruff format（8 files）失败，全部为类型标注与存根问题，无运行时行为变更。

**mypy strict 修复（13 errors → 0）**：
- `portfolio/optimizer.py`：`register_optimizer` 装饰器返回类型从 `type[WeightOptimizer]` 改为 `Callable[[type[WeightOptimizer]], type[WeightOptimizer]]`，消除 4 个子类 "Too many arguments" 误报
- `factor/engine.py`：`_datetime_to_int` 用 `isinstance` 收窄替代 `object → int` 强转，消除 call-overload + no-any-return
- `backtest/orders.py` / `execution.py`：年化波动率 `np.sqrt()` 表达式用 `float()` 包裹，消除 no-any-return
- `factor/builtin/technical.py`：`MyTT.pyi` 的 `MACD` 存根删除错误的 `LOW/HIGH` 参数，与 `MyTT.py` 实际签名 `MACD(CLOSE, SHORT, LONG, M)` 对齐
- `pyproject.toml`：新增 scipy mypy override（`ignore_missing_imports`），统一处理可选依赖的 stubs 缺失，移除冗余 inline `type: ignore`

**ruff format**：8 个 test 文件统一格式化。

**测试**：564 passed, 0 failed；mypy 192 文件零错误；ruff check/format 全绿。

### 1.11.5 (2026-06-13)

**稳定性与代码质量修复** — 全项目代码审计 + 一个潜伏的 ping 崩溃 bug 修复。

**Bug 修复**：
- 修复 `easy-tdx ping` 在非交易时间（服务器握手阶段关闭连接）整个命令崩溃的问题。根因：`ping_host` 仅捕获 `OSError`，但握手期 `_recv_exact_sock` 抛出的 `TdxConnectionError`（继承自 `TdxError(Exception)` 而非 `OSError`）逃出捕获，经 `ping_all` 的 `fut.result()` 重新抛出，导致单台服务器不可用就拖垮整条测速命令。修复后符合 docstring 承诺"不可达服务器不包含在结果中"，并加防御层让 `ping_all` 对异常 future 容错跳过。
- 修复回测 `OrderSimulator._find_bar_index` 把 DataFrame 的 index label 当位置索引用的隐患。当传入 df 的 index 非默认 RangeIndex 时，`idxmax()` 返回的 label 与 `iloc[]` 期望的位置不一致，可能导致撮合取错 K 线。改用 `to_numpy().argmax()` 取真实位置。

**依赖与工程化**：
- scipy 隐式硬依赖声明：`factor/analysis.py` 的 Rank IC（spearman）通过 pandas lazy import scipy，干净环境必报 `ModuleNotFoundError`。新增 `science` 可选依赖组（`pip install easy-tdx[science]`），并在 spearman 分支加 try-import 友好报错（复用 `optimizer.py` 现有模式）。
- `mac/client.py` 板块 N 日涨跌幅排行中静默吞异常的 `except Exception: continue` 补上 `logger.debug` 日志，便于排查。
- `.gitignore` 补全 `.coverage`、`signals.json`。

**文档**：
- `CLAUDE.md` 架构章节更新：补全 `mac/`、`ex/`、`unified.py`、`portfolio/`、`factor/`、`offline/`、`screen/` 等子包，说明四套 client（Windows/macOS/扩展/macOS扩展）的 sync+async 镜像关系。

**测试**：564 passed, 0 failed（+8 新增：2 ping 容错回归、2 非连续 index 回归、4 既有覆盖增强）

### 1.11.1 (2026-06-12)

**量化因子引擎 + 组合管理 + 高级回测增强** — 三大新模块，补齐从因子研究到组合执行的完整量化链路。

**因子引擎（factor/）**：
- `Factor` ABC + 注册表模式（`@register_factor` 装饰器），19 个内置因子
- `FactorEngine`：单股多因子 / 截面批量 / 远期收益计算
- 因子类别：动量、波动率、质量、成交量、技术（桥接 MyTT）、缠论（桥接 ChanlunAnalyser）、价值（占位）
- 因子预处理管道：去极值（MAD）、标准化、排名归一化、填充缺失、正交化
- `FactorAnalyzer`：IC（Spearman）、分层收益（5 组）、换手率、衰减分析、完整报告

**组合管理（portfolio/）**：
- 4 种权重优化器：等权、因子加权、风险平价（逆波动率）、均值方差（scipy 可选）
- 风险模型：Ledoit-Wolf 收缩协方差、组合风险分解
- `RebalanceEngine`：多期调仓回测（周/月/季），100 股整手、佣金+印花税

**高级回测增强（backtest/）**：
- 4 种滑点模型：Fixed、Percent、SquareRoot（Almgren-Chriss）、Volume
- 4 种执行仿真：Immediate、TWAP、VWAP、Limit（限价单 + TTL）
- `AttributionAnalyzer`：成本归因、Brinson 归因（配置/选股/交叉）、因子归因
- 完全向后兼容（`BacktestEngine` 新增 `slippage_model` / `execution_model` 可选参数）

**CLI**：
- `easy-tdx factor list` / `factor analyze` — 因子列表和分析
- `easy-tdx pfactor backtest` — 组合因子选股回测

**测试**：556 passed, 0 failed（+176 新增）

### 1.10.5 (2026-06-12)

**Web API 全面补齐 + 稳定性修复** — 新增 18 个 REST 端点，Web API 与 CLI 接口覆盖对齐，修复多个生产环境问题。

- **板块分析（6 端点）**：板块列表、成分股、所属板块、板块摘要、涨幅排名、N日涨幅排行
- **资金/信息（3 端点）**：个股资金流向、个股信息快照、服务器交易时段
- **排行/竞价/异动（3 端点）**：分类排序行情列表、集合竞价、市场异动
- **扩展市场（4 端点）**：港股/美股/期货的 K 线、报价、分时、逐笔成交
- **技术指标（2 端点）**：指标列表、指标计算（POST）
- 新增 `AsyncMacClient` 依赖注入（`get_mac_client`），Web 层同时管理 TDX + MAC 双客户端连接
- 新增 `AsyncExTdxClient` 依赖注入（`get_ex_client`），可选启用扩展市场端点
- 新增 6 个 MAC 枚举转换器（BoardType/SortType/SortOrder/Category/ExMarket/FilterType）
- 新增 `DictResponse` 和 `ComputeIndicatorsRequest` schemas
- Web API 端点总数从 22 增至 40
- 修复 MAC 客户端连接失败时 12 个端点返回 `AttributeError`（500），现正确返回 503
- 修复扩展市场 dataclass 序列化时 `_raw: bytes` 字段导致 JSON 编码 500 错误
- 修复 `/redoc` 页面 404（CDN `redoc@next` 已失效），手动注册端点并锁定 `redoc@2.2.0` 稳定版

### 1.10.0 (2026-06-12)

**Web API 层** — 新增 FastAPI REST + WebSocket 服务，一键将 easy-tdx 暴露为 HTTP API。

- 新增 `src/easy_tdx/web/` 模块：app factory、6 个路由（market/bars/finance/block/chanlun/realtime）、Pydantic schemas、异常处理
- 新增 `easy-tdx serve` CLI 命令，支持 `--host`、`--port`、`--tdx-host`、`--reload` 参数
- REST 端点覆盖全部 `AsyncTdxClient` 方法（K线/报价/资金流向/板块/财务/缠论分析等）
- WebSocket 端点 `/ws/realtime/{symbol}` 支持实时行情订阅和多标的动态切换
- 自动生成 Swagger UI (`/docs`) 和 ReDoc (`/redoc`) 文档
- 可选依赖 `pip install easy-tdx[web]`，核心安装不受影响
- 20 个离线单元测试覆盖 schemas、路由注册、OpenAPI schema 生成、输入验证
- 修复 `deps.py` 中 `AsyncTdxClient` 在 `TYPE_CHECKING` 下导致运行时 `NameError`（500 → 正常启动）
- 修复 market/category 参数不支持小写（`sz`/`sh`）和非法值（`ZZZ`）导致 500 的问题，统一返回 400 Bad Request

### 1.9.10 (2026-06-11)

**板块 N 日涨跌幅排行** — 新增 `board-change-ranking` 命令，支持按行业/概念/风格板块计算指定日期前 N 个交易日的涨跌幅并排行。

- 新增 `MacClient.get_board_change_ranking()` / `AsyncMacClient` 同名异步方法
- 新增 CLI 命令 `easy-tdx board-change-ranking`，支持 `--type`、`--date`、`--days`、`--top`、`--asc` 参数
- 利用板块指数 K 线直接计算，无需逐个聚合成分股，效率远高于现有 `board-ranking`
- 支持指定截止日期（`--date YYYYMMDD`），周末/节假日自动回退到前一交易日
- 默认列出全部板块，`--top N` 截断前 N 个
- 12 个单元测试覆盖计算正确性、边界条件、排序方向

### 1.9.9 (2026-06-11)

**Bug 修复** — 修复并发扫描（`--workers`）在动态加载策略时静默返回空结果的问题。

- **根因**：`ProcessPoolExecutor` 将动态 `importlib` 加载的策略类 pickle 序列化后发送到子进程，子进程无法反序列化（模块未注册到 `sys.modules`），异常被 `except` 静默吞掉
- **修复**：`_scan_parallel` 改为传递策略文件路径（字符串），子进程内通过 `_load_strategy_class` 自行加载策略类
- 新增 `_get_strategy_file` 辅助函数：从类方法 `co_filename` 反查策略文件路径
- 新增回归测试 `TestParallelPickleFix`

### 1.9.8 (2026-06-11)

**CI 修复** — 修复 CI 流水线 ruff 和 pytest 配置问题。

- 修复 `MyTT.pyi` 类型存根文件行过长导致 ruff check 失败（`.pyi` 文件排除 ruff 检查）
- 添加 `pytest-asyncio` 依赖，修复 `test_realtime.py` 异步测试报错
- 修复 `test_backtest_engine.py` 中未使用变量 `result` 的 lint 警告
- 380 个测试全部通过，CI 全绿

### 1.9.7 (2026-06-11)

**CLI 全量集成** — v1.9.6 新增的 6 项功能全部暴露到 CLI，修复缠论多级别联立的 client 生命周期 bug。

- **`screen scan` 并发扫描**：新增 `--workers N` 参数，ProcessPoolExecutor 并行处理，推荐 4-8 进程，扫描速度提升 4-8 倍
- **`screen scan` 增量缓存**：新增 `--cache PATH` 参数，mtime 检测未修改的 `.day` 文件自动跳过
- **`backtest` 缠论桥接**：新增 `--chanlun-level LEVEL` 参数，引擎自动计算缠论分析并注入策略 `self.chanlun`
- **`portfolio` 组合回测**：新增 `easy-tdx portfolio` 命令，多标的共享资金池、均等分配、汇总绩效
- **`chanlun` 多级别联立**：新增 `--multi-level PERIOD` 参数，分析高级别最后一笔在低级别中的趋势方向、笔重叠、背驰条件
- **Bug 修复**：`cmd_chanlun.py` 中 `_run_multi_level` 在 `with` 块外使用 `client`，导致已关闭连接报错

### 1.9.6 (2026-06-11)

**工程质量全面升级** — 基于 Devin AI 代码审查的 12 项改进建议全部落地，覆盖 CI、回测引擎、缠论模块、扫描引擎和架构层面。

- **CI 覆盖率强制执行**：pytest 命令加入 `--cov-fail-under=50`，CI 不再空转
- **真实平均持仓天数**：`avg_holding_days` 从硬编码 5.0 改为 FIFO 配对计算，区分 int/Timestamp 两种日期格式
- **向量化 datetime 转换**：`_datetime_to_int` 用 `pd.to_datetime` 向量化替代 Python for 循环，大数组性能提升 100x+
- **止损/止盈实际执行**：`BacktestEngine` 新增 `_StopCondition` 跟踪，`OrderSimulator` 在每根 bar 检查 SL/TP 并触发平仓信号
- **缠论信号自动桥接**：`BacktestEngine` 新增 `chanlun_level` 参数，自动调用 `ChanlunAnalyser` 并注入策略，两模块正式打通
- **多标的组合回测**：新增 `PortfolioBacktestEngine`，支持多股票共享资金池、均等/自定义分配、资金加权绩效汇总
- **并发扫描**：`SignalScanner` 新增 `workers` 参数，`ProcessPoolExecutor` 并行处理，扫描速度提升 4-8 倍
- **增量扫描缓存**：新增 mtime 检测 + JSON 缓存文件，未修改的 `.day` 文件自动跳过
- **缠论增量更新**：`ChanlunAnalyser` 新增 `append_klines()` 方法，追加新 K 线后去重重新计算，支持实时场景
- **多级别联立增强**：`query_low_level_qs` 新增趋势方向、笔重叠、背驰条件判断字段
- **MyTT 类型存根**：新增 `MyTT.pyi`，50+ 指标函数的类型标注，mypy strict 零错误
- **实时推送框架**：新增 `realtime/` 模块，`EventBus` 发布/订阅 + `RealtimeStrategy` 基类，asyncio 事件驱动架构（API 骨架）
- 380 个测试通过，57.56% 覆盖率，mypy strict 150 文件零错误

### 1.9.5 (2026-06-10)

**OBV 能量潮趋势策略** — 新增 `obv_trend.py` 策略，基于 OBV 与其 30 日均线 MAOBV 的关系判断多空方向。

- 新增 `strategies/obv_trend.py`：OBV 能量潮趋势策略
- 入场条件：OBV 超过 MAOBV 达 2% 缓冲带 且 MAOBV 趋势向上（20 根确认）
- 出场条件：OBV 跌破 MAOBV，资金流向转空即离场
- MAOBV 趋势仅作入场过滤（确认趋势存在），出场只看 OBV/MAOBV 交叉信号
- 可调参数：`maobv_period`（30）、`maobv_lookback`（20）、`obv_buffer`（0.02）

### 1.9.4 (2026-06-10)

**Bug 修复** — 修复 `easy-tdx version` 命令硬编码版本号的问题，改为从 `pyproject.toml` 动态读取。

- 修复 `cmd_admin.py` 中 `version` 命令硬编码 `1.1.0` 的问题
- 版本号现在通过 `importlib.metadata` 从 `pyproject.toml` 动态获取，不再需要手动同步

### 1.9.3 (2026-06-10)

**新增 `run-all` CLI 命令** — 一行命令批量运行 strategies/ 目录下所有策略并排名，与 `run_all_strategies.py` 脚本功能完全一致。

- 新增 `easy-tdx run-all` CLI 命令，支持 `--count`、`--cash`、`--commission`、`--adjust`、`--period`、`--combo`、`--combo-mode`、`--show`、`--strategies-dir` 参数
- 绩效排名 + 综合评分 + 最佳策略交易明细，输出与脚本完全一致
- 支持多因子组合回测（`--combo 2 --combo 3`）和资金曲线图表展示（`--show`）
- 支持自定义策略目录（`--strategies-dir`）
- `run_all_strategies.py` 保持不变，两种方式并存

### 1.9.2 (2026-06-10)

**策略选股扫描器** — 新增 `screen` 命令组，用策略扫描全市场找出触发买入信号的股票，再做历史回测排名。纯离线数据，零网络 IO。

- 新增 `screen scan` CLI 命令：纯离线扫描本地 `.day` 文件，提取策略信号，输出 JSON
- 新增 `screen rank` CLI 命令：读取扫描结果，批量回测并按夏普/回撤等指标排名
- 新增 `src/easy_tdx/screen/` 模块：`SignalScanner`（扫描引擎）、`SignalRanker`（排名引擎）
- 两步走工作流：scan 几秒扫完全市场 → rank 对信号股做历史评估
- 支持 `--universe` 指定范围（all/sh/sz/自定义文件）、`--sort` 排序、`--names` 在线补名称
- 支持管道模式：`easy-tdx screen scan ... | easy-tdx screen rank --from - --table`
- 新增 20 个单元测试（离线，无需网络）

### 1.9.0 (2026-06-10)

**多因子组合回测** — 新增组合回测引擎，支持 2-3 个因子信号叠加，自动遍历所有组合寻找最优搭配。

- 新增 `backtest/combo.py` 模块：`CombinationRunner`、`extract_factor_signals`、`combine_masks`、`FactorSignals`、`ComboResult`
- 信号合并模式：AND（全部同意）、OR（任一同意）、MAJORITY（过半同意）
- CLI 新增 `--combo-strategies` 和 `--combo-mode` 参数，支持指定策略文件组合回测
- `run_all_strategies.py` 新增 `--combo` 和 `--combo-mode` 选项，自动遍历 C(N,2)/C(N,3) 所有组合并排名
- 核心思路：预提取 N 个因子信号（只跑一次）→ 遍历组合合并遮罩（纯 numpy）→ 批量回测排名
- 新增 14 个单元测试（离线，无需网络）
- 修复 MyTT `MFI()` / `CR()` 指标分母为零时的 RuntimeWarning

### 1.8.2 (2026-06-09)

**策略扩充 + 可视化** — 新增 6 个策略（共 15 个）、`--show` 资金曲线图、茅台 demo 截图。

- 新增 `run_all_strategies.py --show` 参数：自动弹出最佳策略资金曲线 vs 股价归一化对比图（matplotlib 双轴图 + 买卖点标记）
- 新增 `zhuoyao_momentum` 策略：ZHUOYAO 多周期共振（SHORT/TREND/MID 三重过滤）
- 新增 `dmi_trend` 策略：DMI/ADX 趋势强度跟踪
- 新增 `cci_breakout` 策略：CCI ±100 区间突破
- 新增 `mfi_volume` 策略：MFI 量价反转（带成交量权重的 RSI）
- 新增 `trix_cross` 策略：TRIX 三重平滑趋势交叉
- 新增 `mtm_momentum` 策略：MTM 动量零线穿越
- 新增 SH600519 贵州茅台 demo 截图

### 1.8.1 (2026-06-09)

**回测增强** — 批量策略对比脚本新增最佳策略完整交易明细输出；版本号统一为单一来源（`pyproject.toml`）。

- `run_all_strategies.py` 排名结束后自动输出最佳策略的绩效概要 + 最近 10 笔交易记录
- 修复 `turtle_breakout` 策略 `TAQ()` 返回 3 值但只解包 2 个的 bug
- 版本号统一：`pyproject.toml` 为唯一来源，`__init__.py` / `cli/__init__.py` / `docs/conf.py` 均动态读取

### 1.8.0 (2026-06-09)

**回测引擎** — 内置向量回测引擎，支持自定义策略回测和全策略批量对比。

- 新增 `backtest` 子包：Strategy 基类、BacktestEngine、OrderSimulator、PortfolioTracker、PerformanceAnalyzer
- 新增 `easy-tdx backtest` CLI 命令，支持 `--strategy-file`、`--cash`、`--commission`、`--adjust` 等参数
- 绩效报告包含 19 项指标：总收益率、年化收益、最大回撤、夏普比率、索提诺、卡玛、胜率、盈亏比等
- 新增 `strategies/` 目录，包含 9 个开箱即用的策略示例（MA/EMA/MACD/BOLL/RSI/KDJ/BIAS/海龟/量价）
- 新增 `run_all_strategies.py` 批量对比脚本，一键跑完全部策略并按收益率和综合评分排名
- 自带策略在 SZ 300308 上 3 年回测：收益率最高 1413%（expma_cross），综合最优 turtle_breakout
- 30+ 离线单元测试覆盖，零网络依赖

### 1.7.1 (2026-06-08)

**Bug 修复** — 修复缠论笔计算在持续下跌/上涨走势中因"分型陷阱"导致近期笔丢失的问题。

- 修复 `find_bis()` 贪心算法在密集交替分型场景下提前终止的 bug
- 根因：当异类型分型 gap=0 时，算法仍用更极端的同类型分型替换 start_fx，导致 right_kline_index 不断前推，后续所有异类型分型 gap 永远为 0
- 新增 `pending_opposite` 保护机制：存在未配对异类型分型时冻结替换，保留 start_fx 较前位置
- 影响范围：持续下跌/上涨中的高价股（如贵州茅台）或分型密度高的股票
- 新增回归测试 `test_fractal_trap_regression`

### 1.7.0 (2026-06-07)

**缠论技术分析模块** — 新增完整的缠论（ChanLun）计算引擎，通过 CLI 和 Python API 提供个股缠论分析。

- 新增 `chanlun` 子包：K线合并、分型识别、笔/线段/中枢/买卖点/背驰计算
- 新增 `easy-tdx chanlun` CLI 命令，支持 JSON/表格输出
- 新增 MACD 指标计算（纯 numpy，无额外依赖）
- 新增多级别联立分析（MultiLevelAnalyser）
- 计算管道：`DataFrame → K线合并 → 分型 → 笔 → 中枢 → 线段 → 买卖点 → 背驰`
- 49 个离线单元测试覆盖，零网络依赖

### 1.6.1 (2026-06-07)

**Bug 修复** — 修复 sync-all/sync-daily 对指数文件误用股票解析器导致垃圾日期的问题。

- 修复 `_fetch_all_daily_bars` 对指数文件（sh00/sh88/sh99, sz39）错误调用 `get_security_bars()` 的问题
- 指数文件现在正确使用 `get_index_bars()`（服务端响应每条记录多 4 字节上涨/下跌家数）
- 新增 `_is_index_code()` 辅助函数，根据市场和代码前缀判断证券类型

### 1.6.0 (2026-06-07)

**离线数据写入同步** — 从服务端获取最新日线数据并写入本地通达信 .day 文件，替代通达信内置下载功能。

- 新增 `offline sync-daily` CLI 命令：同步单只股票日线，自动增量/全量判断，支持分页获取完整历史
- 新增 `offline sync-all` CLI 命令：一键扫描沪深全市场 .day 文件并同步
- 新增 `write_daily.py` 模块：日线编解码（`encode_daily_bar`）、追加写入（`append_daily_bars`）、末尾日期检测
- 新增 `write_ex_daily.py` 模块：扩展市场日线写入（期货/港股，价格 float32）
- 新增 `write_min_bar.py` 模块：分钟线写入（.5/.lc1/.lc5 格式）
- 写入自动跳过重复日期，空文件自动全量下载，已有数据只做增量追加
- 50 个新增单元测试覆盖编解码 round-trip、追加去重、边界条件

### 1.5.0 (2026-06-02)

**离线数据 CLI 命令** — 新增 `offline` 命令组，无需网络即可通过 CLI 读取本地通达信数据文件。

- 新增 `offline home`：检测通达信安装目录
- 新增 `offline daily`：A 股日线数据（.day 文件）
- 新增 `offline min`：分钟线数据（.5/.lc1/.lc5 文件，`--type` 指定格式）
- 新增 `offline ex-files`：列出扩展市场可用日线文件
- 新增 `offline ex-daily`：扩展市场日线数据（期货/港股/外盘）
- 新增 `offline gbbq`：股本变迁数据
- 新增 `offline financial`：历史财务数据
- 新增 `offline blocks`：自定义板块数据

### 1.4.3 (2026-05-28)

**30日乖离率信号指标** — 新增 BIAS_SIGNAL 指标，在标准乖离率基础上叠加短/长信号线，通过三者位置关系判断趋势方向和转折点。源自通达信经典指标。

- 新增 `BIAS_SIGNAL` 指标：输出 BS_X/BS_SMA/BS_LMA 三条线
- CLI: `easy-tdx indicator BIAS_SIGNAL -m SH -c 600519 --table`
- Python API: `indicators=["BIAS_SIGNAL"]`
- 详见 [30日乖离率信号指标详解](docs/indicator-bias-signal.md)

### 1.4.2 (2026-05-28)

修复 1.4.1 发布遗漏：MyTT.py 中 ZHUOYAO 函数定义未包含在 1.4.1 的 PyPI 包中。

### 1.4.1 (2026-05-28)

**捉妖大师指标** — 新增 ZHUOYAO 多周期涨幅共振指标，通过 20/60/120 日涨幅及指数平滑判断短中长线趋势是否同向，用于筛选趋势刚启动的强势股。

- 新增 `ZHUOYAO` 指标：输出 ZY_LONG/ZY_MID/ZY_SHORT/ZY_TREND 四条线
- CLI: `easy-tdx indicator ZHUOYAO -m SH -c 600519 --table`
- Python API: `indicators=["ZHUOYAO"]`
- 详见 [捉妖大师指标详解](docs/indicator-zhuoyao.md)

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

## 免责声明

本工具仅供学习和技术研究使用，不构成任何投资建议。使用者应自行承担投资决策的全部风险。
作者不对因使用本工具导致的任何直接或间接损失负责。
