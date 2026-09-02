"""ZIG 右侧突破回补策略（Re-entry on Breakout + 硬止损保护）。

交易逻辑
--------
1. **空仓**：ZIG 向上启动（底部波谷确认）→ 全仓买入建仓，挂硬止损（默认 3%）。
2. **持仓**：ZIG 见顶回落 → 全仓卖出，并记录 N 日最高价为 breakout_level。
3. **空仓等待回补**：收盘价突破 breakout_level × (1 + confirm_pct/100)
   → 右侧突破确认，洗盘结束主升确立，全仓买入回补（同样带硬止损）。
4. **风控保护**：买入后未见顶但跌破止损线，由引擎自动触发止损平仓，
   对冲 ZIG 波谷确认的前视偏差（ZIG 是未来函数，拐点回溯标出）。

注意：与内置注册表中的 ``zig_breakout``（``easy_tdx.backtest.strategies``）
同一套逻辑；本文件供 ``--strategy-file`` 离线扫描（``easy-tdx screen scan``）
使用，参数硬编码为默认档。

用法::

    easy-tdx backtest SZ 300223 --strategy-file strategies/zig_breakout.py --table
    easy-tdx screen scan --strategy strategies/zig_breakout.py --universe core
"""

from easy_tdx.backtest import Strategy
from easy_tdx.MyTT import HHV, ZIG


class ZigBreakoutStrategy(Strategy):
    """ZIG 右侧突破回补策略（含硬止损保护）。"""

    def __init__(
        self,
        zig_delta: float = 10.0,
        confirm_pct: float = 2.0,
        hhv_period: int = 20,
        stop_loss_pct: float = 3.0,
    ) -> None:
        super().__init__()
        self.zig_delta = zig_delta
        self.confirm_pct = confirm_pct
        self.hhv_period = hhv_period
        self.stop_loss_pct = stop_loss_pct

    def init(self) -> None:
        self.zig = self.I(ZIG, self.data.close, self.zig_delta)
        self.hhv = self.I(HHV, self.data.high, self.hhv_period)
        self._breakout_level: float = 0.0

    def next(self) -> None:
        i = self._bar_index
        if i == 0:
            return

        cur_close = float(self.data.close[0])
        cur_zig = float(self.zig[i])
        prev_zig = float(self.zig[i - 1])
        cur_pos = self.position["size"]

        # 持仓：ZIG 见顶 → 全仓卖出，记录突破位
        if cur_pos > 0 and cur_zig < prev_zig:
            self._breakout_level = float(self.hhv[i])
            self.sell(size=0)
            return

        # 空仓：两种买入路径（均带硬止损）
        if cur_pos == 0:
            # 路径 1：ZIG 向上启动（底部波谷确认）→ 初始建仓
            if cur_zig > prev_zig:
                self._breakout_level = 0.0
                self._buy_with_stop()
                return

            # 路径 2：右侧突破前高 → 回补建仓（洗盘结束、主升确立）
            if self._breakout_level > 0:
                threshold = self._breakout_level * (1.0 + self.confirm_pct / 100.0)
                if cur_close >= threshold:
                    self._breakout_level = 0.0
                    self._buy_with_stop()

    def _buy_with_stop(self) -> None:
        pct = self.stop_loss_pct / 100.0
        if pct > 0:
            self.buy(size=0, stop_loss_pct=pct)
        else:
            self.buy(size=0)
