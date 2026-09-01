"""回测绩效分析器。

计算资金曲线和交易记录的各项绩效指标。
"""

from __future__ import annotations

import datetime as _dt
from collections import deque
from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
import pandas as pd

if TYPE_CHECKING:
    NDArray = npt.NDArray[np.float64]
else:
    NDArray = np.ndarray


class PerformanceAnalyzer:
    """绩效分析器。

    从资金曲线和交易记录计算 19 项绩效指标。

    Attributes:
        ANNUAL_DAYS: 年化交易日数（默认 252）
        RISK_FREE_RATE: 无风险利率（默认 3%）
    """

    ANNUAL_DAYS = 252
    RISK_FREE_RATE = 0.03

    def __init__(
        self,
        equity_curve: pd.DataFrame,
        trades: pd.DataFrame,
        risk_free_rate: float = 0.03,
    ) -> None:
        """初始化分析器。

        Args:
            equity_curve: 资金曲线 DataFrame，必须包含 total 和 drawdown 列
            trades: 交易记录 DataFrame，必须包含 direction, pnl, rejected 列
            risk_free_rate: 无风险利率（默认 3%）
        """
        self._equity_curve = equity_curve
        self._trades = trades
        self._risk_free_rate = risk_free_rate
        # 数据异常诊断（资金曲线不足/恒定时填充），供上层透出给用户
        self.diagnostic: str | None = None

    def compute(self) -> dict[str, float]:
        """计算绩效指标。

        Returns:
            包含 19 项指标的字典：
            - total_return: 总收益率
            - annual_return: 年化收益率
            - max_drawdown: 最大回撤
            - max_dd_duration: 最大回撤持续时间（bar 数）
            - sharpe: 夏普比率
            - sortino: 索提诺比率
            - calmar: 卡玛比率
            - total_trades: 总交易次数
            - win_trades: 盈利交易次数
            - lose_trades: 亏损交易次数
            - rejected_trades: 被拒绝的交易次数
            - win_rate: 胜率
            - profit_factor: 盈亏比
            - avg_win: 平均盈利
            - avg_loss: 平均亏损
            - max_win: 最大盈利
            - max_loss: 最大亏损
            - avg_holding_days: 平均持仓天数（FIFO 配对、按 size 加权，日历日口径）
            - volatility: 年化波动率
        """
        # 边界检查
        if len(self._equity_curve) < 2:
            self.diagnostic = "资金曲线不足 2 根，无法计算绩效（数据可能为空或不全）"
            return self._empty_metrics()

        total = self._equity_curve["total"].to_numpy()
        drawdown = self._equity_curve["drawdown"].to_numpy()

        # 计算日收益率（除零保护：前值为 0 的位置记为 NaN 后一并过滤）
        safe_prev = np.where(total[:-1] != 0, total[:-1], np.nan)
        daily_ret = np.diff(total) / safe_prev
        # 同时过滤 NaN 和 inf（前值为 0 会产生 inf/nan）
        daily_ret = daily_ret[np.isfinite(daily_ret)]

        # 日收益率数量太少时返回空指标
        if len(daily_ret) < 2:
            self.diagnostic = (
                "有效日收益率不足 2 个，绩效全 0（资金曲线可能恒定，常因数据不全或"
                "交易未生效；建议 easy-tdx ping 切换服务器后重试）"
            )
            return self._empty_metrics()

        # 1. 总收益率（首根净值为 0 时无法定义，记为 0.0）
        total_return = (total[-1] / total[0]) - 1 if total[0] != 0 else 0.0

        # 2. 年化收益率
        n = len(daily_ret)
        annual_return = (1 + total_return) ** (self.ANNUAL_DAYS / n) - 1

        # 3. 最大回撤（从峰值的最大跌幅百分比，0~1 之间）
        drawdown_pct = self._equity_curve["drawdown_pct"].to_numpy()
        max_drawdown = float(np.max(drawdown_pct))

        # 4. 最大回撤持续时间
        max_dd_duration = self._compute_max_dd_duration(total, drawdown)

        # 5. 夏普比率
        rf_daily = self._risk_free_rate / self.ANNUAL_DAYS
        excess_ret = daily_ret - rf_daily
        sharpe = (
            np.mean(excess_ret) / np.std(daily_ret) * np.sqrt(self.ANNUAL_DAYS)
            if np.std(daily_ret) != 0
            else 0
        )

        # 6. 索提诺比率（分母只用负收益标准差）
        neg_ret = excess_ret[excess_ret < 0]
        if len(neg_ret) > 0 and np.std(neg_ret) != 0:
            sortino = np.mean(excess_ret) / np.std(neg_ret) * np.sqrt(self.ANNUAL_DAYS)
        elif len(neg_ret) == 0 and np.mean(excess_ret) > 0:
            # 没有负收益时，返回一个很大的值表示表现优异
            sortino = 999.0
        else:
            sortino = 0.0

        # 7. 卡玛比率
        # 使用小阈值避免除以极小值
        if max_drawdown > 1e-10:
            calmar = annual_return / max_drawdown
        elif annual_return > 0:
            # 无回撤且有正收益时，返回一个很大的值
            calmar = 999.0
        else:
            calmar = 0.0

        # 交易统计
        sell_trades = self._trades[self._trades["direction"] == "SELL"]
        win_trades_mask = sell_trades["pnl"] > 0
        lose_trades_mask = sell_trades["pnl"] <= 0

        # 单笔收益率 = pnl / cost_basis。cost_basis 由 engine._compute_pnls 填入
        # （SELL 对应的移动加权平均成本 × 卖出数量）。无 cost_basis 列或为 0 时
        # 收益率记 NaN，在后续统计里被过滤。
        # 显式转 float64：trades 列可能是 int/object dtype，导致 np.isfinite 失败。
        if "cost_basis" in sell_trades.columns:
            pnl_arr = sell_trades["pnl"].to_numpy(dtype=np.float64)
            cost_arr = sell_trades["cost_basis"].to_numpy(dtype=np.float64)
            with np.errstate(divide="ignore", invalid="ignore"):
                trade_returns = np.where(cost_arr > 0, pnl_arr / cost_arr, np.nan)
        else:
            trade_returns = np.full(len(sell_trades), np.nan)

        # 8. 总交易次数
        total_trades = len(sell_trades)

        # 9. 盈利交易次数
        win_count = np.sum(win_trades_mask)

        # 10. 亏损交易次数
        lose_count = np.sum(lose_trades_mask)

        # 11. 被拒绝的交易次数
        rejected_trades = self._trades["rejected"].sum()

        # 12. 胜率
        win_rate = win_count / (win_count + lose_count) if (win_count + lose_count) > 0 else 0

        # 13. 盈亏比
        win_pnl = sell_trades.loc[win_trades_mask, "pnl"]
        lose_pnl = sell_trades.loc[lose_trades_mask, "pnl"]

        if len(win_pnl) > 0 and len(lose_pnl) > 0:
            profit_factor = win_pnl.sum() / abs(lose_pnl.sum())
            # 限制 inf
            if np.isinf(profit_factor):
                profit_factor = 999.0
        elif len(win_pnl) > 0 and len(lose_pnl) == 0:
            # 全部盈利、无亏损交易：盈亏比理论上为 +∞，统一记为 999.0
            # （与 calmar 在无回撤正收益时的约定一致），避免显示 0.000 造成误解
            profit_factor = 999.0
        else:
            profit_factor = 0.0

        # 14. 平均盈利（单笔收益率口径）
        win_returns = trade_returns[win_trades_mask.to_numpy()]
        win_returns = win_returns[np.isfinite(win_returns)]
        avg_win = float(np.mean(win_returns)) if len(win_returns) > 0 else 0.0

        # 15. 平均亏损（单笔收益率口径）
        lose_returns = trade_returns[lose_trades_mask.to_numpy()]
        lose_returns = lose_returns[np.isfinite(lose_returns)]
        avg_loss = float(np.mean(lose_returns)) if len(lose_returns) > 0 else 0.0

        # 16. 最大盈利（单笔收益率口径）
        max_win = float(np.max(win_returns)) if len(win_returns) > 0 else 0.0

        # 17. 最大亏损（单笔收益率口径）
        max_loss = float(np.min(lose_returns)) if len(lose_returns) > 0 else 0.0

        # 18. 平均持仓天数（FIFO 配对计算）
        avg_holding_days = self._compute_avg_holding_days()

        # 19. 年化波动率
        volatility = np.std(daily_ret) * np.sqrt(self.ANNUAL_DAYS)

        return {
            "total_return": total_return,
            "annual_return": annual_return,
            "max_drawdown": max_drawdown,
            "max_dd_duration": max_dd_duration,
            "sharpe": sharpe,
            "sortino": sortino,
            "calmar": calmar,
            "total_trades": total_trades,
            "win_trades": win_count,
            "lose_trades": lose_count,
            "rejected_trades": rejected_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "max_win": max_win,
            "max_loss": max_loss,
            "avg_holding_days": avg_holding_days,
            "volatility": volatility,
            # 别名键（兼容常见叫法，避免 .get('sharpe_ratio') 等误用返回 0）
            "sharpe_ratio": sharpe,
            "start_cash": float(total[0]),
            "end_value": float(total[-1]),
        }

    def _compute_avg_holding_days(self) -> float:
        """计算平均持仓天数（FIFO 配对）。

        遍历非 rejected 的交易记录，使用 FIFO 队列配对买入和卖出，
        按 size 加权计算平均持仓天数。

        注意：持仓天数按真实日历日计算（解析 ``YYYYMMDD`` 为 ``date`` 后相减），
        而非 YYYYMMDD 整数差——后者在跨月时会放大（如 20240201-20240131=70）。

        Returns:
            加权平均持仓天数，无完整配对时返回 0.0
        """
        if "datetime" not in self._trades.columns:
            return 0.0

        # 只处理非 rejected 的交易
        valid = self._trades[~self._trades["rejected"]]
        if len(valid) == 0:
            return 0.0

        buy_queue: deque[tuple[_dt.date, float]] = deque()  # (date, size)
        total_days = 0.0
        total_size = 0.0

        def to_date(raw_dt: object) -> _dt.date | None:
            """把 datetime 列的值（int YYYYMMDD 或 pd.Timestamp）转为 date。

            无法解析时返回 None（该行将被跳过，不参与配对）。
            """
            if isinstance(raw_dt, pd.Timestamp):
                # 运行时确为 date
                d: _dt.date = raw_dt.date()
                return d
            try:
                # raw_dt 可能是 int/object dtype 标量；统一经 str 转 int
                n = int(str(raw_dt))
            except (TypeError, ValueError):
                return None
            # YYYYMMDD 整数 → 真实日期
            try:
                return _dt.datetime.strptime(str(n), "%Y%m%d").date()
            except ValueError:
                return None

        for _, row in valid.iterrows():
            d = to_date(row["datetime"])
            if d is None:
                continue  # 无法解析日期的行不参与持仓天数计算
            direction = row["direction"]
            size = float(row["size"]) if "size" in valid.columns else 100.0

            if direction == "BUY":
                buy_queue.append((d, size))
            elif direction == "SELL" and buy_queue:
                remaining = size
                while remaining > 0 and buy_queue:
                    buy_d, buy_size = buy_queue[0]
                    # 消费该笔 BUY 的部分或全部
                    consumed = min(remaining, buy_size)
                    holding_days = (d - buy_d).days
                    total_days += holding_days * consumed
                    total_size += consumed
                    remaining -= consumed
                    buy_size -= consumed
                    if buy_size <= 0:
                        buy_queue.popleft()
                    else:
                        buy_queue[0] = (buy_d, buy_size)

        if total_size == 0:
            return 0.0
        return total_days / total_size

    def _compute_max_dd_duration(self, total: NDArray, drawdown: NDArray) -> int:
        """计算最大回撤持续时间。

        找到最大回撤点，然后计算从回撤前的高点到该点的 bar 数。

        Args:
            total: 总权益数组
            drawdown: 回撤数组

        Returns:
            最大回撤持续时间（bar 数）
        """
        if len(drawdown) == 0:
            return 0

        max_dd_idx: int = int(np.argmax(drawdown))
        max_dd_value = drawdown[max_dd_idx]

        # 如果没有回撤，返回 0
        if max_dd_value == 0:
            return 0

        # 找到回撤前的高点
        peak_idx: int = max_dd_idx
        for i in range(max_dd_idx - 1, -1, -1):
            if total[i] > total[max_dd_idx]:
                peak_idx = i
                break

        return int(max_dd_idx - peak_idx)

    def _empty_metrics(self) -> dict[str, float]:
        """返回全零指标字典（数据不足时的默认返回值）。

        数据异常的诊断说明通过 ``self.diagnostic`` 暴露，由上层（CLI/引擎）
        读取后透出给用户，不污染数值型 performance 字典（保持
        ``dict[str, float]`` 类型，避免下游算术/比较类型报错）。

        Returns:
            全零的绩效指标字典（含别名键 sharpe_ratio/start_cash/end_value）。
        """
        return {
            "total_return": 0.0,
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "max_dd_duration": 0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "calmar": 0.0,
            "total_trades": 0,
            "win_trades": 0,
            "lose_trades": 0,
            "rejected_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_win": 0.0,
            "avg_loss": 0.0,
            "max_win": 0.0,
            "max_loss": 0.0,
            "avg_holding_days": 0.0,
            "volatility": 0.0,
            "sharpe_ratio": 0.0,
            "start_cash": 0.0,
            "end_value": 0.0,
        }
