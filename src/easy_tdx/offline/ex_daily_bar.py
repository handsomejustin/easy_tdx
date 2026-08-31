"""扩展市场日线数据读取（期货、港股等 .day 文件）。"""

import struct
from dataclasses import dataclass, field
from pathlib import Path

from ..exceptions import TdxFileNotFoundError

# 日期(4B) 开盘(4Bf) 最高(4Bf) 最低(4Bf) 收盘(4Bf) 成交额(4Bf) 成交量(4B) 结算价(4Bf)
# 第 6 槽为 float32 成交额（元）：与标准市场 sh000300.day 实测对照一致
# （47#IF300 2023-09-11 第 6 槽 = 186871758848.0 元 = sh000300 同日 amount）。
_EX_DAILY_FMT = struct.Struct("<IfffffIf")


@dataclass
class ExDailyBar:
    """扩展市场日线（期货/港股等，含结算价）。

    amount 为成交额（元，float32），vol 为成交量（手，uint32）。
    """

    open: float
    high: float
    low: float
    close: float
    amount: float
    vol: int
    settlement: float
    year: int
    month: int
    day: int
    _raw: bytes = field(default=b"", repr=False, compare=False)


def read_ex_daily_bars(filepath: str | Path) -> list[ExDailyBar]:
    """从本地扩展市场 .day 文件读取日线数据。

    文件位于 vipdoc/ds/ 目录下，如 29#A1801.day。

    Args:
        filepath: .day 文件路径。

    Returns:
        ExDailyBar 列表（按时间升序）。
    """
    filepath = Path(filepath)
    if not filepath.is_file():
        raise TdxFileNotFoundError(f"扩展市场日线文件不存在: {filepath}")

    data = filepath.read_bytes()
    if len(data) < _EX_DAILY_FMT.size:
        return []

    results: list[ExDailyBar] = []
    record_size = _EX_DAILY_FMT.size

    for offset in range(0, len(data) - record_size + 1, record_size):
        raw = data[offset : offset + record_size]
        date_int, op, hi, lo, cl, amount, vol, settlement = _EX_DAILY_FMT.unpack(raw)

        year = date_int // 10000
        month = (date_int % 10000) // 100
        day = date_int % 100

        results.append(
            ExDailyBar(
                open=op,
                high=hi,
                low=lo,
                close=cl,
                amount=amount,
                vol=vol,
                settlement=settlement,
                year=year,
                month=month,
                day=day,
                _raw=raw,
            )
        )

    return results
