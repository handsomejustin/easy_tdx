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

/** 涨跌幅 → 红涨绿跌背景样式（|pct| 分 5 档透明度，与板块热力图/热点矩阵同规）。 */
export function pctCellStyle(pct: number | null | undefined): Record<string, string> {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return { background: 'transparent' }
  if (pct === 0) return { background: 'var(--bg-elevated)', color: 'var(--text-muted)' }
  const mag = Math.abs(pct)
  const tier = mag > 3 ? 0.82 : mag > 2 ? 0.62 : mag > 1 ? 0.42 : mag > 0.5 ? 0.26 : 0.14
  const base = pct > 0 ? '239, 65, 70' : '24, 160, 88' // var(--up) / var(--down) 的 rgb
  return { background: `rgba(${base}, ${tier})`, color: '#fff' }
}
