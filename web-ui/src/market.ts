// A股代码 → 市场智能识别。
// 用户只输入 6 位代码，按代码段规则自动匹配 沪市(SH)/深市(SZ)/北交所(BJ)，
// 拼成后端要求的 "市场:代码" 格式（如 SZ:000001）。

export type Market = 'SH' | 'SZ' | 'BJ'
export type ExMarket = 'HK' | 'US'

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

/**
 * 非 A 股市场识别：5 位数字 = 港股（如 00700），1-5 位字母 = 美股（如 TSLA）。
 * @param code 用户输入的代码（已 trim）
 * @returns 'HK' | 'US'；A 股 6 位数字或其他格式返回 null
 */
export function detectExMarket(code: string): ExMarket | null {
  const c = code.trim()
  if (/^\d{5}$/.test(c)) return 'HK'
  if (/^[A-Za-z]{1,5}$/.test(c)) return 'US'
  return null
}

/** 扩展市场 → 后端 /ex/* 接口的 market 参数（协议名）。 */
export function exMarketParam(m: ExMarket): string {
  return m === 'HK' ? 'HK_MAIN_BOARD' : 'US_STOCK'
}

/** 市场下拉选项（SymbolPicker / StocksPicker 共用）。value 与后端 /ex/* 协议名一致。 */
export interface MarketOption {
  value: string
  label: string
}
export const MARKET_OPTIONS: MarketOption[] = [
  { value: 'auto', label: '自动识别' },
  { value: 'HK', label: '港股' },
  { value: 'US', label: '美股' },
  { value: 'SH_FUTURES', label: '期货·上期所' },
  { value: 'DL_FUTURES', label: '期货·大商所' },
  { value: 'ZZ_FUTURES', label: '期货·郑商所' },
  { value: 'CFFEX_FUTURES', label: '期货·中金所' },
  { value: 'SH_GOLD', label: '期货·上金所' },
  { value: 'GZ_FUTURES', label: '期货·广期所' },
  { value: 'CRYPTO', label: '加密货币·币安' },
]

/**
 * 按市场选择 + 代码生成带前缀的标的符号（如 SZ:000001 / US_STOCK:TSLA / CRYPTO:BTCUSDT）。
 * auto 模式按代码格式识别（6位数字=A股、5位数字=港股、1-5位字母=美股）；
 * 无法识别返回 null。
 */
export function marketPrefix(sel: string, code: string): string | null {
  const c = code.trim()
  if (!c) return null
  if (sel === 'auto') {
    if (/^\d{6}$/.test(c)) return `${detectMarket(c)}:${c}`
    if (/^\d{5}$/.test(c)) return `HK_MAIN_BOARD:${c}`
    if (/^[A-Za-z]{1,5}$/.test(c)) return `US_STOCK:${c.toUpperCase()}`
    return null
  }
  if (sel === 'HK') return `HK_MAIN_BOARD:${c}`
  if (sel === 'US') return `US_STOCK:${c.toUpperCase()}`
  if (sel === 'CRYPTO') return `CRYPTO:${c.toUpperCase().replace(/[\/\-_]/g, '')}`
  return `${sel}:${c}` // 期货各交易所
}

/** 市场中文显示名（A 股 + 扩展市场）。 */
export function marketLabel(market: Market | ExMarket): string {
  switch (market) {
    case 'SH':
      return '沪市'
    case 'BJ':
      return '北交所'
    case 'HK':
      return '港股'
    case 'US':
      return '美股'
    default:
      return '深市'
  }
}
