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

/** KTD2 workbench four-stage rail (Ingest → Matching → Fulfillment → Notice). */

export const WORKBENCH_STAGE_ORDER = [
  'ingest',
  'matching',
  'fulfillment',
  'notice',
] as const

export type WorkbenchStageKey = (typeof WORKBENCH_STAGE_ORDER)[number]

const WORKBENCH_STAGE_LABELS: Record<string, string> = {
  ingest: 'Ingest',
  matching: 'Matching',
  fulfillment: 'Fulfillment',
  notice: 'Notice',
}

export function workbenchStageLabel(stageKey: string): string {
  const normalized = stageKey.trim().toLowerCase()
  if (normalized in WORKBENCH_STAGE_LABELS) return WORKBENCH_STAGE_LABELS[normalized]!
  return normalized.replaceAll('_', ' ')
}

/** Vertical catalog labels (live `data` + coming-soon stubs, KTD3). */
const VERTICAL_LABELS: Record<string, string> = {
  data: 'Data',
  mailchimp: 'Mailchimp',
  lever: 'Lever',
  paylocity: 'Paylocity',
  auth0: 'Auth0',
  cassandra: 'Cassandra',
}

export function verticalLabel(vertical: string): string {
  const normalized = vertical.trim().toLowerCase()
  if (normalized in VERTICAL_LABELS) return VERTICAL_LABELS[normalized]!
  return normalized.replaceAll('_', ' ')
}

const WORKBENCH_STATUS_LABELS: Record<string, string> = {
  not_started: 'Not started',
  skipped: 'Skipped',
  waiting: 'Waiting',
  in_progress: 'In progress',
  complete: 'Complete',
  failed: 'Failed',
}

export function workbenchStatusLabel(status: string): string {
  const normalized = status.trim().toLowerCase()
  if (normalized in WORKBENCH_STATUS_LABELS) return WORKBENCH_STATUS_LABELS[normalized]!
  return normalized.replaceAll('_', ' ')
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
