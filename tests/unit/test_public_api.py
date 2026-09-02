"""公共 API 导出完整性测试 —— 防止 __all__ 与实际导出漂移（审计 #13）。

确保 easy_tdx.__all__ 中每个名字都能从顶层包成功导入，
且文档中描述的模型（FundFlow/MarketStat 等）确实可访问。

复审补充（L3）：进一步断言导出对象的**类型**，避免类名被意外绑成模块、
None、或常量。仅"可导入"不足以守住类型契约。
"""

from __future__ import annotations

import inspect

import easy_tdx

# 期望的导出契约：每个公共名字应对应的对象类型。
# - "class"    → 必须 inspect.isclass（client / 枚举 / 数据模型 / 异常）
# - "func"     → 必须 callable 且非 class（ping_* / save_best_*）
# - "constant" → 兜底（KNOWN_HOSTS / XDXR_CATEGORY_NAMES 等映射表或常量）
_EXPECTED_KIND: dict[str, str] = {
    # client 类
    "TdxClient": "class",
    "AsyncTdxClient": "class",
    "MacClient": "class",
    "AsyncMacClient": "class",
    "MacExClient": "class",
    "AsyncMacExClient": "class",
    "ExTdxClient": "class",
    "AsyncExTdxClient": "class",
    "UnifiedTdxClient": "class",
    "AsyncUnifiedTdxClient": "class",
    # 枚举
    "Market": "class",
    "KlineCategory": "class",
    "Adjust": "class",
    "BoardSortColumn": "class",
    "BoardType": "class",
    "Category": "class",
    "ExMarket": "class",
    "FilterType": "class",
    "Period": "class",
    "SortOrder": "class",
    "SortType": "class",
    # 数据模型
    "SecurityBar": "class",
    "SecurityQuote": "class",
    "SecurityInfo": "class",
    "MinuteBar": "class",
    "TransactionRecord": "class",
    "XdxrRecord": "class",
    "FinanceInfo": "class",
    "CompanyInfoCategory": "class",
    "FinancialFileInfo": "class",
    "FinancialRecord": "class",
    "TdxBlock": "class",
    "MarketStat": "class",
    "FundFlow": "class",
    "HistoricalFundFlow": "class",
    # 异常
    "TdxError": "class",
    "TdxConnectionError": "class",
    "TdxDecodeError": "class",
    "TdxCommandError": "class",
    # 函数
    "ping_all": "func",
    "ping_mac_all": "func",
    "save_best_host": "func",
    "save_best_ex_host": "func",
    # 常量 / 映射表
    "KNOWN_EX_HOSTS": "constant",
    "KNOWN_HOSTS": "constant",
    "CALC_HOSTS": "constant",
    "MAC_HOSTS": "constant",
    "XDXR_CATEGORY_NAMES": "constant",
    "UNUSUAL_TYPE_NAMES": "constant",
}


def test_all_names_are_importable() -> None:
    """__all__ 里每个名字都必须能从 easy_tdx 顶层获取到非 None 对象。"""
    missing = [name for name in easy_tdx.__all__ if getattr(easy_tdx, name, None) is None]
    assert missing == [], f"__all__ 中以下名字无法从 easy_tdx 导入: {missing}"


def test_expected_kind_contract_is_complete() -> None:
    """_EXPECTED_KIND 必须覆盖 __all__ 的每个名字，否则契约会悄悄漂移（审计复审 L3）。"""
    covered = set(_EXPECTED_KIND)
    exported = set(easy_tdx.__all__)
    missing_kind = exported - covered
    extra_kind = covered - exported
    assert not missing_kind, f"以下导出未在 _EXPECTED_KIND 中声明类型契约: {sorted(missing_kind)}"
    assert not extra_kind, f"_EXPECTED_KIND 含未导出的名字（已移除？）: {sorted(extra_kind)}"


def test_exported_objects_have_expected_type() -> None:
    """断言每个导出对象的类型符合契约（审计复审 L3）。

    防止类名被绑成模块/None/常量——仅"可导入"不足以守住类型。
    """
    wrong: list[str] = []
    for name, kind in _EXPECTED_KIND.items():
        obj = getattr(easy_tdx, name, None)
        if obj is None:
            wrong.append(f"{name}: 不应为 None")
            continue
        if kind == "class":
            if not inspect.isclass(obj):
                wrong.append(f"{name}: 期望 class，实际 {type(obj).__name__}")
        elif kind == "func":
            # callable 但不能是 class（避免类被当成函数）
            if not callable(obj) or inspect.isclass(obj):
                wrong.append(f"{name}: 期望 function，实际 {type(obj).__name__}")
        # "constant" 兜底，不做严格断言
    assert wrong == [], "导出对象类型契约违反: \n" + "\n".join(wrong)


def test_documented_models_exported() -> None:
    """api_reference.md 文档描述的模型必须在公共导出中（审计 #13）。"""
    for name in ("FundFlow", "MarketStat", "HistoricalFundFlow", "TdxBlock"):
        assert name in easy_tdx.__all__, f"{name} 应在 easy_tdx.__all__ 中"
        assert inspect.isclass(getattr(easy_tdx, name)), f"{name} 应是类"


def test_core_clients_exported() -> None:
    """8 个 client 类与门面都应导出且确实是类（审计 #13 + 复审 L3）。"""
    for name in (
        "TdxClient",
        "AsyncTdxClient",
        "MacClient",
        "AsyncMacClient",
        "ExTdxClient",
        "AsyncExTdxClient",
        "MacExClient",
        "AsyncMacExClient",
        "UnifiedTdxClient",
        "AsyncUnifiedTdxClient",
    ):
        assert name in easy_tdx.__all__, f"{name} 应在 easy_tdx.__all__ 中"
        assert inspect.isclass(getattr(easy_tdx, name)), f"{name} 应是类"
