// 共享数字格式化工具。ECharts tooltip/axis 统一用两位小数。

/** 数字保留两位小数（NaN/Inf 返回 '-'）。 */
export function fmt2(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-'
  return v.toFixed(2)
}

/** 百分比（接受小数如 0.1234 → "12.34%"）。 */
export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-'
  return `${(v * 100).toFixed(2)}%`
}

/** 成交额/市值大数（元 → 亿/万亿，A股口径）。 */
export function fmtAmount(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-'
  if (Math.abs(v) >= 1e12) return `${(v / 1e12).toFixed(2)}万亿`
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿`
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)}万`
  return v.toFixed(0)
}

/** 成交量（手 → 万手/亿手）。 */
export function fmtVol(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-'
  if (Math.abs(v) >= 1e8) return `${(v / 1e8).toFixed(2)}亿手`
  if (Math.abs(v) >= 1e4) return `${(v / 1e4).toFixed(2)}万手`
  return v.toFixed(0)
}

/** 涨跌幅带号（接受百分数如 2.35 → "+2.35%"）。 */
export function fmtPctSigned(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return '-'
  const s = v.toFixed(digits)
  return v > 0 ? `+${s}%` : `${s}%`
}

/** 按涨跌方向取色 class（涨红/跌绿/平灰）。 */
export function dirClass(v: number | null | undefined): string {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return 'flat'
  return v > 0 ? 'up' : 'down'
}
