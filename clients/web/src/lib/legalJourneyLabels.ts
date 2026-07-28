/** KD29 user-facing coarse stage labels — API keys unchanged (OQ15). */

export const COARSE_STAGE_ORDER = [
  'receive',
  'matching',
  'data_owner_review',
  'legal_review',
  'fulfillment',
  'delivery_notice',
] as const

export type CoarseStageKey = (typeof COARSE_STAGE_ORDER)[number]

const STAGE_LABELS: Record<string, string> = {
  receive: 'receive',
  matching: 'matching',
  data_owner_review: 'data owner review',
  legal_review: 'legal / pre-fulfillment',
  fulfillment: 'fulfillment',
  delivery_notice: 'delivery / DROP notice',
  // Legacy / ops keys occasionally seen in payloads
  triage: 'receive',
  review: 'data owner review',
  notice: 'delivery / DROP notice',
  delivery: 'delivery / DROP notice',
}

export function stageLabel(stageKey: string): string {
  const normalized = stageKey.trim().toLowerCase()
  if (normalized in STAGE_LABELS) return STAGE_LABELS[normalized]!
  return normalized.replaceAll('_', ' ')
}

export function stageReachLabel(stageKey: string): string {
  return stageLabel(stageKey)
}
