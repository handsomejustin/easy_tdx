"""订单撮合模拟器。

将策略信号转换为成交记录，支持多种执行模式、仓位管理和拒绝策略。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from easy_tdx.backtest.types import Signal, Trade

if TYPE_CHECKING:
    from easy_tdx.backtest.slippage import SlippageModel


@dataclass
class OrderSimulator:
    """订单撮合模拟器。

    将策略信号（Signal）转换为成交记录（Trade），支持多种执行模式、
    仓位管理和拒绝策略。

    Attributes:
        df: K线数据 DataFrame
        execution: 成交价规则 (next_open/next_close)
        position_mode: 仓位模式 (full/fixed/percent)
        reject_policy: 拒绝策略 (reduce/skip)
        commission: 佣金费率
        min_commission: 最低佣金
        stamp_tax: 印花税率（仅卖出）
        slippage: 滑点（每股）
    """

    df: pd.DataFrame
    execution: str = "next_open"
    position_mode: str = "full"
    reject_policy: str = "reduce"
    commission: float = 0.0003
    min_commission: float = 5.0
    stamp_tax: float = 0.001
    slippage: float = 0.0
    slippage_model: SlippageModel | None = None

    def __post_init__(self) -> None:
        # datetime → 行号查找表（惰性构建一次）。v1.28 之前每个信号都对整列
        # datetime 做 strftime 扫描（O(信号数×bar 数)，占全流程 ~85% 墙钟），
        # 网格寻优每点都跑一遍 simulate，是实测最大瓶颈。
        self._dt_lookup: dict[int, int] | None = None

    def simulate(
        self,
        signals: list[Signal],
        cash: float,
        position: float,
        position_mode: str | None = None,
    ) -> list[Trade]:
        """模拟订单撮合过程。

        Args:
            signals: 交易信号列表
            cash: 初始现金
            position: 初始持仓（股数）
            position_mode: 仓位模式（覆盖初始化参数）

        Returns:
            成交记录列表
        """
        if position_mode is None:
            position_mode = self.position_mode

        trades: list[Trade] = []
        current_cash = cash
        current_position = position

        for signal in signals:
            # 找到信号对应的 K 线
            bar_idx = self._find_bar_index(signal.datetime)
            if bar_idx is None:
                continue

            # 信号成交时点分三类：
            #  - source="stop"（止损/止盈触发）：延迟到下一根开盘成交，消除"用当根
            #    intrabar 触发价精确成交"的前视偏差；若下一根跳空，取对持仓者更不利的价。
            #  - price is not None 且非 stop（限价单）：在信号 bar 当根以信号价成交。
            #  - 其他（市价策略信号）：按 execution 配置（默认 next_open）在下一根成交。
            if signal.source == "stop":
                exec_idx_raw = self._resolve_exec_index(bar_idx)
                # 下一根不可用时（信号在最后一根 bar 触发），回退到当根收盘成交，
                # 避免止损信号被静默丢弃（审计 #4：不能因延迟成交而漏平仓）。
                next_price: float
                if exec_idx_raw is None or exec_idx_raw >= len(self.df):
                    exec_idx = bar_idx
                    row = self.df.iloc[bar_idx] if bar_idx < len(self.df) else None
                    if row is None:
                        continue
                    next_price = float(row["close"])
                else:
                    exec_idx = exec_idx_raw
                    price_raw = self._get_price(exec_idx, signal.direction)
                    if price_raw is None:
                        continue
                    next_price = price_raw
                # 跳空保护：对 SELL（平仓），若下一根开盘比触发价更不利（更低），
                # 取实际开盘价；否则按触发价（止损已生效）。
                trigger = signal.price if signal.price is not None else next_price
                if signal.direction == "SELL":
                    price: float = min(next_price, trigger)
                else:
                    price = max(next_price, trigger)
            elif signal.price is not None:
                # 限价单：在信号所在 bar 以信号价格成交
                exec_idx = bar_idx
                price = signal.price
            else:
                # 确定成交的 K 线索引
                exec_idx_raw = self._resolve_exec_index(bar_idx)
                if exec_idx_raw is None or exec_idx_raw >= len(self.df):
                    continue
                exec_idx = exec_idx_raw

                # 获取成交价
                price_raw = self._get_price(exec_idx, signal.direction)
                if price_raw is None:
                    continue
                price = price_raw

            # 执行交易
            if signal.direction == "BUY":
                trade = self._execute_buy(
                    signal=signal,
                    bar_idx=bar_idx,
                    exec_idx=exec_idx,
                    price=price,
                    cash=current_cash,
                    position=current_position,
                    position_mode=position_mode,
                )
                if trade is not None:
                    trades.append(trade)
                    if not trade.rejected:
                        current_cash -= trade.size * trade.price + trade.commission + trade.slippage
                        current_position += trade.size

            elif signal.direction == "SELL":
                trade = self._execute_sell(
                    signal=signal,
                    bar_idx=bar_idx,
                    exec_idx=exec_idx,
                    price=price,
                    cash=current_cash,
                    position=current_position,
                    position_mode=position_mode,
                )
                if trade is not None:
                    trades.append(trade)
                    if not trade.rejected:
                        current_cash += trade.size * trade.price - trade.commission - trade.slippage
                        current_position -= trade.size

        return trades

    def _find_bar_index(self, datetime_val: int) -> int | None:
        """查找 datetime 对应的 K 线索引。

        Args:
            datetime_val: 信号时间（int 格式 YYYYMMDD）

        Returns:
            K 线索引，未找到返回 None

        性能（v1.28）：查找表在首次调用时构建一次（O(bar 数)），此后每个
        信号 O(1) 查询；语义与逐信号全列扫描完全一致——重复日期取首个匹配
        （等价于原来的 ``mask.argmax()``），未命中返回 None。
        """
        if self._dt_lookup is None:
            self._dt_lookup = self._build_dt_lookup()
        return self._dt_lookup.get(int(datetime_val))

    def _build_dt_lookup(self) -> dict[int, int]:
        """构建 datetime → 行号查找表（重复日期保留首个出现）。

        与历史行为的对应关系：

        - datetime64 列：向量化转 YYYYMMDD int 后建表（原来每个信号都
          ``strftime`` 全列扫描一遍，是 O(信号数×bar 数) 的热点）；
        - 数值列（int/float）：整数值等价于原 ``dt_col == datetime_val`` 的
          直接比较（非整数 float 不会命中，与原来一致）；
        - 其他列（object 等）：原来直接比较恒不命中、返回 None——这里同样
          产出空表（保持行为不变，包括 object-Timestamp 列不匹配的既有行为）。
        """
        from easy_tdx.backtest.strategy import _datetime_to_int

        dt_col = self.df["datetime"]
        lookup: dict[int, int] = {}

        if pd.api.types.is_datetime64_any_dtype(dt_col):
            ints = _datetime_to_int(dt_col.to_numpy())
            for i, v in enumerate(ints):
                if v == v:  # NaT → NaN，跳过（原 strftime 同样不产出该行）
                    lookup.setdefault(int(v), i)
            return lookup

        arr = dt_col.to_numpy()
        if arr.dtype.kind in "iuf":
            for i, v in enumerate(arr):
                # 浮点列只有整数值（20240104.0）才可能与 int 信号相等，
                # 与原 == 比较语义一致
                if float(v).is_integer():
                    lookup.setdefault(int(v), i)
            return lookup

        # object / 字符串等：原实现 (dt_col == int) 恒为 False → 恒 None
        return lookup

    def _resolve_exec_index(self, bar_idx: int) -> int | None:
        """根据执行模式确定成交的 K 线索引。

        开盘价 / 收盘价模式均在信号后一根 K 线成交（next_open 取次根开盘价，
        next_close 取次根收盘价），避免使用信号当根的未完成/未来数据。

        Args:
            bar_idx: 信号对应的 K 线索引

        Returns:
            成交 K 线索引
        """
        return bar_idx + 1

    def _get_price(self, exec_idx: int, direction: str) -> float | None:
        """根据执行模式获取成交价。

        Args:
            exec_idx: 成交 K 线索引
            direction: 交易方向（仅作保留，当前两种模式均不依赖方向）

        Returns:
            成交价格
        """
        if exec_idx >= len(self.df):
            return None

        row = self.df.iloc[exec_idx]

        if self.execution == "next_open":
            return float(row["open"])
        elif self.execution == "next_close":
            return float(row["close"])
        else:
            return None

    def _calculate_buy_size(
        self,
        signal_size: float,
        price: float,
        cash: float,
        position_mode: str,
    ) -> float:
        """计算买入数量。

        Args:
            signal_size: 信号指定的数量
            price: 成交价格
            cash: 可用现金
            position_mode: 仓位模式

        Returns:
            买入数量（股）
        """
        if position_mode == "full" or signal_size == 0:
            # 全仓：计算可用现金能买多少（100股整手）
            # 先计算最大股数，然后向下取整到100的倍数
            max_cost_per_share = price * (1 + self.commission) + self.slippage
            max_shares_raw = cash / max_cost_per_share
            max_shares = int(max_shares_raw / 100) * 100
            return float(max_shares)
        elif position_mode == "fixed":
            # 固定股数
            return signal_size
        elif position_mode == "percent":
            # 总资产的百分比
            total_value = cash  # 简化：假设现金=总资产
            target_value = total_value * signal_size
            max_shares = int(target_value / price / 100) * 100
            return float(max_shares)
        else:
            return signal_size

    def _calculate_sell_size(
        self,
        signal_size: float,
        position: float,
        position_mode: str,
    ) -> float:
        """计算卖出数量。

        Args:
            signal_size: 信号指定的数量
            position: 当前持仓
            position_mode: 仓位模式

        Returns:
            卖出数量（股）
        """
        if position_mode == "full" or signal_size == 0:
            # 全部卖出
            return position
        elif position_mode == "fixed":
            # 固定股数
            return signal_size
        elif position_mode == "percent":
            # 持仓的百分比
            return position * signal_size
        else:
            return signal_size

    def _calculate_commission(self, size: float, price: float, is_sell: bool = False) -> float:
        """计算手续费。

        Args:
            size: 成交数量
            price: 成交价格
            is_sell: 是否为卖出

        Returns:
            手续费总额
        """
        # 佣金
        commission = max(size * price * self.commission, self.min_commission)

        # 印花税（仅卖出）
        if is_sell:
            stamp = size * price * self.stamp_tax
            commission += stamp

        return commission

    def _compute_slippage(self, size: float, price: float, is_sell: bool) -> float:
        """计算滑点成本。"""
        if self.slippage_model is not None:
            volume = self._get_current_volume()
            volatility = self._estimate_volatility()
            return self.slippage_model.compute(
                price=price,
                size=size,
                volume=volume,
                volatility=volatility,
                direction="SELL" if is_sell else "BUY",
            )
        return size * self.slippage

    def _get_current_volume(self) -> float:
        """获取最后一根K线的成交量，兼容 vol/volume 列名。"""
        if len(self.df) == 0:
            return 0.0
        for col in ("vol", "volume"):
            if col in self.df.columns:
                return float(self.df[col].iloc[-1])
        return 0.0

    def _estimate_volatility(self) -> float:
        """从收盘价估计年化波动率。"""
        if "close" not in self.df.columns or len(self.df) < 2:
            return 0.0
        close = self.df["close"].to_numpy()
        returns = np.diff(close) / close[:-1]
        if len(returns) < 2:
            return 0.0
        daily_vol = float(np.std(returns))
        return float(daily_vol * np.sqrt(252))

    def _execute_buy(
        self,
        signal: Signal,
        bar_idx: int,
        exec_idx: int,
        price: float,
        cash: float,
        position: float,
        position_mode: str,
    ) -> Trade | None:
        """执行买入。

        Args:
            signal: 交易信号
            bar_idx: 信号 K 线索引
            exec_idx: 成交 K 线索引
            price: 成交价格
            cash: 可用现金
            position: 当前持仓
            position_mode: 仓位模式

        Returns:
            成交记录
        """
        # 保存原始信号数量
        original_size = signal.size

        # 计算买入数量
        size = self._calculate_buy_size(signal.size, price, cash, position_mode)

        if size <= 0:
            # 资金不足或计算结果为0
            if self.reject_policy == "skip":
                # 对于 percent 模式，original_size 是百分比（如 0.5），不是股数
                # 对于 fixed/full 模式，original_size 就是股数
                display_size = original_size if position_mode == "fixed" else 100
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="BUY",
                    size=display_size,
                    price=price,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    rejected=True,
                )
            return None

        # 计算费用
        commission = self._calculate_commission(size, price, is_sell=False)
        slippage = self._compute_slippage(size, price, is_sell=False)

        # 检查资金是否足够
        total_cost = size * price + commission + slippage
        if total_cost > cash:
            if self.reject_policy == "skip":
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="BUY",
                    size=original_size,
                    price=price,
                    commission=commission,
                    slippage=slippage,
                    pnl=0.0,
                    rejected=True,
                )
            elif self.reject_policy == "reduce":
                # reduce 模式：重新计算可买数量
                available_cash = cash - self.min_commission - slippage
                if available_cash > price:
                    reduced_size = int(available_cash / price / 100) * 100
                    if reduced_size > 0:
                        commission = self._calculate_commission(reduced_size, price, is_sell=False)
                        slippage = self._compute_slippage(reduced_size, price, is_sell=False)
                        return Trade(
                            datetime=self.df.iloc[exec_idx]["datetime"],
                            direction="BUY",
                            size=reduced_size,
                            price=price,
                            commission=commission,
                            slippage=slippage,
                            pnl=0.0,
                            rejected=False,
                        )
                # 无法买任何数量
                return None

        return Trade(
            datetime=self.df.iloc[exec_idx]["datetime"],
            direction="BUY",
            size=size,
            price=price,
            commission=commission,
            slippage=slippage,
            pnl=0.0,
            rejected=False,
        )

    def _execute_sell(
        self,
        signal: Signal,
        bar_idx: int,
        exec_idx: int,
        price: float,
        cash: float,
        position: float,
        position_mode: str,
    ) -> Trade | None:
        """执行卖出。

        Args:
            signal: 交易信号
            bar_idx: 信号 K 线索引
            exec_idx: 成交 K 线索引
            price: 成交价格
            cash: 可用现金
            position: 当前持仓
            position_mode: 仓位模式

        Returns:
            成交记录
        """
        # 计算卖出数量
        size = self._calculate_sell_size(signal.size, position, position_mode)

        if size <= 0:
            # 无持仓
            if self.reject_policy == "skip":
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="SELL",
                    size=0,
                    price=price,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    rejected=True,
                )
            return None

        # 检查持仓是否足够
        if size > position:
            if self.reject_policy == "skip":
                return Trade(
                    datetime=self.df.iloc[exec_idx]["datetime"],
                    direction="SELL",
                    size=size,
                    price=price,
                    commission=0.0,
                    slippage=0.0,
                    pnl=0.0,
                    rejected=True,
                )
            # reduce 模式：减少到实际持仓
            size = position

        # 计算费用
        commission = self._calculate_commission(size, price, is_sell=True)
        slippage = self._compute_slippage(size, price, is_sell=True)

        return Trade(
            datetime=self.df.iloc[exec_idx]["datetime"],
            direction="SELL",
            size=size,
            price=price,
            commission=commission,
            slippage=slippage,
            pnl=0.0,
            rejected=False,
        )
