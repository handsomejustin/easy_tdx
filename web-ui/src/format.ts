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
