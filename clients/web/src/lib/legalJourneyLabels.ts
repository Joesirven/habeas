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
  'fulfillment.kickoff': 'Fulfillment kickoff pending',
  'fulfillment.kickoff_not_approved': 'Fulfillment kickoff not approved',
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

/** Vertical catalog labels (KD20 catalog + legacy journey stubs). */
const VERTICAL_LABELS: Record<string, string> = {
  communications: 'Communications',
  people_hr: 'People/HR',
  tech: 'Tech',
  bizdev: 'BizDev',
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

/** Ops fine-stage → KTD2 workbench parent (client fallback when workbench API is unavailable). */
const OPS_TO_WORKBENCH: Record<string, WorkbenchStageKey> = {
  received: 'ingest',
  triage: 'ingest',
  download: 'ingest',
  land: 'ingest',
  promote: 'ingest',
  match: 'matching',
  review: 'matching',
  fulfill: 'fulfillment',
  fulfillment: 'fulfillment',
  notice: 'notice',
  delivery: 'notice',
}

/** Map an ops fine-stage key (`meta.stage`) to the four-stage workbench parent. */
export function opsStageToWorkbench(opsStage: string): WorkbenchStageKey | null {
  const key = opsStage.trim().toLowerCase()
  return OPS_TO_WORKBENCH[key] ?? null
}

const STATUS_RANK: Record<string, number> = {
  failed: 5,
  in_progress: 4,
  waiting: 3,
  not_started: 2,
  skipped: 1,
  complete: 0,
}

export type WorkbenchStageStatus =
  | 'not_started'
  | 'skipped'
  | 'in_progress'
  | 'waiting'
  | 'complete'
  | 'failed'

export type DerivedWorkbenchStage = {
  stage: WorkbenchStageKey
  label: string
  status: WorkbenchStageStatus
  blocker: string | null
}

export type DerivedWorkbenchSubstep = {
  key: string
  label: string
  status: WorkbenchStageStatus
  parent: WorkbenchStageKey
  blocker: string | null
}

export type DerivedWorkbenchChrome = {
  stages: DerivedWorkbenchStage[]
  current_stage: WorkbenchStageKey
  substeps: DerivedWorkbenchSubstep[]
  split_posture: boolean
}

type OpsStageLike = {
  stage: string
  label: string
  status: string
  blocker?: string | null
}

function rollupWorkbenchStatus(statuses: WorkbenchStageStatus[]): WorkbenchStageStatus {
  if (statuses.length === 0) return 'not_started'
  let best: WorkbenchStageStatus = 'complete'
  let bestRank = -1
  for (const status of statuses) {
    const rank = STATUS_RANK[status] ?? 0
    if (rank > bestRank) {
      best = status
      bestRank = rank
    }
  }
  return best
}

function asWorkbenchStatus(status: string): WorkbenchStageStatus {
  const normalized = status.trim().toLowerCase()
  if (normalized in STATUS_RANK) return normalized as WorkbenchStageStatus
  return 'not_started'
}

/**
 * Map ops fine journey → four-stage rail + type/source-conditioned substeps (KTD2).
 * Used when `GET …/journey-workbench` is unavailable so detail never falls back to KD29 six keys.
 */
export function deriveWorkbenchChromeFromOpsJourney(opts: {
  stages: OpsStageLike[]
  current_stage: string
  intake_source: string
  request_type?: string | null
}): DerivedWorkbenchChrome {
  const byStage = new Map(opts.stages.map((stage) => [stage.stage, stage]))
  const intake = opts.intake_source.trim().toLowerCase()
  const requestType = (opts.request_type ?? '').trim().toLowerCase()
  const isDrop = intake === 'drop'
  const isAccess =
    requestType === 'access' ||
    requestType === 'access_request' ||
    requestType === 'combined'

  const ingestKeys = isDrop
    ? ['received', 'download', 'land', 'promote']
    : ['received', 'triage']
  const matchingKeys = ['match', 'review']
  const fulfillmentKeys = ['fulfill']
  const noticeKeys = isDrop ? ['notice'] : isAccess ? ['delivery'] : []

  const substepsFor = (keys: string[], parent: WorkbenchStageKey): DerivedWorkbenchSubstep[] =>
    keys
      .map((key) => byStage.get(key))
      .filter((stage): stage is OpsStageLike => stage != null)
      .map((stage) => ({
        key: stage.stage,
        label: stage.label,
        status: asWorkbenchStatus(stage.status),
        parent,
        blocker: stage.blocker ?? null,
      }))

  const ingestSubsteps = substepsFor(ingestKeys, 'ingest')
  const matchingSubsteps = substepsFor(matchingKeys, 'matching')
  const fulfillmentSubsteps = substepsFor(fulfillmentKeys, 'fulfillment')
  const noticeSubsteps = [...substepsFor(noticeKeys, 'notice')]

  // Non-DROP delete/opt-out: surface a single notice placeholder when fulfill is done.
  if (!isDrop && !isAccess && noticeSubsteps.length === 0) {
    const fulfill = byStage.get('fulfill')
    if (fulfill && asWorkbenchStatus(fulfill.status) === 'complete') {
      noticeSubsteps.push({
        key: 'template_notice',
        label: 'Template notice',
        status: 'in_progress',
        parent: 'notice',
        blocker: null,
      })
    }
  }

  const stages: DerivedWorkbenchStage[] = WORKBENCH_STAGE_ORDER.map((key) => {
    const group =
      key === 'ingest'
        ? ingestSubsteps
        : key === 'matching'
          ? matchingSubsteps
          : key === 'fulfillment'
            ? fulfillmentSubsteps
            : noticeSubsteps
    const status = rollupWorkbenchStatus(group.map((step) => step.status))
    const blocker = group.find((step) => step.blocker)?.blocker ?? null
    return {
      stage: key,
      label: workbenchStageLabel(key),
      status,
      blocker,
    }
  })

  // Advance completed prefixes from current ops stage (same idea as coarse rail).
  const currentParent =
    OPS_TO_WORKBENCH[opts.current_stage.trim().toLowerCase()] ?? 'ingest'
  const currentIdx = WORKBENCH_STAGE_ORDER.indexOf(currentParent)
  for (let index = 0; index < currentIdx; index += 1) {
    const stage = stages[index]!
    if (stage.status === 'not_started' || stage.status === 'skipped') {
      stage.status = 'complete'
    }
  }
  if (stages[currentIdx] && stages[currentIdx]!.status === 'not_started') {
    stages[currentIdx]!.status = 'in_progress'
  }

  const matchingIncomplete = matchingSubsteps.some(
    (step) => step.status !== 'complete' && step.status !== 'skipped',
  )
  const fulfillmentStarted = fulfillmentSubsteps.some(
    (step) =>
      step.status === 'in_progress' ||
      step.status === 'waiting' ||
      step.status === 'complete' ||
      step.status === 'failed',
  )
  const split_posture = matchingIncomplete && fulfillmentStarted
  if (split_posture) {
    const matching = stages.find((stage) => stage.stage === 'matching')
    const fulfillment = stages.find((stage) => stage.stage === 'fulfillment')
    if (matching) matching.status = 'in_progress'
    if (fulfillment) fulfillment.status = 'in_progress'
  }

  return {
    stages,
    current_stage: currentParent,
    substeps: [
      ...ingestSubsteps,
      ...matchingSubsteps,
      ...fulfillmentSubsteps,
      ...noticeSubsteps,
    ],
    split_posture,
  }
}
