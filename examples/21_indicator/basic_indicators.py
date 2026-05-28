"""演示：技术指标计算。

通过 MacClient 的 get_stock_kline_with_indicators() 获取 K 线并直接计算技术指标。
内部自动获取 200+ 条历史数据进行 EMA 预热，仅返回最后 count 条结果。

也可单独使用 compute_indicators() 对已有的 K 线 DataFrame 计算指标。

支持的指标（30 个）:
    MACD  KDJ  RSI  BOLL  DMI  ATR  WR  CCI  BIAS  OBV
    VR  EMV  MFI  BRAR  ASI  TRIX  DPO  MTM  ROC  EXPMA
    BBI  PSY  DFMA  CR  KTN  XSII  MASS  TAQ

参数:
    market     -- 市场代码（Market.SH=1, Market.SZ=0）
    code       -- 股票代码
    indicators -- 指标名称列表（不区分大小写），如 ["MACD", "KDJ"]
    count      -- 返回条数（默认 30）
    adjust     -- 复权方式（默认 QFQ 前复权，技术分析推荐前复权）
    params     -- 可选参数覆盖，如 {"MACD": {"SHORT": 10}}

返回 DataFrame 列说明（以 MACD 为例）:
    datetime    datetime  K 线时间
    open        float     开盘价
    high        float     最高价
    low         float     最低价
    close       float     收盘价
    vol         float     成交量
    amount      float     成交额
    MACD_DIF    float     MACD 的 DIF 线
    MACD_DEA    float     MACD 的 DEA 线
    MACD_HIST   float     MACD 柱状图（(DIF-DEA)*2）
"""

from easy_tdx import Adjust, MacClient, Market, Period

with MacClient.from_best_host() as c:
    # --- MACD（贵州茅台，日线，前复权）---
    print("=== MACD（贵州茅台 600519）===")
    df = c.get_stock_kline_with_indicators(
        Market.SH,
        "600519",
        indicators=["MACD"],
        count=10,
    )
    print(df[["datetime", "close", "MACD_DIF", "MACD_DEA", "MACD_HIST"]].to_string(index=False))

    # --- KDJ（平安银行）---
    print("\n=== KDJ（平安银行 000001）===")
    df = c.get_stock_kline_with_indicators(
        Market.SZ,
        "000001",
        indicators=["KDJ"],
        count=10,
    )
    print(df[["datetime", "close", "KDJ_K", "KDJ_D", "KDJ_J"]].to_string(index=False))

    # --- RSI（贵州茅台）---
    print("\n=== RSI（贵州茅台 600519，N=6 短周期）===")
    df = c.get_stock_kline_with_indicators(
        Market.SH,
        "600519",
        indicators=["RSI"],
        count=10,
        params={"RSI": {"N": 6}},
    )
    print(df[["datetime", "close", "RSI"]].to_string(index=False))

    # --- BOLL 布林带 ---
    print("\n=== BOLL 布林带（贵州茅台 600519）===")
    df = c.get_stock_kline_with_indicators(
        Market.SH,
        "600519",
        indicators=["BOLL"],
        count=10,
    )
    print(df[["datetime", "close", "BOLL_UPPER", "BOLL_MID", "BOLL_LOWER"]].to_string(index=False))

    # --- 多指标同时计算 ---
    print("\n=== MACD + KDJ + RSI + BOLL 联合计算 ===")
    df = c.get_stock_kline_with_indicators(
        Market.SH,
        "600519",
        indicators=["MACD", "KDJ", "RSI", "BOLL"],
        count=5,
    )
    cols = ["datetime", "close", "MACD_DIF", "KDJ_K", "RSI", "BOLL_UPPER", "BOLL_LOWER"]
    print(df[cols].to_string(index=False))

    # --- 仅输出指标列（不含 OHLCV）---
    print("\n=== 仅指标值（--no-ohlcv 模式）===")
    df = c.get_stock_kline_with_indicators(
        Market.SZ,
        "000001",
        indicators=["MACD", "RSI"],
        count=5,
    )
    indicator_cols = [
        c for c in df.columns if c not in ("open", "high", "low", "close", "vol", "amount")
    ]
    print(df[indicator_cols].to_string(index=False))

    # --- 分钟 K 线 + 指标 ---
    print("\n=== 5 分钟线 MACD（贵州茅台 600519）===")
    df = c.get_stock_kline_with_indicators(
        Market.SH,
        "600519",
        indicators=["MACD"],
        period=Period.MIN_5,
        count=5,
    )
    print(df[["datetime", "close", "MACD_DIF", "MACD_DEA", "MACD_HIST"]].to_string(index=False))

    # --- 使用 compute_indicators 独立计算 ---
    print("\n=== 独立使用 compute_indicators ===")
    from easy_tdx.indicator import compute_indicators

    raw_df = c.get_stock_kline(Market.SH, "600519", Period.DAILY, count=200, adjust=Adjust.QFQ)
    result = compute_indicators(raw_df, ["ATR", "CCI", "WR"], tail=5)
    print(result[["datetime", "close", "ATR", "CCI", "WR1", "WR2"]].to_string(index=False))

# 运行结果（示例）:
# === MACD（贵州茅台 600519）===
#             datetime   close  MACD_DIF  MACD_DEA  MACD_HIST
# 2025-05-02 00:00:00 1492.00     -4.12     -1.56      -5.12
# 2025-05-05 00:00:00 1485.00     -5.23     -2.29      -5.88
# 2025-05-06 00:00:00 1498.00     -4.56     -2.94      -3.24
# 2025-05-07 00:00:00 1510.00     -3.12     -3.18       0.11
# 2025-05-08 00:00:00 1505.00     -2.45     -3.03       1.16
# 2025-05-09 00:00:00 1505.00     -1.89     -2.80       1.82
# 2025-05-12 00:00:00 1498.00     -1.78     -2.60       1.64
# 2025-05-13 00:00:00 1510.00     -0.89     -2.26       2.74
# 2025-05-14 00:00:00 1509.00     -0.12     -1.83       3.42
# 2025-05-15 00:00:00 1521.00      1.23     -1.22       4.90
#
# === KDJ（平安银行 000001）===
#             datetime  close  KDJ_K  KDJ_D   KDJ_J
# 2025-05-02 00:00:00  12.45  65.32  58.76   78.44
# 2025-05-05 00:00:00  12.30  42.15  53.23   19.98
# 2025-05-06 00:00:00  12.58  71.23  59.23   95.24
# 2025-05-07 00:00:00  12.72  82.45  65.47  116.41
# 2025-05-08 00:00:00  12.65  74.56  67.29  89.11
# ...
