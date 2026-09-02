"""强势股排名引擎 — 全市场多周期涨幅加权排序。

核心流程：
1. 扫描 vipdoc/{sh,sz}/lday/*.day 获取 A 股文件列表
2. 每只股票：read_daily_bars() → 计算 ret_5/ret_20/ret_60/vol_20
3. 按预设模式加权合成 strength 分数
4. 排序输出

三种预设：
    steady   — 中长期稳健（w60 主导 + 波动率惩罚），选出稳着涨的票
    breakout — 近期妖股爆发（w5 主导，纯涨幅），选出短期最猛的票
    balanced — 三周期均衡（等权 + 波动率惩罚）
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.offline.daily_bar import _detect_security_type, read_daily_bars
from easy_tdx.offline.paths import resolve_vipdoc

_A_STOCK_TYPES = frozenset({"SH_A_STOCK", "SZ_A_STOCK"})

# ── 预设模式 ──────────────────────────────────────────────────────────────

STRENGTH_PRESETS: dict[str, dict[str, Any]] = {
    "steady": {
        "w5": 0.2,
        "w20": 0.3,
        "w60": 0.5,
        "vol_adjusted": True,
        "desc": "中长期稳健强势：权重偏 60 日，波动率惩罚，选出稳着涨的票",
    },
    "breakout": {
        "w5": 0.6,
        "w20": 0.3,
        "w60": 0.1,
        "vol_adjusted": False,
        "desc": "近期妖股爆发：权重偏 5 日，无波动率惩罚，选出短期最猛的票",
    },
    "balanced": {
        "w5": 0.34,
        "w20": 0.33,
        "w60": 0.33,
        "vol_adjusted": True,
        "desc": "均衡强势：三周期等权，波动率调整",
    },
}


@dataclass
class StrengthResult:
    """单只股票的强势分结果。

    Attributes:
        rank: 排名（排序后赋值）
        code: 6 位股票代码
        market: 市场（SZ/SH）
        name: 股票名称（可选，需在线查询补齐）
        last_close: 最新收盘价
        last_date: 最新交易日（YYYYMMDD 整数）
        ret_5: 5 日涨幅
        ret_20: 20 日涨幅
        ret_60: 60 日涨幅
        vol_20: 20 日波动率（对数收益率标准差）
        strength: 强势综合分
    """

    rank: int = 0
    code: str = ""
    market: str = ""
    name: str = ""
    last_close: float = 0.0
    last_date: int = 0
    ret_5: float = 0.0
    ret_20: float = 0.0
    ret_60: float = 0.0
    vol_20: float = 0.0
    strength: float = 0.0


def compute_strength_metrics(
    closes: pd.Series,
    w5: float,
    w20: float,
    w60: float,
    vol_adjusted: bool,
) -> dict[str, float] | None:
    """纯计算函数：给定收盘价序列，返回强势指标字典。

    Args:
        closes: 收盘价 Series（按时间升序）
        w5/w20/w60: 三周期权重（自动归一化）
        vol_adjusted: 是否除以波动率

    Returns:
        {"ret_5", "ret_20", "ret_60", "vol_20", "strength"} 或 None（数据不足）
    """
    n = len(closes)
    if n < 65:  # 至少需要 61 日算 ret_60，留余量
        return None

    # 权重归一化
    w_sum = w5 + w20 + w60
    if w_sum <= 0:
        return None
    w5, w20, w60 = w5 / w_sum, w20 / w_sum, w60 / w_sum

    last = closes.iloc[-1]
    ret_5 = last / closes.iloc[-6] - 1
    ret_20 = last / closes.iloc[-21] - 1
    ret_60 = last / closes.iloc[-61] - 1

    # 20 日波动率（对数收益率标准差）
    log_ret = np.log(closes / closes.shift(1))
    vol_20 = float(log_ret.rolling(20).std().iloc[-1])

    if vol_20 <= 0 or np.isnan(vol_20):
        return None

    raw = w5 * ret_5 + w20 * ret_20 + w60 * ret_60
    strength = raw / vol_20 if vol_adjusted else raw

    if np.isnan(strength):
        return None

    return {
        "ret_5": float(ret_5),
        "ret_20": float(ret_20),
        "ret_60": float(ret_60),
        "vol_20": vol_20,
        "strength": float(strength),
    }


class StrengthRanker:
    """全市场强势股排名器。

    用法::

        ranker = StrengthRanker(preset="steady")
        results = ranker.rank(top_n=50)
        for r in results[:5]:
            print(f"#{r.rank} {r.market}{r.code} strength={r.strength:.2f}")
    """

    def __init__(
        self,
        vipdoc_path: str | Path | None = None,
        preset: str = "steady",
        w5: float | None = None,
        w20: float | None = None,
        w60: float | None = None,
        vol_adjusted: bool | None = None,
        min_listed_days: int = 65,
        min_amount: float = 0.0,
    ) -> None:
        """初始化排名器。

        Args:
            vipdoc_path: vipdoc 目录路径，None 则自动检测
            preset: 预设模式 steady/breakout/balanced
            w5/w20/w60: 自定义权重（非 None 时覆盖预设）
            vol_adjusted: 自定义波动率惩罚开关（非 None 时覆盖预设）
            min_listed_days: 最小上市天数（默认 65，保证能算 60 日涨幅）
            min_amount: 最近 5 日日均成交额下限（默认 0 不过滤，单位：元）
        """
        if preset not in STRENGTH_PRESETS:
            raise ValueError(f"未知预设 '{preset}'，可选: {list(STRENGTH_PRESETS.keys())}")
        cfg = STRENGTH_PRESETS[preset]
        self._preset = preset
        self._w5 = w5 if w5 is not None else cfg["w5"]
        self._w20 = w20 if w20 is not None else cfg["w20"]
        self._w60 = w60 if w60 is not None else cfg["w60"]
        self._vol_adjusted = vol_adjusted if vol_adjusted is not None else cfg["vol_adjusted"]
        self._min_listed_days = min_listed_days
        self._min_amount = min_amount
        self._vipdoc = resolve_vipdoc(vipdoc_path)

    @property
    def preset(self) -> str:
        """当前预设名称。"""
        return self._preset

    def rank(
        self,
        universe: str = "all",
        top_n: int = 50,
        workers: int = 0,
        progress_callback: Any = None,
    ) -> list[StrengthResult]:
        """扫描全市场并返回强势股排名。

        Args:
            universe: all/sh/sz/core/<文件路径>（core=159 只核心龙头池）
            top_n: 返回前 N 名，0=全部
            workers: 并发进程数（0=串行，4-8 推荐）
            progress_callback: 回调(current, total, name)

        Returns:
            按 strength 降序排列的 StrengthResult 列表
        """
        files = self._collect_files(universe)
        if not files:
            return []
        total = len(files)

        if workers <= 0:
            results = self._rank_serial(files, total, progress_callback)
        else:
            results = self._rank_parallel(files, total, workers, progress_callback)

        # 排序 + 赋名次
        results.sort(key=lambda r: r.strength, reverse=True)
        for i, r in enumerate(results):
            r.rank = i + 1

        if top_n > 0:
            results = results[:top_n]
        return results

    def _collect_files(self, universe: str) -> list[tuple[Path, str, str]]:
        """收集 A 股 .day 文件列表（复用 scanner 的逻辑）。"""
        exchanges: list[str] = []
        if universe in ("all", "sz", "core"):
            exchanges.append("sz")
        if universe in ("all", "sh", "core"):
            exchanges.append("sh")

        # 核心龙头池：跨沪深按名单过滤（与 scanner 同一名单）
        core_codes: set[str] | None = None
        if universe == "core":
            from easy_tdx.screen.universe import core_leader_codes

            core_codes = core_leader_codes()

        # 从文件列表模式读取
        if universe not in ("all", "sh", "sz", "core"):
            return self._collect_from_file(universe)

        files: list[tuple[Path, str, str]] = []
        for exchange in exchanges:
            lday_dir = self._vipdoc / exchange / "lday"
            if not lday_dir.is_dir():
                continue
            for filepath in sorted(lday_dir.glob("*.day")):
                if _detect_security_type(filepath.name) not in _A_STOCK_TYPES:
                    continue
                code = filepath.name.lower()[2:8]
                if core_codes is not None and code not in core_codes:
                    continue
                files.append((filepath, exchange.upper(), code))
        return files

    def _collect_from_file(self, filepath: str) -> list[tuple[Path, str, str]]:
        """从文件读取股票列表（每行 "市场 代码"）。"""
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
                exchange = market_str.lower()
                day_file = self._vipdoc / exchange / "lday" / f"{exchange}{code}.day"
                if day_file.is_file():
                    files.append((day_file, market_str, code))
        return files

    def _rank_serial(
        self,
        files: list[tuple[Path, str, str]],
        total: int,
        progress_callback: Any,
    ) -> list[StrengthResult]:
        """串行扫描。"""
        results: list[StrengthResult] = []
        for idx, (filepath, market, code) in enumerate(files):
            if progress_callback:
                progress_callback(idx, total, filepath.name)
            try:
                r = self._compute_one(filepath, market, code)
                if r is not None:
                    results.append(r)
            except Exception:
                continue
        if progress_callback:
            progress_callback(total, total, "done")
        return results

    def _rank_parallel(
        self,
        files: list[tuple[Path, str, str]],
        total: int,
        workers: int,
        progress_callback: Any,
    ) -> list[StrengthResult]:
        """并发扫描（ProcessPoolExecutor）。"""
        import concurrent.futures

        tasks = [
            (
                str(fp),
                mkt,
                code,
                self._w5,
                self._w20,
                self._w60,
                self._vol_adjusted,
                self._min_listed_days,
                self._min_amount,
            )
            for fp, mkt, code in files
        ]

        results: list[StrengthResult] = []
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as ex:
            future_map = {ex.submit(_compute_strength_one, *t): i for i, t in enumerate(tasks)}
            done = 0
            for fut in concurrent.futures.as_completed(future_map):
                done += 1
                idx = future_map[fut]
                if progress_callback:
                    progress_callback(done, total, files[idx][0].name)
                try:
                    r = fut.result()
                    if r is not None:
                        results.append(r)
                except Exception:
                    continue
        if progress_callback:
            progress_callback(total, total, "done")
        return results

    def _compute_one(self, filepath: Path, market: str, code: str) -> StrengthResult | None:
        """计算单只股票的强势分。"""
        bars = read_daily_bars(filepath)
        if len(bars) < self._min_listed_days:
            return None

        closes = pd.Series([b.close for b in bars])

        # 成交额过滤（最近 5 日平均值）
        if self._min_amount > 0:
            recent_amount = float(np.mean([b.amount for b in bars[-5:]]))
            if recent_amount < self._min_amount:
                return None

        metrics = compute_strength_metrics(
            closes, self._w5, self._w20, self._w60, self._vol_adjusted
        )
        if metrics is None:
            return None

        last_bar = bars[-1]
        return StrengthResult(
            code=code,
            market=market,
            last_close=last_bar.close,
            last_date=last_bar.year * 10000 + last_bar.month * 100 + last_bar.day,
            ret_5=metrics["ret_5"],
            ret_20=metrics["ret_20"],
            ret_60=metrics["ret_60"],
            vol_20=metrics["vol_20"],
            strength=metrics["strength"],
        )

    @staticmethod
    def to_json(results: list[StrengthResult], preset: str, data_date: int) -> str:
        """将排名结果序列化为 JSON 字符串。"""
        data = {
            "scan_time": datetime.now().isoformat(timespec="seconds"),
            "preset": preset,
            "preset_desc": STRENGTH_PRESETS.get(preset, {}).get("desc", ""),
            "data_date": data_date,
            "total_ranked": len(results),
            "ranking": [
                {
                    "rank": r.rank,
                    "code": r.code,
                    "market": r.market,
                    "name": r.name,
                    "last_close": r.last_close,
                    "last_date": r.last_date,
                    "ret_5": r.ret_5,
                    "ret_20": r.ret_20,
                    "ret_60": r.ret_60,
                    "vol_20": r.vol_20,
                    "strength": r.strength,
                }
                for r in results
            ],
        }
        return json.dumps(data, ensure_ascii=False, indent=2, default=_json_default)

    @staticmethod
    def to_table(results: list[StrengthResult], preset: str, data_date: int) -> str:
        """将排名结果格式化为表格字符串。"""
        if not results:
            return "无有效排名结果"

        desc = STRENGTH_PRESETS.get(preset, {}).get("desc", "")
        lines = [
            f"[*] 强势股排名 [{preset}] 共 {len(results)} 只",
            f"    数据截止: {_fmt_date(data_date)} | {desc}",
            "═" * 96,
            f"{'排名':>4}  {'代码':<10} {'名称':<8} {'现价':>10} "
            f"{'5日':>8} {'20日':>8} {'60日':>8} {'波动率':>8} {'强势分':>8}",
            "─" * 96,
        ]

        for r in results:
            medal = (
                " *1*"
                if r.rank == 1
                else " *2*"
                if r.rank == 2
                else " *3*"
                if r.rank == 3
                else "    "
            )
            name = r.name[:6] if r.name else ""
            lines.append(
                f"{medal}{r.rank:>2}  {r.market}{r.code:<9} {name:<8} "
                f"{r.last_close:>9.2f} {r.ret_5:>7.2%} {r.ret_20:>7.2%} "
                f"{r.ret_60:>7.2%} {r.vol_20:>7.4f} {r.strength:>8.2f}"
            )
        return "\n".join(lines)


def _compute_strength_one(
    filepath: str,
    market: str,
    code: str,
    w5: float,
    w20: float,
    w60: float,
    vol_adjusted: bool,
    min_listed_days: int,
    min_amount: float,
) -> StrengthResult | None:
    """顶层函数（供 ProcessPoolExecutor 调用）。"""
    bars = read_daily_bars(filepath)
    if len(bars) < min_listed_days:
        return None

    closes = pd.Series([b.close for b in bars])

    if min_amount > 0:
        recent = float(np.mean([b.amount for b in bars[-5:]]))
        if recent < min_amount:
            return None

    metrics = compute_strength_metrics(closes, w5, w20, w60, vol_adjusted)
    if metrics is None:
        return None

    last = bars[-1]
    return StrengthResult(
        code=code,
        market=market,
        last_close=last.close,
        last_date=last.year * 10000 + last.month * 100 + last.day,
        ret_5=metrics["ret_5"],
        ret_20=metrics["ret_20"],
        ret_60=metrics["ret_60"],
        vol_20=metrics["vol_20"],
        strength=metrics["strength"],
    )


def _fmt_date(d: int) -> str:
    """YYYYMMDD 整数 → YYYY-MM-DD 字符串。"""
    s = str(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:]}" if len(s) == 8 else str(d)


def _json_default(obj: Any) -> Any:
    """JSON 序列化辅助（numpy 标量等）。"""
    if hasattr(obj, "item"):
        return obj.item()
    raise TypeError(f"无法序列化 {type(obj)}")
