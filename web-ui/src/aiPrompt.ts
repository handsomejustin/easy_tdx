// AI 解读 Prompt 生成器：把单标的回测报告组装成一段结构化提示词，
// 用户复制后发给任意 LLM（ChatGPT / Claude / DeepSeek / 豆包…）即可获得针对性解读。
//
// 约束：本文件只允许 **type-only** 的本地导入（编译期擦除），
// 保证 node --test 可直跑（与 grading/__tests__ 同一套自检方式）；
// 运行时逻辑全部自包含，不依赖其他模块的值。
//
// 文案口径与后端对齐：指标含义见 src/data/glossary.ts，
// 评分权重见 scoring.py，WF/体检语义见 walkforward.py / fitness.py。

import type {
  BacktestResult,
  Category,
  EvaluateReport,
  ExecutionMode,
  Performance,
  Trade,
  WalkForwardResult,
} from './types'
import type { GradeResult } from './grading/types'

// ── 输入 ─────────────────────────────────────────────────────────────────────

export interface AiPromptInput {
  /** 完整标的代码（带市场前缀，如 "SZ:000001"） */
  symbol: string
  category: Category
  startDate: string
  endDate: string
  /** K 线根数（store.ohlcv.length） */
  bars: number
  /** 策略中文名（如「双均线交叉」） */
  strategyLabel: string
  params: Record<string, number | string | boolean>
  cash: number
  commission: number
  slippage: number
  execution: ExecutionMode
  result: BacktestResult
  /** 附加分析（未勾选/未跑完时传 null，对应段落自动省略） */
  wf?: WalkForwardResult | null
  evaluate?: EvaluateReport | null
  grade?: GradeResult | null
  /** 评级档位的一句话含义（GRADE_META[grade].hint，由组件传入） */
  gradeHint?: string
}

// ── 展示辅助（自包含，避免运行时依赖其他模块）────────────────────────────────

const CATEGORY_LABELS: Record<Category, string> = {
  DAY: '日线',
  WEEK: '周线',
  MONTH: '月线',
  MIN_5: '5 分钟',
  MIN_15: '15 分钟',
  MIN_30: '30 分钟',
  MIN_60: '60 分钟',
  MIN_120: '120 分钟',
}

const EXECUTION_LABELS: Record<ExecutionMode, string> = {
  next_open: '次日开盘价',
  next_close: '次日收盘价',
}

/** 与 MetricTable 同源同序的 25 项指标清单（label + 数字格式） */
const METRIC_LINES: Array<{
  key: keyof Performance
  label: string
  format: 'percent' | 'ratio' | 'int' | 'days'
  group: string
}> = [
  { key: 'total_return', label: '总收益率', format: 'percent', group: '收益' },
  { key: 'annual_return', label: '年化收益', format: 'percent', group: '收益' },
  { key: 'sharpe', label: '夏普比率', format: 'ratio', group: '收益' },
  { key: 'sortino', label: '索提诺比率', format: 'ratio', group: '收益' },
  { key: 'calmar', label: '卡玛比率', format: 'ratio', group: '收益' },
  { key: 'max_drawdown', label: '最大回撤', format: 'percent', group: '风险' },
  { key: 'max_dd_duration', label: '回撤持续', format: 'days', group: '风险' },
  { key: 'volatility', label: '波动率(年化)', format: 'percent', group: '风险' },
  { key: 'ulcer_index', label: 'Ulcer 指数', format: 'percent', group: '风险' },
  { key: 'var_95', label: '日 VaR (95%)', format: 'percent', group: '风险' },
  { key: 'cvar_95', label: '日 CVaR (95%)', format: 'percent', group: '风险' },
  { key: 'total_trades', label: '总交易数', format: 'int', group: '交易' },
  { key: 'win_trades', label: '盈利次数', format: 'int', group: '交易' },
  { key: 'lose_trades', label: '亏损次数', format: 'int', group: '交易' },
  { key: 'win_rate', label: '胜率', format: 'percent', group: '交易' },
  { key: 'profit_factor', label: '盈亏比(利润因子)', format: 'ratio', group: '交易' },
  { key: 'avg_win', label: '平均盈利', format: 'percent', group: '交易' },
  { key: 'avg_loss', label: '平均亏损', format: 'percent', group: '交易' },
  { key: 'max_win', label: '最大盈利', format: 'percent', group: '交易' },
  { key: 'max_loss', label: '最大亏损', format: 'percent', group: '交易' },
  { key: 'avg_holding_days', label: '平均持仓天数', format: 'ratio', group: '交易' },
  { key: 'sqn', label: 'SQN 系统质量', format: 'ratio', group: '交易' },
  { key: 'max_consecutive_wins', label: '最大连胜', format: 'int', group: '交易' },
  { key: 'max_consecutive_losses', label: '最大连亏', format: 'int', group: '交易' },
  { key: 'rejected_trades', label: '拒单数', format: 'int', group: '交易' },
]

function fmtMetric(format: 'percent' | 'ratio' | 'int' | 'days', v: number | undefined): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '-'
  if (format === 'percent') return `${(v * 100).toFixed(2)}%`
  if (format === 'int') return String(Math.round(v))
  if (format === 'days') return `${v.toFixed(0)} 天`
  return v.toFixed(3)
}

function pct(v: number | undefined | null): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '-'
  return `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`
}

function ratio(v: number | undefined | null): string {
  if (v === undefined || v === null || !Number.isFinite(v)) return '-'
  return v.toFixed(2)
}

function fmtParams(params: Record<string, number | string | boolean>): string {
  const entries = Object.entries(params)
  if (entries.length === 0) return '（默认参数）'
  return entries.map(([k, v]) => `${k}=${v}`).join(', ')
}

function fmtMoney(v: number): string {
  return v.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
}

/** "2025-06-23T00:00:00" → "2025-06-23"（截掉时间部分，提示词更整洁） */
function fmtDate(dt: string): string {
  return dt.slice(0, 10)
}

/** WF 窗口字段防御性转数字：老版本后端曾把有限 float 序列化成字符串
 * （如 "-0.2078"），Number() 对数字原值透明、对字符串强制转换、非法值给 NaN。 */
function n(v: number | string | null | undefined): number | undefined {
  const x = Number(v)
  return Number.isFinite(x) ? x : undefined
}

// ── 各段落构建 ───────────────────────────────────────────────────────────────

function sectionRole(): string {
  return [
    '# 角色设定',
    '',
    '你是一位做了十几年量化交易的老手，说话直来直去，心是好的。现在你正和一个刚入门的朋友（我）聊天，我什么都不懂，你解释什么都要说人话。',
    '',
    '# 任务',
    '',
    '下面是我跑出来的回测报告，帮我看看这个策略到底行不行。内容上要说到这六件事，顺序随意，用你自然的说话方式组织：',
    '',
    '1. **先给结论**：这策略现在处于什么状态——「可以继续往下走」「底子不错但还差几步」还是「问题不小，得大改」？一句话说清，再讲理由；',
    '2. **优点和毛病都要讲**：先说说它强在哪（哪些数字是真的好看、说明策略做对了什么），再讲你担心什么。别只挑刺，也别光报喜——我是想知道这策略能不能用，不是来听审判也不是来听表扬的。挑最有说服力的几组数字讲，不用面面俱到；',
    '3. **说说持有体验**：真拿钱跑这个策略，过程大概什么感受——多久交易一次、最惨的时候有多惨、普通人拿不拿得住；',
    '4. **判断是规律还是运气**：从分时段数据（Walk-Forward 各窗收益、训练/验证/测试三段、和死拿不动的对比）找证据。有担心就直说，但像朋友提醒那样说，别像下判决书；',
    '5. **给可执行的下一步**：几条我马上能做的事（改什么参数、加什么过滤、先做什么测试再谈实盘），别空谈；',
    '6. **最后打个分**：给这个策略一个 0-10 的「信心分」，代表你现在有多大把握它值得继续投入。打分要和前面说的话一致（前面夸的多就别打低分，反过来也一样），再用一两句话说说为什么是这个分、到几分你会建议我拿小仓位试试。参考刻度：0-3 建议放弃，4-6 值得继续改（说清往哪改），7-8 可以小仓位试错，9 以上才谈逐步加仓。',
    '',
    '# 说话方式（很重要）',
    '',
    '- 像靠谱朋友给建议：直接、坦诚，但不刻薄、不吓唬人。指出问题是为了帮我做决定，不是逞口舌之快；',
    '- 别像写报告：不要一堆小标题、密集加粗和列表堆砌，自然分段，最关键的结论偶尔加粗就行；',
    '- 禁止八股句式：「事实是」「我的推断是」「总的来说」「综上所述」「作为你的…」「好的，收到」这类全部不要；不确定的地方自然地说「我猜」「大概率」，不要贴标签；',
    '- 不要客套开场，也不要结尾祝词，上来就说正事，说完就停；',
    '- 全文控制在 800 字以内，一屏读完，句句有用；宁可少讲两点，也不要注水；',
    '- 只引用报告里有的数字，报告里没有的不要臆造；要估计就明说是估计；',
    '- 专业词第一次出现时顺口解释一句，别让我再去查。',
    '',
    '参考语气：「这策略胜率近八成、盈亏比四倍，底子是好的；但我最担心的是最近两年基本没赚钱——测试段只涨了 0.16%，这就是我不敢给高分的主要原因。」',
    '',
  ].join('\n')
}

function sectionConfig(i: AiPromptInput): string {
  const lines = [
    '# 回测配置',
    '',
    `- 标的：${i.symbol}（${CATEGORY_LABELS[i.category] ?? i.category}）`,
    `- 回测区间：${i.startDate} ~ ${i.endDate}（共 ${i.bars} 根 K 线）`,
    `- 策略：${i.strategyLabel}`,
    `- 参数：${fmtParams(i.params)}`,
    `- 初始资金：${fmtMoney(i.cash)} 元；佣金 ${i.commission}；滑点 ${i.slippage}；成交价：${EXECUTION_LABELS[i.execution] ?? i.execution}`,
    '',
  ]
  return lines.join('\n')
}

function sectionMetrics(perf: Performance): string {
  const lines = ['# 绩效指标', '']
  for (const g of ['收益', '风险', '交易']) {
    lines.push(`**${g}类**`)
    for (const m of METRIC_LINES.filter((x) => x.group === g)) {
      lines.push(`- ${m.label}：${fmtMetric(m.format, perf[m.key] as number | undefined)}`)
    }
    lines.push('')
  }
  return lines.join('\n')
}

function sectionEquity(result: BacktestResult): string {
  const eq = result.equity_curve
  if (!eq || eq.length === 0) return ''
  let peak = eq[0]
  let trough = eq[0]
  for (const p of eq) {
    if (p.total > peak.total) peak = p
    if (p.total < trough.total) trough = p
  }
  return [
    '# 净值概览',
    '',
    `- 期初资产：${fmtMoney(eq[0].total)} 元（${fmtDate(eq[0].datetime)}）`,
    `- 期末资产：${fmtMoney(eq[eq.length - 1].total)} 元（${fmtDate(eq[eq.length - 1].datetime)}）`,
    `- 峰值：${fmtMoney(peak.total)} 元（${fmtDate(peak.datetime)}）；谷值：${fmtMoney(trough.total)} 元（${fmtDate(trough.datetime)}）`,
    '',
  ].join('\n')
}

function sectionWf(wf: WalkForwardResult): string {
  if (!wf || wf.windows.length === 0) return ''
  const lines = [
    '# Walk-Forward 样本外验证（同参数跨时段稳定性）',
    '',
    `- 窗口数：${wf.n_windows}；前 ${(wf.warmup_ratio * 100).toFixed(0)}% 数据为预热区不参与评估；每窗从空仓独立开仓`,
    `- 盈利窗占比：${(wf.consistency * 100).toFixed(0)}%（${wf.windows.filter((w) => (n(w.total_return) ?? 0) > 0).length}/${wf.windows.length}）`,
    `- 连乘收益（各窗复利衔接）：${pct(wf.chained_return)}`,
    `- 最差窗 / 最好窗：${pct(wf.worst_window)} / ${pct(wf.best_window)}；平均夏普：${ratio(wf.mean_sharpe)}；总交易：${wf.total_trades} 笔`,
    '',
    '逐窗收益（时间升序，红涨绿跌口径无关，正=赚）：',
    '',
  ]
  for (const w of wf.windows) {
    lines.push(
      `- 窗${w.index + 1}（${w.start} ~ ${w.end}）：${pct(n(w.total_return))}，夏普 ${ratio(n(w.sharpe))}，最大回撤 ${pct(n(w.max_drawdown))}，${w.total_trades} 笔（胜率 ${pct(n(w.win_rate))}）`,
    )
  }
  lines.push('')
  return lines.join('\n')
}

function sectionEvaluate(ev: EvaluateReport): string {
  const lines = ['# 一条龙评估', '']

  // 综合评分
  const labels: Record<string, string> = {
    total_return: '收益',
    sharpe: '夏普',
    max_drawdown: '回撤',
    sortino: '索提诺',
    wf_consistency: 'WF 一致性',
  }
  lines.push(`**综合评分：${ev.score.total.toFixed(1)} / 100**（权重：${Object.entries(ev.score.weights_used)
    .map(([k, w]) => `${labels[k] ?? k} ${(w * 100).toFixed(0)}%`)
    .join(' + ')}）`)
  lines.push(`- 分项：${Object.entries(ev.score.components)
    .map(([k, v]) => `${labels[k] ?? k} ${v.toFixed(0)}`)
    .join('，')}`)
  lines.push('')

  // 基准对比
  const b = ev.benchmark
  lines.push('**对比买入持有基准**')
  lines.push(`- 策略总收益 ${pct(ev.performance.total_return)} vs 买入持有 ${pct(b.buy_hold.total_return)}，超额收益 ${pct(b.excess_return)}`)
  if (b.alpha !== undefined || b.beta !== undefined) {
    lines.push(
      `- α（年化超额）${pct(b.alpha)}；β（敏感度）${ratio(b.beta)}；信息比率 ${ratio(b.information_ratio)}；跟踪误差 ${pct(b.tracking_error)}`,
    )
  }
  lines.push(`- 买入持有基准：年化 ${pct(b.buy_hold.annual_return)}，最大回撤 ${pct(b.buy_hold.max_drawdown)}，夏普 ${ratio(b.buy_hold.sharpe)}，卡玛 ${ratio(b.buy_hold.calmar)}，波动率 ${pct(b.buy_hold.volatility)}`)
  lines.push('')

  // 适配性体检
  const f = ev.fitness
  lines.push(
    `**适配性体检：${f.passed_count}/${f.total_checks} 通过（train/valid/test = ${f.split.map((s) => (s * 100).toFixed(0)).join('/')}）${f.high_fitness ? '，达到「高适配」' : ''}**`,
  )
  for (const c of f.checks) {
    lines.push(`- ${c.passed ? '✓' : '✗'} ${c.detail}`)
  }
  lines.push('')
  return lines.join('\n')
}

function sectionGrade(grade: GradeResult, hint: string | undefined): string {
  const lines = [
    '# 评级（不看收益率，面向「普通人拿不拿得住」）',
    '',
    `- 档位：**${grade.grade}**（总分 ${grade.score.toFixed(1)}/100）${hint ? `——${hint}` : ''}`,
  ]
  if (grade.dimensions.length > 0) {
    lines.push(
      `- 维度得分：${grade.dimensions
        .map((d) => `${d.label} ${d.score.toFixed(0)}/100（权重 ${(d.weight * 100).toFixed(0)}%）`)
        .join('，')}`,
    )
  }
  if (grade.vetoes.length > 0) {
    lines.push(`- ⚠ 一票否决：${grade.vetoes.map((v) => v.reason).join('；')}`)
  }
  if (grade.insufficientSample) {
    lines.push('- ⚠ 交易样本有限（< 10 笔），胜率/盈亏比已降权处理')
  }
  if (grade.isLosing) {
    lines.push('- ⚠ 系统亏损（利润因子 < 1）')
  }
  lines.push('')
  return lines.join('\n')
}

function sectionTrades(trades: Trade[]): string {
  const recent = trades.slice(-8)
  if (recent.length === 0) return ''
  const lines = ['# 最近成交（最后 8 笔）', '']
  for (const t of recent) {
    const dir = t.direction === 'BUY' ? '买入' : '卖出'
    const pnl = t.direction === 'SELL' && t.pnl !== 0 ? `，本笔盈亏 ${t.pnl >= 0 ? '+' : ''}${fmtMoney(t.pnl)} 元` : ''
    lines.push(`- ${fmtDate(t.datetime)} ${dir} ${Math.round(t.size)} 股 @ ${t.price.toFixed(2)}${pnl}`)
  }
  lines.push('')
  return lines.join('\n')
}

function sectionFooter(): string {
  return [
    '# 背景与免责',
    '',
    '以上数据来自 easy-tdx 的历史 K 线回测（已计入佣金与滑点）。历史回测存在幸存者偏差与未来不确定性，不构成投资建议，你的解读也以研究学习为目的。',
    '数据里缺失的项（显示 - 或整段没有的）直接跳过，不用专门解释局限。',
    '好了，开始吧。',
  ].join('\n')
}

// ── 主函数 ───────────────────────────────────────────────────────────────────

/** 组装 AI 解读 Prompt（markdown 结构，任意 LLM 可直接消费）。 */
export function buildAiPrompt(input: AiPromptInput): string {
  const parts: string[] = [
    sectionRole(),
    sectionConfig(input),
    sectionMetrics(input.result.performance),
    sectionEquity(input.result),
  ]
  if (input.wf) parts.push(sectionWf(input.wf))
  if (input.evaluate) parts.push(sectionEvaluate(input.evaluate))
  if (input.grade) parts.push(sectionGrade(input.grade, input.gradeHint))
  const trades = sectionTrades(input.result.trades)
  if (trades) parts.push(trades)
  parts.push(sectionFooter())
  return parts.join('\n')
}
