// A股代码 → 市场智能识别。
// 用户只输入 6 位代码，按代码段规则自动匹配 沪市(SH)/深市(SZ)/北交所(BJ)，
// 拼成后端要求的 "市场:代码" 格式（如 SZ:000001）。

export type Market = 'SH' | 'SZ' | 'BJ'

/**
 * 根据 6 位股票代码智能判断所属市场。
 *
 * 规则（按优先级，先匹配到的为准）：
 *   - 北交所(BJ)：43/83/87/92/93/920（小盘/三板）或 4xx/8xx 开头
 *   - 沪市(SH) ：6/9 开头（主板 60/68 科创、B 股 900）或 5 开头（基金 50/51/56/58）
 *   - 其余归深市(SZ)：000/001/002/003/300/301 创业板、200 B股 等
 *
 * @param code 6 位股票代码（纯数字）
 * @returns 市场代码 SH/SZ/BJ；无法判断时默认深市（覆盖面最广）
 */
export function detectMarket(code: string): Market {
  const c = code.trim()
  if (!/^\d{6}$/.test(c)) return 'SZ'

  // 通达信板块指数（沪市）：880 统计 / 881 行业 / 885 概念等
  if (/^88[0-9]/.test(c)) return 'SH'

  // 北交所：43/83/87/92(含920段)/93 + 4xx/8xx（三板/小盘）
  if (/^(43|83|87|92|93|4|8)/.test(c)) return 'BJ'

  // 沪市：6xx（主板/科创板 60/68）、9xx（B股）、5xx（沪市基金 50/51/56/58/50ETF 等）
  if (/^[695]/.test(c)) return 'SH'

  // 其余归深市：000/001/002/003/300/301/200 等
  return 'SZ'
}

/**
 * 把 6 位代码转成后端要求的 "市场:代码" 格式。
 * @param code 6 位股票代码
 */
export function toSymbol(code: string): string {
  return `${detectMarket(code)}:${code.trim()}`
}

/** 市场中文显示名。 */
export function marketLabel(market: Market): string {
  switch (market) {
    case 'SH':
      return '沪市'
    case 'BJ':
      return '北交所'
    default:
      return '深市'
  }
}
