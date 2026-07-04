/**
 * 评级系统类型定义。
 *
 * 评级目的：让普通人一眼判断这个品种/策略是否适合「经常参与投资」。
 * - 不只是看收益，更要看「套牢后能不能回本」「大部分时间是不是在亏」。
 * - 低评级 = 不建议普通人参与，哪怕近期收益率高，长期套牢风险也大。
 *
 * 5 档：S（优秀）/ A（适合）/ B（谨慎）/ C（不建议经常参与）/ D（别碰）。
 */

/** 评级档位。D 包含「系统亏损」和「样本不足」两类特殊情况。 */
export type Grade = 'S' | 'A' | 'B' | 'C' | 'D'

/** 单个评分维度（如「最大回撤」「胜率」）。 */
export interface DimensionScore {
  /** 维度标识，如 'max_drawdown' / 'win_rate' */
  key: string
  /** 中文名，如「最大回撤」 */
  label: string
  /** 该维度原始值 */
  raw: number
  /** 该维度在 0–100 的单项分（越接近 100 越好） */
  score: number
  /** 该维度在总分中的权重（0–1，所有维度权重和应为 1） */
  weight: number
}

/** 一票否决触发记录。 */
export interface VetoHit {
  /** 否决规则标识 */
  key: string
  /** 触发原因（中文，可直接展示） */
  reason: string
  /** 否决后的结果档位 */
  cap: Grade
}

/** 评级结果。所有场景的评级函数都返回这个结构。 */
export interface GradeResult {
  /** 最终档位 */
  grade: Grade
  /** 总分（0–100，否决后为否决后的分数） */
  score: number
  /** 各维度明细，用于展示「为什么是这个评级」 */
  dimensions: DimensionScore[]
  /** 触发的一票否决规则（空数组表示未触发） */
  vetoes: VetoHit[]
  /**
   * 是否为「交易样本不足」（笔数 < 10）。
   * 触发后：win_rate / profit_factor 维度权重降为 0，重分配给净值类维度。
   * 评级照常给出（不再否决到 D），但前端会展示「⚠ 交易样本有限」提示。
   */
  insufficientSample: boolean
  /** 是否为「系统亏损」（profit_factor < 1，实际在亏钱） */
  isLosing: boolean
  /** 评级使用的场景，便于前端展示差异化文案 */
  scenario: 'single' | 'portfolio' | 'optimize'
}

/** 档位到展示元数据的映射（颜色、文案）。供 GradeBadge 使用。 */
export interface GradeMeta {
  grade: Grade
  /** 主色 CSS 变量名（如 'var(--warn)'）或直接颜色值 */
  color: string
  /** 一句话含义 */
  hint: string
  /** 是否适合普通人参与 */
  recommend: 'yes' | 'caution' | 'no'
}

/** 档位元数据表。 */
export const GRADE_META: Record<Grade, GradeMeta> = {
  S: {
    grade: 'S',
    color: '#e0b341', // 金
    hint: '长期持有体验优秀，回撤浅、胜率稳',
    recommend: 'yes',
  },
  A: {
    grade: 'A',
    color: 'var(--down)', // 绿（A 股惯例绿即好）
    hint: '适合经常参与，套牢后能较快回本',
    recommend: 'yes',
  },
  B: {
    grade: 'B',
    color: 'var(--accent)', // 蓝
    hint: '可参与但需择时，套牢回本有压力',
    recommend: 'caution',
  },
  C: {
    grade: 'C',
    color: 'var(--warn)', // 橙
    hint: '风险偏高，长期套牢风险大',
    recommend: 'caution',
  },
  D: {
    grade: 'D',
    color: 'var(--up)', // 红（A 股惯例红即危险）
    hint: '持有体验差或系统亏损，不建议参与',
    recommend: 'no',
  },
}

/** 档位分数阈值（左闭右开：score >= 阈值即落入该档）。 */
export const GRADE_THRESHOLDS: { grade: Grade; minScore: number }[] = [
  { grade: 'S', minScore: 88 },
  { grade: 'A', minScore: 73 },
  { grade: 'B', minScore: 58 },
  { grade: 'C', minScore: 43 },
  { grade: 'D', minScore: 0 },
]
