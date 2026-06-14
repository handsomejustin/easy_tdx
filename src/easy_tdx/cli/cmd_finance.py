"""财务数据命令。"""

from __future__ import annotations

import click


@click.command("f10")
@click.argument("code")
@click.option(
    "--type",
    "report_type",
    type=click.Choice(["lrb", "fzb", "llb"], case_sensitive=False),
    default="lrb",
    help="报表类型: lrb(利润表) / fzb(资产负债表) / llb(现金流量表)",
)
@click.option("--num", default=8, type=int, help="取最近 N 期（默认 8）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def f10(code: str, report_type: str, num: int, use_table: bool, output_fmt: str) -> None:
    """获取财报三表（新浪数据源，独立于 TDX 行情服务器）。

    \b
    报表类型：
      lrb  利润表（默认）
      fzb  资产负债表
      llb  现金流量表

    \b
    示例：

      easy-tdx f10 600519                          # 茅台利润表，最近 8 期

      easy-tdx f10 600519 --type fzb --num 4       # 资产负债表，最近 4 期

      easy-tdx f10 000001 --type llb --table       # 平安现金流量表，表格输出
    """
    from ..sina import SinaClient, SinaError
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt
    client = SinaClient()
    try:
        df = client.get_financial_report(code, report_type=report_type, num=num)
    except SinaError as e:
        print_error(str(e))
        raise SystemExit(1) from e
    print_output(df, fmt)


@click.command("fund-flow")
@click.argument("market")
@click.argument("code")
@click.option("--start", default=0, type=int, help="起始偏移")
@click.option("--count", default=30, type=int, help="请求数量")
def fund_flow(market: str, code: str, start: int, count: int) -> None:
    """获取历史资金流向（暂未实现）。

    示例：

      easy-tdx fund-flow SZ 000001
    """
    raise click.UsageError("fund-flow 命令暂未实现，请使用 TdxClient.get_history_fund_flow() API")
