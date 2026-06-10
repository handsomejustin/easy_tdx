"""信号扫描引擎 — 纯离线，从本地 .day 文件提取策略信号。

核心流程：
1. 扫描 vipdoc/{sh,sz}/lday/*.day 获取文件列表
2. 按 universe 过滤（all/sh/sz/文件列表）
3. 过滤掉非 A 股（指数、基金、债券）
4. 每个文件：read_daily_bars() → DataFrame → extract_factor_signals() → 检查 buy_mask[-1]
5. 输出触发信号的股票列表
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from easy_tdx.backtest.combo import extract_factor_signals
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.offline.daily_bar import _detect_security_type, read_daily_bars
from easy_tdx.offline.paths import resolve_vipdoc

# A 股类型白名单
_A_STOCK_TYPES = frozenset(
    {
        "SH_A_STOCK",
        "SZ_A_STOCK",
    }
)


@dataclass
class ScanResult:
    """单只股票的扫描结果。

    Attributes:
        code: 6 位股票代码
        market: 市场（SZ/SH）
        signal_date: 信号日期（YYYYMMDD 整数）
        last_close: 最后收盘价
    """

    code: str
    market: str
    signal_date: int
    last_close: float


class SignalScanner:
    """策略信号扫描器。

    用法::

        scanner = SignalScanner(
            strategy_cls=RSIStrategy,
            vipdoc_path="C:\\new_jyplug\\vipdoc",
        )
        results = scanner.scan(universe="all")
        for r in results:
            print(f"{r.market}{r.code} 触发买入信号 @ {r.signal_date}")
    """

    def __init__(
        self,
        strategy_cls: type[Strategy],
        vipdoc_path: str | Path | None = None,
        cash: float = 100_000.0,
        commission: float = 0.0003,
    ) -> None:
        """初始化扫描器。

        Args:
            strategy_cls: 策略类（Strategy 子类）
            vipdoc_path: vipdoc 目录路径，None 则自动检测
            cash: 初始资金（影响全仓信号判断）
            commission: 佣金率
        """
        self._strategy_cls = strategy_cls
        self._vipdoc = resolve_vipdoc(vipdoc_path)
        self._cash = cash
        self._commission = commission

    def scan(
        self,
        universe: str = "all",
        progress_callback: Any = None,
        workers: int = 0,
    ) -> list[ScanResult]:
        """扫描全市场，返回触发买入信号的股票列表。

        Args:
            universe: 股票范围
                - "all": 沪深全部 A 股（默认）
                - "sh": 仅上海
                - "sz": 仅深圳
                - 文件路径: 每行一个 "市场 代码"（如 "SZ 000001"）
            progress_callback: 进度回调函数(current, total, filename)
            workers: 并发工作进程数
                - 0: 串行模式（默认，向后兼容）
                - 1: 串行但使用 executor 基础设施
                - 2+: ProcessPoolExecutor 并发执行

        Returns:
            触发买入信号的 ScanResult 列表
        """
        # 1. 收集文件列表
        files = self._collect_files(universe)

        if not files:
            return []

        total = len(files)

        # 串行模式（workers=0，向后兼容）
        if workers <= 0:
            return self._scan_serial(files, total, progress_callback)

        # 并发模式
        return self._scan_parallel(files, total, workers, progress_callback)

    def _scan_serial(
        self,
        files: list[tuple[Path, str, str]],
        total: int,
        progress_callback: Any,
    ) -> list[ScanResult]:
        """串行扫描（原有逻辑）。"""
        results: list[ScanResult] = []

        for idx, (filepath, market, code) in enumerate(files):
            if progress_callback:
                progress_callback(idx, total, filepath.name)

            try:
                result = self._scan_one(filepath, market, code)
                if result is not None:
                    results.append(result)
            except Exception:
                continue

        if progress_callback:
            progress_callback(total, total, "done")

        return results

    def _scan_parallel(
        self,
        files: list[tuple[Path, str, str]],
        total: int,
        workers: int,
        progress_callback: Any,
    ) -> list[ScanResult]:
        """并发扫描（ProcessPoolExecutor）。"""
        import concurrent.futures

        # 构建参数：每个任务需要的独立数据
        tasks = [
            (str(filepath), market, code, self._strategy_cls, self._cash, self._commission)
            for filepath, market, code in files
        ]

        results: list[ScanResult] = []
        completed = 0

        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(_scan_one_file, *task): i for i, task in enumerate(tasks)
            }

            for future in concurrent.futures.as_completed(future_to_idx):
                completed += 1
                idx = future_to_idx[future]

                if progress_callback:
                    progress_callback(completed, total, files[idx][0].name)

                try:
                    result = future.result()
                    if result is not None:
                        results.append(result)
                except Exception:
                    continue

        if progress_callback:
            progress_callback(total, total, "done")

        return results

    def _collect_files(self, universe: str) -> list[tuple[Path, str, str]]:
        """收集需要扫描的 .day 文件列表。

        Args:
            universe: 股票范围

        Returns:
            [(filepath, market_str, code), ...] 列表
        """
        # 确定要扫描的交易所目录
        exchanges: list[str] = []
        if universe in ("all", "sz"):
            exchanges.append("sz")
        if universe in ("all", "sh"):
            exchanges.append("sh")

        # 从文件列表模式读取
        if universe not in ("all", "sh", "sz"):
            return self._collect_from_file(universe)

        # 扫描目录
        files: list[tuple[Path, str, str]] = []
        for exchange in exchanges:
            lday_dir = self._vipdoc / exchange / "lday"
            if not lday_dir.is_dir():
                continue

            for filepath in sorted(lday_dir.glob("*.day")):
                # 从文件名提取代码
                name = filepath.name.lower()
                code = name[2:8]

                # 过滤非 A 股
                sec_type = _detect_security_type(filepath.name)
                if sec_type not in _A_STOCK_TYPES:
                    continue

                market = exchange.upper()
                files.append((filepath, market, code))

        return files

    def _collect_from_file(self, filepath: str) -> list[tuple[Path, str, str]]:
        """从文件读取股票列表。

        每行格式: "市场 代码"（如 "SZ 000001"）

        Args:
            filepath: 股票列表文件路径

        Returns:
            [(filepath, market_str, code), ...] 列表
        """
        path = Path(filepath)
        if not path.is_file():
            raise FileNotFoundError(f"股票列表文件不存在: {filepath}")

        files: list[tuple[Path, str, str]] = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    market_str = parts[0].upper()
                    code = parts[1]
                else:
                    continue

                # 定位 .day 文件
                exchange = market_str.lower()
                day_file = self._vipdoc / exchange / "lday" / f"{exchange}{code}.day"
                if day_file.is_file():
                    files.append((day_file, market_str, code))

        return files

    def _scan_one(self, filepath: Path, market: str, code: str) -> ScanResult | None:
        """扫描单只股票。

        Args:
            filepath: .day 文件路径
            market: 市场代码（SZ/SH）
            code: 6 位股票代码

        Returns:
            ScanResult 如果触发信号，否则 None
        """
        bars = read_daily_bars(filepath)
        if len(bars) < 30:
            # 数据太少，无法计算有意义的指标
            return None

        df = _bars_to_df(bars)
        if df.empty:
            return None

        # 提取信号遮罩
        try:
            factor_signals = extract_factor_signals(
                self._strategy_cls,
                df,
                cash=self._cash,
                commission=self._commission,
            )
        except Exception:
            return None

        # 检查最后一根 bar 是否有买入信号
        if not factor_signals.buy_mask[-1]:
            return None

        # 获取最后收盘价和日期
        last_bar = bars[-1]
        signal_date = last_bar.year * 10000 + last_bar.month * 100 + last_bar.day
        last_close = last_bar.close

        return ScanResult(
            code=code,
            market=market,
            signal_date=signal_date,
            last_close=last_close,
        )

    def to_json(
        self,
        results: list[ScanResult],
        strategy_name: str,
        strategy_file: str,
        total_scanned: int,
    ) -> str:
        """将扫描结果序列化为 JSON 字符串。

        Args:
            results: 扫描结果列表
            strategy_name: 策略名称
            strategy_file: 策略文件路径
            total_scanned: 总扫描股票数

        Returns:
            JSON 字符串
        """
        data = {
            "scan_time": datetime.now().isoformat(timespec="seconds"),
            "strategy": strategy_name,
            "strategy_file": strategy_file,
            "total_scanned": total_scanned,
            "total_signals": len(results),
            "signals": [
                {
                    "code": r.code,
                    "market": r.market,
                    "signal_date": r.signal_date,
                    "last_close": r.last_close,
                }
                for r in results
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2)


def _bars_to_df(bars: list[Any]) -> pd.DataFrame:
    """将 SecurityBar 列表转为策略所需的 DataFrame。

    Args:
        bars: SecurityBar 列表（按时间升序）

    Returns:
        DataFrame，包含 datetime, open, close, high, low, vol, amount 列
    """
    if not bars:
        return pd.DataFrame()

    rows = []
    for b in bars:
        dt = pd.Timestamp(year=b.year, month=b.month, day=b.day)
        rows.append(
            {
                "datetime": dt,
                "open": b.open,
                "close": b.close,
                "high": b.high,
                "low": b.low,
                "vol": b.vol,
                "amount": b.amount,
            }
        )

    return pd.DataFrame(rows)


def _scan_one_file(
    filepath: str,
    market: str,
    code: str,
    strategy_cls: type[Strategy],
    cash: float,
    commission: float,
) -> ScanResult | None:
    """顶层扫描函数（供 ProcessPoolExecutor 调用）。

    将实例方法逻辑提取为独立函数，避免 pickle 实例方法的问题。
    逻辑与 SignalScanner._scan_one 完全一致。

    Args:
        filepath: .day 文件路径字符串
        market: 市场代码（SZ/SH）
        code: 6 位股票代码
        strategy_cls: Strategy 子类
        cash: 初始资金
        commission: 佣金率

    Returns:
        ScanResult 如果触发信号，否则 None
    """
    bars = read_daily_bars(filepath)
    if len(bars) < 30:
        return None

    df = _bars_to_df(bars)
    if df.empty:
        return None

    try:
        factor_signals = extract_factor_signals(
            strategy_cls,
            df,
            cash=cash,
            commission=commission,
        )
    except Exception:
        return None

    if not factor_signals.buy_mask[-1]:
        return None

    last_bar = bars[-1]
    signal_date = last_bar.year * 10000 + last_bar.month * 100 + last_bar.day
    last_close = last_bar.close

    return ScanResult(
        code=code,
        market=market,
        signal_date=signal_date,
        last_close=last_close,
    )
