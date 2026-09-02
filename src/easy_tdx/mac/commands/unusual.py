"""异动数据查询（0x1237）。"""

import struct
from datetime import time

from ..._binary import unpack_from
from ...codec.mac_frame import build_mac_request
from ...commands.base import BaseCommand
from ..models import UnusualItem

# 异动类型 → 粗粒度名称映射（Issue #62）。
# 0x15/0x16/0x1D/0x1E 语义由 2026-09-01 全市场 12871 条实测锚定，详见
# docs/protocol-unknown-fields.md「市场异动（0x1237）异动类型」一节。
UNUSUAL_TYPE_NAMES: dict[int, str] = {
    0x03: "主力买入卖出",
    0x04: "加速拉升",
    0x05: "加速下跌",
    0x06: "低位反弹",
    0x07: "高位回落",
    0x08: "撑杆跳高",
    0x09: "平台跳水",
    0x0A: "单笔冲涨跌",
    0x0B: "区间放量",
    0x0C: "区间缩量",
    0x10: "大单托盘",
    0x11: "大单压盘",
    0x12: "大单锁盘",
    0x13: "竞价试盘",
    0x14: "涨跌停",
    0x15: "竞价/尾盘异动",
    0x16: "盘中强势弱势",
    0x1D: "急速拉升",
    0x1E: "急速下跌",
}


def _describe_unusual(unusual_type: int, data: bytes, hour: int = 9) -> tuple[str, str]:
    """根据异动类型解析描述和数值。hour 用于区分竞价/尾盘双时刻信号（0x15）。"""
    if len(data) < 13:
        return "", ""
    v1, v2, v3, v4 = struct.unpack_from("<B2fI", data)

    if unusual_type == 0x03:
        desc = f"主力{'买入' if v1 == 0x00 else '卖出'}"
        val = f"{v2:.2f}/{v3:.2f}"
    elif unusual_type == 0x04:
        desc = "加速拉升"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x05:
        desc = "加速下跌"
        val = ""
    elif unusual_type == 0x06:
        desc = "低位反弹"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x07:
        desc = "高位回落"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x08:
        desc = "撑杆跳高"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x09:
        desc = "平台跳水"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x0A:
        desc = f"单笔冲{'跌' if v2 < 0 else '涨'}"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x0B:
        direction = "平" if v3 == 0 else "跌" if v3 < 0 else "涨"
        desc = f"区间放量{direction}"
        val = f"{v2:.1f}倍" + ("" if v3 == 0 else f"{v3 * 100:.2f}%")
    elif unusual_type == 0x0C:
        desc = "区间缩量"
        val = ""
    elif unusual_type == 0x10:
        desc = "大单托盘"
        val = f"{v4:.2f}/{v3:.2f}"
    elif unusual_type == 0x11:
        desc = "大单压盘"
        val = f"{v2:.2f}/{v3:.2f}"
    elif unusual_type == 0x12:
        desc = "大单锁盘"
        val = ""
    elif unusual_type == 0x13:
        # 竞价试盘（09:15~09:20 触发）：v1=0x00 试买（申报价高于昨收）/ 0x01 试卖
        # （低于昨收）；v2 为申报价，v3 为竞价量（手）。方向规律 2026-09-02
        # 全量 552 条对照昨收 549 条一致（2 条恰等于昨收的边界 + 1 条异常）。
        if v1 == 0x01:
            desc = "竞价试卖"
        else:
            desc = "竞价试买"
        val = f"{v2:.2f}/{v3:.0f}手"
    elif unusual_type == 0x14:
        direction = "涨" if v1 == 0x00 else "跌"
        if len(data) >= 10:
            sub_type, v2_alt, v3_alt = struct.unpack_from("<Bff", data, 1)
        else:
            sub_type, v2_alt, v3_alt = 0, 0.0, 0.0
        if sub_type == 0x01:
            desc = f"逼近{direction}停"
        elif sub_type == 0x02:
            desc = f"封{direction}停板"
        elif sub_type == 0x04:
            desc = f"封{direction}大减"
        elif sub_type == 0x05:
            desc = f"打开{direction}停"
        else:
            desc = f"涨跌停({direction})"
        val = f"{v2_alt:.2f}/{v3_alt:.2f}"
    elif unusual_type == 0x15:
        # 竞价/尾盘异动：开盘竞价（09:25）与收盘（15:00）两个撮合时刻都会触发。
        # v1=0x02 拉升 / 0x03 下跌 / 0x01 平稳（±0.5% 分档）；v2 为时段尾段价格
        # 变动（相对昨收），v3 为该时段成交量（手）。
        stage = "竞价" if hour < 12 else "尾盘"
        if v1 == 0x02:
            desc = f"{stage}拉升"
        elif v1 == 0x03:
            desc = f"{stage}下跌"
        elif v1 == 0x01:
            desc = f"{stage}平稳"
        else:
            desc = f"{stage}异动"
        val = f"{v2 * 100:.2f}%/{v3:.0f}手"
    elif unusual_type == 0x16:
        # 盘中强势/弱势：v2 = 触发时涨跌幅（09:25 样本与开盘涨幅 49/49 精确一致），
        # v1 为带符号强弱等级（0x01~0x03 强势 1~3 级，0xFD~0xFF 弱势 1~3 级）。
        desc = "盘中强势" if v2 >= 0 else "盘中弱势"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x1D:
        desc = "急速拉升"
        val = f"{v2 * 100:.2f}%"
    elif unusual_type == 0x1E:
        desc = "急速下跌"
        val = f"{v2 * 100:.2f}%"
    else:
        desc = f"异动类型{unusual_type:#04x}"
        val = ""

    return desc, val


class UnusualCmd(BaseCommand[list[UnusualItem]]):
    """查询异动数据。

    Parameters
    ----------
    market : int
        市场代码。
    start : int
        起始偏移量。
    count : int
        请求数量（最大 600）。
    """

    def __init__(self, market: int, start: int = 0, count: int = 600) -> None:
        self._market = market
        self._start = start
        self._count = min(count, 600)

    def build_request(self) -> bytes:
        # H:market, H:start, 2x padding, H:count, 2x padding, 5×H monitoring params
        body = struct.pack(
            "<HH2xH2xH5H",
            self._market,
            self._start,
            self._count,
            1,  # monitor param 1
            200,  # monitor param 2
            30,  # monitor param 3
            40,  # monitor param 4
            50,  # monitor param 5
            200,  # monitor param 6
        )
        return build_mac_request(0x1237, body)

    def parse_response(self, body: bytes) -> list[UnusualItem]:
        (count,) = unpack_from("<H", body, 0, "unusual count")

        results: list[UnusualItem] = []
        for i in range(count):
            offset = 2 + i * 32
            if offset + 32 > len(body):
                break

            market, code_raw, _, unusual_type, _, index, _z = unpack_from(
                "<H6sBBBHH", body, offset, f"unusual record[{i}]"
            )

            hour, minute_sec = unpack_from("<BH", body, offset + 29, f"unusual time[{i}]")

            desc, value = _describe_unusual(unusual_type, body[offset + 15 : offset + 28], hour)

            results.append(
                UnusualItem(
                    index=index,
                    market=market,
                    code=code_raw.decode("gbk", errors="replace").rstrip("\x00"),
                    name="",  # populated below from text section
                    time=time(hour, minute_sec // 100, minute_sec % 100),
                    desc=desc,
                    value=value,
                    unusual_type=unusual_type,
                )
            )

        # Text section: stock names in GBK, comma-separated
        binary_length = 2 + count * 32
        text_bytes = body[binary_length:]
        text_list = text_bytes.decode("gbk", errors="ignore").strip(",").split(",")

        # Fill names from text section
        populated: list[UnusualItem] = []
        for i, item in enumerate(results):
            name = text_list[i] if i < len(text_list) else ""
            populated.append(
                UnusualItem(
                    index=item.index,
                    market=item.market,
                    code=item.code,
                    name=name,
                    time=item.time,
                    desc=item.desc,
                    value=item.value,
                    unusual_type=item.unusual_type,
                )
            )

        return populated
