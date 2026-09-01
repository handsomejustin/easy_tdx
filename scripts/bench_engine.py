"""bench_engine — 回测引擎信号生成路径基准（v1.28）。

测「单标的 N 根 × 指定内置策略 全流程」（engine.run 端到端）在两条信号
路径下的耗时，并附信号生成阶段（_generate_signals）的归因分解——
v1.25 实测指标缓存墙钟仅 ~1.01x，瓶颈在逐 bar Python 循环，本脚本即为其
优化前后的量化依据（数字进 CHANGELOG，报告用 --json 机器可读）。

用法::

    .venv/Scripts/python.exe scripts/bench_engine.py                    # 800 根 ma_cross
    .venv/Scripts/python.exe scripts/bench_engine.py --bars 300 --runs 30 --strategy macd
    .venv/Scripts/python.exe scripts/bench_engine.py --json             # CI/脚本消费
"""

from __future__ import annotations

import argparse
import json
import statistics
import time

import numpy as np
import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategies import get_registry


def synthetic_ohlcv(n: int, seed: int = 42, base: float = 20.0) -> pd.DataFrame:
    """确定性随机游走 OHLCV（与对拍单测同款生成方式）。"""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.02, n)
    close = base * np.cumprod(1.0 + rets)
    open_ = np.concatenate([[base], close[:-1]])
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0.0, 0.008, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0.0, 0.008, n)))
    vol = rng.integers(50_000, 5_000_000, n).astype(float)
    dates = pd.bdate_range("2022-01-04", periods=n)
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "vol": vol,
            "amount": vol * close,
        }
    )


def _time_path(engine: BacktestEngine, df: pd.DataFrame, runs: int) -> dict[str, float]:
    """计时一条路径：全流程 run + 仅信号生成阶段（归因用）。"""
    engine.run(df)  # 预热（numpy/pandas 内部缓存、导入惰性初始化）

    full_times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        engine.run(df)
        full_times.append(time.perf_counter() - t0)

    # 信号生成单独计时（引擎其余阶段：OrderSimulator/Portfolio/Performance）
    sig_times: list[float] = []
    for _ in range(runs):
        t0 = time.perf_counter()
        engine._generate_signals(df, None)
        sig_times.append(time.perf_counter() - t0)

    return {
        "full_median_ms": statistics.median(full_times) * 1000,
        "full_min_ms": min(full_times) * 1000,
        "signal_median_ms": statistics.median(sig_times) * 1000,
        "signal_min_ms": min(sig_times) * 1000,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="回测引擎信号路径基准")
    parser.add_argument("--bars", type=int, default=800, help="K 线根数（默认 800）")
    parser.add_argument("--runs", type=int, default=20, help="每条路径计时次数（取中位数）")
    parser.add_argument("--strategy", default="ma_cross", help="内置策略名（默认 ma_cross）")
    parser.add_argument("--seed", type=int, default=42, help="合成行情种子")
    parser.add_argument("--json", action="store_true", help="JSON 输出（机器可读）")
    args = parser.parse_args()

    df = synthetic_ohlcv(args.bars, seed=args.seed)
    strat = get_registry().get(args.strategy).build()

    loop = BacktestEngine(strat, signal_path="loop")
    vec = BacktestEngine(get_registry().get(args.strategy).build(), signal_path="vector")

    loop_stats = _time_path(loop, df, args.runs)
    vec_stats = _time_path(vec, df, args.runs)

    result = {
        "strategy": args.strategy,
        "bars": args.bars,
        "runs": args.runs,
        "trades": len(loop.run(df).trades),
        "loop": loop_stats,
        "vector": vec_stats,
        "full_speedup": loop_stats["full_median_ms"] / vec_stats["full_median_ms"],
        "signal_speedup": loop_stats["signal_median_ms"] / vec_stats["signal_median_ms"],
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            f"策略={result['strategy']}  bars={result['bars']}  runs={result['runs']}"
            f"  trades={result['trades']}"
        )
        print(
            f"逐 bar  路径：全流程 {loop_stats['full_median_ms']:.1f}ms"
            f"（最快 {loop_stats['full_min_ms']:.1f}）｜信号生成"
            f" {loop_stats['signal_median_ms']:.1f}ms"
        )
        print(
            f"向量化路径：全流程 {vec_stats['full_median_ms']:.1f}ms"
            f"（最快 {vec_stats['full_min_ms']:.1f}）｜信号生成"
            f" {vec_stats['signal_median_ms']:.1f}ms"
        )
        print(f"加速比：全流程 ×{result['full_speedup']:.2f}", end="")
        print(f"｜信号生成 ×{result['signal_speedup']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
