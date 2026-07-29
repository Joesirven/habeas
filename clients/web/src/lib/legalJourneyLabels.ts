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

/** Known technical action_type / reason keys → human labels (wire values unchanged). */
const ACTION_REASON_LABELS: Record<string, string> = {
  'notice.review': 'Fulfillment notice pending',
  'matching.review': 'Matching review pending',
  'access.delivery': 'Access delivery pending',
  'delivery.confirm': 'Delivery confirmation pending',
  'workflow.assignment': 'Assignment pending',
}

/**
 * Map API action/reason keys to plain-English UI labels.
 * Fallback: `.` → ` · `, `_` → spaces (inbox reasonLabel convention).
 */
export function actionReasonLabel(reason: string): string {
  const normalized = reason.trim()
  if (normalized in ACTION_REASON_LABELS) return ACTION_REASON_LABELS[normalized]!
  return normalized.replaceAll('.', ' · ').replaceAll('_', ' ')
}

/**
 * Queue status noun for a reason key — pending by default, or approved when cleared.
 * e.g. notice.review + pending → "Fulfillment notice pending"
 */
export function queueStatusLabel(
  reason: string,
  reviewStatus?: string,
): string {
  const pending = actionReasonLabel(reason)
  const status = (reviewStatus ?? 'pending').trim().toLowerCase()
  if (status === 'approved' && pending.endsWith(' pending')) {
    return `${pending.slice(0, -' pending'.length)} approved`
  }
  return pending
}

/** User-facing copy for Legal Notice gate before weekly DROP upload. */
export const NOTICE_APPROVAL = {
  noun: 'Fulfillment notice pending',
  action: 'Approve fulfillment notice',
  confirmTitle: 'Approve fulfillment notice?',
  hint: 'Clear this gate so the fulfilled DROP row can enter the weekly upload batch',
  empty: 'No fulfillment notices waiting.',
  beforeUpload: 'Fulfillment notice pending — weekly upload',
} as const
