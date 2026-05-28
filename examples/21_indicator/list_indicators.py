"""演示：列出所有可用技术指标及其参数。

使用 list_indicators() 查看所有支持的指标名称、输入需求、输出列和默认参数。
无需网络连接。
"""

from easy_tdx.indicator import list_indicators

indicators = list_indicators()

print(f"共 {len(indicators)} 个技术指标\n")

# 按所需输入列分组展示
groups: dict[str, list[dict]] = {}
for info in indicators:
    key = "+".join(info["inputs"])
    groups.setdefault(key, []).append(info)

for inputs, items in groups.items():
    print(f"── 输入: {inputs} {'─' * 50}")
    for item in items:
        params_str = (
            ", ".join(f"{k}={v}" for k, v in item["default_params"].items())
            if item["default_params"]
            else ""
        )
        outputs_str = ", ".join(item["outputs"])
        line = f"  {item['name']:<8} {item['description']}"
        if params_str:
            line += f"  (默认: {params_str})"
        print(line)
        print(f"           输出: {outputs_str}")
    print()

# 运行结果:
# 共 30 个技术指标
#
# ── 输入: close ──────────────────────────────────────────────────────────
#   MACD     MACD 指数平滑异同移动平均线  (默认: SHORT=12, LONG=26, M=9)
#            输出: MACD_DIF, MACD_DEA, MACD_HIST
#   RSI      RSI 相对强弱指标  (默认: N=24)
#            输出: RSI
#   BOLL     BOLL 布林带  (默认: N=20, P=2)
#            输出: BOLL_UPPER, BOLL_MID, BOLL_LOWER
#   ...
#
# ── 输入: close+high+low ────────────────────────────────────────────────
#   KDJ      KDJ 随机指标  (默认: N=9, M1=3, M2=3)
#            输出: KDJ_K, KDJ_D, KDJ_J
#   ...
