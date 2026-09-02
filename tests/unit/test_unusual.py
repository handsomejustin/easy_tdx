"""市场异动（0x1237）异动类型解析测试（Issue #62）。

背景实测（2026-09-01 午间，全市场 SH+SZ 共 12871 条）：
- 0x15 仅出现在 09:25:00~09:25:02（竞价撮合时刻），v1 为方向档
  （0x02 拉升 / 0x03 下跌 / 0x01 平稳，±0.5% 分档），v2 为竞价尾段
  价格变动（相对昨收，参考时刻收敛于 09:23:30~09:24:00），v3 为竞价
  匹配量（手，略小于最终撮合量）。pytdx2 把 0x15 标作"尾盘"与实测矛盾，
  系对 PC 推送协议枚举的错误类推。
- 0x16 全天分布，v2 为触发时涨跌幅：09:25 的 49 条样本与当日开盘涨幅
  （open/pre_close-1）49/49 精确一致；全时段与收盘涨跌幅符号一致率
  97%~100%。v1 为带符号强弱等级（0x01~0x03 强势、0xFD~0xFF 弱势，
  六组 v2 区间互不重叠且单调）。
- 0x1D / 0x1E 全天分布，v1 恒为 0x00 / 0x01（方向），v2 恒正 / 恒负
  （阈值下限 ±0.6%），v3 恒 0。
"""

import struct
from datetime import time

from easy_tdx import UNUSUAL_TYPE_NAMES
from easy_tdx.mac.commands.unusual import UnusualCmd, _describe_unusual


def _record(
    utype: int,
    data_hex: str,
    hour: int = 9,
    minute_sec: int = 2500,
    market: int = 1,
    code: str = "600551",
) -> bytes:
    """构造一条 32 字节异动记录（<H6sBBBHH> 头 + 13B 数据区 + 保留 + <BH> 时间）。"""
    return (
        struct.pack("<H6sBBBHH", market, code.encode("gbk"), 0, utype, 0, 1, 0)
        + bytes.fromhex(data_hex)
        + b"\x00"  # offset 28：全类型实测恒 0
        + struct.pack("<BH", hour, minute_sec)
    )


def _body(records: list[bytes]) -> bytes:
    text = ",".join("测试股" for _ in records)
    return struct.pack("<H", len(records)) + b"".join(records) + text.encode("gbk")


class TestDescribeUnusualKnownTypes:
    """既有 15 种类型（0x03~0x0C、0x10~0x14）解析不回归。"""

    def test_type_0x04(self):
        # 真实样本：605365 立达信 2026-09-01 09:35:11
        desc, val = _describe_unusual(0x04, bytes.fromhex("00b8d73d3d0000000000000000"))
        assert desc == "加速拉升"
        assert val == "4.63%"

    def test_unknown_type_fallback(self):
        desc, val = _describe_unusual(0x42, bytes.fromhex("00" * 13))
        assert desc == "异动类型0x42"
        assert val == ""


class TestType0x15:
    """0x15 竞价/尾盘异动（Issue #62）。

    双时刻信号：开盘竞价 09:25（当日 1191 条）与收盘 15:00:01~04（当日 86 条，
    SH 52 / SZ 29 / BJ 5）都触发；desc 按记录小时区分「竞价/尾盘」前缀。
    """

    def test_auction_drop(self):
        # 真实样本：600551 时代出版 09:25:00，v1=0x03 竞价下跌
        desc, val = _describe_unusual(0x15, bytes.fromhex("030c9846bc003e1d4700000000"))
        assert desc == "竞价下跌"
        assert val == "-1.21%/40254手"

    def test_auction_rise(self):
        # 真实样本：600127 金健米业 09:25:00，v1=0x02 竞价拉升（尾段自 10.84 冲至 12.05）
        desc, val = _describe_unusual(0x15, bytes.fromhex("0213d2cd3d00367b4700000000"))
        assert desc == "竞价拉升"
        assert val == "10.05%/64310手"

    def test_auction_flat(self):
        # 真实样本：600410 华胜天成 09:25:01，v1=0x01 竞价平稳（尾段价格未动）
        desc, val = _describe_unusual(0x15, bytes.fromhex("01000000000098a54500000000"))
        assert desc == "竞价平稳"
        assert val == "0.00%/5299手"

    def test_close_rise_uses_tail_prefix(self):
        # 真实样本：600123 15:00:01（收盘撮合时刻），v1=0x02 尾盘拉升
        desc, val = _describe_unusual(0x15, bytes.fromhex("027bb4dd3b0004a84500000000"), 15)
        assert desc == "尾盘拉升"
        assert val == "0.68%/5376手"

    def test_close_drop_uses_tail_prefix(self):
        # 真实样本：600221 15:00:01，v1=0x03 尾盘下跌
        desc, val = _describe_unusual(0x15, bytes.fromhex("03c10ffcbb839c274800000000"), 15)
        assert desc == "尾盘下跌"
        assert val == "-0.77%/171634手"

    def test_unknown_sub_type_falls_back(self):
        desc, _ = _describe_unusual(0x15, struct.pack("<B2fI", 0x77, 0.0, 100.0, 0))
        assert desc == "竞价异动"
        desc, _ = _describe_unusual(0x15, struct.pack("<B2fI", 0x77, 0.0, 100.0, 0), 15)
        assert desc == "尾盘异动"


class TestType0x16:
    """0x16 盘中强势/弱势（Issue #62 主体）。"""

    def test_strong_at_auction(self):
        # 真实样本：600551 时代出版 09:25:00，v2=+5.82% 与当日开盘涨幅精确一致
        desc, val = _describe_unusual(0x16, bytes.fromhex("010f506e3dcb846e3d00000000"))
        assert desc == "盘中强势"
        assert val == "5.82%"

    def test_weak_at_auction(self):
        # 真实样本：600683 京投发展 09:25:01，v1=0xFF（弱势 1 级），v2=-6.40%
        desc, val = _describe_unusual(0x16, bytes.fromhex("ffc71d83bd690383bd00000000"))
        assert desc == "盘中弱势"
        assert val == "-6.40%"

    def test_new_stock_no_limit(self):
        # 真实样本：601123 N马矿 09:25:00，新股无涨跌幅限制，v2=+245.86%
        desc, val = _describe_unusual(0x16, bytes.fromhex("03775a1d404a5b1d4000000000"))
        assert desc == "盘中强势"
        assert val == "245.86%"


class TestType0x13:
    """0x13 竞价试盘（2026-09-02 破译）。

    v1 为方向：0x00 试买（申报价高于昨收）/ 0x01 试卖（低于昨收）——552 条对照
    昨收 549 条一致；v2 为申报价、v3 为竞价量（手）。旧实现一律显示「竞价试买」，
    方向相反的一半记录描述错误。
    """

    def test_auction_test_buy(self):
        # 真实样本：603980 09:15:14，申报价 8.71 高于昨收 7.92（往上试）
        desc, val = _describe_unusual(0x13, bytes.fromhex("00295c0b41006c354600000000"))
        assert desc == "竞价试买"
        assert val == "8.71/11611手"

    def test_auction_test_sell(self):
        # 真实样本：603900 09:15:17，申报价 6.46 低于昨收 7.17（往下试）
        desc, val = _describe_unusual(0x13, bytes.fromhex("0152b8ce400000c94300000000"))
        assert desc == "竞价试卖"
        assert val == "6.46/402手"


class TestType0x1D0x1E:
    """0x1D 急速拉升 / 0x1E 急速下跌（Issue #62 顺带补齐）。"""

    def test_fast_rise(self):
        # 真实样本：605365 立达信 09:35:08
        desc, val = _describe_unusual(0x1D, bytes.fromhex("009d50843c0000000000000000"))
        assert desc == "急速拉升"
        assert val == "1.62%"

    def test_fast_fall(self):
        # 真实样本：601123 N马矿 09:35:03
        desc, val = _describe_unusual(0x1E, bytes.fromhex("019cd393bc0000000000000000"))
        assert desc == "急速下跌"
        assert val == "-1.80%"


class TestUnusualCmdParseResponse:
    def test_parse_new_types_end_to_end(self):
        body = _body(
            [
                _record(0x16, "010f506e3dcb846e3d00000000", 9, 2500),
                _record(0x15, "030c9846bc003e1d4700000000", 9, 2500),
                _record(0x1D, "009d50843c0000000000000000", 9, 3508),
                _record(0x1E, "019cd393bc0000000000000000", 9, 3503),
            ]
        )
        items = UnusualCmd(1, 0, 600).parse_response(body)
        assert len(items) == 4
        assert [i.desc for i in items] == ["盘中强势", "竞价下跌", "急速拉升", "急速下跌"]
        assert items[0].value == "5.82%"
        assert items[1].value == "-1.21%/40254手"
        assert items[0].time == time(9, 25, 0)
        assert items[2].time == time(9, 35, 8)
        assert items[0].unusual_type == 0x16
        assert all(i.name == "测试股" for i in items)

    def test_parse_close_record_names_tail_prefix(self):
        """15:00 的 0x15 记录端到端应得到「尾盘拉升」（真实收盘样本 600123）。"""
        rec = _record(0x15, "027bb4dd3b0004a84500000000", 15, 1)
        items = UnusualCmd(1, 0, 600).parse_response(_body([rec]))
        assert items[0].desc == "尾盘拉升"
        assert items[0].value == "0.68%/5376手"
        assert items[0].time == time(15, 0, 1)

    def test_record_layout_unchanged(self):
        """记录仍为 32 字节定长，时间槽位于 offset 29。"""
        rec = _record(0x16, "010f506e3dcb846e3d00000000", 14, 5701)
        assert len(rec) == 32
        items = UnusualCmd(1, 0, 600).parse_response(_body([rec]))
        assert items[0].time == time(14, 57, 1)


class TestTypeNames:
    def test_names_cover_all_described_types(self):
        """映射表应覆盖 _describe_unusual 的全部分支（0x03~0x0C、0x10~0x16、0x1D、0x1E）。"""
        assert set(UNUSUAL_TYPE_NAMES) == {
            *range(0x03, 0x0D),
            *range(0x10, 0x17),
            0x1D,
            0x1E,
        }

    def test_mapped_types_produce_named_desc(self):
        """映射表中的类型不应落入"异动类型0x??"兜底分支。"""
        zeros = bytes.fromhex("00" * 13)
        for utype in UNUSUAL_TYPE_NAMES:
            desc, _ = _describe_unusual(utype, zeros)
            assert not desc.startswith("异动类型"), f"0x{utype:02X} 未实现解析分支"

    def test_top_level_export(self):
        import easy_tdx

        assert easy_tdx.UNUSUAL_TYPE_NAMES is UNUSUAL_TYPE_NAMES
        assert UNUSUAL_TYPE_NAMES[0x16] == "盘中强势弱势"
