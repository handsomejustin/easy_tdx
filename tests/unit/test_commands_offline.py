"""离线 fixture 测试：将录制的原始 body 字节喂给各命令 parse_response，验证解析结果。

fixtures/ 目录下每个 .hex 文件是一次真实服务器响应的 body（已解压），
对应的 .json 文件记录关键预期值，供手工核对。
此测试文件直接断言解析结果，无需网络连接。
"""

from __future__ import annotations

import pathlib
import struct

FIXTURES = pathlib.Path(__file__).parent.parent / "fixtures"


def load_hex(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / f"{name}.hex").read_text(encoding="utf-8").strip())


# ---------------------------------------------------------------------------
# security_count
# ---------------------------------------------------------------------------


def test_security_count_parse():
    from easy_tdx.commands.security_count import GetSecurityCountCmd
    from easy_tdx.models.enums import Market

    body = load_hex("security_count")
    cmd = GetSecurityCountCmd(Market.SH)
    count = cmd.parse_response(body)

    assert isinstance(count, int)
    assert count > 0
    # 体积固定为 2 字节，结果与录制时完全一致
    assert count == 26885


# ---------------------------------------------------------------------------
# security_list
# ---------------------------------------------------------------------------


def test_security_list_parse():
    from easy_tdx.commands.security_list import GetSecurityListCmd
    from easy_tdx.models.enums import Market

    body = load_hex("security_list")
    cmd = GetSecurityListCmd(Market.SH, 0)
    records = cmd.parse_response(body)

    assert len(records) == 1000

    r0 = records[0]
    assert r0.code == "999999"
    assert r0.name == "上证指数"
    assert abs(r0.pre_close - 3966.171142578125) < 0.01

    # _raw present and non-empty for every record
    assert all(len(r._raw) > 0 for r in records)


def test_security_list_pre_close_uses_tdx_float_for_a_share():
    from easy_tdx.commands.security_list import GetSecurityListCmd
    from easy_tdx.models.enums import Market

    body = struct.pack("<H", 1) + struct.pack(
        "<6sH8s4sBI4s",
        b"600000",
        100,
        "\u6d66\u53d1\u94f6\u884c".encode("gbk"),
        b"\x00\x00\x00\x00",
        2,
        0x411B851F,
        b"\x00\x00\x00\x00",
    )

    record = GetSecurityListCmd(Market.SH, 24000).parse_response(body)[0]

    assert record.code == "600000"
    assert record.name == "浦发银行"
    assert abs(record.pre_close - 9.72) < 0.01


def test_security_list_gbk_no_crash():
    """Bug #2 修复验证：GBK 解码不崩溃，所有记录均有 code。"""
    from easy_tdx.commands.security_list import GetSecurityListCmd
    from easy_tdx.models.enums import Market

    body = load_hex("security_list")
    cmd = GetSecurityListCmd(Market.SH, 0)
    records = cmd.parse_response(body)
    assert all(r.code for r in records)


# ---------------------------------------------------------------------------
# security_bars
# ---------------------------------------------------------------------------


def test_security_bars_parse():
    from easy_tdx.commands.security_bars import GetSecurityBarsCmd
    from easy_tdx.models.enums import KlineCategory, Market

    body = load_hex("security_bars")
    cmd = GetSecurityBarsCmd(Market.SH, "600000", KlineCategory.DAY, 0, 5)
    bars = cmd.parse_response(body)

    assert len(bars) == 5

    b0 = bars[0]
    assert abs(b0.open - 10.25) < 0.01
    assert abs(b0.high - 10.25) < 0.01
    assert abs(b0.low - 10.08) < 0.01
    assert abs(b0.close - 10.12) < 0.01
    assert b0.vol > 0

    # OHLC sanity: high ≥ open,close,low; low ≤ open,close
    for bar in bars:
        assert bar.high >= bar.open - 0.001
        assert bar.high >= bar.close - 0.001
        assert bar.low <= bar.open + 0.001
        assert bar.low <= bar.close + 0.001
        assert bar.vol > 0
        assert len(bar._raw) > 0


def test_security_bars_truncated_drops_partial_last_record():
    """TDX 服务端偶发截断：响应头声称有 N 条，但末尾记录被切。

    解析器应丢弃残缺的末条，返回已成功解析的前若干条，而非整体抛 500。
    """
    from easy_tdx.commands.security_bars import GetSecurityBarsCmd
    from easy_tdx.models.enums import KlineCategory, Market

    body = load_hex("security_bars")  # 完整 5 条
    # 把最后一条的 body 切掉 3 字节 → 末条 zipday 4 字节不够，触发截断
    truncated = body[:-3]
    cmd = GetSecurityBarsCmd(Market.SH, "600000", KlineCategory.DAY, 0, 5)
    bars = cmd.parse_response(truncated)

    assert len(bars) == 4  # 前 4 条完整，末条残缺被丢弃


def test_security_bars_truncated_first_record_returns_empty():
    """若连第一条都无法解析（body 完全没有记录数据），返回空列表而非抛异常。

    v1.19.2 实测：SH600519 等正常股票偶发返回 ret_count>0 但 body 为空，
    服务器侧问题。v1.18.3 的容错有 ``if bars:`` 条件导致此场景仍 raise → 500，
    老人看到"取行情失败"。改为始终 return（空列表让前端分页重试比 500 好）。
    """
    from easy_tdx.commands.security_bars import GetSecurityBarsCmd
    from easy_tdx.models.enums import KlineCategory, Market

    body = load_hex("security_bars")
    # 构造 header 声称 5 条但 body 只有 header(2 字节)+1 字节 → 第一条就截断
    truncated = body[:3]
    # 强行把 ret_count 写成 5
    truncated = struct.pack("<H", 5) + truncated[2:]
    cmd = GetSecurityBarsCmd(Market.SH, "600000", KlineCategory.DAY, 0, 5)

    bars = cmd.parse_response(truncated)
    assert bars == []


# ---------------------------------------------------------------------------
# security_quotes
# ---------------------------------------------------------------------------


def test_security_quotes_parse():
    from easy_tdx.commands.security_quotes import GetSecurityQuotesCmd
    from easy_tdx.models.enums import Market

    body = load_hex("security_quotes")
    cmd = GetSecurityQuotesCmd([(Market.SH, "600000")])
    quotes = cmd.parse_response(body)

    assert len(quotes) == 1

    q = quotes[0]
    assert q.code == "600000"
    assert abs(q.pre_close - 9.93) < 0.01

    # unknown fields are captured (not discarded)
    assert hasattr(q, "unknown_2")
    assert hasattr(q, "unknown_3")
    assert hasattr(q, "unknown_5")
    assert hasattr(q, "unknown_6")
    assert hasattr(q, "unknown_7")
    assert hasattr(q, "unknown_8")
    assert hasattr(q, "rise_speed")
    assert len(q._raw) > 0

    # fixed values from frozen fixture
    assert q.unknown_2 == -1
    assert q.unknown_3 == 22694

    # confirmed semantic fields
    assert isinstance(q.trading_status, int)
    assert isinstance(q.open_amount, float)
    assert q.open_amount == 22694 * 100.0

    # 股票按 2 位小数（分）报价（Issue #8）
    assert q.decimal_point == 2


def _build_quote_record(market: int, code: str, price_raw: int) -> bytes:
    """构造一条 security_quotes 记录：仅 price_raw 有值，其余全置 0。

    price_raw 单位是「厘」(0.001 元)，由调用方按品种精度给出：
    股票=分(×100)，ETF/指数=厘(×1000)。
    """
    from easy_tdx.codec.price import put_price

    rec = struct.pack("<B6sH", market, code.encode(), 0)  # market, code, active1
    rec += put_price(price_raw)  # price_raw
    rec += put_price(0) * 4  # last_close/open/high/low diffs
    rec += put_price(0) * 2  # unknown_0, unknown_1
    rec += put_price(0) * 2  # vol, cur_vol
    rec += struct.pack("<I", 0)  # amount
    rec += put_price(0) * 2  # s_vol, b_vol
    rec += put_price(0) * 2  # unknown_2, unknown_3
    rec += put_price(0) * 20  # 5 档 bid/ask diffs + vols
    rec += struct.pack("<H", 0)  # trading_status
    rec += put_price(0) * 4  # unknown_5-8
    rec += struct.pack("<hH", 0, 0)  # rise_speed, active2
    return rec


def _build_quote_body(market: int, code: str, price_raw: int) -> bytes:
    return b"\xb1\xcb" + struct.pack("<H", 1) + _build_quote_record(market, code, price_raw)


def test_security_quotes_decimal_point_classification():
    """Issue #8 + 看板指数修复：价格小数位按 market+code 代码段推断。

    同一代码不同市场含义不同：SZ 000001=平安银行(股票,2位)，
    SH 000001=上证指数，故必须结合市场判断。
    大盘指数点位恒两位小数（2026-09-01 实测：科创50 1647.53、沪深300 4611.44、
    上证 3979.89），报价原始单位为「分」；曾按 3 位（厘）解析导致看板指数缩小 10 倍。
    """
    from easy_tdx.commands.security_quotes import _price_decimal_digits
    from easy_tdx.models.enums import Market

    # ETF / 基金 / 可转债 / 国债 / 880 统计指数 -> 3 位（厘）
    assert _price_decimal_digits(Market.SZ, "159922") == 3  # 深 ETF
    assert _price_decimal_digits(Market.SZ, "161725") == 3  # 深 LOF 基金
    assert _price_decimal_digits(Market.SZ, "128095") == 3  # 深 可转债
    assert _price_decimal_digits(Market.SZ, "111002") == 3  # 深 国债
    assert _price_decimal_digits(Market.SH, "510300") == 3  # 沪 ETF
    assert _price_decimal_digits(Market.SH, "511990") == 3  # 沪 货币基金
    assert _price_decimal_digits(Market.SH, "880005") == 3  # 统计指数（market_stat 依赖 3 位语义）

    # 大盘指数 -> 2 位（分，点位恒两位小数）
    assert _price_decimal_digits(Market.SH, "000001") == 2  # 上证指数
    assert _price_decimal_digits(Market.SH, "000300") == 2  # 沪深 300
    assert _price_decimal_digits(Market.SZ, "399001") == 2  # 深证成指

    # 股票 -> 2 位（分）
    assert _price_decimal_digits(Market.SZ, "000001") == 2  # 深主板（平安银行）
    assert _price_decimal_digits(Market.SZ, "002594") == 2  # 中小板
    assert _price_decimal_digits(Market.SZ, "300750") == 2  # 创业板
    assert _price_decimal_digits(Market.SH, "600000") == 2  # 沪主板
    assert _price_decimal_digits(Market.SH, "688981") == 2  # 科创板


def test_security_quotes_etf_price_not_inflated_10x():
    """Issue #8：ETF 价格必须按 3 位小数解析，不能仍被放大 10 倍。

    159922 现价 6.123 元 → price_raw=6123（厘）。错误地按 /100 解析会得到 61.23。
    """
    from easy_tdx.commands.security_quotes import GetSecurityQuotesCmd
    from easy_tdx.models.enums import Market

    body = _build_quote_body(int(Market.SZ), "159922", 6123)
    q = GetSecurityQuotesCmd([(Market.SZ, "159922")]).parse_response(body)[0]

    assert q.decimal_point == 3
    assert abs(q.price - 6.123) < 1e-9
    assert q.price < 10.0  # 不能是 61.23 这种被放大 10 倍的值


def test_security_quotes_stock_price_unchanged():
    """Issue #8 回归保护：股票仍按 2 位小数解析，行为不变。

    600000 现价 9.89 元 → price_raw=989（分）。
    """
    from easy_tdx.commands.security_quotes import GetSecurityQuotesCmd
    from easy_tdx.models.enums import Market

    body = _build_quote_body(int(Market.SH), "600000", 989)
    q = GetSecurityQuotesCmd([(Market.SH, "600000")]).parse_response(body)[0]

    assert q.decimal_point == 2
    assert abs(q.price - 9.89) < 1e-9


def test_security_quotes_index_price_2_digits():
    """看板指数修复：上证指数 SH000001 现价 3979.89 → 按 2 位小数（分）解析。

    实测（2026-09-01）：SH 000/880 系列 decimal_point 报 3，但 000 系大盘指数
    的原始单位是分。3123456 → 31234.56。
    """
    from easy_tdx.commands.security_quotes import GetSecurityQuotesCmd
    from easy_tdx.models.enums import Market

    body = _build_quote_body(int(Market.SH), "000001", 3123456)
    q = GetSecurityQuotesCmd([(Market.SH, "000001")]).parse_response(body)[0]

    assert q.decimal_point == 2
    assert abs(q.price - 31234.56) < 1e-6


# ---------------------------------------------------------------------------
# minute_time
# ---------------------------------------------------------------------------


def test_minute_time_parse():
    from easy_tdx.commands.minute_time import GetMinuteTimeDataCmd
    from easy_tdx.models.enums import Market

    body = load_hex("minute_time")
    cmd = GetMinuteTimeDataCmd(Market.SH, "600000")
    bars = cmd.parse_response(body)

    assert len(bars) == 240

    b0 = bars[0]
    assert isinstance(b0.price, float)
    assert isinstance(b0.vol, int)
    # Bug #5 fix: _unknown_1 is preserved, not discarded
    assert hasattr(b0, "_unknown_1")
    assert isinstance(b0._unknown_1, int)
    assert len(b0._raw) > 0

    # fixed values
    assert abs(b0.price - 0.01) < 0.001
    assert b0.vol == 48
    assert b0._unknown_1 == 54


# ---------------------------------------------------------------------------
# history_minute_time
# ---------------------------------------------------------------------------


def test_history_minute_time_parse():
    from easy_tdx.commands.minute_time import GetHistoryMinuteTimeDataCmd
    from easy_tdx.models.enums import Market

    body = load_hex("history_minute_time")
    cmd = GetHistoryMinuteTimeDataCmd(Market.SH, "600000", 20250108)
    bars = cmd.parse_response(body)

    assert len(bars) == 240

    b0 = bars[0]
    assert abs(b0.price - 10.29) < 0.01
    assert b0.vol == 10044
    assert hasattr(b0, "_unknown_1")
    assert len(b0._raw) > 0


# ---------------------------------------------------------------------------
# transaction (current day)
# ---------------------------------------------------------------------------


def test_transaction_parse():
    from easy_tdx.commands.transaction import GetTransactionDataCmd
    from easy_tdx.models.enums import Market

    body = load_hex("transaction")
    cmd = GetTransactionDataCmd(Market.SH, "600000", 0, 10)
    recs = cmd.parse_response(body)

    assert len(recs) == 10

    r0 = recs[0]
    assert r0.hour == 14
    assert r0.minute == 59
    assert abs(r0.price - 9.9) < 0.01
    assert r0.vol == 0

    # Bug #4 fix: unknown_last captured
    assert hasattr(r0, "unknown_last")
    assert len(r0._raw) > 0

    # buyorsell: 0=buy, 1=sell, 2=neutral, 8=auction — field is an int
    for r in recs:
        assert isinstance(r.buyorsell, int)


# ---------------------------------------------------------------------------
# history_transaction
# ---------------------------------------------------------------------------


def test_history_transaction_parse():
    from easy_tdx.commands.transaction import GetHistoryTransactionDataCmd
    from easy_tdx.models.enums import Market

    body = load_hex("history_transaction")
    cmd = GetHistoryTransactionDataCmd(Market.SH, "600000", 20250108, 0, 10)
    recs = cmd.parse_response(body)

    assert len(recs) == 10

    r0 = recs[0]
    assert r0.hour == 14
    assert r0.minute == 56
    assert abs(r0.price - 10.3) < 0.01
    assert r0.vol == 50

    assert hasattr(r0, "unknown_last")
    assert len(r0._raw) > 0

    for r in recs:
        assert isinstance(r.buyorsell, int)


# ---------------------------------------------------------------------------
# xdxr_info
# ---------------------------------------------------------------------------


def test_xdxr_info_parse():
    from easy_tdx.commands.xdxr_info import GetXdxrInfoCmd
    from easy_tdx.models.enums import Market

    body = load_hex("xdxr_info")
    cmd = GetXdxrInfoCmd(Market.SH, "600000")
    recs = cmd.parse_response(body)

    assert len(recs) == 87

    r0 = recs[0]
    assert r0.year == 1999
    assert r0.month == 11
    assert r0.day == 10
    assert r0.category == 5

    # Bug #1 fix: each record has a unique date (not all reading from body[:7])
    dates = {(r.year, r.month, r.day) for r in recs}
    assert len(dates) > 1, "All records have the same date — Bug #1 not fixed!"

    # category == 1 字段应已从“每10股”归一化为“每股”
    cash = next(r for r in recs if (r.year, r.month, r.day, r.category) == (2000, 7, 6, 1))
    assert abs(cash.fenhong - 0.15) < 1e-6

    bonus = next(r for r in recs if (r.year, r.month, r.day, r.category) == (2002, 8, 22, 1))
    assert abs(bonus.fenhong - 0.2) < 1e-6
    assert abs(bonus.songzhuangu - 0.5) < 1e-6

    assert all(len(r._raw) > 0 for r in recs)

    # share count decode: 通达信自定义浮点，单位万股，与 FinanceInfo.zong_guben/10000 一致
    stock_recs = [r for r in recs if 2 <= r.category <= 10]
    last = stock_recs[-1]
    # 最近一条 hou_zongguben ≈ 3_330_583.75 万股
    # 与 FinanceInfo.zong_guben 33_305_837_500 ÷ 10000 完全吻合
    assert last.hou_zongguben is not None
    assert abs(last.hou_zongguben - 3_330_583.75) < 1.0


def test_xdxr_info_category_1_normalizes_per_10_share_fields():
    from easy_tdx.commands.xdxr_info import GetXdxrInfoCmd
    from easy_tdx.models.enums import Market

    body = bytearray(b"\x00" * 9)
    body.extend(struct.pack("<H", 1))
    body.extend(struct.pack("<B6s", 1, b"600000"))
    body.extend(b"\x00")
    body.extend(struct.pack("<I", 20200102))
    body.extend(struct.pack("<B", 1))
    body.extend(struct.pack("<ffff", 2.0, 8.0, 5.0, 3.0))

    rec = GetXdxrInfoCmd(Market.SH, "600000").parse_response(bytes(body))[0]

    assert abs(rec.fenhong - 0.2) < 1e-6
    assert abs(rec.songzhuangu - 0.5) < 1e-6
    assert abs(rec.peigu - 0.3) < 1e-6
    assert abs(rec.peigujia - 8.0) < 1e-6


# ---------------------------------------------------------------------------
# finance_info
# ---------------------------------------------------------------------------


def test_finance_info_parse():
    from easy_tdx.commands.finance_info import GetFinanceInfoCmd
    from easy_tdx.models.enums import Market

    body = load_hex("finance_info")
    cmd = GetFinanceInfoCmd(Market.SH, "600000")
    info = cmd.parse_response(body)

    # Check key fields are present and reasonable
    assert info.liutong_guben > 0
    assert info.zong_guben > 0
    assert info.meigujing_zichan > 0

    # Fixed values from frozen fixture
    assert abs(info.liutong_guben - 33305837500.0) < 1e6
    assert abs(info.zong_guben - 33305837500.0) < 1e6
    assert abs(info.meigujing_zichan - 22.13) < 0.1

    assert len(info._raw) > 0


# ---------------------------------------------------------------------------
# company_info_category
# ---------------------------------------------------------------------------


def test_company_info_category_parse():
    from easy_tdx.commands.company_info import GetCompanyInfoCategoryCmd
    from easy_tdx.models.enums import Market

    body = load_hex("company_info_category")
    cmd = GetCompanyInfoCategoryCmd(Market.SH, "600000")
    cats = cmd.parse_response(body)

    assert len(cats) == 16

    c0 = cats[0]
    assert c0.name == "最新提示"
    assert c0.filename == "600000.txt"
    assert c0.start == 0
    assert c0.length == 11426


# ---------------------------------------------------------------------------
# company_info_content
# ---------------------------------------------------------------------------


def test_company_info_content_parse():
    from easy_tdx.commands.company_info import GetCompanyInfoContentCmd
    from easy_tdx.models.enums import Market

    body = load_hex("company_info_content")
    cmd = GetCompanyInfoContentCmd(Market.SH, "600000", "600000.txt", 0, 11426)
    text = cmd.parse_response(body)

    assert isinstance(text, str)
    assert len(text) == 8070
    assert "600000" in text
    assert "浦发银行" in text
