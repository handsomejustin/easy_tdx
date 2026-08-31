"""离线本地数据读写命令 —— 读取本地通达信数据文件 & 从服务端同步写入。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import click

if TYPE_CHECKING:
    import pandas as pd

    from ..client import TdxClient
    from ..models.bar import SecurityBar


@click.group()
def offline() -> None:
    """离线本地数据读写（读取本地通达信数据文件 & 从服务端同步写入）。

    读取需要本地已安装通达信并下载过对应数据。
    sync-daily 可从服务端获取最新日线并追加到本地 .day 文件。

    示例：

      easy-tdx offline home

      easy-tdx offline daily SZ 000001 --table

      easy-tdx offline min SH 600519 --type lc5 --table

      easy-tdx offline ex-files --table

      easy-tdx offline ex-daily 29#A1801 --table

      easy-tdx offline sync-daily SZ 000001

      easy-tdx offline sync-daily SH 600519 --vipdoc C:\\new_jyplug\\vipdoc
    """
    pass


@offline.command()
def home() -> None:
    """检测并显示通达信安装目录。"""
    from ..offline import detect_tdx_home

    tdx_home = detect_tdx_home()
    if tdx_home is None:
        click.echo("未检测到通达信安装目录，请设置 TDX_HOME 环境变量")
        raise SystemExit(1)
    click.echo(str(tdx_home))


@offline.command()
@click.argument("market")
@click.argument("code")
@click.option("--count", default=0, type=int, help="返回条数（0=全部）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def daily(
    market: str,
    code: str,
    count: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """读取 A 股日线数据（.day 文件）。

    MARKET: 市场代码（SZ/SH）
    CODE: 6 位股票代码

    示例：

      easy-tdx offline daily SZ 000001 --table

      easy-tdx offline daily SH 600519 --count 30 --table
    """
    import pandas as pd

    from .output import print_error, print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt

    try:
        from ..offline import find_daily_bar_file, read_daily_bars

        filepath = find_daily_bar_file(parse_market(market), code)
        bars = read_daily_bars(filepath)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)

    if not bars:
        click.echo("未读取到数据，请确认通达信已下载该股票的日线数据")
        raise SystemExit(0)

    rows = [
        {
            "datetime": f"{b.year}-{b.month:02d}-{b.day:02d}",
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "vol": b.vol,
            "amount": b.amount,
        }
        for b in (bars[-count:] if count > 0 else bars)
    ]
    print_output(pd.DataFrame(rows), fmt)


@offline.command()
@click.argument("market")
@click.argument("code")
@click.option(
    "--type",
    "bar_type",
    type=click.Choice(["5min", "lc1", "lc5"]),
    default="5min",
    help="分钟线类型: 5min(.5) / lc1(.lc1) / lc5(.lc5)",
)
@click.option("--count", default=0, type=int, help="返回条数（0=全部）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def min(
    market: str,
    code: str,
    bar_type: str,
    count: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """读取分钟线数据（.5 / .lc1 / .lc5 文件）。

    MARKET: 市场代码（SZ/SH）
    CODE: 6 位股票代码

    示例：

      easy-tdx offline min SZ 000001 --table

      easy-tdx offline min SH 600519 --type lc1 --count 100 --table
    """
    import pandas as pd

    from .output import print_error, print_output
    from .parsers import parse_market

    fmt = "table" if use_table else output_fmt

    try:
        from ..offline import read_5min_bars, read_lc_min_bars
        from ..offline.finders import find_5min_bar_file, find_lc1_bar_file, find_lc5_bar_file

        mkt = parse_market(market)
        if bar_type == "5min":
            filepath = find_5min_bar_file(mkt, code)
            bars = read_5min_bars(filepath)
        elif bar_type == "lc1":
            filepath = find_lc1_bar_file(mkt, code)
            bars = read_lc_min_bars(filepath)
        else:
            filepath = find_lc5_bar_file(mkt, code)
            bars = read_lc_min_bars(filepath)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)

    if not bars:
        click.echo("未读取到数据，请确认通达信已下载该股票的分钟线数据")
        raise SystemExit(0)

    rows = [
        {
            "datetime": f"{b.year}-{b.month:02d}-{b.day:02d} {b.hour:02d}:{b.minute:02d}",
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "vol": b.vol,
            "amount": b.amount,
        }
        for b in (bars[-count:] if count > 0 else bars)
    ]
    print_output(pd.DataFrame(rows), fmt)


@offline.command("ex-files")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
def ex_files(use_table: bool) -> None:
    """列出扩展市场可用的日线数据文件。

    文件位于 vipdoc/ds/lday/ 目录下。
    """
    import pandas as pd

    from ..offline.paths import detect_tdx_home
    from .output import print_error, print_output

    fmt = "table" if use_table else "json"

    tdx_home = detect_tdx_home()
    if tdx_home is None:
        print_error("未检测到通达信安装目录，请设置 TDX_HOME 环境变量")
        raise SystemExit(1)

    lday_dir = tdx_home / "vipdoc" / "ds" / "lday"
    if not lday_dir.is_dir():
        print_error(f"扩展市场目录不存在: {lday_dir}")
        raise SystemExit(1)

    files = sorted(lday_dir.glob("*.day"))
    if not files:
        click.echo("扩展市场目录为空，请在通达信中下载扩展市场数据")
        raise SystemExit(0)

    rows = [{"filename": f.name, "size_kb": round(f.stat().st_size / 1024, 1)} for f in files]
    print_output(pd.DataFrame(rows), fmt)


@offline.command("ex-daily")
@click.argument("filename")
@click.option("--count", default=0, type=int, help="返回条数（0=全部）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def ex_daily(
    filename: str,
    count: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """读取扩展市场日线数据（期货/港股/外盘）。

    FILENAME: 文件名（如 29#A1801）或完整路径

    示例：

      easy-tdx offline ex-daily 29#A1801 --table

      easy-tdx offline ex-daily 12#A_IXIC --count 30 --table
    """
    from pathlib import Path

    import pandas as pd

    from ..offline import read_ex_daily_bars
    from ..offline.paths import detect_tdx_home
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt

    filepath = Path(filename)
    if not filepath.is_file():
        # 路径穿越防护（审计 #16）：仅当 filename 是裸文件名（不含路径分隔符 / \ 与
        # 父目录引用 ..）时，才允许拼接到 vipdoc 目录下，防止 "../foo" 写出目录之外。
        # 允许通达信扩展行情文件名的常见字符（含 #，如 "29#A1801"、"12#A_IXIC"）。
        if re.search(r"[\\/]|(\.\.)", filename):
            raise click.BadParameter("filename 禁止包含路径分隔符(/ \\)或父目录引用(..)")
        tdx_home = detect_tdx_home()
        if tdx_home is not None:
            filepath = tdx_home / "vipdoc" / "ds" / "lday" / f"{filename}.day"

    try:
        bars = read_ex_daily_bars(filepath)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)

    if not bars:
        click.echo("未读取到数据，请确认文件存在且已下载对应数据")
        raise SystemExit(0)

    rows = [
        {
            "datetime": f"{b.year}-{b.month:02d}-{b.day:02d}",
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "amount": b.amount,
            "vol": b.vol,
            "settlement": b.settlement,
        }
        for b in (bars[-count:] if count > 0 else bars)
    ]
    print_output(pd.DataFrame(rows), fmt)


@offline.command()
@click.argument("filepath")
@click.option("--count", default=0, type=int, help="返回条数（0=全部）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def gbbq(
    filepath: str,
    count: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """读取股本变迁数据（gbbq 文件）。

    FILEPATH: gbbq 文件路径

    示例：

      easy-tdx offline gbbq C:\\new_jyplug\\T0002\\hq_cache\\gbbq --table
    """
    import pandas as pd

    from ..offline import read_gbbq
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt

    try:
        records = read_gbbq(filepath)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)

    if not records:
        click.echo("未读取到数据")
        raise SystemExit(0)

    rows = [
        {
            "market": r.market,
            "code": r.code,
            "datetime": r.datetime,
            "category": r.category,
            "hongli_panqianliutong": r.hongli_panqianliutong,
            "peigujia_qianzongguben": r.peigujia_qianzongguben,
            "songgu_qianzongguben": r.songgu_qianzongguben,
            "peigu_houzongguben": r.peigu_houzongguben,
        }
        for r in (records[-count:] if count > 0 else records)
    ]
    print_output(pd.DataFrame(rows), fmt)


@offline.command()
@click.argument("filepath")
@click.option("--count", default=0, type=int, help="返回条数（0=全部）")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def financial(
    filepath: str,
    count: int,
    use_table: bool,
    output_fmt: str,
) -> None:
    """读取历史财务数据（gpcw*.dat / gpcw*.zip）。

    FILEPATH: 财务数据文件路径

    示例：

      easy-tdx offline financial C:\\new_jyplug\\vipdoc\\sz\\gpcw.zip --count 5 --table
    """
    import pandas as pd

    from ..offline import read_history_financial
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt

    try:
        records = read_history_financial(filepath)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)

    if not records:
        click.echo("未读取到数据")
        raise SystemExit(0)

    display = records[-count:] if count > 0 else records
    rows = [
        {
            "code": r.code,
            "market": r.market.value,
            "report_date": r.report_date,
        }
        for r in display
    ]
    print_output(pd.DataFrame(rows), fmt)


@offline.command()
@click.argument("block_dir")
@click.option("--table", "use_table", is_flag=True, help="表格输出")
@click.option("--output", "output_fmt", type=click.Choice(["json", "table", "csv"]), default="json")
def blocks(
    block_dir: str,
    use_table: bool,
    output_fmt: str,
) -> None:
    """读取自定义板块数据。

    BLOCK_DIR: 自定义板块目录路径（如 C:\\new_jyplug\\T0002\\blocknew）

    示例：

      easy-tdx offline blocks C:\\new_jyplug\\T0002\\blocknew --table
    """
    import pandas as pd

    from ..offline import read_customer_blocks
    from .output import print_error, print_output

    fmt = "table" if use_table else output_fmt

    try:
        result = read_customer_blocks(block_dir)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)

    if not result:
        click.echo("未读取到板块数据")
        raise SystemExit(0)

    rows = [
        {
            "blockname": b.blockname,
            "type": b.block_type,
            "stock_count": len(b.codes),
            "codes": ",".join(b.codes[:10]) + ("..." if len(b.codes) > 10 else ""),
        }
        for b in result
    ]
    print_output(pd.DataFrame(rows), fmt)


# ---------------------------------------------------------------------------
# sync-daily：从服务端同步日线到本地 .day 文件
# ---------------------------------------------------------------------------


def _df_to_bars(df: pd.DataFrame) -> list[SecurityBar]:
    """将日线 DataFrame 转换为 SecurityBar 列表（按日期升序）。"""
    from ..models.bar import SecurityBar

    bars: list[SecurityBar] = []
    for _, row in df.iterrows():
        dt = row["date"]
        bars.append(
            SecurityBar(
                open=row["open"],
                close=row["close"],
                high=row["high"],
                low=row["low"],
                vol=row["vol"],
                amount=row["amount"],
                year=dt.year,
                month=dt.month,
                day=dt.day,
                hour=0,
                minute=0,
            )
        )
    bars.sort(key=lambda b: b.year * 10000 + b.month * 100 + b.day)
    return bars


def _is_index_code(exchange: str, code: str) -> bool:
    """根据市场和代码前缀判断是否为指数。

    指数需要调用 get_index_bars()（服务端响应每条记录多 4 字节），
    而非 get_security_bars()。
    """
    head = code[:2]
    if exchange == "sh":
        return head in ("00", "88", "99")
    if exchange == "sz":
        return head == "39"
    return False


def _fetch_all_daily_bars(
    client: TdxClient,
    market: int,
    code: str,
    need_full: bool = False,
    is_index: bool = False,
) -> list[SecurityBar]:
    """从服务端分页获取全部日线数据。

    Args:
        client: 已连接的 TdxClient。
        market: 市场代码（0=SZ, 1=SH）。
        code: 6 位股票代码。
        need_full: True 表示拉取全量历史（空文件场景），
                   False 表示只拉最近一页（增量更新）。
        is_index: True 表示指数，使用 get_index_bars()。

    Returns:
        SecurityBar 列表（按日期升序）。
    """
    from ..models.enums import KlineCategory, Market

    mkt = Market(market)
    fetch_fn = client.get_index_bars if is_index else client.get_security_bars

    all_bars: list[SecurityBar] = []
    start = 0
    page_size = 800
    max_pages = 50 if need_full else 1  # 50 页 = 40000 条，足够覆盖 A 股全部历史

    for _ in range(max_pages):
        df = fetch_fn(mkt, code, KlineCategory.DAY, start, page_size)
        if df.empty:
            break
        all_bars.extend(_df_to_bars(df))
        if len(df) < page_size:
            break  # 最后一页不满，已无更多数据
        start += page_size

    # 去重并按日期升序排列（跨页可能有重叠）
    seen: set[tuple[int, int, int]] = set()
    unique: list[SecurityBar] = []
    for b in all_bars:
        key = (b.year, b.month, b.day)
        if key not in seen:
            seen.add(key)
            unique.append(b)
    unique.sort(key=lambda b: b.year * 10000 + b.month * 100 + b.day)
    return unique


def _sync_one_daily(client: TdxClient, filepath: Path) -> tuple[int, str]:
    """同步单只股票日线，返回 (写入条数, 状态消息)。"""
    from ..offline import append_daily_bars, get_last_bar_date
    from ..offline.daily_bar import _SECURITY_COEFFICIENTS, _detect_security_type

    # 文件名 → 市场 + 代码
    name = filepath.name.lower()  # e.g. sh600000.day
    exchange = name[:2]  # "sh" or "sz"
    code = name[2:8]
    market = 1 if exchange == "sh" else 0  # Market.SH=1, Market.SZ=0

    # 判断是否需要全量拉取（空文件 → 全量，有数据 → 增量）
    last_date = get_last_bar_date(filepath)
    need_full = last_date is None

    # 判断是否为指数（指数需要 get_index_bars，响应格式不同）
    is_index = _is_index_code(exchange, code)

    # 从服务端分页获取日线
    bars = _fetch_all_daily_bars(client, market, code, need_full=need_full, is_index=is_index)
    if not bars:
        return 0, "服务端无数据"

    # 检测证券类型获取系数
    sec_type = _detect_security_type(filepath.name)
    price_coeff, vol_coeff = _SECURITY_COEFFICIENTS.get(sec_type, (0.01, 0.01))

    # 协议返回的成交量单位是股；encode_daily_bar 在 vol_coeff=0.01 时按 ×100
    # 写入（.day 原始字段为股，读取端 ×0.01 还原为手），故写入前须换算为手。
    # 否则日成交 > 4295 万股（如招商银行等大盘股）的 bar 会溢出 uint32。
    if vol_coeff == 0.01:
        for b in bars:
            b.vol /= 100

    # 追加写入
    written = append_daily_bars(filepath, bars, price_coeff, vol_coeff)
    if written > 0:
        return written, f"+{written}"
    return 0, "已是最新"


@offline.command("sync-daily")
@click.argument("market")
@click.argument("code")
@click.option("--vipdoc", default=None, help="vipdoc 目录路径（默认自动检测）")
def sync_daily(market: str, code: str, vipdoc: str | None) -> None:
    """从服务端同步日线数据到本地 .day 文件。

    自动检测本地文件末尾日期，从服务端分页获取缺失的数据并追加写入。
    空文件自动全量下载，已有数据只做增量更新。
    建议在通达信关闭时执行，避免文件被锁定。

    MARKET: 市场代码（SZ/SH）
    CODE: 6 位股票代码

    示例：

      easy-tdx offline sync-daily SZ 000001

      easy-tdx offline sync-daily SH 000001 --vipdoc C:\\new_jyplug\\vipdoc
    """
    from ..client import TdxClient
    from ..offline import find_daily_bar_file
    from .output import print_error
    from .parsers import parse_market

    mkt = parse_market(market)

    try:
        filepath = find_daily_bar_file(mkt, code, vipdoc)
        click.echo(f"目标文件: {filepath}")

        click.echo("正在连接服务端获取日线数据...")
        with TdxClient.from_best_host() as client:
            written, msg = _sync_one_daily(client, filepath)

        if written > 0:
            click.echo(f"✓ 成功写入 {written} 条新记录")
        else:
            click.echo(f"本地已是最新，无需写入 ({msg})")

    except PermissionError:
        click.echo(f"✗ 文件被锁定，请关闭通达信后重试: {filepath}", err=True)
        raise SystemExit(1)
    except Exception as e:
        print_error(str(e))
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# sync-all：一键同步全部日线
# ---------------------------------------------------------------------------


@offline.command("sync-all")
@click.option("--vipdoc", default=None, help="vipdoc 目录路径（默认自动检测）")
def sync_all(vipdoc: str | None) -> None:
    """一键同步全部本地日线数据（沪深全市场）。

    扫描 vipdoc 下所有 .day 文件，自动连接服务端获取最新数据并追加写入。
    建议在通达信关闭时执行，避免文件被锁定。

    示例：

      easy-tdx offline sync-all

      easy-tdx offline sync-all --vipdoc C:\\new_jyplug\\vipdoc
    """
    import time

    from ..client import TdxClient
    from ..offline.paths import resolve_vipdoc

    try:
        vipdoc_path = resolve_vipdoc(vipdoc)
    except Exception as e:
        click.echo(f"✗ {e}", err=True)
        raise SystemExit(1)

    # 1. 扫描所有 .day 文件
    all_files: list[Path] = []
    for exchange in ("sh", "sz"):
        lday_dir = vipdoc_path / exchange / "lday"
        if lday_dir.is_dir():
            all_files.extend(sorted(lday_dir.glob("*.day")))

    if not all_files:
        click.echo("未找到任何 .day 文件，请确认 vipdoc 路径正确")
        raise SystemExit(0)

    total = len(all_files)
    click.echo(f"发现 {total} 个 .day 文件，开始同步...")

    # 2. 连接服务端，逐个同步
    success = 0
    skipped = 0
    failed = 0
    total_written = 0

    with TdxClient.from_best_host() as client:
        for idx, filepath in enumerate(all_files, 1):
            name = filepath.name
            try:
                written, msg = _sync_one_daily(client, filepath)
                total_written += written
                if written > 0:
                    success += 1
                else:
                    skipped += 1
                click.echo(f"  [{idx}/{total}] {name}: {msg}")
            except PermissionError:
                failed += 1
                click.echo(f"  [{idx}/{total}] {name}: ✗ 文件被锁定", err=True)
            except Exception as e:
                failed += 1
                click.echo(f"  [{idx}/{total}] {name}: ✗ {e}", err=True)

            # 每 100 只暂停一小段，避免请求过快被服务器断开
            if idx % 100 == 0:
                time.sleep(0.2)

    # 3. 汇总
    click.echo("")
    summary = (
        f"同步完成: {total} 只 | "
        f"更新 {success} | 已是最新 {skipped} | "
        f"失败 {failed} | 共写入 {total_written} 条"
    )
    click.echo(summary)
