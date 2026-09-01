"""获取实时五档行情命令（最多 80 只/次）。

所有未知字段（unknown_N）保留原始解析值，供逆向分析。
"""

import struct

from .._binary import unpack_from
from ..codec.price import get_price
from ..codec.volume import get_volume
from ..exceptions import TdxDecodeError
from ..models.enums import Market
from ..models.quote import SecurityQuote
from .base import BaseCommand


def _price_decimal_digits(market: Market, code: str) -> int:
    """推断某证券报价的有效小数位数。

    通达信协议中，price 及各档差分按品种以「分」或「厘」为基本单位编码：
    股票/大盘指数 2 位（分；指数点位恒两位小数，如科创50 1647.53），
    ETF/基金/可转债/国债 3 位（厘）。
    若一律按 /100 解析，ETF 等品种价格会被放大 10 倍（见 Issue #8）；
    反之指数按 3 位解析会缩小 10 倍（见 2026-09 看板指数修复）。

    decimal_point 不在行情响应包内，只能凭 market + code 代码段推断。
    注意同一代码不同市场含义不同：SZ 000001=平安银行(股票,2位)，
    SH 000001=上证指数(3位)，故必须结合市场判断。

    Returns:
        2 或 3
    """
    code = (code or "").strip().rstrip("\x00")

    # 上海：5 开头为基金/国债，0/3/8/9 开头需看前缀
    if market == Market.SH:
        if code.startswith("5"):  # 51x ETF、55x 货币基金、56x 跨境ETF、58x 科创ETF
            return 3
        if code.startswith("000"):
            # 000001 上证指数、000300 沪深300、000688 科创50 等——指数系列。
            # 实测（2026-09-01）：这些指数的报价原始单位是「分」（÷100），
            # 点位恒为 2 位小数（科创50 1647.53 / 沪深300 4611.44）；
            # 按 3 位（厘）解析会缩小 10 倍。深市指数（39xxxx）走默认 2 位同理。
            return 2
        if code.startswith("880"):
            # 880xxx 统计指数（880005 涨跌家数等）：字段是计数语义，
            # market_stat 依赖 ÷1000 解码（price×10 还原家数），勿动。
            return 3
        if code.startswith("88"):
            # 881xxx 行业板块指数、885xxx 概念板块指数——同大盘指数，
            # 点位两位小数（实测 881106 种植业 1039.93，按 3 位曾缩成 103.993）。
            return 2
        return 2  # 60xxxx / 68xxxx 科创板 A 股

    # 深圳：1/3 开头的 15x/16x/18x 为基金，12x 为可转债，11x 为国债
    if market == Market.SZ:
        if code.startswith("1"):  # 159 ETF、163/165/166/167 基金、128 可转债、111/112/113 国债
            return 3
        if code.startswith("3"):  # 300/301 创业板（股票）
            return 2
        # 000/001/002/003 主板、中小板 A 股
        return 2

    # 北京：暂按 A 股 2 位处理
    return 2


def _format_server_time(raw: int) -> str:
    """将 reversed_bytes0 整数转换为 HH:MM:SS.mmm 字符串。

    该字段编码为“小时 + 百万分之一小时的小数部分”。
    例如：14999212 → "14:59:57.163"
    """
    hours, fractional_hour = divmod(raw, 1_000_000)
    total_millis = fractional_hour * 3600 // 1000
    minutes, remainder = divmod(total_millis, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


class GetSecurityQuotesCmd(BaseCommand[list[SecurityQuote]]):
    """批量获取实时行情（最多 80 只）。

    Args:
        stocks: [(market, code), ...] 列表
    """

    def __init__(self, stocks: list[tuple[Market, str]]) -> None:
        if not stocks:
            raise ValueError("stocks 不能为空")
        if len(stocks) > 80:
            raise ValueError("单次最多查询 80 只股票")
        self.stocks = stocks

    def build_request(self) -> bytes:
        n = len(self.stocks)
        payload_len = n * 7 + 12
        header = struct.pack(
            "<HIHHIIHH",
            0x010C,
            0x02006320,
            payload_len,
            payload_len,
            0x0005053E,
            0,
            0,
            n,
        )
        body = bytearray(header)
        for market, code in self.stocks:
            body.extend(struct.pack("<B6s", int(market), code.encode("utf-8")))
        return bytes(body)

    def parse_response(self, body: bytes) -> list[SecurityQuote]:
        pos = 0
        # pytdx 跳过前2字节（b1 cb 魔数）
        pos += 2
        (num,) = unpack_from("<H", body, pos, "security_quotes header")
        pos += 2

        results: list[SecurityQuote] = []

        for _ in range(num):
            record_start = pos

            market_b, code_b, active1 = unpack_from(
                "<B6sH",
                body,
                pos,
                "security_quotes record header",
            )
            pos += 9

            price_raw, pos = get_price(body, pos)
            last_close_diff, pos = get_price(body, pos)
            open_diff, pos = get_price(body, pos)
            high_diff, pos = get_price(body, pos)
            low_diff, pos = get_price(body, pos)

            # unknown_0: 服务器时间戳原始整数（get_price 解码）
            unknown_0, pos = get_price(body, pos)
            # unknown_1: 通常等于 -price_raw（pytdx 注释推测）
            unknown_1, pos = get_price(body, pos)

            vol, pos = get_price(body, pos)
            cur_vol, pos = get_price(body, pos)

            amount, _ = get_volume(body, pos)
            pos += 4

            s_vol, pos = get_price(body, pos)
            b_vol, pos = get_price(body, pos)

            unknown_2, pos = get_price(body, pos)  # IndexOpenAmount(指数)/舍入残差(个股)
            unknown_3, pos = get_price(body, pos)  # StockOpenAmount(个股)/负值(指数)

            # 五档买盘
            bid1_d, pos = get_price(body, pos)
            ask1_d, pos = get_price(body, pos)
            bv1, pos = get_price(body, pos)
            av1, pos = get_price(body, pos)

            bid2_d, pos = get_price(body, pos)
            ask2_d, pos = get_price(body, pos)
            bv2, pos = get_price(body, pos)
            av2, pos = get_price(body, pos)

            bid3_d, pos = get_price(body, pos)
            ask3_d, pos = get_price(body, pos)
            bv3, pos = get_price(body, pos)
            av3, pos = get_price(body, pos)

            bid4_d, pos = get_price(body, pos)
            ask4_d, pos = get_price(body, pos)
            bv4, pos = get_price(body, pos)
            av4, pos = get_price(body, pos)

            bid5_d, pos = get_price(body, pos)
            ask5_d, pos = get_price(body, pos)
            bv5, pos = get_price(body, pos)
            av5, pos = get_price(body, pos)

            # 尾部：2字节 H（交易状态标志，0x8020=停牌）+ 4个 get_price + 2字节 h + 2字节 H
            (trading_status,) = unpack_from("<H", body, pos, "security_quotes tail flag")
            pos += 2
            unknown_5, pos = get_price(body, pos)
            unknown_6, pos = get_price(body, pos)
            unknown_7, pos = get_price(body, pos)
            unknown_8, pos = get_price(body, pos)
            rise_speed_raw, active2 = unpack_from(
                "<hH",
                body,
                pos,
                "security_quotes tail",
            )
            pos += 4

            try:
                market = Market(market_b)
            except ValueError as e:
                raise TdxDecodeError(f"security_quotes 非法 market 值: {market_b}") from e

            code = code_b.decode("utf-8").rstrip("\x00")
            # 价格按品种有效小数位解析：股票/大盘指数 ÷100，ETF/基金/债券/880 统计指数 ÷1000（Issue #8）
            divisor = 10 ** _price_decimal_digits(market, code)
            p = price_raw / divisor

            results.append(
                SecurityQuote(
                    market=market,
                    code=code,
                    price=p,
                    pre_close=(price_raw + last_close_diff) / divisor,
                    open=(price_raw + open_diff) / divisor,
                    high=(price_raw + high_diff) / divisor,
                    low=(price_raw + low_diff) / divisor,
                    vol=float(vol),
                    cur_vol=float(cur_vol),
                    amount=amount,
                    s_vol=float(s_vol),
                    b_vol=float(b_vol),
                    active1=active1,
                    active2=active2,
                    bid1=(price_raw + bid1_d) / divisor,
                    bid_vol1=float(bv1),
                    bid2=(price_raw + bid2_d) / divisor,
                    bid_vol2=float(bv2),
                    bid3=(price_raw + bid3_d) / divisor,
                    bid_vol3=float(bv3),
                    bid4=(price_raw + bid4_d) / divisor,
                    bid_vol4=float(bv4),
                    bid5=(price_raw + bid5_d) / divisor,
                    bid_vol5=float(bv5),
                    ask1=(price_raw + ask1_d) / divisor,
                    ask_vol1=float(av1),
                    ask2=(price_raw + ask2_d) / divisor,
                    ask_vol2=float(av2),
                    ask3=(price_raw + ask3_d) / divisor,
                    ask_vol3=float(av3),
                    ask4=(price_raw + ask4_d) / divisor,
                    ask_vol4=float(av4),
                    ask5=(price_raw + ask5_d) / divisor,
                    ask_vol5=float(av5),
                    rise_speed=rise_speed_raw / 100.0,
                    limit_up=None,
                    limit_down=None,
                    decimal_point=_price_decimal_digits(market, code),
                    unknown_2=unknown_2,
                    unknown_3=unknown_3,
                    unknown_5=unknown_5,
                    unknown_6=unknown_6,
                    unknown_7=unknown_7,
                    unknown_8=unknown_8,
                    server_time=_format_server_time(unknown_0),
                    trading_status=trading_status,
                    open_amount=unknown_3 * 100.0,
                    _raw=body[record_start:pos],
                )
            )

        return results
