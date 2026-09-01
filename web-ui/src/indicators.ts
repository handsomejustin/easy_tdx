// 技术指标前端计算库（与后端 MyTT/indicator.py 同口径的常用子集）。
// 输入均为按时间正序的价格数组，输出与输入等长（前期无法计算的点为 null）。

/** 简单移动平均 MA(n)。 */
export function ma(data: number[], n: number): Array<number | null> {
  const out: Array<number | null> = []
  let sum = 0
  for (let i = 0; i < data.length; i++) {
    sum += data[i]
    if (i >= n) sum -= data[i - n]
    out.push(i >= n - 1 ? sum / n : null)
  }
  return out
}

/** 指数移动平均 EMA(n)，首值用前 n 项均值（无则首个有效值）。 */
export function ema(data: number[], n: number): Array<number | null> {
  const out: Array<number | null> = []
  const k = 2 / (n + 1)
  let prev: number | null = null
  let seed = 0
  for (let i = 0; i < data.length; i++) {
    if (prev === null) {
      seed += data[i]
      if (i === n - 1) {
        prev = seed / n
        out.push(prev)
      } else {
        out.push(null)
      }
    } else {
      prev = data[i] * k + prev * (1 - k)
      out.push(prev)
    }
  }
  return out
}

/** 国内 SMA(X, N, M)：X*M/N + 前值*(N-M)/N，首值 = 首个 X。 */
function smaCN(data: number[], n: number, m: number): Array<number | null> {
  const out: Array<number | null> = []
  let prev: number | null = null
  for (const v of data) {
    if (prev === null) {
      prev = v
      out.push(v)
    } else {
      prev = (v * m) / n + (prev * (n - m)) / n
      out.push(prev)
    }
  }
  return out
}

/** 布林带 BOLL(20, 2)：中轨 MA20，上下轨 ±2×标准差。 */
export function boll(
  data: number[],
  n = 20,
  p = 2,
): { mid: Array<number | null>; upper: Array<number | null>; lower: Array<number | null> } {
  const mid = ma(data, n)
  const upper: Array<number | null> = []
  const lower: Array<number | null> = []
  for (let i = 0; i < data.length; i++) {
    if (mid[i] === null) {
      upper.push(null)
      lower.push(null)
      continue
    }
    let ssum = 0
    for (let j = i - n + 1; j <= i; j++) ssum += (data[j] - (mid[i] as number)) ** 2
    const sd = Math.sqrt(ssum / n)
    upper.push((mid[i] as number) + p * sd)
    lower.push((mid[i] as number) - p * sd)
  }
  return { mid, upper, lower }
}

/** MACD(12,26,9)：DIF、DEA、MACD 柱（= 2×(DIF-DEA)，国内口径）。 */
export function macd(
  closes: number[],
  fast = 12,
  slow = 26,
  signal = 9,
): { dif: Array<number | null>; dea: Array<number | null>; hist: Array<number | null> } {
  const ef = ema(closes, fast)
  const es = ema(closes, slow)
  const dif = closes.map((_, i) =>
    ef[i] !== null && es[i] !== null ? (ef[i] as number) - (es[i] as number) : null,
  )
  // DEA = DIF 的 EMA(9)：剔除前缀 null 后计算再回填
  const firstIdx = dif.findIndex((v) => v !== null)
  const dea: Array<number | null> = new Array(closes.length).fill(null)
  if (firstIdx >= 0) {
    const valid = dif.slice(firstIdx) as number[]
    const deaValid = ema(valid, signal)
    for (let i = 0; i < deaValid.length; i++) dea[firstIdx + i] = deaValid[i]
  }
  const hist = dif.map((v, i) =>
    v !== null && dea[i] !== null ? 2 * (v - (dea[i] as number)) : null,
  )
  return { dif, dea, hist }
}

/** KDJ(9,3,3)：RSV→K=SMA(RSV,3,1)→D=SMA(K,3,1)→J=3K-2D。 */
export function kdj(
  highs: number[],
  lows: number[],
  closes: number[],
  n = 9,
): { k: Array<number | null>; d: Array<number | null>; j: Array<number | null> } {
  const rsv: number[] = []
  for (let i = 0; i < closes.length; i++) {
    const hi = Math.max(...highs.slice(Math.max(0, i - n + 1), i + 1))
    const lo = Math.min(...lows.slice(Math.max(0, i - n + 1), i + 1))
    rsv.push(hi === lo ? 50 : ((closes[i] - lo) / (hi - lo)) * 100)
  }
  const k = smaCN(rsv, 3, 1)
  // smaCN 等长输出；k 无 null（首值即有效），直接算
  const kk = k as number[]
  const dd = smaCN(kk, 3, 1) as number[]
  const j = kk.map((v, i) => 3 * v - 2 * dd[i])
  return { k: kk, d: dd, j }
}

/** RSI(n)：Wilder 平滑（SMA(U,n,1)/SMA(D,n,1) 国内近似）。 */
export function rsi(closes: number[], n = 14): Array<number | null> {
  const out: Array<number | null> = []
  let avgU = 0
  let avgD = 0
  for (let i = 0; i < closes.length; i++) {
    if (i === 0) {
      out.push(null)
      continue
    }
    const ch = closes[i] - closes[i - 1]
    const u = Math.max(ch, 0)
    const d = Math.max(-ch, 0)
    if (i <= n) {
      avgU += u / n
      avgD += d / n
      out.push(i === n ? (avgD === 0 ? 100 : 100 - (100 * avgU) / (avgU + avgD)) : null)
    } else {
      avgU = (avgU * (n - 1) + u) / n
      avgD = (avgD * (n - 1) + d) / n
      out.push(avgD === 0 ? 100 : 100 - (100 * avgU) / (avgU + avgD))
    }
  }
  return out
}
