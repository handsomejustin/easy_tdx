"""成分股/排行报价分页合并顺序回归测试。

真实 bug（v1.32.x）：BoardMembersQuotesCmd 分页合并曾用 ``batch + all_quotes``
前插，而协议 ``start=0`` 返回排序后**最前**的一页——多页时整表被按页倒序拼接：
成分股超过单页 80 只的板块（如半导体 SH881319），弹窗涨跌幅榜从第 81 名开头，
前 80 名被压到后面，肉眼即"乱序"。

本测试钉死：多页合并必须按请求顺序追加，且 start 偏移正确推进。
"""

from unittest.mock import patch

import pytest

from easy_tdx.mac.client import AsyncMacClient, MacClient
from easy_tdx.mac.enums import SortOrder, SortType
from easy_tdx.mac.models import MacQuoteField

_TOTAL = 100  # 超过单页 80，触发两页


def _make_rows(start: int, n: int) -> list[MacQuoteField]:
    """模拟服务器：按涨跌幅降序返回第 start..start+n 名。"""

    def code(i: int) -> str:
        return f"{600000 + i:06d}"

    return [
        MacQuoteField(
            market=1,
            code=code(i),
            name=f"股{i}",
            fields={"change_pct": 10.0 - i * 0.2},
        )
        for i in range(start, start + n)
    ]


def _fake_execute_factory(seen: list):
    def fake_execute(cmd):
        seen.append(cmd)
        # 真实服务器按剩余行数返回（末页不足 page_size），模拟之
        n = min(cmd._page_size, _TOTAL - cmd._start)
        return _make_rows(cmd._start, n)

    return fake_execute


def test_board_members_pages_appended_in_order():
    """get_board_members 多页合并按页序追加：第 0 行=第 1 名，第 80 行=第 81 名。"""
    client = MacClient.__new__(MacClient)
    seen: list = []

    with patch.object(client, "_execute", side_effect=_fake_execute_factory(seen)):
        df = client.get_board_members(
            "881319",
            count=_TOTAL,
            sort_type=SortType.CHANGE_PCT,
            sort_order=SortOrder.DESC,
        )

    assert len(df) == _TOTAL
    assert df["code"].tolist() == [f"{600000 + i:06d}" for i in range(_TOTAL)]
    # 两页：start 0（80 行）→ start 80（20 行）
    assert [c._start for c in seen] == [0, 80]


@pytest.mark.asyncio
async def test_board_members_async_pages_appended_in_order():
    client = AsyncMacClient.__new__(AsyncMacClient)
    seen: list = []

    async def fake_execute(cmd):
        seen.append(cmd)
        return _make_rows(cmd._start, cmd._page_size)

    with patch.object(client, "_execute", side_effect=fake_execute):
        df = await client.get_board_members(
            "881319",
            count=_TOTAL,
            sort_type=SortType.CHANGE_PCT,
            sort_order=SortOrder.DESC,
        )

    assert df["code"].tolist() == [f"{600000 + i:06d}" for i in range(_TOTAL)]
    assert [c._start for c in seen] == [0, 80]


def test_quotes_list_pages_appended_in_order():
    """get_stock_quotes_list（看板涨跌榜数据源）同样按页序追加。"""
    client = MacClient.__new__(MacClient)
    seen: list = []

    with patch.object(client, "_execute", side_effect=_fake_execute_factory(seen)):
        df = client.get_stock_quotes_list(
            category=1,  # Category.A
            count=_TOTAL,
            sort_type=SortType.CHANGE_PCT,
            sort_order=SortOrder.DESC,
        )

    assert df["code"].tolist() == [f"{600000 + i:06d}" for i in range(_TOTAL)]
    assert [c._start for c in seen] == [0, 80]
