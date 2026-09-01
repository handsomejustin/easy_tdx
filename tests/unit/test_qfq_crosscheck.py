"""QFQ 对拍校验（公式法 vs 跳空检测法）的单元测试。

覆盖 ``easy_tdx.mac.qfq_check``：

- 已知除权案例回归（合成数据复现两类历史上被下游反馈过的场景）：
  * 「茅台式」——长期多重现金分红叠加深层历史，本地重算后应全正且事件处连续；
  * 「浦发式」——送转股事件，前复权方向应为「旧价向下缩放」。
- 反例检测：复权方向算反 → ``wrong_direction``；漏事件 → ``residual_gap``；
  NONE 跳空但 XDXR 缺记录 → ``unexplained_gap``；负价 → ``bad_price``。
- 涨跌停幅度推断（主板/双创/北交所）与跳空检测阈值。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from easy_tdx.mac.adjust import apply_forward_adjust, has_bad_prices
from easy_tdx.mac.qfq_check import (
    board_limit_ratio,
    crosscheck_qfq,
    detect_ex_dividend_gaps,
)


def _kline(
    closes: list[float],
    start: str = "2010-01-01",
    opens: list[float] | None = None,
) -> pd.DataFrame:
    """构造最小 NONE K 线。默认 open=close；可显式给 opens 制造除权跳空。"""
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="D")
    arr = np.array(closes, dtype=float)
    o = np.array(opens, dtype=float) if opens is not None else arr.copy()
    return pd.DataFrame(
        {
            "datetime": dates,
            "open": o,
            "high": np.maximum(o, arr) * 1.01,
            "low": np.minimum(o, arr) * 0.99,
            "close": arr,
            "vol": [100.0] * n,
        }
    )


def _xdxr(
    events: list[tuple[str, float, float, float, float]],
) -> pd.DataFrame:
    """构造 XDXR 记录：list of (date, fenhong, peigujia, songzhuangu, peigu)。"""
    return pd.DataFrame(
        [
            {
                "date": d,
                "category": 1,
                "fenhong": fh,
                "peigujia": pj,
                "songzhuangu": sz,
                "peigu": pg,
            }
            for d, fh, pj, sz, pg in events
        ]
    )


# --------------------------------------------------------------------------- #
# 涨跌停幅度推断
# --------------------------------------------------------------------------- #


def test_board_limit_ratio_by_code() -> None:
    """主板 10%、双创 20%、北交所 30%。"""
    assert board_limit_ratio("600519") == 0.10  # 沪主板（茅台）
    assert board_limit_ratio("600000") == 0.10  # 沪主板（浦发）
    assert board_limit_ratio("000001") == 0.10  # 深主板
    assert board_limit_ratio("300750") == 0.20  # 创业板
    assert board_limit_ratio("688981") == 0.20  # 科创板
    assert board_limit_ratio("832000") == 0.30  # 北交所
    assert board_limit_ratio("430047") == 0.30  # 北交所
    assert board_limit_ratio("600000", market=2) == 0.30  # market 显式指定优先


# --------------------------------------------------------------------------- #
# 跳空检测（detect_ex_dividend_gaps）
# --------------------------------------------------------------------------- #


def test_detect_gap_finds_ex_dividend_drop() -> None:
    """主板股票开盘相对昨收跌超 10.5% → 判定为除权跳空。"""
    # 10 根平稳 + 除权日开盘腰斩（-50%）
    closes = [10.0] * 5 + [5.0] * 5
    opens = [10.0] * 5 + [2.5] + [5.0] * 4
    df = _kline(closes, opens=opens)
    gaps = detect_ex_dividend_gaps(df, "600000")
    assert gaps == ["2010-01-06"]  # 第 6 根（index 5）为除权日


def test_detect_gap_ignores_normal_limit_down() -> None:
    """恰好跌停（-10.0%）不算除权跳空（被 0.5% 余量排除）。"""
    closes = [10.0] * 5 + [9.0] * 5
    opens = [10.0] * 5 + [9.0] + [9.0] * 4  # ex 开盘恰好 -10%
    df = _kline(closes, opens=opens)
    assert detect_ex_dividend_gaps(df, "600000") == []


def test_detect_gap_uses_chinext_threshold() -> None:
    """创业板（20% 涨跌停）：-15% 的跳空不报警，-25% 报警。"""
    closes = [10.0] * 5 + [7.5] * 5
    opens = [10.0] * 5 + [8.5] + [7.5] * 4  # -15% → 不报
    df = _kline(closes, opens=opens)
    assert detect_ex_dividend_gaps(df, "300750") == []

    opens2 = [10.0] * 5 + [7.0] + [7.5] * 4  # -30% → 报
    df2 = _kline(closes, opens=opens2)
    assert detect_ex_dividend_gaps(df2, "300750") == ["2010-01-06"]


# --------------------------------------------------------------------------- #
# 已知案例回归（合成）
# --------------------------------------------------------------------------- #


def test_maotai_style_multi_dividend_case() -> None:
    """「茅台式」：多笔大额现金分红叠加深层历史。

    场景：高价股（1700 元）历经 3 次每笔 40~60 元分红，NONE 价格在除权日
    出现 -3% 左右的真实跳空（小额，低于跌停阈值），深层历史经公式法
    前复权后应全正、除权日前后连续、对拍通过。
    """
    # 构造 300 根：价格在 1700 附近随机游走，3 个除权日各扣一次分红
    rng = np.random.default_rng(42)
    n = 300
    prices = 1700.0 + np.cumsum(rng.normal(0, 8, n))
    events = [(50, "2010-04-20"), (60, "2010-07-20"), (40, "2010-09-20")]
    closes = prices.copy()
    opens = prices.copy()
    dates = pd.date_range("2010-01-01", periods=n, freq="D")
    for fh, ex in events:
        ex_ts = pd.Timestamp(ex)
        idx = int(np.searchsorted(dates.to_numpy(), np.datetime64(ex_ts)))
        opens[idx] = closes[idx - 1] - fh  # 除权日开盘 = 昨收 - 分红
        closes[idx:] -= fh  # 之后价格整体降一档（简化）
    none_df = _kline(list(closes), opens=list(opens))
    xd = _xdxr([(ex, fh, 0.0, 0.0, 0.0) for fh, ex in events])

    qfq = apply_forward_adjust(none_df, xd)
    # 1. 全正（茅台负价问题的回归断言）
    assert not has_bad_prices(qfq)
    # 2. 对拍通过：无 bad_price / residual_gap / wrong_direction
    report = crosscheck_qfq(none_df, qfq, xd, "600519", 1)
    assert report.ok, [i.to_dict() for i in report.issues]
    assert report.events_checked == 3


def test_pufa_style_songzhuangu_direction() -> None:
    """「浦发式」：送转股事件的前复权方向。

    10 送 3（songzhuangu=0.3）：除权日理论价格 = 昨收 / 1.3。正确的前复权
    应把除权日**之前**的价格向下缩放（factor = 1/1.3），而不是抬升之后的价格。
    """
    # 20 根 10 元平稳，除权日后理论价 10/1.3 ≈ 7.69
    closes = [10.0] * 10 + [7.69] * 10
    opens = [10.0] * 10 + [7.69] + [7.69] * 9
    none_df = _kline(closes, opens=opens)
    xd = _xdxr([("2010-01-11", 0.0, 0.0, 0.3, 0.0)])

    qfq = apply_forward_adjust(none_df, xd)
    # 旧价被向下缩放：前 10 根 ≈ 10/1.3 ≈ 7.69，与除权后持平（连续）；
    # 最新价锚定不动
    assert abs(qfq["close"].iloc[0] - 7.69) <= 0.02
    assert abs(qfq["close"].iloc[-1] - 7.69) <= 1e-9
    # 方向正确 → 对拍通过（除权日 open=7.69 ≈ 复权后昨收 7.69）
    report = crosscheck_qfq(none_df, qfq, xd, "600000", 1)
    assert report.ok, [i.to_dict() for i in report.issues]


# --------------------------------------------------------------------------- #
# 反例检测
# --------------------------------------------------------------------------- #


def test_wrong_direction_adjustment_detected() -> None:
    """复权方向算反 → 除权日残留大幅跳空。

    方向反演（因子取倒数）：把除权日**之前**的价格放大 ×1.3 而非缩放
    ÷1.3，除权日 open=7.69 对上「复权后」昨收 13.0 → 残差 -41% →
    ``residual_gap``。
    """
    # NONE：10 送 3 场景，除权日开盘 7.69（-23%，超主板阈值 → 会被跳空检测捕获）
    closes = [10.0] * 10 + [7.69] * 10
    opens = [10.0] * 10 + [7.69] + [7.69] * 9
    none_df = _kline(closes, opens=opens)
    xd = _xdxr([("2010-01-11", 0.0, 0.0, 0.3, 0.0)])

    reversed_df = none_df.copy()
    reversed_df.loc[reversed_df.index <= 9, ["open", "high", "low", "close"]] *= 1.3
    report = crosscheck_qfq(none_df, reversed_df, xd, "600000", 1)
    assert not report.ok
    assert any(i.kind == "residual_gap" for i in report.issues)


def test_over_adjustment_detected() -> None:
    """过度复权（旧价缩得过低）→ 除权日向上跳空 → wrong_direction。"""
    closes = [10.0] * 10 + [7.69] * 10
    opens = [10.0] * 10 + [7.69] + [7.69] * 9
    none_df = _kline(closes, opens=opens)
    xd = _xdxr([("2010-01-11", 0.0, 0.0, 0.3, 0.0)])

    over = none_df.copy()
    over.loc[over.index <= 9, ["open", "high", "low", "close"]] *= 0.5  # 应 ÷1.3 却 ×0.5
    report = crosscheck_qfq(none_df, over, xd, "600000", 1)
    assert not report.ok
    assert any(i.kind == "wrong_direction" for i in report.issues)


def test_missed_event_residual_gap_detected() -> None:
    """漏算事件（复权结果等于 NONE 原始序列）→ residual_gap。"""
    closes = [10.0] * 10 + [7.69] * 10
    opens = [10.0] * 10 + [7.69] + [7.69] * 9
    none_df = _kline(closes, opens=opens)
    xd = _xdxr([("2010-01-11", 0.0, 0.0, 0.3, 0.0)])

    # 「复权结果」其实是未复权的 NONE（公式法漏调）→ 除权日残留 -23% 跳空
    report = crosscheck_qfq(none_df, none_df.copy(), xd, "600000", 1)
    assert not report.ok
    assert any(i.kind == "residual_gap" for i in report.issues)


def test_unexplained_gap_without_xdxr_record() -> None:
    """NONE 存在除权跳空但 XDXR 无对应记录 → unexplained_gap（不影响 ok）。"""
    closes = [10.0] * 10 + [7.69] * 10
    opens = [10.0] * 10 + [7.69] + [7.69] * 9
    none_df = _kline(closes, opens=opens)

    # XDXR 为空（数据源缺记录），公式法无从调整 → 序列本身「连续性」检查通过，
    # 但跳空检测应报 unexplained_gap 提示人工核查
    report = crosscheck_qfq(none_df, none_df.copy(), None, "600000", 1)
    assert report.gaps_detected == 1
    assert any(i.kind == "unexplained_gap" for i in report.issues)
    # unexplained_gap 属于「证据链不一致」而非「复权结果错误」，ok 保持 True
    assert report.ok


def test_bad_price_reported() -> None:
    """复权结果含负价 → bad_price（ok=False）。"""
    closes = [10.0] * 5
    none_df = _kline(closes)
    bad = none_df.copy()
    bad.loc[0, ["open", "high", "low", "close"]] = -1.0
    report = crosscheck_qfq(none_df, bad, None, "600000", 1)
    assert not report.ok
    assert any(i.kind == "bad_price" for i in report.issues)


def test_clean_series_passes() -> None:
    """无事件、无跳空的干净序列 → ok=True、零问题。"""
    closes = [10.0 + 0.1 * i for i in range(20)]
    none_df = _kline(closes)
    report = crosscheck_qfq(none_df, none_df.copy(), None, "600000", 1)
    assert report.ok
    assert report.issues == []
    assert report.events_checked == 0
    assert report.gaps_detected == 0


def test_report_to_dict_roundtrip() -> None:
    """报告可序列化为 JSON 兼容字典。"""
    closes = [10.0] * 10 + [7.69] * 10
    opens = [10.0] * 10 + [7.69] + [7.69] * 9
    none_df = _kline(closes, opens=opens)
    xd = _xdxr([("2010-01-11", 0.0, 0.0, 0.3, 0.0)])
    report = crosscheck_qfq(none_df, none_df.copy(), xd, "600000", 1)
    d = report.to_dict()
    assert d["symbol"] == "1:600000"
    assert d["ok"] is False
    assert isinstance(d["issues"], list) and d["issues"]
    assert {"kind", "date", "detail"} == set(d["issues"][0].keys())
