"""加密货币命令（Binance 公共 API，现货）。"""

from __future__ import annotations

import click


@click.group()
def crypto() -> None:
    """加密货币行情（Binance 现货，免费公共 API）。

    示例：

      easy-tdx crypto kline BTCUSDT --period 1d --table

      easy-tdx crypto price ETHUSDT --table
    """
    pass


@crypto.command()
@click.argument("symbol")
@click.option("--period", default="1d", help="周期: 1m/5m/15m/30m/1h/4h/1d/1w/1M 等")
@click.option("--count", default=500, type=int, help="K线数量（1..1000）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def kline(symbol: str, period: str, count: int, use_table: bool, output_fmt: str) -> None:
    """获取加密货币 K 线（OHLCV）。

    SYMBOL: 交易对，如 BTCUSDT（兼容 btc/usdt 写法）。
    """
    from ..crypto import CryptoClient
    from .output import print_output

    fmt = "table" if use_table else output_fmt
    df = CryptoClient().klines(symbol, interval=period, limit=count)
    print_output(df, fmt)


@crypto.command()
@click.argument("symbol")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def price(symbol: str, use_table: bool, output_fmt: str) -> None:
    """获取加密货币最新价。"""
    import pandas as pd

    from ..crypto import CryptoClient
    from .output import print_output

    fmt = "table" if use_table else output_fmt
    p = CryptoClient().ticker_price(symbol)
    df = pd.DataFrame([{"symbol": symbol.upper(), "price": p}])
    print_output(df, fmt)
