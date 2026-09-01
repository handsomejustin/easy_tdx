"""``easy-tdx formula`` 命令组：通达信公式的计算 / 选股 / 回测。

公式方言见 :mod:`easy_tdx.formula`（命名布尔输出 = 信号列）。

示例::

    easy-tdx formula compute SH 600519 --formula "金叉: CROSS(MA(C,5), MA(C,20));"
    easy-tdx formula screen --symbols SH:600519,SZ:000001 --formula "..." --signal 金叉
    easy-tdx formula backtest SH 600519 --file my_formula.txt
"""

from __future__ import annotations

import json
from typing import Any

import click
import pandas as pd


@click.group("formula")
def formula() -> None:
    """通达信公式：计算 / 选股 / 回测（命名布尔输出即信号）。"""


def _load_formula(text: str | None, file: str | None) -> str:
    from easy_tdx.formula import compile_formula

    if file:
        from pathlib import Path

        source = Path(file).read_text(encoding="utf-8")
    elif text:
        source = text
    else:
        click.echo("错误: 必须提供 --formula 或 --file", err=True)
        raise SystemExit(1)
    compile_formula(source)  # 提前暴露语法错误
    return source


def _fetch(market: str, code: str, count: int, adjust: str) -> pd.DataFrame:
    from ..cli.conn import get_mac_client
    from ..cli.parsers import parse_adjust, parse_market, parse_period

    with get_mac_client() as client:
        return client.get_stock_kline(
            parse_market(market),
            code,
            period=parse_period("DAILY"),
            start=0,
            count=count,
            adjust=parse_adjust(adjust),
        )


@formula.command("compute")
@click.argument("market", type=click.Choice(["SH", "SZ", "BJ"]))
@click.argument("code")
@click.option("--formula", "formula_text", default=None, help="公式文本")
@click.option("--file", "formula_file", default=None, help="公式文件路径（.txt）")
@click.option("--count", default=120, type=int, help="K 线根数（默认 120）")
@click.option(
    "--adjust", default="QFQ", type=click.Choice(["NONE", "QFQ", "HFQ"]), help="复权（默认 QFQ）"
)
@click.option("--tail", default=10, type=int, help="同时输出最近 N 根的信号明细（默认 10）")
def formula_compute(
    market: str,
    code: str,
    formula_text: str | None,
    formula_file: str | None,
    count: int,
    adjust: str,
    tail: int,
) -> None:
    """在指定标的上计算公式，输出最后一根的各列值 + 最近信号明细。"""
    from easy_tdx.formula import compile_formula

    source = _load_formula(formula_text, formula_file)
    df = _fetch(market, code, count, adjust)
    if df is None or len(df) == 0:
        click.echo(f"错误: {market}:{code} 未取到 K 线", err=True)
        raise SystemExit(1)
    result = compile_formula(source).compute(df)
    payload = {
        "symbol": f"{market}:{code}",
        "signals": result.signals,
        "values": result.values,
        "last_row": result.last_row(),
    }
    if tail > 0 and result.columns:
        dt_col = "datetime" if "datetime" in df.columns else "date"
        recent_idx = df[dt_col].iloc[-tail:]
        recent = result.to_frame().iloc[-tail:]
        recent.insert(0, "date", [str(pd.Timestamp(d).date()) for d in recent_idx])
        payload["recent"] = json.loads(recent.to_json(orient="records", force_ascii=False))
    click.echo(json.dumps(payload, ensure_ascii=False, default=str))


@formula.command("screen")
@click.option("--symbols", required=True, help="标的列表：逗号分隔或 @文件（SH:600519,SZ:000001）")
@click.option("--formula", "formula_text", default=None, help="公式文本")
@click.option("--file", "formula_file", default=None, help="公式文件路径")
@click.option(
    "--signal", "signal_col", default=None, help="筛选信号列（默认第一个信号列，最后一根=1 通过）"
)
@click.option("--count", default=120, type=int, help="每标的 K 线根数")
@click.option(
    "--adjust", default="QFQ", type=click.Choice(["NONE", "QFQ", "HFQ"]), help="复权（默认 QFQ）"
)
def formula_screen(
    symbols: str,
    formula_text: str | None,
    formula_file: str | None,
    signal_col: str | None,
    count: int,
    adjust: str,
) -> None:
    """批量选股：公式信号列在最后一根 = 1 的标的（附各数值列，供排序）。"""
    from easy_tdx.formula import compile_formula

    source = _load_formula(formula_text, formula_file)
    if symbols.startswith("@"):
        from pathlib import Path

        symbol_list = [
            ln.strip()
            for ln in Path(symbols[1:]).read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    else:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    compiled = compile_formula(source)
    hits: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for sym in symbol_list:
        market, code = sym.split(":", 1)
        try:
            df = _fetch(market, code, count, adjust)
            if df is None or len(df) == 0:
                raise ValueError("未取到 K 线")
            result = compiled.compute(df)
            col = signal_col or (result.signals[0] if result.signals else None)
            if col is None:
                raise ValueError("公式无布尔信号输出")
            if result.last_row().get(col, 0.0) >= 1.0:
                row: dict[str, Any] = {"symbol": sym}
                row.update({k: v for k, v in result.last_row().items() if k != col})
                hits.append(row)
        except Exception as exc:  # noqa: BLE001 — 单标的失败跳过
            errors.append({"symbol": sym, "error": str(exc)})
    click.echo(
        json.dumps(
            {"total": len(symbol_list), "hits": hits, "errors": errors},
            ensure_ascii=False,
            default=str,
        )
    )


@formula.command("backtest")
@click.argument("market", type=click.Choice(["SH", "SZ", "BJ"]))
@click.argument("code")
@click.option("--formula", "formula_text", default=None, help="公式文本")
@click.option("--file", "formula_file", default=None, help="公式文件路径")
@click.option("--buy", "buy_col", default=None, help="买入信号列（默认自动挑选）")
@click.option("--sell", "sell_col", default=None, help="卖出信号列（默认自动挑选）")
@click.option("--count", default=500, type=int, help="K 线根数（默认 500）")
@click.option("--cash", default=100000.0, type=float, help="初始资金")
@click.option(
    "--adjust", default="QFQ", type=click.Choice(["NONE", "QFQ", "HFQ"]), help="复权（默认 QFQ）"
)
@click.option("--auto-fees", "auto_fees", is_flag=True, help="按品种自动费率（ETF 免印花税等）")
def formula_backtest(
    market: str,
    code: str,
    formula_text: str | None,
    formula_file: str | None,
    buy_col: str | None,
    sell_col: str | None,
    count: int,
    cash: float,
    adjust: str,
    auto_fees: bool,
) -> None:
    """公式回测：信号列在下一根开盘成交（next_open），输出绩效 + 评级 + 评分。"""
    from easy_tdx.backtest.formula_strategy import run_formula_backtest

    source = _load_formula(formula_text, formula_file)
    df = _fetch(market, code, count, adjust)
    if df is None or len(df) == 0:
        click.echo(f"错误: {market}:{code} 未取到 K 线", err=True)
        raise SystemExit(1)
    try:
        out = run_formula_backtest(
            df,
            source,
            buy_col=buy_col,
            sell_col=sell_col,
            cash=cash,
            symbol=f"{market}:{code}",
            auto_fees=auto_fees,
        )
    except ValueError as exc:
        click.echo(f"错误: {exc}", err=True)
        raise SystemExit(1)
    click.echo(json.dumps(out, ensure_ascii=False, default=str))
