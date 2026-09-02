"""issue #64 验证脚本：指数 K 线 vol 字段语义核查（连真实服务器）。

结论（2026-09-02 实测，对照新浪实时行情与东方财富分钟K）：
  - 指数分钟线（MIN_1/3/5/15/30/60）：协议每条记录的两个 4 字节字段
    f1 ≈ f2/100、f2 = 成交额(元)。f1 是"成交额(百元)"而非成交量，
    真实分钟成交量不在报文中（东财 15:00 5min bar 实测 13,954,814 手，
    而协议 f1 返回 208,748,512 ≈ amount/100）。
  - 指数日线：f1 = 成交量(手)，与新浪实时行情一致（差值仅为自定义
    浮点解码噪声 ~1e-7）。日线路径正确。
  - 指数周/月/季/年：f1 = 真实成交量/100（本周三交易日日线 vol 合计
    1,666,668,288 手，周线 f1 = 16,666,683，恰好 ÷100）。
  - 附带发现：股票周/月线 f1 同样 = 真实vol/100（浦发 8/31-9/2 三日
    日线 vol 合计 269,388,528 股，周线 f1×100 = 269,388,500）；
    指数分时接口 vol 列 = 成交额(万元)（全日合计 ≈ 日成交额/10000）。

用法：python scripts/verify_issue64.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from easy_tdx.client import TdxClient  # noqa: E402
from easy_tdx.models.enums import KlineCategory, Market  # noqa: E402


def main() -> None:
    cl = TdxClient()
    cl.connect()
    try:
        print(f"{'调用':<44s} {'vol(返回)':>16s} {'amount(返回)':>18s} amt/vol")
        cases = [
            ("SH000001 MIN_5  (指数分钟, issue场景)", Market.SH, "000001", KlineCategory.MIN_5),
            ("SH000001 MIN_1  (指数分钟)", Market.SH, "000001", KlineCategory.MIN_1),
            ("SH000001 DAY    (指数日线, 正确)", Market.SH, "000001", KlineCategory.DAY),
            ("SH000001 WEEK   (指数周线, /100)", Market.SH, "000001", KlineCategory.WEEK),
            ("SH000001 MONTH  (指数月线, /100)", Market.SH, "000001", KlineCategory.MONTH),
            ("SZ399001 MIN_5  (深成指分钟)", Market.SZ, "399001", KlineCategory.MIN_5),
            ("SZ399006 MIN_5  (创业板指分钟)", Market.SZ, "399006", KlineCategory.MIN_5),
        ]
        for label, mkt, code, cat in cases:
            df = cl.get_index_bars(mkt, code, cat, 0, 1)
            r = df.iloc[-1]
            ratio = r["amount"] / r["vol"] if r["vol"] else float("nan")
            print(f"{label:<44s} {r['vol']:>16,.0f} {r['amount']:>18,.0f} {ratio:>10.2f}")

        # 分钟线 f1 与 amount/100 的偏差（仅剩解码噪声）
        df = cl.get_index_bars(Market.SH, "000001", KlineCategory.MIN_5, 0, 5)
        print("\n分钟线 f1 vs amount/100（应≈1.0，偏差为解码噪声）:")
        for _, r in df.iterrows():
            print(
                f"  {r['datetime']}  vol={r['vol']:>13,.0f}  amount/100={r['amount'] / 100:>13,.0f}"
                f"  比值={r['vol'] / (r['amount'] / 100):.8f}"
            )

        # 分时接口 vol 全日合计 ≈ 日成交额/10000（万元）
        mt = cl.get_minute_time_data(Market.SH, "000001")
        day = cl.get_index_bars(Market.SH, "000001", KlineCategory.DAY, 0, 1).iloc[-1]
        print(
            f"\n指数分时 vol 全日合计 = {mt['vol'].sum():,.0f}"
            f"  日成交额/10000 = {day['amount'] / 10000:,.0f}（≈成交额万元，非成交量）"
        )
    finally:
        cl.close()


if __name__ == "__main__":
    main()
