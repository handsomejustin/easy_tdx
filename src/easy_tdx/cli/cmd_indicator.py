"""技术指标命令。"""

from __future__ import annotations

import click


def _parse_indicator_params(s: str) -> dict[str, dict[str, int | float]]:
    """解析指标参数字符串。

    格式: ``SHORT=10,LONG=22`` 或 ``MACD.SHORT=10,KDJ.N=14``
    无前缀的参数应用到所有请求的指标。
    """
    result: dict[str, dict[str, int | float]] = {}
    if not s:
        return result

    for pair in s.split(","):
        pair = pair.strip()
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        key = key.strip()
        val = val.strip()

        if "." in key:
            indicator, param = key.split(".", 1)
            indicator = indicator.strip().upper()
            param = param.strip()
            result.setdefault(indicator, {})[param] = float(val) if "." in val else int(val)
        else:
            result.setdefault("*", {})[key] = float(val) if "." in val else int(val)
    return result


@click.command()
@click.argument("indicators")
@click.option("--market", "-m", required=True, help="市场: SH/SZ/BJ")
@click.option("--code", "-c", required=True, help="股票代码")
@click.option(
    "--period",
    default="DAILY",
    help="K线周期: DAILY/5MIN/15MIN/30MIN/60MIN/1MIN/WEEKLY/MONTHLY",
)
@click.option("--count", default=30, type=int, help="返回条数（默认30）")
@click.option("--adjust", default="QFQ", help="复权: NONE/QFQ/HFQ（默认QFQ）")
@click.option("--params", default=None, help="指标参数: SHORT=10,LONG=22 或 MACD.SHORT=10")
@click.option("--no-ohlcv", is_flag=True, help="不显示原始OHLCV列")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def indicator(
    indicators: str,
    market: str,
    code: str,
    period: str,
    count: int,
    adjust: str,
    params: str | None,
    no_ohlcv: bool,
    use_table: bool,
    output_fmt: str,
) -> None:
    """计算技术指标。

    示例：

      easy-tdx indicator MACD -m SH -c 600519 --table

      easy-tdx indicator MACD,KDJ,RSI -m SH -c 600519 --count 10 --table

      easy-tdx indicator BOLL -m SZ -c 000001 --params N=10,P=1.5
    """
    from ..indicator import compute_indicators
    from .conn import get_mac_client
    from .output import print_error, print_output
    from .parsers import parse_adjust, parse_market, parse_period

    fmt = "table" if use_table else output_fmt
    mkt = parse_market(market)
    indicator_list = [n.strip() for n in indicators.split(",")]
    parsed_params = _parse_indicator_params(params) if params else {}

    # 将通配符参数应用到所有指标
    wildcard = parsed_params.pop("*", {})
    final_params: dict[str, dict[str, int | float]] = {}
    for name in indicator_list:
        final_params[name.upper()] = {**wildcard, **parsed_params.get(name.upper(), {})}

    fetch_count = max(120 + count, 200)
    try:
        with get_mac_client() as client:
            df = client.get_stock_kline(
                mkt,
                code,
                period=parse_period(period),
                count=fetch_count,
                adjust=parse_adjust(adjust),
            )
        if df.empty:
            print_error("未获取到K线数据")
            return
        result = compute_indicators(
            df,
            indicator_list,
            final_params,
            keep_ohlcv=not no_ohlcv,
            tail=count,
        )
        print_output(result, fmt)
    except ValueError as e:
        print_error(str(e))
    except Exception as e:
        print_error(f"{type(e).__name__}: {e}")


@click.command("indicator-list")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def indicator_list(use_table: bool, output_fmt: str) -> None:
    """列出可用的技术指标。"""
    import pandas as pd

    from ..indicator import list_indicators
    from .output import print_output

    fmt = "table" if use_table else output_fmt
    info = list_indicators()
    df = pd.DataFrame(info)
    if fmt == "table":
        df["default_params"] = df["default_params"].apply(lambda d: str(d))
    print_output(df, fmt)
