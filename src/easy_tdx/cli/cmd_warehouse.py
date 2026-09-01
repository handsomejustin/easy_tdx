"""``easy-tdx warehouse`` 命令组：本地 K 线仓库的同步 / 查询 / 统计 / 自检。

仓库为 DuckDB 单文件（默认 ``~/.easy_tdx/warehouse.duckdb``），依赖可选
安装：``pip install easy-tdx[warehouse]``。

示例::

    easy-tdx warehouse sync --symbols SH:600519,SZ:000001
    easy-tdx warehouse query SH 600519 --count 30
    easy-tdx warehouse stats
    easy-tdx warehouse check --symbols SH:600519
"""

from __future__ import annotations

import json
import sys
from typing import Any

import click


def _require_warehouse(db_path: str | None) -> Any:
    """惰性导入 warehouse（duckdb 可选依赖），失败给友好错误。"""
    try:
        from easy_tdx.warehouse import KlineWarehouse
    except ImportError as exc:
        click.echo(f"错误: {exc}", err=True)
        raise SystemExit(2) from exc
    return KlineWarehouse(db_path) if db_path else KlineWarehouse()


@click.group("warehouse")
def warehouse() -> None:
    """本地 K 线数据仓库（DuckDB）：同步、查询、统计、健康自检。"""


@warehouse.command("sync")
@click.option(
    "--symbols", required=True, help="标的列表：逗号分隔（SH:600519,SZ:000001）或 @文件（每行一个）"
)
@click.option("--period", default="DAILY", help="K 线周期（默认 DAILY）")
@click.option("--max-bars", default=8000, type=int, help="首同步最大拉取根数（默认 8000）")
@click.option("--tail-bars", default=15, type=int, help="增量同步尾部根数（默认 15）")
@click.option(
    "--adjust",
    default="QFQ",
    type=click.Choice(["NONE", "QFQ", "HFQ"]),
    help="复权口径（默认 QFQ）",
)
@click.option(
    "--db", "db_path", default=None, help="仓库文件路径（默认 ~/.easy_tdx/warehouse.duckdb）"
)
def warehouse_sync(
    symbols: str,
    period: str,
    max_bars: int,
    tail_bars: int,
    adjust: str,
    db_path: str | None,
) -> None:
    """增量同步行情进仓库（首同步全量、此后只补尾部）。"""
    if symbols.startswith("@"):
        from pathlib import Path

        path = Path(symbols[1:])
        if not path.exists():
            click.echo(f"错误: 标的列表文件不存在 {path}", err=True)
            raise SystemExit(1)
        symbol_list = [
            ln.strip()
            for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
    else:
        symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]

    with _require_warehouse(db_path) as wh:
        from easy_tdx.warehouse import WarehouseSyncer

        def _progress(done: int, total: int, sym: str) -> None:
            click.echo(f"[{done}/{total}] {sym}", err=True)

        from ..cli.conn import get_mac_client

        with get_mac_client() as client:
            syncer = WarehouseSyncer(
                client, wh, max_bars=max_bars, tail_bars=tail_bars, adjust=adjust
            )
            summary = syncer.sync(symbol_list, period=period, progress=_progress)
        click.echo(
            json.dumps(
                {k: v for k, v in summary.items() if k != "details"},
                ensure_ascii=False,
            )
        )


@warehouse.command("query")
@click.argument("market", type=click.Choice(["SH", "SZ", "BJ"]))
@click.argument("code")
@click.option("--period", default="DAILY", help="K 线周期（默认 DAILY）")
@click.option("--count", default=None, type=int, help="最近 N 根（默认全部）")
@click.option("--start", default=None, help="开始日期 YYYY-MM-DD")
@click.option("--end", default=None, help="结束日期 YYYY-MM-DD")
@click.option("--include-provisional", is_flag=True, help="包含未收盘的临时 bar（默认忽略）")
@click.option("--db", "db_path", default=None, help="仓库文件路径")
def warehouse_query(
    market: str,
    code: str,
    period: str,
    count: int | None,
    start: str | None,
    end: str | None,
    include_provisional: bool,
    db_path: str | None,
) -> None:
    """查询仓库中的 K 线（JSON 输出，datetime/OHLCV/status）。"""
    with _require_warehouse(db_path) as wh:
        df = wh.query(
            market,
            code,
            period=period,
            start=start,
            end=end,
            count=count,
            include_provisional=include_provisional,
        )
    if len(df) == 0:
        click.echo("[]")
        return
    out = json.loads(df.to_json(orient="records", date_format="iso", force_ascii=False))
    click.echo(json.dumps(out, ensure_ascii=False))


@warehouse.command("stats")
@click.option("--period", default="DAILY", help="K 线周期（默认 DAILY）")
@click.option("--db", "db_path", default=None, help="仓库文件路径")
def warehouse_stats(period: str, db_path: str | None) -> None:
    """仓库统计：各标的行数 / 数据范围 / provisional 行数。"""
    with _require_warehouse(db_path) as wh:
        df = wh.symbols(period=period)
    if len(df) == 0:
        click.echo("仓库为空，请先执行 easy-tdx warehouse sync", err=True)
        raise SystemExit(1)
    df_out = df.copy()
    df_out["first"] = df_out["first"].astype(str)
    df_out["last"] = df_out["last"].astype(str)
    click.echo(
        json.dumps(
            json.loads(df_out.to_json(orient="records", force_ascii=False)), ensure_ascii=False
        )
    )


@warehouse.command("check")
@click.option("--symbols", default=None, help="只检查指定标的（逗号分隔），默认全仓库")
@click.option("--db", "db_path", default=None, help="仓库文件路径")
def warehouse_check(symbols: str | None, db_path: str | None) -> None:
    """仓库健康自检：缺口 / 异常跳变 / 最新度 / 临时行。"""
    with _require_warehouse(db_path) as wh:
        market = code = None
        if symbols:
            first = [s.strip() for s in symbols.split(",") if s.strip()][0]
            market, code = first.split(":", 1)
            if ":" not in symbols and len(symbols.split(",")) > 1:
                click.echo("错误: --symbols 自检模式一次只支持一个标的", err=True)
                raise SystemExit(1)
        report = wh.health_check(market=market, code=code)
    click.echo(json.dumps(report, ensure_ascii=False, default=str))
    if report["issues"]:
        sys.exit(0)  # 有问题不报错退出——自检结果本身是正常输出
