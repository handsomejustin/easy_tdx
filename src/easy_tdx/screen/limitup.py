"""涨停生态计算（本地 vipdoc .day 文件，离线快速回算连板/炸板/跌停）。

设计要点：

- **数据源**：``vipdoc/{sh,sz}/lday/*.day``（与 strength 扫描器同款读取器
  :func:`easy_tdx.offline.daily_bar.read_daily_bars`），不依赖网络；数据新鲜度
  取决于本机通达信客户端的数据日期，因此结果必须携带 ``data_date`` 供前端明示。
- **涨停判定**：收盘价 == 涨停价（前收 × 涨幅上限，四舍五入到分）。
  涨幅上限按代码段近似：主板(60/00) 10%、创业板(30)/科创板(68) 20%。
  .day 文件无证券名称，无法识别 ST——对主板额外按 5% 判定并标记 ``st=True``
  （常规股票恰收在 +5.00% 整的误报率极低，前端展示名称后可自辨）。
- **炸板**：当日 high 触及涨停价但收盘未封住（close < 涨停价）。
- **连板高度（streak）**：截至最新一根 bar 的连续涨停天数（按 bar 连续计，
  停牌跳日不中断，与通行口径一致）。
- 纯函数 + 文件遍历分离，便于用合成 .day 文件做单测。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from easy_tdx.offline.daily_bar import _detect_security_type, read_daily_bars
from easy_tdx.offline.paths import resolve_vipdoc

_A_STOCK_TYPES = frozenset({"SH_A_STOCK", "SZ_A_STOCK"})

__all__ = [
    "LimitUpEntry",
    "LimitUpEcology",
    "compute_limitup_ecology",
    "compute_limitup_history",
]


def _round_price(x: float) -> float:
    """四舍五入到分（Python round 是银行家舍入，交易所是四舍五入，不能混用）。"""
    return math.floor(x * 100 + 0.5) / 100


def _eq_price(a: float, b: float) -> bool:
    return abs(a - b) < 1e-4


def _limit_ratio(code: str) -> float:
    """涨幅上限：创业板/科创板 20%，其余主板 10%（ST 由调用侧按 5% 二次判定）。"""
    if code.startswith(("30", "68")):
        return 0.20
    return 0.10


@dataclass
class LimitUpEntry:
    """单只涨停/跌停/炸板股票的回算结果。"""

    code: str
    market: str  # SH / SZ
    pct: float  # 最新日涨跌幅（%，按 close/prev_close-1）
    streak: int = 0  # 连续涨停/跌停天数（截至最新 bar）
    st: bool = False  # 主板 5% 判定（疑似 ST）
    blown: bool = False  # 炸板（曾触及涨停未封住）


@dataclass
class LimitUpEcology:
    """全市场涨停生态快照。"""

    data_date: int  # 全市场最新 bar 日期 YYYYMMDD（vipdoc 新鲜度）
    total: int  # 参与统计的股票数
    limit_up: list[LimitUpEntry] = field(default_factory=list)
    limit_down: list[LimitUpEntry] = field(default_factory=list)
    blown: list[LimitUpEntry] = field(default_factory=list)  # 炸板（曾涨停未封住）

    def summary(self) -> dict[str, object]:
        heights = [e.streak for e in self.limit_up]
        touched = len(self.limit_up) + len(self.blown)
        return {
            "data_date": self.data_date,
            "total": self.total,
            "limit_up_count": len(self.limit_up),
            "limit_down_count": len(self.limit_down),
            "blown_count": len(self.blown),
            # 炸板率 = 炸板 / (封住 + 炸板)，无分母时为 None
            "blown_rate": round(len(self.blown) / touched * 100, 1) if touched else None,
            "max_streak": max(heights) if heights else 0,
            "first_board": sum(1 for h in heights if h == 1),
            "second_board": sum(1 for h in heights if h == 2),
            "plus3": sum(1 for h in heights if h >= 3),
        }


def _entry_from_closes(
    closes: list[float],
    last_high: float,
    market: str,
    code: str,
) -> LimitUpEntry | None:
    """从收盘价序列判定最新交易日的涨停/跌停/炸板与连板高度。

    Args:
        closes: 最近若干根 bar 的收盘价（时间升序，最后一根 = 数据日）。
        last_high: 数据日的最高价（炸板判定用）。
        market: SH / SZ。
        code: 6 位代码。
    """
    if len(closes) < 2:
        return None
    prev = closes[-2]
    if prev <= 0:
        return None

    pct = (closes[-1] / prev - 1.0) * 100.0
    entry = LimitUpEntry(code=code, market=market, pct=round(pct, 2))

    up_ratio = _limit_ratio(code)
    limit_up_price = _round_price(prev * (1 + up_ratio))
    # 主板 5%：疑似 ST 涨停。低价股（< 3 元）最小报价单位 0.01 占比过大，
    # +5% 整的巧合概率骤增，跳过 ST 判定（宁可漏报不误报）。
    st_applicable = up_ratio == 0.10 and prev >= 3.0
    st_price = _round_price(prev * 1.05) if st_applicable else None
    limit_down_price = _round_price(prev * (1 - up_ratio))
    st_down_price = _round_price(prev * 0.95) if st_applicable else None

    def _eq(a: float, b: float) -> bool:
        return abs(a - b) < 1e-4

    def _is_up(i: int) -> bool:
        """第 i 根是否涨停（用第 i-1 根收盘作前收）。"""
        if i < 1:
            return False
        p = closes[i - 1]
        c = closes[i]
        if _eq(c, _round_price(p * (1 + up_ratio))):
            return True
        return st_applicable and _eq(c, _round_price(p * 1.05))

    # 连板高度（截至最后一根）
    streak = 0
    i = len(closes) - 1
    while i >= 1 and _is_up(i):
        streak += 1
        i -= 1
    entry.streak = streak
    entry.st = bool(streak > 0 and st_price is not None and _eq(closes[-1], st_price))

    if streak > 0:
        entry.blown = False
        return entry

    # 未封住的场合：炸板（high 触及涨停价）或跌停
    if _eq(last_high, limit_up_price):
        entry.blown = True
        return entry

    if _eq(closes[-1], limit_down_price) or (
        st_down_price is not None and _eq(closes[-1], st_down_price)
    ):
        down_streak = 0
        j = len(closes) - 1
        while j >= 1:
            p = closes[j - 1]
            c = closes[j]
            hit = _eq(c, _round_price(p * (1 - up_ratio)))
            if not hit and st_applicable:
                hit = _eq(c, _round_price(p * 0.95))
            if not hit:
                break
            down_streak += 1
            j -= 1
        entry.streak = down_streak
        return entry
    return None


def compute_limitup_ecology(
    vipdoc_path: str | Path | None = None,
    *,
    max_files: int = 20000,
) -> LimitUpEcology:
    """扫描全市场 .day 文件，回算最新交易日的涨停生态。

    Args:
        vipdoc_path: vipdoc 目录，None 则自动检测。
        max_files: 文件数上限（防意外巨量文件拖死扫描）。

    Returns:
        :class:`LimitUpEcology`；vipdoc 不可用时 total=0。
    """
    eco = LimitUpEcology(data_date=0, total=0)
    try:
        vipdoc = resolve_vipdoc(vipdoc_path)
    except Exception:  # noqa: BLE001 — 路径不存在/自动检测失败：按空数据处理
        return eco
    if not vipdoc.is_dir():
        return eco

    files: list[tuple[Path, str, str]] = []
    for exchange in ("sz", "sh"):
        lday_dir = vipdoc / exchange / "lday"
        if not lday_dir.is_dir():
            continue
        for filepath in sorted(lday_dir.glob("*.day")):
            if _detect_security_type(filepath.name) not in _A_STOCK_TYPES:
                continue
            code = filepath.name.lower()[2:8]
            files.append((filepath, exchange.upper(), code))
            if len(files) >= max_files:
                break
        if len(files) >= max_files:
            break
    eco.total = len(files)

    # 一遍读取，仅保留尾部收盘/最高价；随后按"最后一根日期 == 全市场最新交易日"
    # 过滤——vipdoc 里大量文件因停牌/退市/未下载而停在历史日期，若不过滤会把
    # 多年前的"涨停"当成今天的（真实教训：退市前仙股文件冒出 5 连板）。
    _TAIL = 13  # 连板判定最多回看 12 根 + 判定用前收
    scanned: list[tuple[int, str, str, list[float], list[float]]] = []
    for filepath, market, code in files:
        try:
            bars = read_daily_bars(filepath)
        except Exception:  # noqa: BLE001 — 单文件损坏不阻塞整体
            continue
        if len(bars) < 2:
            continue
        tail = bars[-_TAIL:]
        last_date = bars[-1].year * 10000 + bars[-1].month * 100 + bars[-1].day
        scanned.append(
            (
                last_date,
                market,
                code,
                [b.close for b in tail],
                [b.high for b in tail],
            )
        )
        if last_date > eco.data_date:
            eco.data_date = last_date

    for last_date, market, code, closes, highs in scanned:
        if last_date != eco.data_date:
            continue  # 数据不新鲜（停牌/退市/未下载），不参与今日生态
        entry = _entry_from_closes(closes, highs[-1], market, code)
        if entry is None:
            continue
        if entry.blown:
            eco.blown.append(entry)
        elif entry.pct > 0 and entry.streak > 0:
            eco.limit_up.append(entry)
        elif entry.pct < 0 and entry.streak > 0:
            eco.limit_down.append(entry)

    eco.limit_up.sort(key=lambda e: (-e.streak, -e.pct))
    eco.limit_down.sort(key=lambda e: (-e.streak, e.pct))
    eco.blown.sort(key=lambda e: -e.pct)
    return eco


def compute_limitup_history(
    vipdoc_path: str | Path | None = None,
    *,
    days: int = 60,
    max_files: int = 20000,
) -> list[dict[str, int]]:
    """逐日统计最近 ``days`` 个交易日的涨停/跌停家数（离线回补，无需采样积累）。

    与 :func:`compute_limitup_ecology` 的"只看最新交易日"不同，本函数把每只股票
    窗口内的每一根 bar 都按同一涨停判定规则计数——历史日期上它就是当时真实的
    涨停家数（陈旧文件在此是合法的历史数据，无污染问题）。

    Returns:
        按 date 升序的 ``[{"date": YYYYMMDD, "limit_up": n, "limit_down": m}]``；
        vipdoc 不可用时返回空列表。
    """
    try:
        vipdoc = resolve_vipdoc(vipdoc_path)
    except Exception:  # noqa: BLE001 — 路径不存在/自动检测失败：按空数据处理
        return []

    counts: dict[int, dict[str, int]] = {}
    if not vipdoc.is_dir():
        return []

    n_files = 0
    for exchange in ("sz", "sh"):
        lday_dir = vipdoc / exchange / "lday"
        if not lday_dir.is_dir():
            continue
        for filepath in sorted(lday_dir.glob("*.day")):
            if _detect_security_type(filepath.name) not in _A_STOCK_TYPES:
                continue
            code = filepath.name.lower()[2:8]
            try:
                bars = read_daily_bars(filepath)
            except Exception:  # noqa: BLE001 — 单文件损坏不阻塞整体
                continue
            tail = bars[-(days + 13) :]
            if len(tail) < 2:
                continue
            n_files += 1
            if n_files >= max_files:
                break
            up_ratio = _limit_ratio(code)
            closes = [b.close for b in tail]
            date_ints = [b.year * 10000 + b.month * 100 + b.day for b in tail]
            for i in range(1, len(tail)):
                p, c = closes[i - 1], closes[i]
                if p <= 0:
                    continue
                st_applicable = up_ratio == 0.10 and p >= 3.0
                d = date_ints[i]
                bucket = counts.setdefault(d, {"limit_up": 0, "limit_down": 0})
                if _eq_price(c, _round_price(p * (1 + up_ratio))) or (
                    st_applicable and _eq_price(c, _round_price(p * 1.05))
                ):
                    bucket["limit_up"] += 1
                elif _eq_price(c, _round_price(p * (1 - up_ratio))) or (
                    st_applicable and _eq_price(c, _round_price(p * 0.95))
                ):
                    bucket["limit_down"] += 1
        if n_files >= max_files:
            break

    recent = sorted(counts)[-days:] if days > 0 else []
    return [
        {
            "date": d,
            "limit_up": counts[d]["limit_up"],
            "limit_down": counts[d]["limit_down"],
        }
        for d in recent
    ]
