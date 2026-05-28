"""easy-tdx CLI -- Agent 友好的通达信行情命令行工具。"""

from __future__ import annotations

import click

from .cmd_admin import ping, version
from .cmd_auction import auction
from .cmd_board import belong_board, board_list, board_members, board_ranking, board_summary
from .cmd_capital import capital_flow
from .cmd_ex import ex
from .cmd_finance import f10, fund_flow
from .cmd_info import server_info, symbol_info
from .cmd_indicator import indicator, indicator_list
from .cmd_kline import kline
from .cmd_monitor import market_stat, unusual
from .cmd_quote import quote, quote_list
from .cmd_tick import tick
from .cmd_transaction import transaction


@click.group()
@click.version_option(version="1.4.0", prog_name="easy-tdx")
def cli() -> None:
    """easy-tdx -- 通达信行情数据 CLI（默认 JSON 输出，适合 Agent 使用）。

    所有命令默认输出 JSON。使用 --table 切换为表格，--output 指定格式。

    示例：

      easy-tdx ping

      easy-tdx kline SZ 000001 --table

      easy-tdx quote "SZ 000001,SH 600519"

      easy-tdx quote-list A --count 20 --table
    """
    pass


cli.add_command(ping)
cli.add_command(version)
cli.add_command(kline)
cli.add_command(quote)
cli.add_command(quote_list)
cli.add_command(tick)
cli.add_command(transaction)
cli.add_command(auction)
cli.add_command(board_list)
cli.add_command(board_members)
cli.add_command(board_ranking)
cli.add_command(board_summary)
cli.add_command(belong_board)
cli.add_command(capital_flow)
cli.add_command(unusual)
cli.add_command(market_stat)
cli.add_command(server_info)
cli.add_command(symbol_info)
cli.add_command(f10)
cli.add_command(fund_flow)
cli.add_command(ex)
cli.add_command(indicator)
cli.add_command(indicator_list)
