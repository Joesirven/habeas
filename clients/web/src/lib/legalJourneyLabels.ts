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

export function isWorkbenchStageKey(value: string): value is WorkbenchStageKey {
  return (WORKBENCH_STAGE_ORDER as readonly string[]).includes(value)
}

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
  test: 'Test vertical',
  axios_headquarters: 'Axios HQ',
  lever: 'Lever',
  paylocity: 'Paylocity',
  auth0: 'Auth0',
  cassandra: 'Cassandra',
  bizdev_contacts: 'Contact Us Google Sheet',
  hr_alumni: 'Alumni Google Sheet',
}

export function verticalLabel(vertical: string): string {
  const normalized = vertical.trim().toLowerCase()
  if (normalized in VERTICAL_LABELS) return VERTICAL_LABELS[normalized]!
  return normalized.replaceAll('_', ' ')
}

/** Matching-review system titles — mirrors catalog MATCHING_SYSTEM_LABELS. */
const SYSTEM_LABELS: Record<string, string> = {
  axios_headquarters: 'Axios HQ',
  paylocity: 'Paylocity',
  lever: 'Lever',
  auth0: 'Auth0',
  google_sheets: 'Google Sheets',
  bizdev_contacts: 'Contact Us Google Sheet',
  hr_alumni: 'Alumni Google Sheet',
  cassandra: 'CA DROP',
}

/** Catalog slug for the CA DROP hash index — a source, not a connection chip. */
export const DROP_HASH_SYSTEM_ID = 'cassandra'
export const TEST_VERTICAL_ID = 'test'

/** Test vertical placeholders — never show CA DROP as a system name. */
const TEST_VERTICAL_SYSTEM_LABELS: Record<string, string> = {
  cassandra: 'System A',
  hr_alumni: 'System B',
}

export function systemLabel(system: string): string {
  const normalized = system.trim().toLowerCase()
  if (normalized in SYSTEM_LABELS) return SYSTEM_LABELS[normalized]!
  return verticalLabel(normalized)
}

function isDropSourceDisplayLabel(label: string): boolean {
  const normalized = label.trim().toLowerCase()
  return (
    normalized === 'ca drop' ||
    normalized === 'california drop' ||
    normalized === 'cassandra' ||
    normalized === 'drop'
  )
}

/**
 * Visible system / connection name.
 * CA DROP is a source — never returned here. Test vertical uses System A / System B.
 */
export function catalogSystemDisplayLabel(
  system: string | null | undefined,
  options?: { vertical?: string | null; systemLabel?: string | null },
): string | null {
  const id = (system ?? '').trim()
  const vertical = (options?.vertical ?? '').trim().toLowerCase()
  if (vertical === TEST_VERTICAL_ID && id) {
    return TEST_VERTICAL_SYSTEM_LABELS[id] ?? `System ${id}`
  }
  const apiLabel = options?.systemLabel?.trim() || ''
  if (apiLabel && !isDropSourceDisplayLabel(apiLabel)) return apiLabel
  if (!id) return null
  if (id.toLowerCase() === DROP_HASH_SYSTEM_ID) return null
  return systemLabel(id)
}

/**
 * Catalog color tokens → existing Tailwind / Habeas chip classes.
 * Brand navy/mid/light only — no purple or terracotta.
 */
const MATCHING_SYSTEM_COLOR_CLASSES: Record<string, string> = {
  mid: 'border-habeas-mid/30 bg-habeas-mid/10 text-habeas-mid',
  navy: 'border-habeas-navy/30 bg-habeas-navy/8 text-habeas-navy',
  light: 'border-habeas-light/40 bg-habeas-light/15 text-habeas-navy',
  slate: 'border-line bg-canvas text-ink-soft',
  sky: 'border-sky-200 bg-sky-50 text-sky-900',
  teal: 'border-habeas-light/35 bg-habeas-light/10 text-habeas-mid',
}

export function matchingSystemColorClass(token: string): string {
  const normalized = token.trim().toLowerCase()
  return MATCHING_SYSTEM_COLOR_CLASSES[normalized] ?? MATCHING_SYSTEM_COLOR_CLASSES.slate!
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
  /** Batch/stack panes: visible count breakdown (e.g. "8 complete · 2 in progress"). */
  statusLabel?: string
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

const OPS_SUBSTEP_SEQUENCE = [
  'received',
  'triage',
  'download',
  'land',
  'promote',
  'match',
  'review',
  'fulfill',
  'notice',
  'delivery',
] as const

const OPS_SUBSTEP_LABELS: Record<string, string> = {
  received: 'Received',
  triage: 'Triage',
  download: 'Download',
  land: 'Land',
  promote: 'Promote',
  match: 'Match',
  review: 'Review',
  fulfill: 'Fulfill',
  notice: 'Notice',
  delivery: 'Delivery',
  template_notice: 'Template notice',
}

const STATUS_COUNT_ORDER: WorkbenchStageStatus[] = [
  'complete',
  'in_progress',
  'waiting',
  'failed',
  'skipped',
  'not_started',
]

function isDropIntake(intakeSource: string): boolean {
  return intakeSource.trim().toLowerCase() === 'drop'
}

function isAccessRequestType(requestType?: string | null): boolean {
  const normalized = (requestType ?? '').trim().toLowerCase()
  return (
    normalized === 'access' ||
    normalized === 'access_request' ||
    normalized === 'combined'
  )
}

/** Ops fine-stage keys nested under each workbench parent (intake/type-conditioned). */
function workbenchSubstepKeys(opts: {
  intake_source: string
  request_type?: string | null
  kind?: string | null
  current_stage?: string | null
}): Record<WorkbenchStageKey, string[]> {
  const isDrop = isDropIntake(opts.intake_source)
  const current = (opts.current_stage ?? '').trim().toLowerCase()
  const isAccess =
    isAccessRequestType(opts.request_type) ||
    (opts.kind ?? '').trim().toLowerCase() === 'delivery' ||
    current === 'delivery'
  return {
    ingest: isDrop ? ['received', 'download', 'land', 'promote'] : ['received', 'triage'],
    matching: ['match', 'review'],
    fulfillment: ['fulfill'],
    notice: isDrop ? ['notice'] : isAccess ? ['delivery'] : [],
  }
}

function resolveCurrentOpsStage(currentStage: string, applicableKeys: string[]): string {
  const key = currentStage.trim().toLowerCase()
  if ((OPS_SUBSTEP_SEQUENCE as readonly string[]).includes(key)) return key
  if (isWorkbenchStageKey(key)) {
    return applicableKeys.find((item) => OPS_TO_WORKBENCH[item] === key) ?? key
  }
  return key
}

function inferredOpsSubstepStatus(
  key: string,
  currentOps: string,
  currentStatus?: WorkbenchStageStatus | null,
): WorkbenchStageStatus {
  if (key === 'template_notice') {
    return key === currentOps ? (currentStatus ?? 'in_progress') : 'in_progress'
  }
  const keyIdx = OPS_SUBSTEP_SEQUENCE.indexOf(key as (typeof OPS_SUBSTEP_SEQUENCE)[number])
  const currentIdx = OPS_SUBSTEP_SEQUENCE.indexOf(
    currentOps as (typeof OPS_SUBSTEP_SEQUENCE)[number],
  )
  if (keyIdx < 0 || currentIdx < 0) {
    return key === currentOps ? (currentStatus ?? 'in_progress') : 'not_started'
  }
  if (keyIdx < currentIdx) return 'complete'
  if (keyIdx === currentIdx) return currentStatus ?? 'in_progress'
  return 'not_started'
}

/** Visible count breakdown for a stack substep or vertical cluster. */
export function formatStackSubstepCounts(
  counts: Partial<Record<string, number>>,
): string {
  return STATUS_COUNT_ORDER.filter((status) => (counts[status] ?? 0) > 0)
    .map((status) => `${counts[status]} ${workbenchStatusLabel(status).toLowerCase()}`)
    .join(' · ')
}

export type StackJourneyMember = {
  request_id: string
  current_stage: string
  intake_source: string
  request_type?: string | null
  kind?: string | null
  /** When set, overrides inferred in_progress for this member's current substep. */
  status?: WorkbenchStageStatus | null
}

export type AggregatedWorkbenchChrome = DerivedWorkbenchChrome & {
  member_count: number
}

export type OwnerSystemStackMember = {
  request_id: string
  current_stage: string
  vertical?: string | null
  system?: string | null
  system_label?: string | null
  connections?: Array<{
    system?: string | null
    system_label?: string | null
    current_stage?: string | null
    vertical?: string | null
  }>
}

type OwnerSystemMemberRow = {
  request_id: string
  system: string
  system_label: string
  current_stage: string
}

function expandOwnerSystemMembers(
  members: OwnerSystemStackMember[],
): OwnerSystemMemberRow[] {
  const unique = new Map<string, OwnerSystemMemberRow>()
  for (const member of members) {
    const connections =
      member.connections && member.connections.length > 0
        ? member.connections
        : [{ system: member.system, system_label: member.system_label, current_stage: member.current_stage }]
    for (const connection of connections) {
      const system = connection.system?.trim() || ''
      if (!system) continue
      const system_label = catalogSystemDisplayLabel(system, {
        vertical: connection.vertical ?? member.vertical,
        systemLabel: connection.system_label,
      })
      if (!system_label) continue
      const key = `${member.request_id.trim()}::${system}`
      if (unique.has(key)) continue
      unique.set(key, {
        request_id: member.request_id,
        system,
        system_label,
        current_stage: connection.current_stage?.trim() || member.current_stage,
      })
    }
  }
  return [...unique.values()]
}

function parentStatusFromCurrentStage(
  parent: WorkbenchStageKey,
  currentStage: string,
): WorkbenchStageStatus {
  const currentParent = OPS_TO_WORKBENCH[currentStage.trim().toLowerCase()] ?? 'ingest'
  const currentIdx = WORKBENCH_STAGE_ORDER.indexOf(currentParent)
  const parentIdx = WORKBENCH_STAGE_ORDER.indexOf(parent)
  if (parentIdx < 0 || currentIdx < 0) return 'not_started'
  if (parentIdx < currentIdx) return 'complete'
  if (parentIdx === currentIdx) return 'in_progress'
  return 'not_started'
}

/**
 * Owner batch substeps — one row per owned system/connection under each
 * workbench stage, with aggregate counts. Never two fake requests and never
 * first-member-only.
 */
export function aggregateOwnerSystemWorkbenchSubsteps(
  members: OwnerSystemStackMember[],
): DerivedWorkbenchSubstep[] {
  const rows = expandOwnerSystemMembers(members)
  const systems = new Map<string, string>()
  for (const row of rows) {
    if (!systems.has(row.system)) systems.set(row.system, row.system_label)
  }

  const substeps: DerivedWorkbenchSubstep[] = []
  for (const parent of WORKBENCH_STAGE_ORDER) {
    for (const [system, label] of systems) {
      const counts: Partial<Record<WorkbenchStageStatus, number>> = {}
      for (const row of rows) {
        if (row.system !== system) continue
        const status = parentStatusFromCurrentStage(parent, row.current_stage)
        counts[status] = (counts[status] ?? 0) + 1
      }
      const statuses = STATUS_COUNT_ORDER.filter((status) => (counts[status] ?? 0) > 0)
      substeps.push({
        key: `${parent}-${system}`,
        label,
        status: rollupWorkbenchStatus(statuses),
        parent,
        blocker: null,
        statusLabel: formatStackSubstepCounts(counts),
      })
    }
  }
  return substeps
}

/**
 * Four-stage chrome + substep counts across every unique request in a stack.
 * Used by batch/thread detail so Ingest/Matching/Fulfillment/Notice never
 * render the first member's pipeline as if it were the group.
 */
export function aggregateStackWorkbenchChrome(
  members: StackJourneyMember[],
): AggregatedWorkbenchChrome {
  const unique = new Map<string, StackJourneyMember>()
  for (const member of members) {
    const id = member.request_id.trim()
    if (!id || unique.has(id)) continue
    unique.set(id, member)
  }
  const uniqueMembers = [...unique.values()]

  type Tally = {
    key: string
    label: string
    parent: WorkbenchStageKey
    counts: Partial<Record<WorkbenchStageStatus, number>>
  }
  const tallies = new Map<string, Tally>()

  const bump = (key: string, parent: WorkbenchStageKey, status: WorkbenchStageStatus) => {
    const existing = tallies.get(key)
    if (existing) {
      existing.counts[status] = (existing.counts[status] ?? 0) + 1
      return
    }
    tallies.set(key, {
      key,
      label: OPS_SUBSTEP_LABELS[key] ?? key.replaceAll('_', ' '),
      parent,
      counts: { [status]: 1 },
    })
  }

  for (const member of uniqueMembers) {
    const grouped = workbenchSubstepKeys(member)
    const applicable = [
      ...grouped.ingest,
      ...grouped.matching,
      ...grouped.fulfillment,
      ...grouped.notice,
    ]
    const currentOps = resolveCurrentOpsStage(member.current_stage, applicable)
    const noticeKeys =
      grouped.notice.length > 0
        ? grouped.notice
        : inferredOpsSubstepStatus('fulfill', currentOps) === 'complete'
          ? ['template_notice']
          : []
    const keysByParent: Array<[WorkbenchStageKey, string[]]> = [
      ['ingest', grouped.ingest],
      ['matching', grouped.matching],
      ['fulfillment', grouped.fulfillment],
      ['notice', noticeKeys],
    ]
    for (const [parent, keys] of keysByParent) {
      for (const key of keys) {
        bump(key, parent, inferredOpsSubstepStatus(key, currentOps, member.status))
      }
    }
  }

  const substepOrder = [...OPS_SUBSTEP_SEQUENCE, 'template_notice']
  const substeps: DerivedWorkbenchSubstep[] = substepOrder
    .map((key) => tallies.get(key))
    .filter((row): row is Tally => row != null)
    .map((row) => ({
      key: row.key,
      label: row.label,
      status: rollupWorkbenchStatus(
        STATUS_COUNT_ORDER.filter((status) => (row.counts[status] ?? 0) > 0),
      ),
      parent: row.parent,
      blocker: null,
      statusLabel: formatStackSubstepCounts(row.counts),
    }))

  const groupFor = (parent: WorkbenchStageKey) =>
    substeps.filter((step) => step.parent === parent)

  const ingestSubsteps = groupFor('ingest')
  const matchingSubsteps = groupFor('matching')
  const fulfillmentSubsteps = groupFor('fulfillment')
  const noticeSubsteps = groupFor('notice')

  const stages: DerivedWorkbenchStage[] = WORKBENCH_STAGE_ORDER.map((key) => {
    const group =
      key === 'ingest'
        ? ingestSubsteps
        : key === 'matching'
          ? matchingSubsteps
          : key === 'fulfillment'
            ? fulfillmentSubsteps
            : noticeSubsteps
    return {
      stage: key,
      label: workbenchStageLabel(key),
      status: rollupWorkbenchStatus(group.map((step) => step.status)),
      blocker: null,
    }
  })

  const currentParents = uniqueMembers.map(
    (member) => OPS_TO_WORKBENCH[member.current_stage.trim().toLowerCase()] ?? 'ingest',
  )
  const parentIndexes = currentParents.map((parent) => WORKBENCH_STAGE_ORDER.indexOf(parent))
  const currentIdx =
    parentIndexes.length === 0
      ? 0
      : Math.min(...parentIndexes, WORKBENCH_STAGE_ORDER.length - 1)
  const current_stage = WORKBENCH_STAGE_ORDER[Math.max(0, currentIdx)] ?? 'ingest'
  for (let index = 0; index < currentIdx; index += 1) {
    const stage = stages[index]!
    if (stage.status === 'not_started' || stage.status === 'skipped') {
      stage.status = 'complete'
    }
  }
  if (
    uniqueMembers.length > 0 &&
    stages[currentIdx] &&
    stages[currentIdx]!.status === 'not_started'
  ) {
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
    current_stage,
    substeps,
    split_posture,
    member_count: uniqueMembers.length,
  }
}

/**
 * Four-stage rail for ThreadReviewPane / batch detail.
 * Prefer stack rollups whenever more than one unique request is in the stack
 * so `batchWorkbench.stages` (API first-member journey) never paints the rail.
 * Single-member stacks keep richer API stages when the caller supplies them.
 */
export function preferStackChromeStages(
  apiStages: DerivedWorkbenchStage[] | null | undefined,
  stackChrome: AggregatedWorkbenchChrome | null | undefined,
): DerivedWorkbenchStage[] {
  if (stackChrome != null && stackChrome.member_count > 1) {
    return stackChrome.stages
  }
  return apiStages ?? stackChrome?.stages ?? []
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
  const grouped = workbenchSubstepKeys({
    intake_source: opts.intake_source,
    request_type: opts.request_type,
  })
  const ingestKeys = grouped.ingest
  const matchingKeys = grouped.matching
  const fulfillmentKeys = grouped.fulfillment
  const noticeKeys = grouped.notice
  const isDrop = isDropIntake(opts.intake_source)
  const isAccess = isAccessRequestType(opts.request_type)

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
