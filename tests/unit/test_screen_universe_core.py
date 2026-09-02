"""核心龙头池（screen/universe.py）与 universe="core" 过滤测试（v1.29）。"""

from __future__ import annotations

from pathlib import Path

from easy_tdx.screen.scanner import SignalScanner
from easy_tdx.screen.strength import StrengthRanker
from easy_tdx.screen.universe import CORE_LEADERS, core_leader_codes


class TestCoreLeadersData:
    def test_count_159_and_unique(self):
        assert len(CORE_LEADERS) == 159
        assert len(set(CORE_LEADERS)) == 159

    def test_all_six_digit_ashare_codes(self):
        for code in CORE_LEADERS:
            assert len(code) == 6 and code.isdigit(), code
            assert code[0] in ("0", "3", "6"), f"非沪深 A 股代码: {code}"

    def test_known_leaders_present(self):
        assert CORE_LEADERS.get("600519") == "贵州茅台"
        assert CORE_LEADERS.get("300750") == "宁德时代"
        assert CORE_LEADERS.get("002415") == "海康威视"

    def test_core_leader_codes(self):
        codes = core_leader_codes()
        assert isinstance(codes, set) and len(codes) == 159


def _make_vipdoc(tmp_path: Path) -> Path:
    """构造假 vipdoc（_detect_security_type 只看文件名，内容无关）。

    名单内：600519/300750/002415；名单外：600000/002999；指数：399001。
    """
    vipdoc = tmp_path / "vipdoc"
    for exchange, codes in [
        ("sh", ["600519", "600000"]),
        ("sz", ["300750", "002415", "002999", "399001"]),
    ]:
        lday = vipdoc / exchange / "lday"
        lday.mkdir(parents=True)
        for code in codes:
            (lday / f"{exchange}{code}.day").write_bytes(b"")
    return vipdoc


_EXPECTED_CORE = {"600519", "300750", "002415"}


class TestUniverseCoreFilter:
    def test_scanner_core_filters_to_leaders(self, tmp_path):
        scanner = SignalScanner(
            strategy_cls=object,  # _collect_files 不实例化策略
            vipdoc_path=_make_vipdoc(tmp_path),
        )
        codes = {code for _, _, code in scanner._collect_files("core")}
        assert codes == _EXPECTED_CORE  # 名单外 600000/002999 与指数 399001 均被排除

    def test_strength_core_filters_to_leaders(self, tmp_path):
        ranker = StrengthRanker(vipdoc_path=_make_vipdoc(tmp_path))
        codes = {code for _, _, code in ranker._collect_files("core")}
        assert codes == _EXPECTED_CORE

    def test_scanner_all_still_includes_non_leaders(self, tmp_path):
        scanner = SignalScanner(strategy_cls=object, vipdoc_path=_make_vipdoc(tmp_path))
        codes = {code for _, _, code in scanner._collect_files("all")}
        assert codes == {"600519", "600000", "300750", "002415", "002999"}
        assert "399001" not in codes  # 指数在任意 universe 下都被排除
