/**
 * 评分引擎核心：插值、加权、否决。
 *
 * 这一层是纯函数 + 零业务依赖，所有场景（单标的/组合/寻优）共用。
 */

import { GRADE_THRESHOLDS, type DimensionScore, type Grade, type GradeResult, type VetoHit } from './types'
import { THRESHOLDS, type DimensionKey } from './thresholds'

/**
 * 按锚点列表做线性插值，返回 0–100 的分数。
 *
 * 锚点按 threshold 升序排列。值越界时取端点（不再外推）。
 * 锚点的 score 走向决定了「越大越好」还是「越小越好」——引擎不关心方向。
 *
 * @example
 * interpolate(THRESHOLDS.max_drawdown.anchors, 0.4165)  // ≈ 30（回撤深）
 * interpolate(THRESHOLDS.sharpe.anchors, 0.529)         // ≈ 42
 */
export function interpolate(anchors: readonly { threshold: number; score: number }[], value: number): number {
  if (!Number.isFinite(value)) return 0
  if (anchors.length === 0) return 0

  // 值小于最小锚点 → 取最低分
  if (value <= anchors[0].threshold) return anchors[0].score
  // 值大于最大锚点 → 取最高分
  if (value >= anchors[anchors.length - 1].threshold) return anchors[anchors.length - 1].score

  // 找到 value 落在哪两个锚点之间，线性插值
  for (let i = 0; i < anchors.length - 1; i++) {
    const a = anchors[i]
    const b = anchors[i + 1]
    if (value >= a.threshold && value <= b.threshold) {
      if (a.threshold === b.threshold) return a.score
      const ratio = (value - a.threshold) / (b.threshold - a.threshold)
      return a.score + ratio * (b.score - a.score)
    }
  }
  // 理论上不会走到这里
  return anchors[anchors.length - 1].score
}

/** 构造一个维度的评分对象。 */
export function scoreDimension(key: DimensionKey, raw: number, weight: number): DimensionScore {
  const cfg = THRESHOLDS[key]
  return {
    key,
    label: cfg.label,
    raw,
    score: interpolate(cfg.anchors, raw),
    weight,
  }
}

/** 加权求和得到总分（0–100）。权重会在调用方归一化。 */
export function weightedTotal(dimensions: DimensionScore[]): number {
  const totalWeight = dimensions.reduce((s, d) => s + d.weight, 0)
  if (totalWeight <= 0) return 0
  return dimensions.reduce((s, d) => s + d.score * d.weight, 0) / totalWeight
}

/** 把分数映射到档位（不考虑否决）。 */
export function scoreToGrade(score: number): Grade {
  for (const { grade, minScore } of GRADE_THRESHOLDS) {
    if (score >= minScore) return grade
  }
  return 'D'
}

/** 档位排序值，便于比较「S > A > B > C > D」。 */
const GRADE_ORDER: Grade[] = ['D', 'C', 'B', 'A', 'S']
export function gradeRank(g: Grade): number {
  return GRADE_ORDER.indexOf(g)
}

/** 取两个档位中「更差」的那个（用于一票否决 cap）。 */
export function worseGrade(a: Grade, b: Grade): Grade {
  return gradeRank(a) <= gradeRank(b) ? a : b
}

/**
 * 根据原始分数、维度明细和否决规则，组装最终的 GradeResult。
 *
 * @param scenario 评级场景
 * @param dimensions 各维度明细（权重已设定）
 * @param vetoes 触发的否决规则（按优先级，引擎不重复计算）
 * @param flags { insufficientSample, isLosing } 特殊标记
 */
export function buildResult(
  scenario: GradeResult['scenario'],
  dimensions: DimensionScore[],
  vetoes: VetoHit[],
  flags: { insufficientSample: boolean; isLosing: boolean },
): GradeResult {
  const rawScore = weightedTotal(dimensions)
  let grade = scoreToGrade(rawScore)

  // 应用所有否决规则：取最严格的 cap
  for (const v of vetoes) {
    grade = worseGrade(grade, v.cap)
  }

  return {
    grade,
    score: Math.round(rawScore * 10) / 10, // 保留 1 位小数
    dimensions,
    vetoes,
    insufficientSample: flags.insufficientSample,
    isLosing: flags.isLosing,
    scenario,
  }
}
