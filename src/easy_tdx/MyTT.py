# MyTT 麦语言-通达信-同花顺指标实现     https://github.com/mpquant/MyTT
# MyTT高级函数验证版本：               https://github.com/mpquant/MyTT/blob/main/MyTT_plus.py
# Python2老版本pandas特别的MyTT：      https://github.com/mpquant/MyTT/blob/main/MyTT_python2.py
# V2.1  2021-6-6   新增 BARSLAST函数 SLOPE,FORCAST线性回归预测函数
# V2.3  2021-6-13  新增 TRIX,DPO,BRAR,DMA,MTM,MASS,ROC,VR,ASI等指标
# V2.4  2021-6-27  新增 EXPMA,OBV,MFI指标, 改进SMA核心函数(核心函数彻底无循环)
# V2.7  2021-11-21 修正 SLOPE,BARSLAST,函数,新加FILTER,LONGCROSS,
#             感谢qzhjiang对SLOPE,SMA等函数的指正
# V2.8  2021-11-23 修正 FORCAST,WMA函数,欢迎qzhjiang,stanene,bcq加入社群，一起来完善myTT库
# V2.9  2021-11-29 新增 HHVBARS,LLVBARS,CONST, VALUEWHEN功能函数
# V2.92 2021-11-30 新增 BARSSINCEN函数,现在可以 pip install MyTT 完成安装
# V3.0  2021-12-04 改进 DMA函数支持序列,新增XS2 薛斯通道II指标
# V3.1  2021-12-19 新增 TOPRANGE,LOWRANGE一级函数
# V3.2  2023-04-04 新增 CR指标
# V3.3  2023-11-09 新增 SIN,COS,TAN序列处理的三角函数
# V4.0  2026-06-02 handsomejustin 新增 ZHUOYAO,BIAS_SIGNAL两个自创函数
# V4.1  2026-06-14 新增 SAR(抛物线转向), VWAP(成交量加权均价), AROON(阿隆指标); 注册 FK
# V4.2  2026-07-09 新增 FSL(分水岭指标)
# V4.3  2026-09-03 新增无未来函数指标16个：HMA,KAMA,SUPERTREND,CHANDELIER,ICHIMOKU,
#             UOS,CMO,TSI,FISHER,SQUEEZE,CHOP,AD,CMF,EFI,BBP,BBW（全部只引用当期及历史数据）

# 以下所有函数如无特别说明，输入参数S均为numpy序列或者列表list，N为整型int
# 应用层1级函数完美兼容通达信或同花顺，具体使用方法请参考通达信

import numpy as np
import pandas as pd


# ------------------ 0级：核心工具函数 --------------------------------------------
def RD(N, D=3):
    return np.round(N, D)  # 四舍五入取3位小数


def RET(S, N=1):
    return np.array(S)[-N]  # 返回序列倒数第N个值,默认返回最后一个


def ABS(S):
    return np.abs(S)  # 返回N的绝对值


def LN(S):
    return np.log(S)  # 求底是e的自然对数,


def POW(S, N):
    return np.power(S, N)  # 求S的N次方


def SQRT(S):
    return np.sqrt(S)  # 求S的平方根


def SIN(S):
    return np.sin(S)  # 求S的正弦值（弧度)


def COS(S):
    return np.cos(S)  # 求S的余弦值（弧度)


def TAN(S):
    return np.tan(S)  # 求S的正切值（弧度)


def MAX(S1, S2):
    return np.maximum(S1, S2)  # 序列max


def MIN(S1, S2):
    return np.minimum(S1, S2)  # 序列min


def IF(S, A, B):
    return np.where(S, A, B)  # 序列布尔判断 return=A  if S==True  else  B


def REF(S, N=1):  # 对序列整体下移动N,返回序列(shift后会产生NAN)
    return pd.Series(S).shift(N).values


def DIFF(S, N=1):  # 前一个值减后一个值,前面会产生nan
    return pd.Series(S).diff(N).values  # np.diff(S)直接删除nan，会少一行


def STD(S, N):  # 求序列的N日标准差，返回序列
    return pd.Series(S).rolling(N).std(ddof=0).values


def SUM(S, N):  # 对序列求N天累计和，返回序列    N=0对序列所有依次求和
    return pd.Series(S).rolling(N).sum().values if N > 0 else pd.Series(S).cumsum().values


def CONST(S):  # 返回序列S最后的值组成常量序列
    return np.full(len(S), S[-1])


def HHV(S, N):  # HHV(C, 5) 最近5天收盘最高价
    return pd.Series(S).rolling(N).max().values


def LLV(S, N):  # LLV(C, 5) 最近5天收盘最低价
    return pd.Series(S).rolling(N).min().values


def HHVBARS(S, N):  # 求N周期内S最高值到当前周期数, 返回序列
    return pd.Series(S).rolling(N).apply(lambda x: np.argmax(x[::-1]), raw=True).values


def LLVBARS(S, N):  # 求N周期内S最低值到当前周期数, 返回序列
    return pd.Series(S).rolling(N).apply(lambda x: np.argmin(x[::-1]), raw=True).values


def MA(S, N):  # 求序列的N日简单移动平均值，返回序列
    return pd.Series(S).rolling(N).mean().values


def EMA(S, N):  # 指数移动平均,为了精度 S>4*N  EMA至少需要120周期     alpha=2/(span+1)
    return pd.Series(S).ewm(span=N, adjust=False).mean().values


def SMA(S, N, M=1):  # 中国式的SMA,至少需要120周期才精确 (雪球180周期)    alpha=1/(1+com)
    return pd.Series(S).ewm(alpha=M / N, adjust=False).mean().values  # com=N-M/M


def WMA(S, N):  # 通达信S序列的N日加权移动平均 Yn = (1*X1+2*X2+3*X3+...+n*Xn)/(1+2+3+...+Xn)
    return (
        pd.Series(S)
        .rolling(N)
        .apply(lambda x: x[::-1].cumsum().sum() * 2 / N / (N + 1), raw=True)
        .values
    )


def DMA(S, A):  # 求S的动态移动平均，A作平滑因子,必须 0<A<1  (此为核心函数，非指标）
    if isinstance(A, int | float):
        return pd.Series(S).ewm(alpha=A, adjust=False).mean().values
    A = np.array(A)
    A[np.isnan(A)] = 1.0
    Y = np.zeros(len(S))
    Y[0] = S[0]
    for i in range(1, len(S)):
        Y[i] = A[i] * S[i] + (1 - A[i]) * Y[i - 1]  # A支持序列 by jqz1226
    return Y


def AVEDEV(S, N):  # 平均绝对偏差  (序列与其平均值的绝对差的平均值)
    return pd.Series(S).rolling(N).apply(lambda x: (np.abs(x - x.mean())).mean()).values


def SLOPE(S, N):  # 返S序列N周期回线性回归斜率
    return (
        pd.Series(S).rolling(N).apply(lambda x: np.polyfit(range(N), x, deg=1)[0], raw=True).values
    )


def FORCAST(S, N):  # 返回S序列N周期回线性回归后的预测值， jqz1226改进成序列出
    return (
        pd.Series(S)
        .rolling(N)
        .apply(lambda x: np.polyval(np.polyfit(range(N), x, deg=1), N - 1), raw=True)
        .values
    )


def LAST(S, A, B):  # 从前A日到前B日一直满足S_BOOL条件, 要求A>B & A>0 & B>=0
    return np.array(
        pd.Series(S).rolling(A + 1).apply(lambda x: np.all(x[::-1][B:]), raw=True), dtype=bool
    )


# -- 1级：应用层函数(通过0级核心函数实现）使用方法请参考通达信 --------------------
def COUNT(S, N):  # COUNT(CLOSE>O, N):  最近N天满足S_BOO的天数  True的天数
    return SUM(S, N)


def EVERY(S, N):  # EVERY(CLOSE>O, 5)   最近N天是否都是True
    return IF(SUM(S, N) == N, True, False)


def EXIST(S, N):  # EXIST(CLOSE>3010, N=5)  n日内是否存在一天大于3000点
    return IF(SUM(S, N) > 0, True, False)


def FILTER(S, N):  # FILTER函数，S满足条件后，将其后N周期内的数据置为0, FILTER(C==H,5)
    for i in range(len(S)):
        S[i + 1 : i + 1 + N] = 0 if S[i] else S[i + 1 : i + 1 + N]
    return S  # 例：FILTER(C==H,5) 涨停后，后5天不再发出信号


def BARSLAST(S):  # 上一次条件成立到当前的周期, BARSLAST(C/REF(C,1)>=1.1) 上一次涨停到今天的天数
    M = np.concatenate(([0], np.where(S, 1, 0)))
    for i in range(1, len(M)):
        M[i] = 0 if M[i] else M[i - 1] + 1
    return M[1:]


def BARSLASTCOUNT(S):  # 统计连续满足S条件的周期数        by jqz1226
    rt = np.zeros(len(S) + 1)  # BARSLASTCOUNT(CLOSE>OPEN)表示统计连续收阳的周期数
    for i in range(len(S)):
        rt[i + 1] = rt[i] + 1 if S[i] else rt[i + 1]
    return rt[1:]


def BARSSINCEN(S, N):  # N周期内第一次S条件成立到现在的周期数,N为常量  by jqz1226
    return (
        pd.Series(S)
        .rolling(N)
        .apply(lambda x: N - 1 - np.argmax(x) if np.argmax(x) or x[0] else 0, raw=True)
        .fillna(0)
        .values.astype(int)
    )


def CROSS(
    S1, S2
):  # 判断向上金叉穿越 CROSS(MA(C,5),MA(C,10))  判断向下死叉穿越 CROSS(MA(C,10),MA(C,5))
    return np.concatenate(
        ([False], np.logical_not((S1 > S2)[:-1]) & (S1 > S2)[1:])
    )  # 不使用0级函数,移植方便  by jqz1226


def LONGCROSS(
    S1, S2, N
):  # 两条线维持一定周期后交叉,S1在N周期内都小于S2,本周期从S1下方向上穿过S2时返回1,否则返回0
    return np.array(
        np.logical_and(LAST(S1 < S2, N, 1), (S1 > S2)), dtype=bool
    )  # N=1时等同于CROSS(S1, S2)


def VALUEWHEN(S, X):  # 当S条件成立时,取X的当前值,否则取VALUEWHEN的上个成立时的X值   by jqz1226
    return pd.Series(np.where(S, X, np.nan)).ffill().values


def BETWEEN(S, A, B):  # S处于A和B之间时为真。 包括 A<S<B 或 A>S>B
    return ((A < S) & (S < B)) | ((A > S) & (S > B))


def TOPRANGE(S):  # TOPRANGE(HIGH)表示当前最高价是近多少周期内最高价的最大值 by jqz1226
    rt = np.zeros(len(S))
    for i in range(1, len(S)):
        rt[i] = np.argmin(np.flipud(S[:i] < S[i]))
    return rt.astype("int")


def LOWRANGE(S):  # LOWRANGE(LOW)表示当前最低价是近多少周期内最低价的最小值 by jqz1226
    rt = np.zeros(len(S))
    for i in range(1, len(S)):
        rt[i] = np.argmin(np.flipud(S[:i] > S[i]))
    return rt.astype("int")


# ------------------   2级：技术指标函数(全部通过0级，1级函数实现） ------------------------------
def MACD(CLOSE, SHORT=12, LONG=26, M=9):  # EMA的关系，S取120日，和雪球小数点2位相同
    DIF = EMA(CLOSE, SHORT) - EMA(CLOSE, LONG)
    DEA = EMA(DIF, M)
    MACD = (DIF - DEA) * 2
    return RD(DIF), RD(DEA), RD(MACD)


def KDJ(CLOSE, HIGH, LOW, N=9, M1=3, M2=3):  # KDJ指标
    low_n = LLV(LOW, N)
    high_n = HHV(HIGH, N)
    high_low_diff = high_n - low_n
    # 避免除零：当最高价等于最低价时，RSV 应该为 50（中性）
    with np.errstate(divide="ignore", invalid="ignore"):
        rsv = (CLOSE - low_n) / high_low_diff * 100
    rsv = np.where(high_low_diff == 0, 50, rsv)  # 除零时返回 50
    K = EMA(rsv, (M1 * 2 - 1))
    D = EMA(K, (M2 * 2 - 1))
    J = K * 3 - D * 2
    return K, D, J


def RSI(CLOSE, N=24):  # RSI指标,和通达信小数点2位相同
    DIF = CLOSE - REF(CLOSE, 1)
    abs_dif_sma = SMA(ABS(DIF), N)
    # 避免除零：当价格完全不变时，RSI 应该为 50（中性）
    with np.errstate(divide="ignore", invalid="ignore"):
        rsi_value = SMA(MAX(DIF, 0), N) / abs_dif_sma * 100
    rsi_value = np.where(abs_dif_sma == 0, 50, rsi_value)  # 除零时返回 50
    return RD(rsi_value)


def WR(CLOSE, HIGH, LOW, N=10, N1=6):  # W&R 威廉指标
    high_n = HHV(HIGH, N)
    low_n = LLV(LOW, N)
    high_low_diff = high_n - low_n
    with np.errstate(divide="ignore", invalid="ignore"):
        wr = (high_n - CLOSE) / high_low_diff * 100
    wr = np.where(high_low_diff == 0, 50, wr)  # 除零时返回 50

    high_n1 = HHV(HIGH, N1)
    low_n1 = LLV(LOW, N1)
    high_low_diff1 = high_n1 - low_n1
    with np.errstate(divide="ignore", invalid="ignore"):
        wr1 = (high_n1 - CLOSE) / high_low_diff1 * 100
    wr1 = np.where(high_low_diff1 == 0, 50, wr1)  # 除零时返回 50

    return RD(wr), RD(wr1)


def BIAS(CLOSE, L1=6, L2=12, L3=24):  # BIAS乖离率
    BIAS1 = (CLOSE - MA(CLOSE, L1)) / MA(CLOSE, L1) * 100
    BIAS2 = (CLOSE - MA(CLOSE, L2)) / MA(CLOSE, L2) * 100
    BIAS3 = (CLOSE - MA(CLOSE, L3)) / MA(CLOSE, L3) * 100
    return RD(BIAS1), RD(BIAS2), RD(BIAS3)


def BOLL(CLOSE, N=20, P=2):  # BOLL指标，布林带
    MID = MA(CLOSE, N)
    UPPER = MID + STD(CLOSE, N) * P
    LOWER = MID - STD(CLOSE, N) * P
    return RD(UPPER), RD(MID), RD(LOWER)


def PSY(CLOSE, N=12, M=6):
    PSY = COUNT(CLOSE > REF(CLOSE, 1), N) / N * 100
    PSYMA = MA(PSY, M)
    return RD(PSY), RD(PSYMA)


def CCI(CLOSE, HIGH, LOW, N=14):
    TP = (HIGH + LOW + CLOSE) / 3
    return (TP - MA(TP, N)) / (0.015 * AVEDEV(TP, N))


def ATR(CLOSE, HIGH, LOW, N=20):  # 真实波动N日平均值
    TR = MAX(MAX((HIGH - LOW), ABS(REF(CLOSE, 1) - HIGH)), ABS(REF(CLOSE, 1) - LOW))
    return MA(TR, N)


def BBI(CLOSE, M1=3, M2=6, M3=12, M4=20):  # BBI多空指标
    return (MA(CLOSE, M1) + MA(CLOSE, M2) + MA(CLOSE, M3) + MA(CLOSE, M4)) / 4


def DMI(CLOSE, HIGH, LOW, M1=14, M2=6):  # 动向指标：结果和同花顺，通达信完全一致
    TR = SUM(MAX(MAX(HIGH - LOW, ABS(HIGH - REF(CLOSE, 1))), ABS(LOW - REF(CLOSE, 1))), M1)
    HD = HIGH - REF(HIGH, 1)
    LD = REF(LOW, 1) - LOW
    DMP = SUM(IF((HD > 0) & (HD > LD), HD, 0), M1)
    DMM = SUM(IF((LD > 0) & (LD > HD), LD, 0), M1)
    PDI = DMP * 100 / TR
    MDI = DMM * 100 / TR
    ADX = MA(ABS(MDI - PDI) / (PDI + MDI) * 100, M2)
    ADXR = (ADX + REF(ADX, M2)) / 2
    return PDI, MDI, ADX, ADXR


def TAQ(HIGH, LOW, N):  # 唐安奇通道(海龟)交易指标，大道至简，能穿越牛熊
    UP = HHV(HIGH, N)
    DOWN = LLV(LOW, N)
    MID = (UP + DOWN) / 2
    return UP, MID, DOWN


def KTN(CLOSE, HIGH, LOW, N=20, M=10):  # 肯特纳交易通道, N选20日，ATR选10日
    MID = EMA((HIGH + LOW + CLOSE) / 3, N)
    ATRN = ATR(CLOSE, HIGH, LOW, M)
    UPPER = MID + 2 * ATRN
    LOWER = MID - 2 * ATRN
    return UPPER, MID, LOWER


def TRIX(CLOSE, M1=12, M2=20):  # 三重指数平滑平均线
    TR = EMA(EMA(EMA(CLOSE, M1), M1), M1)
    TRIX = (TR - REF(TR, 1)) / REF(TR, 1) * 100
    TRMA = MA(TRIX, M2)
    return TRIX, TRMA


def VR(CLOSE, VOL, M1=26):  # VR容量比率
    LC = REF(CLOSE, 1)
    return SUM(IF(CLOSE > LC, VOL, 0), M1) / SUM(IF(CLOSE <= LC, VOL, 0), M1) * 100


def CR(CLOSE, HIGH, LOW, N=20):  # CR价格动量指标
    MID = REF(HIGH + LOW + CLOSE, 1) / 3
    num = SUM(MAX(0, HIGH - MID), N)
    den = SUM(MAX(0, MID - LOW), N)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den * 100, 100)


def EMV(HIGH, LOW, VOL, N=14, M=9):  # 简易波动指标
    VOLUME = MA(VOL, N) / VOL
    MID = 100 * (HIGH + LOW - REF(HIGH + LOW, 1)) / (HIGH + LOW)
    EMV = MA(MID * VOLUME * (HIGH - LOW) / MA(HIGH - LOW, N), N)
    MAEMV = MA(EMV, M)
    return EMV, MAEMV


def DPO(CLOSE, M1=20, M2=10, M3=6):  # 区间震荡线
    DPO = CLOSE - REF(MA(CLOSE, M1), M2)
    MADPO = MA(DPO, M3)
    return DPO, MADPO


def BRAR(OPEN, CLOSE, HIGH, LOW, M1=26):  # BRAR-ARBR 情绪指标
    AR = SUM(HIGH - OPEN, M1) / SUM(OPEN - LOW, M1) * 100
    BR = SUM(MAX(0, HIGH - REF(CLOSE, 1)), M1) / SUM(MAX(0, REF(CLOSE, 1) - LOW), M1) * 100
    return AR, BR


def DFMA(CLOSE, N1=10, N2=50, M=10):  # 平行线差指标
    DIF = MA(CLOSE, N1) - MA(CLOSE, N2)
    DIFMA = MA(DIF, M)  # 通达信指标叫DMA 同花顺叫新DMA
    return DIF, DIFMA


def MTM(CLOSE, N=12, M=6):  # 动量指标
    MTM = CLOSE - REF(CLOSE, N)
    MTMMA = MA(MTM, M)
    return MTM, MTMMA


def MASS(HIGH, LOW, N1=9, N2=25, M=6):  # 梅斯线
    MASS = SUM(MA(HIGH - LOW, N1) / MA(MA(HIGH - LOW, N1), N1), N2)
    MA_MASS = MA(MASS, M)
    return MASS, MA_MASS


def ROC(CLOSE, N=12, M=6):  # 变动率指标
    ROC = 100 * (CLOSE - REF(CLOSE, N)) / REF(CLOSE, N)
    MAROC = MA(ROC, M)
    return ROC, MAROC


def EXPMA(CLOSE, N1=12, N2=50):  # EMA指数平均数指标
    return EMA(CLOSE, N1), EMA(CLOSE, N2)


def OBV(CLOSE, VOL):  # 能量潮指标
    return SUM(IF(CLOSE > REF(CLOSE, 1), VOL, IF(CLOSE < REF(CLOSE, 1), -VOL, 0)), 0) / 10000


def MFI(CLOSE, HIGH, LOW, VOL, N=14):  # MFI指标是成交量的RSI指标
    TYP = (HIGH + LOW + CLOSE) / 3
    pos_mf = SUM(IF(TYP > REF(TYP, 1), TYP * VOL, 0), N)
    neg_mf = SUM(IF(TYP < REF(TYP, 1), TYP * VOL, 0), N)
    with np.errstate(divide="ignore", invalid="ignore"):
        V1 = np.where(neg_mf > 0, pos_mf / neg_mf, np.where(pos_mf > 0, np.inf, 0))
    return 100 - (100 / (1 + V1))


def ASI(OPEN, CLOSE, HIGH, LOW, M1=26, M2=10):  # 振动升降指标
    LC = REF(CLOSE, 1)
    AA = ABS(HIGH - LC)
    BB = ABS(LOW - LC)
    CC = ABS(HIGH - REF(LOW, 1))
    DD = ABS(LC - REF(OPEN, 1))
    R = IF(
        (AA > BB) & (AA > CC),
        AA + BB / 2 + DD / 4,
        IF((BB > CC) & (BB > AA), BB + AA / 2 + DD / 4, CC + DD / 4),
    )
    X = CLOSE - LC + (CLOSE - OPEN) / 2 + LC - REF(OPEN, 1)
    SI = 16 * X / R * MAX(AA, BB)
    ASI = SUM(SI, M1)
    ASIT = MA(ASI, M2)
    return ASI, ASIT


def XSII(CLOSE, HIGH, LOW, N=102, M=7):  # 薛斯通道II
    AA = MA((2 * CLOSE + HIGH + LOW) / 4, 5)  # 最新版DMA才支持 2021-12-4
    TD1 = AA * N / 100
    TD2 = AA * (200 - N) / 100
    CC = ABS((2 * CLOSE + HIGH + LOW) / 4 - MA(CLOSE, 20)) / MA(CLOSE, 20)
    DD = DMA(CLOSE, CC)
    TD3 = (1 + M / 100) * DD
    TD4 = (1 - M / 100) * DD
    return TD1, TD2, TD3, TD4


def ZHUOYAO(CLOSE, N1=120, N2=60, N3=20, M=10):  # 捉妖大师指标：中长短线趋势共振
    LONG1 = (CLOSE / REF(CLOSE, N1) - 1) * 100  # 120日涨跌幅
    LONG = EMA(LONG1, M)  # 长线 EXPMA(长线1,10)
    MID = (CLOSE / REF(CLOSE, N2) - 1) * 100  # 中线 60日涨跌幅
    SHORT = (CLOSE / REF(CLOSE, N3) - 1) * 100  # 短线 20日涨跌幅
    TREND = EMA(MID, M)  # 趋势 EXPMA(中线,10)
    return RD(LONG), RD(MID), RD(SHORT), RD(TREND)


def BIAS_SIGNAL(CLOSE, P=10, M=30):  # 乖离率信号指标：M日乖离 + 短/长信号线趋势判断
    X = (CLOSE - MA(CLOSE, M)) / MA(CLOSE, M) * 100  # M日乖离率
    S_SMA = MA(X, P)  # 短周期信号线 MA(X,P)
    X_LMA = MA(X, M)  # 长周期信号线 MA(X,M)
    return RD(X), RD(S_SMA), RD(X_LMA)


def FK(CLOSE):  # FK趋势指标：快线EMA(2)与斜率外推慢线EMA(42)比较
    fast = EMA(CLOSE, 2)
    slow = EMA(SLOPE(CLOSE, 21) * 20 + CLOSE, 42)
    return fast > slow


def OUTPERFORM_20D(CLOSE, INDEX_CLOSE):  # 20日相对强度：个股涨幅跑赢大盘返回1，否则返回0
    stock_ret = (CLOSE - REF(CLOSE, 20)) / REF(CLOSE, 20)
    index_ret = (INDEX_CLOSE - REF(INDEX_CLOSE, 20)) / REF(INDEX_CLOSE, 20)
    return IF(stock_ret > index_ret, 1, 0)


def SAR(HIGH, LOW, AF_STEP=0.02, AF_MAX=0.2):  # 抛物线转向指标：基于 ATR 思想的动态止损位
    HIGH = np.asarray(HIGH, dtype=float)
    LOW = np.asarray(LOW, dtype=float)
    n = len(HIGH)
    sar = np.full(n, np.nan)
    if n == 0:
        return sar
    # 初始假设上涨趋势：SAR 起点取首根低点，极值点取首根高点
    bull = True
    af = AF_STEP
    ep = HIGH[0]
    sar[0] = LOW[0]
    for i in range(1, n):
        # 下一根 SAR = 前一根 SAR + AF * (EP - 前一根 SAR)
        new_sar = sar[i - 1] + af * (ep - sar[i - 1])
        # SAR 不能进入前两根 K 线极值范围（Wilder 标准限制，避免 SAR 被价格穿越）
        prev2 = max(i - 2, 0)
        if bull:
            new_sar = min(new_sar, LOW[i - 1], LOW[prev2])
        else:
            new_sar = max(new_sar, HIGH[i - 1], HIGH[prev2])
        sar[i] = new_sar
        # 反转判断：上涨时 LOW 穿越止损位 / 下跌时 HIGH 穿越止损位
        if bull and LOW[i] <= new_sar:
            bull = False
            sar[i] = ep  # 反转点 SAR = 前极值点
            ep = LOW[i]
            af = AF_STEP
        elif not bull and HIGH[i] >= new_sar:
            bull = True
            sar[i] = ep
            ep = HIGH[i]
            af = AF_STEP
        else:
            # 无反转，更新极值点和加速因子
            if bull and HIGH[i] > ep:
                ep = HIGH[i]
                af = min(af + AF_STEP, AF_MAX)
            elif not bull and LOW[i] < ep:
                ep = LOW[i]
                af = min(af + AF_STEP, AF_MAX)
    return sar


def VWAP(CLOSE, HIGH, LOW, VOL, N=20):  # 成交量加权均价：N日滚动机构基准成本价
    TP = (HIGH + LOW + CLOSE) / 3.0  # 典型价格
    num = pd.Series(TP * VOL).rolling(N).sum().values
    den = pd.Series(VOL).rolling(N).sum().values
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(den > 0, num / den, np.nan)


def AROON(HIGH, LOW, N=25):  # 阿隆指标：趋势启动时机识别（N周期内新高/新低距今多少根）
    # HHVBARS/LLVBARS 返回极值距今的周期数
    up_bars = HHVBARS(HIGH, N)  # N周期最高价距今周期数
    down_bars = LLVBARS(LOW, N)  # N周期最低价距今周期数
    AROON_UP = (N - up_bars) / N * 100  # 越接近100=近期创新高=上涨动能强
    AROON_DOWN = (N - down_bars) / N * 100  # 越接近100=近期创新低=下跌动能强
    OSC = AROON_UP - AROON_DOWN  # 震荡指标：正值多头，负值空头
    return RD(AROON_UP), RD(AROON_DOWN), RD(OSC)


def FSL(CLOSE, VOL, CAPITAL):  # 分水岭指标：多空趋势强弱分界（SWS含换手率动态平滑）
    # SWL = (EMA(C,5)*7 + EMA(C,10)*3) / 10  : 5日/10日指数均值的加权合成
    SWL = (EMA(CLOSE, 5) * 7 + EMA(CLOSE, 10) * 3) / 10
    # SWS = DMA(EMA(C,12), MAX(1, 100*SUM(VOL,5)/(3*CAPITAL)))
    #     平滑因子 = 5日成交量换手率放大值，CAPITAL 为流通股本
    A = MAX(1, 100 * (SUM(VOL, 5) / (3 * CAPITAL)))
    A = MIN(A, 1.0)  # 模拟通达信 DMA(X,A) 内部钳制 A<=1，避免序列因子越界发散
    SWS = DMA(EMA(CLOSE, 12), A)
    return RD(SWL), RD(SWS)


# ── V4.3 新增：无未来函数指标（只引用当期及历史数据，信号不漂移） ────────────
def HMA(S, N=16):  # Hull 赫尔均线：WMA(2*WMA(N/2)-WMA(N), sqrt(N))，低滞后且不重绘
    return WMA(2 * WMA(S, N // 2) - WMA(S, N), max(int(round(np.sqrt(N))), 1))


def KAMA(S, N=10, FAST=2, SLOW=30):  # 考夫曼自适应均线：效率比驱动平滑系数（贴价/走平自适应）
    S = np.asarray(S, dtype=float)
    change = np.abs(S - REF(S, N))  # N 周期净变化
    volatility = SUM(np.abs(DIFF(S)), N)  # N 周期路径总波动
    with np.errstate(divide="ignore", invalid="ignore"):
        er = np.where(volatility > 0, change / volatility, 0.0)  # 效率比 0~1
    er = np.where(np.isnan(change) | np.isnan(volatility), np.nan, er)  # 预热段保持 NaN
    fast_sc = 2.0 / (FAST + 1)
    slow_sc = 2.0 / (SLOW + 1)
    sc = (er * (fast_sc - slow_sc) + slow_sc) ** 2  # 平滑系数（ER 高→贴价，ER 低→走平）
    out = np.full(len(S), np.nan)
    valid = np.flatnonzero(~np.isnan(sc))
    if len(valid):
        start = valid[0]
        out[start] = S[start]
        for i in range(start + 1, len(S)):
            out[i] = out[i - 1] + sc[i] * (S[i] - out[i - 1])
    return out


def SUPERTREND(CLOSE, HIGH, LOW, N=10, M=3.0):  # 超级趋势：HL2±M*ATR 递推锁带，穿带翻多空
    CLOSE = np.asarray(CLOSE, dtype=float)
    HIGH = np.asarray(HIGH, dtype=float)
    LOW = np.asarray(LOW, dtype=float)
    n = len(CLOSE)
    sar_like = np.full(n, np.nan)
    if n == 0:
        return sar_like, np.zeros(0, dtype=int)
    # Wilder 平滑 ATR（与 TradingView ta.rma 同口径）；首根 TR 用自身 H-L
    prev_c = np.concatenate(([CLOSE[0]], CLOSE[:-1]))
    tr = MAX(MAX(HIGH - LOW, ABS(HIGH - prev_c)), ABS(LOW - prev_c))
    atr = np.empty(n)
    atr[0] = tr[0]
    for i in range(1, n):
        atr[i] = atr[i - 1] + (tr[i] - atr[i - 1]) / N
    hl2 = (HIGH + LOW) / 2
    basic_up = hl2 + M * atr
    basic_dn = hl2 - M * atr
    # 递推锁带：带只朝价格方向收紧，反向放宽被前收盘穿越时重置
    final_up = basic_up.copy()
    final_dn = basic_dn.copy()
    for i in range(1, n):
        final_up[i] = (
            basic_up[i]
            if (basic_up[i] < final_up[i - 1] or CLOSE[i - 1] > final_up[i - 1])
            else final_up[i - 1]
        )
        final_dn[i] = (
            basic_dn[i]
            if (basic_dn[i] > final_dn[i - 1] or CLOSE[i - 1] < final_dn[i - 1])
            else final_dn[i - 1]
        )
    direction = np.ones(n, dtype=int)  # 1=多头（ST=下轨），-1=空头（ST=上轨）
    for i in range(1, n):
        if direction[i - 1] == 1:
            direction[i] = -1 if CLOSE[i] < final_dn[i] else 1
        else:
            direction[i] = 1 if CLOSE[i] > final_up[i] else -1
    st = np.where(direction == 1, final_dn, final_up)
    return st, direction


def CHANDELIER(CLOSE, HIGH, LOW, N=22, M=22, K=3.0):  # 吊灯止损：多头 HHV-K*ATR / 空头 LLV+K*ATR
    atr = ATR(CLOSE, HIGH, LOW, M)
    long_stop = HHV(HIGH, N) - atr * K
    short_stop = LLV(LOW, N) + atr * K
    return long_stop, short_stop


def ICHIMOKU(HIGH, LOW, CLOSE, P1=9, P2=26, P3=52, SHIFT=26):  # 一目均衡表：五线一云
    tenkan = (HHV(HIGH, P1) + LLV(LOW, P1)) / 2  # 转换线
    kijun = (HHV(HIGH, P2) + LLV(LOW, P2)) / 2  # 基准线
    span_a = REF((tenkan + kijun) / 2, SHIFT)  # 先行带A：SHIFT期前的值画到当前（仅过去数据）
    span_b = REF((HHV(HIGH, P3) + LLV(LOW, P3)) / 2, SHIFT)  # 先行带B
    chikou = REF(CLOSE, -SHIFT)  # 迟行带：当前收盘画回SHIFT期前，仅作图示（当期信号禁用）
    return tenkan, kijun, span_a, span_b, chikou


def UOS(CLOSE, HIGH, LOW, P1=7, P2=14, P3=28, M=6):  # 终极指标：7/14/28 三周期 BP/TR 加权动量
    th = MAX(HIGH, REF(CLOSE, 1))  # 真高
    tl = MIN(LOW, REF(CLOSE, 1))  # 真低
    bp = CLOSE - tl  # 买压
    tr = th - tl  # 真波幅

    def _avg(p):  # SMA(BP,p)/SMA(TR,p)，分母为零（一字段）时取中性 0.5
        num, den = MA(bp, p), MA(tr, p)
        with np.errstate(divide="ignore", invalid="ignore"):
            ratio = np.where(den > 0, num / den, 0.5)
        return np.where(np.isnan(num) | np.isnan(den), np.nan, ratio)

    uos = 100 * (4 * _avg(P1) + 2 * _avg(P2) + _avg(P3)) / 7
    uos_ma = MA(uos, M)
    return RD(uos), RD(uos_ma)


def CMO(CLOSE, N=14):  # 钱德动量振荡器：(涨幅和-跌幅和)/总波幅*100，比RSI更锐利对称
    dif = DIFF(CLOSE)
    up = SUM(MAX(dif, 0), N)
    dn = SUM(MAX(-dif, 0), N)
    total = up + dn
    with np.errstate(divide="ignore", invalid="ignore"):
        cmo = np.where(total > 0, (up - dn) / total * 100, 0.0)
    return RD(np.where(np.isnan(total), np.nan, cmo))


def TSI(CLOSE, R=25, S=13, M=13):  # 真实强度指数：动量双重EMA平滑归一（William Blau）
    m = DIFF(CLOSE)
    num = EMA(EMA(m, R), S)
    den = EMA(EMA(ABS(m), R), S)
    with np.errstate(divide="ignore", invalid="ignore"):
        tsi = np.where(den != 0, 100 * num / den, 0.0)
    tsi = np.where(np.isnan(num) | np.isnan(den), np.nan, tsi)
    return RD(tsi), RD(EMA(tsi, M))


def FISHER(HIGH, LOW, N=9):  # 费雪变换（John Ehlers）：区间位置正态化，拐点尖锐
    price = (HIGH + LOW) / 2.0
    highest = HHV(price, N)
    lowest = LLV(price, N)
    rng = highest - lowest
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.where(rng > 0, 2.0 * (price - lowest) / rng - 1.0, 0.0)  # 归一化到 -1~1
    norm = np.where(np.isnan(rng), np.nan, raw)
    n = len(price)
    value = np.full(n, np.nan)
    fisher = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(norm[i]):
            continue
        prev_v = 0.0 if np.isnan(value[i - 1]) else value[i - 1]
        prev_f = 0.0 if np.isnan(fisher[i - 1]) else fisher[i - 1]
        v = 0.33 * norm[i] + 0.67 * prev_v
        v = max(-0.999, min(0.999, v))  # 钳制避免 ln 发散
        value[i] = v
        fisher[i] = 0.5 * np.log((1 + v) / (1 - v)) + 0.5 * prev_f
    return fisher, REF(fisher, 1)  # 第二返回值为触发线（前一期值）


def SQUEEZE(CLOSE, HIGH, LOW, N=20, BB=2.0, KC=1.5):  # TTM 挤压动量：布林收进肯特纳，回归动量定方向
    mid = MA(CLOSE, N)
    dev = STD(CLOSE, N) * BB
    tr = MAX(MAX(HIGH - LOW, ABS(HIGH - REF(CLOSE, 1))), ABS(LOW - REF(CLOSE, 1)))
    range_ma = MA(tr, N)
    # 挤压判定：布林带（±dev）整体落在肯特纳通道（±KC×range_ma）内部（NaN 预热期比较为 False）
    sqz_on = dev < KC * range_ma
    # 动量：中价偏离 (HH+LL)/2 与 SMA(C,N) 的均值，取线性回归当前拟合值
    delta = CLOSE - ((HHV(HIGH, N) + LLV(LOW, N)) / 2 + mid) / 2
    mom = FORCAST(delta, N)
    return sqz_on, RD(mom)


def CHOP(HIGH, LOW, CLOSE, N=14):  # 盘整指数：>61.8 震荡 / <38.2 趋势（ΣTR/区间 对数缩放到 0~100）
    tr = MAX(MAX(HIGH - LOW, ABS(HIGH - REF(CLOSE, 1))), ABS(LOW - REF(CLOSE, 1)))
    tr_sum = SUM(tr, N)
    rng = HHV(HIGH, N) - LLV(LOW, N)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where((tr_sum > 0) & (rng > 0), tr_sum / rng, np.nan)
    return 100 * np.log10(ratio) / np.log10(N)


def AD(CLOSE, HIGH, LOW, VOL):  # 累积/派发线（Marc Chaikin）：CLV*VOL 累计，OBV 的精细化版
    rng = HIGH - LOW
    with np.errstate(divide="ignore", invalid="ignore"):
        clv = np.where(rng > 0, ((CLOSE - LOW) - (HIGH - CLOSE)) / rng, 0.0)  # 收盘位置 -1~1
    return SUM(clv * VOL, 0)


def CMF(CLOSE, HIGH, LOW, VOL, N=20):  # 佳庆资金流量：N日 CLV*VOL 之和 / N日成交量之和
    rng = HIGH - LOW
    with np.errstate(divide="ignore", invalid="ignore"):
        clv = np.where(rng > 0, ((CLOSE - LOW) - (HIGH - CLOSE)) / rng, 0.0)
    mfv_sum = SUM(clv * VOL, N)
    vol_sum = SUM(VOL, N)
    with np.errstate(divide="ignore", invalid="ignore"):
        cmf = np.where(vol_sum > 0, mfv_sum / vol_sum, 0.0)
    return np.where(np.isnan(vol_sum) | np.isnan(mfv_sum), np.nan, cmf)


def EFI(CLOSE, VOL, N=13):  # 艾尔德强力指数：EMA(ΔC×V)，同时融合方向/幅度/成交量三维
    return EMA(DIFF(CLOSE) * VOL, N)


def BBP(CLOSE, N=20, P=2):  # 布林位置 %B：收盘在带内位置百分比（0=下轨，50=中轨，100=上轨）
    mid = MA(CLOSE, N)
    dev = STD(CLOSE, N) * P
    width = 2 * dev
    with np.errstate(divide="ignore", invalid="ignore"):
        pos = np.where(width > 0, (CLOSE - (mid - dev)) / width * 100, 50.0)
    return RD(np.where(np.isnan(width), np.nan, pos))


def BBW(CLOSE, N=20, P=2):  # 布林带宽：(上轨-下轨)/中轨*100，收窄=波动挤压/变盘预警
    mid = MA(CLOSE, N)
    dev = STD(CLOSE, N) * P
    with np.errstate(divide="ignore", invalid="ignore"):
        width = np.where(mid > 0, 2 * dev / mid * 100, np.nan)
    return RD(width)


# 望大家能提交更多指标和函数  https://github.com/mpquant/MyTT
