"""easy-tdx CLI -- Agent 友好的通达信行情命令行工具。"""

from __future__ import annotations

import click

from ..backtest.cli import backtest, portfolio
from ..screen.cli import screen
from .cmd_admin import ping, version
from .cmd_announcement import announcement
from .cmd_auction import auction
from .cmd_board import (
    belong_board,
    board_change_ranking,
    board_list,
    board_members,
    board_ranking,
    board_summary,
)
from .cmd_capital import capital_flow
from .cmd_chanlun import chanlun
from .cmd_company import company_info, company_info_content, finance_info
from .cmd_crypto import crypto
from .cmd_ex import ex
from .cmd_factor import factor
from .cmd_finance import f10, fund_flow
from .cmd_indicator import indicator, indicator_list
from .cmd_info import server_info, symbol_info
from .cmd_kline import kline
from .cmd_monitor import market_stat, unusual
from .cmd_offline import offline
from .cmd_pfactor import pfactor
from .cmd_quote import quote, quote_list
from .cmd_run_all import run_all
from .cmd_tick import tick
from .cmd_transaction import transaction
from .cmd_web import serve


@click.group()
@click.version_option(
    version=__import__("importlib.metadata", fromlist=["version"]).version("easy-tdx"),
    prog_name="easy-tdx",
)
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
cli.add_command(announcement)
cli.add_command(kline)
cli.add_command(quote)
cli.add_command(quote_list)
cli.add_command(tick)
cli.add_command(transaction)
cli.add_command(auction)
cli.add_command(board_list)
cli.add_command(board_members)
cli.add_command(board_ranking)
cli.add_command(board_change_ranking)
cli.add_command(board_summary)
cli.add_command(belong_board)
cli.add_command(capital_flow)
cli.add_command(unusual)
cli.add_command(market_stat)
cli.add_command(server_info)
cli.add_command(symbol_info)
cli.add_command(f10)
cli.add_command(fund_flow)
cli.add_command(finance_info)
cli.add_command(company_info)
cli.add_command(company_info_content)
cli.add_command(ex)
cli.add_command(crypto)
cli.add_command(indicator)
cli.add_command(indicator_list)
cli.add_command(offline)
cli.add_command(chanlun)
cli.add_command(factor)
cli.add_command(pfactor)
cli.add_command(backtest)
cli.add_command(portfolio)
cli.add_command(run_all)
cli.add_command(screen)
cli.add_command(serve)
