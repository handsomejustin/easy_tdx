# 策略示例集

可直接用于 `easy-tdx backtest --strategy-file` 的策略文件。

## 用法

```bash
# 在项目根目录执行
easy-tdx backtest SZ 000001 --strategy-file strategies/ma_cross.py --table
easy-tdx backtest SH 600519 --strategy-file strategies/macd_cross.py --cash 50000 --table
```

## 策略列表

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
| `obv_trend.py` | OBV 能量潮趋势 | 量价趋势 | 资金持续流入的上升趋势 |

## 编写自定义策略

复制任意一个策略文件作为模板，继承 `Strategy` 基类：

```python
from easy_tdx.backtest import Strategy, crossover
from easy_tdx import MyTT


class MyStrategy(Strategy):
    def init(self):
        # 注册指标
        self.ma = self.I(MyTT.MA, self.data.close, 10)

    def next(self):
        # 每根 K 线调用一次
        if self.data.close[0] > self.ma[self._bar_index]:
            self.buy(size=0)     # size=0 表示全仓
        elif self.position["size"] > 0:
            self.sell(size=0)    # size=0 表示清仓
```

完整 API 参考：[docs/backtest_usage.md](../docs/backtest_usage.md)
