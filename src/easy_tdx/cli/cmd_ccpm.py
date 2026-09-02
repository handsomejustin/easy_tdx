"""中金所成交持仓排名命令（独立数据源，无需 TDX 服务器）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    import pandas as pd

#: 表格模式下的中文列名（JSON/CSV 保持英文机器友好列名）
_COLUMN_LABELS = {
    "trading_day": "交易日",
    "product": "品种",
    "instrument": "合约",
    "rank": "排名",
    "vol_member": "成交量·会员",
    "vol": "成交量(手)",
    "vol_chg": "增减",
    "long_member": "持买单·会员",
    "long_pos": "持买单量(手)",
    "long_chg": "增减2",
    "short_member": "持卖单·会员",
    "short_pos": "持卖单量(手)",
    "short_chg": "增减3",
}


@click.command("ccpm")
@click.argument("product", default="IF")
@click.option(
    "--date",
    "trade_date",
    default=None,
    help="交易日 YYYY-MM-DD（缺省自动回溯到最近有数据的交易日）",
)
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
@click.option("--refresh", is_flag=True, help="忽略本地缓存，强制重新抓取")
@click.option("--no-cache", is_flag=True, help="本次不读也不写本地缓存")
def ccpm(
    product: str,
    trade_date: str | None,
    use_table: bool,
    output_fmt: str,
    refresh: bool,
    no_cache: bool,
) -> None:
    """获取中金所成交持仓排名（官网每日收盘后约 16:15 发布，前 20 名会员）。

    \b
    品种代码：
      IF 沪深300  IH 上证50  IC 中证500  IM 中证1000
      TS 2年国债  TF 5年国债  T 10年国债  TL 30年国债
      all = 一次抓取全部 8 个品种

    \b
    示例：

      easy-tdx ccpm IF --table

      easy-tdx ccpm IF --date 2026-09-02

      easy-tdx ccpm all --date 2026-08-28 --table
    """
    from ..ccpm import PRODUCT_CODES, CcpmClient, CcpmError
    from .output import print_error, print_output

    products = PRODUCT_CODES if product.strip().lower() == "all" else [product.strip().upper()]
    client = CcpmClient(use_cache=not no_cache)
    frames = []
    try:
        for p in products:
            if trade_date:
                frames.append(client.get_rank(p, trade_date, refresh=refresh))
            else:
                frames.append(client.latest_rank(p, refresh=refresh))
    except (CcpmError, ValueError) as e:
        print_error(str(e))
        raise SystemExit(1) from e

    import pandas as pd

    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]

    fmt = "table" if use_table else output_fmt
    if fmt == "table":
        click.echo(_render_table(df))
    else:
        print_output(df, fmt)


def _render_table(df: pd.DataFrame) -> str:
    """中文表头 + 不截断会员名的表格渲染。"""
    from .output import _render_table_full

    return _render_table_full(df.rename(columns=_COLUMN_LABELS))
