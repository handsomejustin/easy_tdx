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
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from easy_tdx.backtest.combo import extract_factor_signals
from easy_tdx.backtest.strategy import Strategy
from easy_tdx.offline.daily_bar import _detect_security_type, read_daily_bars
from easy_tdx.offline.paths import resolve_vipdoc

logger = logging.getLogger(__name__)

# 单股扫描失败（损坏的 .day、策略抛错等）属于"跳过该股、继续扫"的容错语义，
# 但完全静默会让系统性失败（如断网后所有文件读取异常）被吞掉（审计 #6 / 复审 L2）。
# 因此：每次失败记录 warning，扫描结束后若失败率超过阈值则记录 summary。
_SCAN_FAILURE_RATE_THRESHOLD = 0.5

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
        cache_file: str | Path | None = None,
    ) -> None:
        """初始化扫描器。

        Args:
            strategy_cls: 策略类（Strategy 子类）
            vipdoc_path: vipdoc 目录路径，None 则自动检测
            cash: 初始资金（影响全仓信号判断）
            commission: 佣金率
            cache_file: 增量扫描缓存文件路径（JSON），
                None 则每次全量扫描
        """
        self._strategy_cls = strategy_cls
        self._vipdoc = resolve_vipdoc(vipdoc_path)
        self._cash = cash
        self._commission = commission
        self._cache_file = Path(cache_file) if cache_file else None

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
                - "core": 核心龙头池 159 只（跨沪深按名单过滤）
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
        """串行扫描（支持增量缓存）。"""
        cache = self._load_cache()
        results: list[ScanResult] = []
        updated_cache: dict[str, Any] = {}
        # 单股扫描失败计数（审计 #6 / 复审 L2）：系统性失败（如大量损坏 .day）
        # 不应被完全静默，循环结束后按失败率发出汇总告警。
        failures = 0

        for idx, (filepath, market, code) in enumerate(files):
            if progress_callback:
                progress_callback(idx, total, filepath.name)

            # 增量检查：文件 mtime 未变则复用缓存结果
            cache_key = str(filepath)
            try:
                mtime = filepath.stat().st_mtime
            except OSError:
                continue

            cached = cache.get(cache_key)
            if cached is not None and cached.get("mtime") == mtime:
                result_data = cached.get("result")
                if result_data is not None:
                    results.append(
                        ScanResult(
                            code=result_data["code"],
                            market=result_data["market"],
                            signal_date=result_data["signal_date"],
                            last_close=result_data["last_close"],
                        )
                    )
                updated_cache[cache_key] = cached
                continue

            # 需要重新扫描
            try:
                result = self._scan_one(filepath, market, code)
                if result is not None:
                    results.append(result)
                # 更新缓存
                updated_cache[cache_key] = {
                    "mtime": mtime,
                    "result": (
                        {
                            "code": result.code,
                            "market": result.market,
                            "signal_date": result.signal_date,
                            "last_close": result.last_close,
                        }
                        if result is not None
                        else None
                    ),
                }
            except Exception:
                # 单股失败属"跳过继续"容错语义，但记录 warning 以暴露系统性
                # 失败（如损坏 .day / 策略 bug），不再完全静默（审计 #6 / 复审 L2）。
                failures += 1
                logger.warning("扫描 %s (%s) 失败，已跳过", code, filepath.name, exc_info=True)
                continue

        self._scan_failure_summary(failures, total)

        self._save_cache(updated_cache)

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
        """并发扫描（ProcessPoolExecutor）。

        与串行路径一致地接入 mtime 增量缓存（审计 #15）：派发任务前先按 mtime
        跳过未变文件、复用缓存结果，仅对变化的文件派发到进程池；子进程结果
        返回后由主进程统一写缓存，避免每次 --workers 全量重算 5000 只。
        """
        import concurrent.futures

        # 策略类不可跨进程 pickle（动态 importlib 加载的类子进程无法解析），
        # 改为传递策略文件路径，子进程自行加载
        strategy_file = _get_strategy_file(self._strategy_cls)

        cache = self._load_cache()
        updated_cache: dict[str, Any] = {}
        results: list[ScanResult] = []
        completed = 0
        # 单股扫描失败计数（审计 #6 / 复审 L2）：与串行路径一致。
        failures = 0

        # 第一遍：命中缓存的文件直接复用，未命中的收集为待扫描任务
        pending: list[tuple[int, tuple[Path, str, str], float]] = []
        for idx, (filepath, market, code) in enumerate(files):
            cache_key = str(filepath)
            try:
                mtime = filepath.stat().st_mtime
            except OSError:
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, filepath.name)
                continue

            cached = cache.get(cache_key)
            if cached is not None and cached.get("mtime") == mtime:
                result_data = cached.get("result")
                if result_data is not None:
                    results.append(
                        ScanResult(
                            code=result_data["code"],
                            market=result_data["market"],
                            signal_date=result_data["signal_date"],
                            last_close=result_data["last_close"],
                        )
                    )
                updated_cache[cache_key] = cached
                completed += 1
                if progress_callback:
                    progress_callback(completed, total, filepath.name)
            else:
                pending.append((idx, (filepath, market, code), mtime))

        # 第二遍：仅对变化的文件派发到进程池
        tasks = [
            (str(filepath), market, code, strategy_file, self._cash, self._commission)
            for _, (filepath, market, code), _ in pending
        ]

        if tasks:
            with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
                future_to_pending = {
                    executor.submit(_scan_one_file, *task): pend
                    for task, pend in zip(tasks, pending)
                }

                for future in concurrent.futures.as_completed(future_to_pending):
                    idx, (filepath, market, code), mtime = future_to_pending[future]
                    completed += 1

                    if progress_callback:
                        progress_callback(completed, total, filepath.name)

                    try:
                        result = future.result()
                        if result is not None:
                            results.append(result)
                        # 子进程结果回写缓存（主进程统一写，保证一致性）
                        updated_cache[str(filepath)] = {
                            "mtime": mtime,
                            "result": (
                                {
                                    "code": result.code,
                                    "market": result.market,
                                    "signal_date": result.signal_date,
                                    "last_close": result.last_close,
                                }
                                if result is not None
                                else None
                            ),
                        }
                    except Exception:
                        # 子进程异常（损坏 .day / 策略 bug）不再完全静默，
                        # 记录 warning 并计数，循环结束后按失败率汇总告警
                        # （审计 #6 / 复审 L2）。
                        failures += 1
                        logger.warning(
                            "扫描 %s (%s) 失败，已跳过",
                            code,
                            filepath.name,
                            exc_info=True,
                        )
                        continue

        self._scan_failure_summary(failures, total)

        self._save_cache(updated_cache)

        if progress_callback:
            progress_callback(total, total, "done")

        return results

    @staticmethod
    def _scan_failure_summary(failures: int, total: int) -> None:
        """扫描结束后按失败率发出汇总告警（审计 #6 / 复审 L2）。

        单股失败本身是"跳过继续"的容错语义，不中断整批扫描；但当失败比例
        超过阈值（如一半文件损坏/读取异常）时，几乎可以肯定是系统性问题
        （目录配置错误、磁盘故障、策略 bug），此时发出一条醒目的 warning，
        避免用户得到一份"空结果"却以为"没有信号"。
        """
        if failures <= 0 or total <= 0:
            return
        rate = failures / total
        if rate >= _SCAN_FAILURE_RATE_THRESHOLD:
            logger.warning(
                "扫描完成但失败率过高：%d/%d (%.0f%%) 的文件扫描失败，"
                "请检查 .day 文件完整性或策略实现",
                failures,
                total,
                rate * 100,
            )

    def _collect_files(self, universe: str) -> list[tuple[Path, str, str]]:
        """收集需要扫描的 .day 文件列表。

        Args:
            universe: 股票范围

        Returns:
            [(filepath, market_str, code), ...] 列表
        """
        # 确定要扫描的交易所目录
        exchanges: list[str] = []
        if universe in ("all", "sz", "core"):
            exchanges.append("sz")
        if universe in ("all", "sh", "core"):
            exchanges.append("sh")

        # 核心龙头池：跨沪深按名单过滤（见 screen/universe.py）
        core_codes: set[str] | None = None
        if universe == "core":
            from easy_tdx.screen.universe import core_leader_codes

            core_codes = core_leader_codes()

        # 从文件列表模式读取
        if universe not in ("all", "sh", "sz", "core"):
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

                # 核心龙头池模式：只保留名单内的代码
                if core_codes is not None and code not in core_codes:
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

    def _load_cache(self) -> dict[str, Any]:
        """加载增量扫描缓存。"""
        if self._cache_file is None or not self._cache_file.is_file():
            return {}
        try:
            with open(self._cache_file, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self, cache: dict[str, Any]) -> None:
        """保存增量扫描缓存。"""
        if self._cache_file is None:
            return
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(cache, f, ensure_ascii=False)
        except OSError:
            pass

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
            # 单股策略计算失败视为"无信号"并跳过；debug 记录以便排查策略 bug，
            # 不升级为 warning 以免在 5000 只批量扫描时刷屏（审计 #6 / 复审 L2）。
            logger.debug("策略计算异常 %s，视为无信号", code, exc_info=True)
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
    strategy_file: str,
    cash: float,
    commission: float,
) -> ScanResult | None:
    """顶层扫描函数（供 ProcessPoolExecutor 调用）。

    在子进程内动态加载策略类，避免跨进程 pickle 序列化失败。
    逻辑与 SignalScanner._scan_one 完全一致。

    Args:
        filepath: .day 文件路径字符串
        market: 市场代码（SZ/SH）
        code: 6 位股票代码
        strategy_file: 策略文件路径（子进程内动态加载）
        cash: 初始资金
        commission: 佣金率

    Returns:
        ScanResult 如果触发信号，否则 None
    """
    # 子进程内加载策略类（每次调用都重新加载，开销可忽略）
    strategy_cls = _load_strategy_class(strategy_file)

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
        # 单股策略计算失败视为"无信号"并跳过；debug 记录以便排查策略 bug
        # （审计 #6 / 复审 L2）。
        logger.debug("策略计算异常 %s，视为无信号", code, exc_info=True)
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


def _get_strategy_file(strategy_cls: type) -> str:
    """获取策略类所在的文件路径。

    按优先级尝试：sys.modules → 类方法 co_filename → inspect.getfile。
    适用于标准 import 和 importlib 动态加载的模块。

    Args:
        strategy_cls: Strategy 子类

    Returns:
        策略文件路径字符串
    """
    import sys

    # 1. 从 sys.modules 查找（适用于标准 import 加载的模块）
    mod = sys.modules.get(strategy_cls.__module__)
    if mod is not None and hasattr(mod, "__file__") and mod.__file__:
        return mod.__file__

    # 2. 从类自身定义的方法的 code object 反查文件路径
    #    （适用于 importlib 动态加载的模块，__module__ 是临时名但方法保留了源文件信息）
    for attr_name in ("init", "next", "on_bar", "on_tick"):
        method = strategy_cls.__dict__.get(attr_name)
        if method is not None and hasattr(method, "__code__"):
            filepath: str = method.__code__.co_filename
            if filepath and not filepath.startswith("<"):
                return filepath

    # 3. 任意自定义方法
    for attr_val in strategy_cls.__dict__.values():
        if callable(attr_val) and hasattr(attr_val, "__code__"):
            filepath2: str = attr_val.__code__.co_filename
            if filepath2 and not filepath2.startswith("<"):
                return filepath2

    raise ValueError(
        f"策略类 {strategy_cls.__name__} 无法定位源文件路径，"
        "并发模式（--workers）仅支持从 .py 文件加载的策略"
    )


def _load_strategy_class(strategy_file: str) -> type[Strategy]:
    """在子进程内动态加载策略类。

    与 CLI 的 _load_strategy 逻辑一致，提取为顶层函数以便子进程调用。

    Args:
        strategy_file: 策略文件路径

    Returns:
        Strategy 子类
    """
    import importlib.util

    file_path = Path(strategy_file)
    spec = importlib.util.spec_from_file_location("strategy_module", file_path)
    if spec is None or spec.loader is None:
        return None  # type: ignore[return-value]

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for attr_name in dir(module):
        obj = getattr(module, attr_name)
        try:
            if isinstance(obj, type) and issubclass(obj, Strategy) and obj is not Strategy:
                return obj
        except TypeError:
            pass

    return None  # type: ignore[return-value]
