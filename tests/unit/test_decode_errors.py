"""坏包与解码异常回归测试。"""

from __future__ import annotations

import struct
from pathlib import Path

import pytest

from easy_tdx.codec.frame import FrameHeader, decompress_body
from easy_tdx.commands.company_info import GetCompanyInfoCategoryCmd
from easy_tdx.commands.security_bars import GetSecurityBarsCmd
from easy_tdx.commands.security_count import GetSecurityCountCmd
from easy_tdx.commands.xdxr_info import GetXdxrInfoCmd
from easy_tdx.exceptions import TdxDecodeError
from easy_tdx.models.enums import KlineCategory, Market

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_hex(name: str) -> bytes:
    return bytes.fromhex((FIXTURES / f"{name}.hex").read_text(encoding="utf-8").strip())


def test_security_count_truncated_raises_tdxdecodeerror() -> None:
    with pytest.raises(TdxDecodeError):
        GetSecurityCountCmd(Market.SH).parse_response(b"")


def test_company_info_category_truncated_raises_tdxdecodeerror() -> None:
    body = _load_hex("company_info_category")
    cmd = GetCompanyInfoCategoryCmd(Market.SH, "600000")

    with pytest.raises(TdxDecodeError):
        cmd.parse_response(body[:-10])


def test_xdxr_info_truncated_raises_tdxdecodeerror() -> None:
    body = _load_hex("xdxr_info")
    cmd = GetXdxrInfoCmd(Market.SH, "600000")

    with pytest.raises(TdxDecodeError):
        cmd.parse_response(body[:-10])


def test_frame_bad_zlib_raises_tdxdecodeerror() -> None:
    with pytest.raises(TdxDecodeError):
        decompress_body(FrameHeader(0, 0, 0, 4, 8), b"xxxx")


def test_frame_unzipsize_mismatch_raises_tdxdecodeerror() -> None:
    with pytest.raises(TdxDecodeError):
        decompress_body(FrameHeader(0, 0, 0, 3, 4), b"abc")


# --------------------------------------------------------------------------- #
# security_bars 残缺尾记录：服务器 ret_count 与 body 实际长度偶发不匹配
# （实测日志：SH600519 报"day datetime: 数据不足，需要 4 字节，偏移 2，
# 实际剩余 0 字节"）。修复策略是丢弃残缺尾记录、返回已解析的完整记录，
# 而不是让整批数据 500。
# --------------------------------------------------------------------------- #


def _make_day_record(yyyymmdd: int) -> bytes:
    """构造一条合法日线记录：4B datetime + 4 price(0x00) + 8B volume(0)。"""
    return struct.pack("<I", yyyymmdd) + b"\x00" * 4 + b"\x00\x00\x00\x00" * 2


def test_security_bars_truncated_tail_returns_partial_results() -> None:
    """ret_count=3 但 body 只够 1 条 + 残渣 → 返回 1 条，不抛异常。"""
    body = struct.pack("<H", 3) + _make_day_record(20240101) + b"\x00\x00"
    cmd = GetSecurityBarsCmd(Market.SZ, "000001", KlineCategory.DAY, 0, 800)
    bars = cmd.parse_response(body)
    assert len(bars) == 1
    assert (bars[0].year, bars[0].month, bars[0].day) == (2024, 1, 1)


def test_security_bars_ret_count_lies_returns_actual_count() -> None:
    """ret_count 撒大谎（说 100 条实际 2 条）→ 按 body 实际长度截断。"""
    body = struct.pack("<H", 100) + _make_day_record(20240101) + _make_day_record(20240102)
    cmd = GetSecurityBarsCmd(Market.SH, "600519", KlineCategory.DAY, 0, 800)
    bars = cmd.parse_response(body)
    assert len(bars) == 2


def test_security_bars_empty_body_returns_empty_list() -> None:
    """ret_count=0 → 空列表，不抛异常。"""
    cmd = GetSecurityBarsCmd(Market.SZ, "000001", KlineCategory.DAY, 0, 800)
    bars = cmd.parse_response(struct.pack("<H", 0))
    assert bars == []


def test_security_bars_complete_body_not_affected() -> None:
    """正常完整 body 不受 graceful degradation 影响（不能误伤）。"""
    body = struct.pack("<H", 2) + _make_day_record(20240101) + _make_day_record(20240102)
    cmd = GetSecurityBarsCmd(Market.SZ, "000001", KlineCategory.DAY, 0, 800)
    bars = cmd.parse_response(body)
    assert len(bars) == 2
    assert (bars[1].year, bars[1].month, bars[1].day) == (2024, 1, 2)
