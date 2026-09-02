"""MyTT.ZIG 之字转向指标单元测试（借鉴 Fork 移植，v1.29）。

覆盖：边界输入（空/单根/零阈值）、单调序列恒等、V 型反转拐点标定、
阈值两种写法（5 与 0.05）等价、输出形状与有限性。
"""

from __future__ import annotations

import numpy as np

from easy_tdx.MyTT import ZIG


def test_zig_empty_and_single():
    assert ZIG(np.array([]), 10).size == 0
    single = ZIG(np.array([42.0]), 10)
    assert single.shape == (1,) and single[0] == 42.0


def test_zig_zero_threshold_returns_self():
    s = np.array([1.0, 5.0, 2.0, 8.0])
    assert np.array_equal(ZIG(s, 0), s)


def test_zig_monotonic_series_identity():
    """单调序列无拐点，ZIG 退化为自身（RD 保留 3 位小数）。"""
    line = np.linspace(1.0, 2.0, 50)
    assert np.allclose(ZIG(line, 10), line, atol=1e-3)


def test_zig_v_shape_trough():
    """V 型反转：谷底被标为拐点，前后两段各自线性插值。"""
    v = np.concatenate([np.linspace(100.0, 80.0, 30), np.linspace(80.0, 120.0, 40)])
    z = ZIG(v, 5)
    assert z.shape == v.shape
    assert np.isfinite(z).all()
    assert abs(z[0] - 100) < 0.01
    assert abs(z[-1] - 120) < 0.01
    # 谷底（两个 80 中的后者，上升段起点）被精确对齐
    assert abs(z.min() - 80) < 0.01
    assert abs(z[30] - 80) < 0.01
    # 拐点间线性：下降段任意点是两端点的线性插值
    assert abs(z[15] - (100 + 80) / 2) < 0.01


def test_zig_threshold_forms_equivalent():
    s = 100 + 10 * np.sin(np.arange(80) / 6.0)
    assert np.allclose(ZIG(s, 5), ZIG(s, 0.05), atol=1e-9)


def test_zig_zigzag_alternating_peaks():
    """标准锯齿：每个预设峰谷都应成为拐点（ZIG 值在拐点处触及其价格）。"""
    seg = [10.0, 13.0, 10.0, 13.0, 10.0, 13.0]  # ±30% 摆动，阈值 10% 必转向
    s = np.array(seg)
    z = ZIG(s, 10)
    for i, price in enumerate(seg):
        assert abs(z[i] - price) < 0.01, f"锯齿序列每根都是拐点: idx={i}"


def test_zig_noisy_series_shape():
    rng = np.random.default_rng(7)
    s = 100 + np.cumsum(rng.normal(0, 1.5, 200))
    z = ZIG(s, 12)
    assert z.shape == s.shape
    assert np.isfinite(z).all()
    assert z.min() >= s.min() - 1e-3 and z.max() <= s.max() + 1e-3
