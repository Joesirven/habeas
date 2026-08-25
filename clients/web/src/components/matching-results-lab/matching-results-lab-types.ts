import type {
  InboxStatusOption,
  MatchingResultLabMethodId,
} from '@/components/inbox-status-lab/status-selector-types'
import type {
  DropResponseStatusCode,
  MatchedPersonContact,
  MatchingResultDetail,
  MatchingResultRow,
  NeedsAttentionItem,
} from '@/lib/api'
import type { MatchingConnectorGate } from '@/lib/connection-display'
import { catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { isRequestUuid } from '@/lib/utils'

export type { InboxStatusOption, MatchingResultLabMethodId }

export {
  MATCHING_RESULT_LAB_METHODS,
  MATCHING_RESULT_LAB_METHOD_STORAGE_KEY,
  readMatchingResultLabMethod,
  writeMatchingResultLabMethod,
} from '@/components/inbox-status-lab/status-selector-types'

export type MatchingResultsLabViewExportName =
  | 'NativeSelectView'
  | 'SegmentedView'
  | 'RadioPopoverView'
  | 'ComboboxView'
  | 'SplitButtonView'
  | 'InlineChipsView'
  | 'CommandPaletteView'
  | 'StepperConfirmView'
  | 'TwoTierView'
  | 'ApplySelectionView'

/** Map method id → view module export name under `./views/`. */
export const MATCHING_RESULTS_LAB_VIEW_MODULES: Record<
  MatchingResultLabMethodId,
  MatchingResultsLabViewExportName
> = {
  'native-select': 'NativeSelectView',
  segmented: 'SegmentedView',
  'radio-popover': 'RadioPopoverView',
  combobox: 'ComboboxView',
  'split-button': 'SplitButtonView',
  'inline-chips': 'InlineChipsView',
  'command-palette': 'CommandPaletteView',
  'stepper-confirm': 'StepperConfirmView',
  'two-tier': 'TwoTierView',
  'apply-selection': 'ApplySelectionView',
}

export type MatchingLabTarget = {
  request_id: string
  vertical: string | null
  system: string | null
}

/** Queue identity — (request_id, vertical, system). Never POST this as request_id. */
export function matchingLabItemKey(item: {
  request_id: string
  vertical?: string | null
  system?: string | null
  system_id?: string | null
}): string {
  const requestId = item.request_id.trim()
  const vertical = item.vertical?.trim() ?? ''
  const system = matchingLabSystemId(item) ?? ''
  if (vertical && system) return `${requestId}::${vertical}::${system}`
  if (vertical) return `${requestId}::${vertical}`
  return requestId
}

export function matchingLabSystemId(item: {
  system?: string | null
  system_id?: string | null
}): string | null {
  const value = (item.system ?? item.system_id)?.trim()
  return value || null
}

export function matchingLabTarget(item: NeedsAttentionItem): MatchingLabTarget {
  return {
    request_id: item.request_id,
    vertical: item.vertical?.trim() || null,
    system: matchingLabSystemId(item),
  }
}

/** Canonical UUID for mutations — drop composite lab keys. */
export function matchingLabRequestId(value: string): string | null {
  const requestId = value.includes('::') ? value.slice(0, value.indexOf('::')) : value
  return isRequestUuid(requestId) ? requestId : null
}

/** Pending-like review → matching.review; approved → matching.approved; else matching. */
function matchingStageFromReviewStatus(reviewStatus: string): string {
  const status = reviewStatus.trim().toLowerCase()
  if (status === 'matching.review' || status === 'matching.approved' || status === 'matching') {
    return status
  }
  if (status.includes('pending')) return 'matching.review'
  if (status === 'approved' || status === 'review_approved' || status.startsWith('approved')) {
    return 'matching.approved'
  }
  return 'matching'
}

/** Landed DROP Data matching_results row → inbox queue item. */
export function matchingResultRowToInboxItem(row: MatchingResultRow): NeedsAttentionItem {
  return {
    request_id: row.request_id,
    reason: 'matching_result',
    kind: 'matching',
    current_stage: matchingStageFromReviewStatus(row.review_status),
    intake_source: 'drop',
    received_at: row.recorded_at,
    requested_at: row.recorded_at,
    approval_id: row.approval_id,
    matched: row.matched,
    match_count: row.match_count,
    match_type: row.match_type,
    recommended_response_status: row.recommended_response_status,
    matched_via: row.matched_via,
    requestor_state: row.requestor_state ?? null,
    review_status: row.review_status,
    vertical: 'data',
  }
}

export function dwidsForStatus(
  statusId: string | null,
  _contacts: MatchedPersonContact[],
  selected: string[],
): string[] {
  if (statusId === '5') return []
  if (statusId === '3' || statusId === '4') return selected
  return selected
}

export function parseDropStatusId(statusId: string | null): DropResponseStatusCode | null {
  if (statusId === '3' || statusId === '4' || statusId === '5') return Number(statusId) as DropResponseStatusCode
  return null
}

/** Results lab System A — CA DROP / MDR people. */
export const MATCHING_LAB_SYSTEM_A_IDS = ['cassandra'] as const
/** Results lab System B — Auth0 (hr_alumni maps here for this lab). */
export const MATCHING_LAB_SYSTEM_B_IDS = ['auth0', 'hr_alumni'] as const

export type MatchingLabSystemKind = 'a' | 'b' | 'other'
export type MatchingLabPeopleSource = 'mdr' | 'auth0'

export type MatchingLabSystemIdentity = {
  system?: string | null
  system_id?: string | null
  system_label?: string | null
  vertical?: string | null
}

export type MatchingLabSystemDisplay = {
  kind: MatchingLabSystemKind
  /** Owner-facing: System A / System B, or catalog name. */
  label: string
  source: MatchingLabPeopleSource | null
  /** MDR or Auth0 — directory used for add-person search. */
  sourceLabel: string | null
}

export const MATCHING_LAB_SYSTEM_KIND_LABEL: Record<MatchingLabSystemKind, string> = {
  a: 'System A',
  b: 'System B',
  other: 'This system',
}

export const MATCHING_LAB_PEOPLE_SOURCE_LABEL: Record<MatchingLabPeopleSource, string> = {
  mdr: 'MDR',
  auth0: 'Auth0',
}

const SYSTEM_A_IDS = new Set<string>(MATCHING_LAB_SYSTEM_A_IDS)
const SYSTEM_B_IDS = new Set<string>(MATCHING_LAB_SYSTEM_B_IDS)

export function matchingLabNormalizeSystemId(value: string | null | undefined): string | null {
  const trimmed = value?.trim().toLowerCase()
  return trimmed || null
}

export function matchingLabSystemKind(
  system: string | null | undefined,
): MatchingLabSystemKind {
  const id = matchingLabNormalizeSystemId(system)
  if (!id) return 'other'
  if (SYSTEM_A_IDS.has(id)) return 'a'
  if (SYSTEM_B_IDS.has(id)) return 'b'
  return 'other'
}

const CATALOG_ONLY_VERTICAL_IDS = new Set([
  'axios_hq',
  'lever',
  'paylocity',
  'cassandra',
])

/**
 * Directory search source — vertical first.
 * data → MDR; auth0 → Auth0; catalog-only (axios_hq / lever / paylocity / cassandra) → none.
 * Cassandra system id is not MDR unless vertical is data.
 */
export function matchingLabPeopleSource(
  system: string | null | undefined,
  vertical?: string | null,
): MatchingLabPeopleSource | null {
  const verticalId = matchingLabNormalizeSystemId(vertical)
  if (verticalId === 'data') return 'mdr'
  if (verticalId === 'auth0') return 'auth0'
  if (verticalId && CATALOG_ONLY_VERTICAL_IDS.has(verticalId)) return null
  const kind = matchingLabSystemKind(system)
  if (kind === 'b') return 'auth0'
  return null
}

export function matchingLabResolveSystemId(
  item: MatchingLabSystemIdentity | null | undefined,
  detail?: MatchingLabSystemIdentity | null,
): string | null {
  return (
    matchingLabNormalizeSystemId(detail?.system) ??
    matchingLabNormalizeSystemId(item ? matchingLabSystemId(item) : null)
  )
}

/** System A (MDR) vs System B (Auth0) — results-lab labels, not catalog chips. */
export function matchingLabSystemDisplay(
  item: MatchingLabSystemIdentity | null | undefined,
  detail?: MatchingLabSystemIdentity | null,
): MatchingLabSystemDisplay {
  const systemId = matchingLabResolveSystemId(item, detail)
  const kind = matchingLabSystemKind(systemId)
  const source = matchingLabPeopleSource(systemId, detail?.vertical ?? item?.vertical)
  const sourceLabel = source ? MATCHING_LAB_PEOPLE_SOURCE_LABEL[source] : null
  if (kind === 'a' || kind === 'b') {
    return {
      kind,
      label: MATCHING_LAB_SYSTEM_KIND_LABEL[kind],
      source,
      sourceLabel,
    }
  }
  const catalog = catalogSystemDisplayLabel(systemId, {
    vertical: detail?.vertical ?? item?.vertical,
    systemLabel: detail?.system_label ?? item?.system_label,
  })
  return {
    kind: 'other',
    label: catalog ?? MATCHING_LAB_SYSTEM_KIND_LABEL.other,
    source: null,
    sourceLabel: null,
  }
}

export type MatchedPersonPii = {
  name: string
  email: string | null
  phone: string | null
  dob: string | null
}

export function matchedPersonName(contact: MatchedPersonContact): string {
  const lastName = contact.last_name?.trim()
  const first = contact.first_initial?.trim()
  if (lastName && first) return `${first} ${lastName}`
  if (lastName) return lastName
  const lastInitial = contact.last_initial?.trim()
  if (first || lastInitial) return `${first || '·'}${lastInitial || '·'}`
  return '—'
}

export function matchedPersonEmail(contact: MatchedPersonContact): string | null {
  const email = contact.email?.trim()
  return email || null
}

export function matchedPersonPhone(contact: MatchedPersonContact): string | null {
  for (const row of contact.phones ?? []) {
    const number = row.number?.trim()
    if (number) return number
  }
  return null
}

/** Compact `MM/DD/YY` from ISO `YYYY-MM-DD`; otherwise the trimmed raw value. */
export function matchedPersonDob(contact: MatchedPersonContact): string | null {
  const raw = contact.dob?.trim()
  if (!raw) return null
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!match) return raw
  return `${match[2]}/${match[3]}/${match[1]!.slice(2)}`
}

export function matchedPersonPii(contact: MatchedPersonContact): MatchedPersonPii {
  return {
    name: matchedPersonName(contact),
    email: matchedPersonEmail(contact),
    phone: matchedPersonPhone(contact),
    dob: matchedPersonDob(contact),
  }
}

export function matchedPersonSearchHaystack(contact: MatchedPersonContact): string {
  const pii = matchedPersonPii(contact)
  return [
    pii.name,
    pii.email,
    pii.phone,
    pii.dob,
    contact.state,
    contact.last_name,
    contact.first_initial,
    contact.last_initial,
    contact.dwid,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

export function filterMatchedPeople(
  contacts: readonly MatchedPersonContact[],
  query: string,
): MatchedPersonContact[] {
  const needle = query.trim().toLowerCase()
  if (!needle) return []
  return contacts.filter((contact) => matchedPersonSearchHaystack(contact).includes(needle))
}

/** Directory search for additional people (MDR on data, Auth0 on auth0). */
export type SearchPeopleFn = (
  query: string,
) => MatchedPersonContact[] | Promise<MatchedPersonContact[]>

export type MatchingResultsViewProps = {
  item: NeedsAttentionItem | null
  detail: MatchingResultDetail | null
  contacts: MatchedPersonContact[]
  loading: boolean
  ownerLanguage: boolean
  statusOptions: InboxStatusOption[]
  statusId: string | null
  onStatusChange: (statusId: string) => void
  selectedDwids: string[]
  onSelectedDwidsChange: (dwids: string[]) => void
  disabled?: boolean
  pending?: boolean
  onApply: (draft?: { statusId: string; selectedDwids: string[] }) => void
  batchDefaultStatus: string | null
  onBatchDefaultStatusChange: (statusId: string) => void
  useBatchDefault: boolean
  onUseBatchDefaultChange: (useDefault: boolean) => void
  selectedCount: number
  onApplySelection: () => void
  /** Search additional people. MDR for data, Auth0 for auth0. */
  onSearchPeople?: SearchPeopleFn
  /** Matching refresh-cadence gate — disable search; never show Connected. */
  peopleSearchBlocked?: MatchingConnectorGate | null
  /** Catalog-only / not-live vertical — disable search with setup copy. */
  peopleSearchPending?: { title: string; support: string } | null
}
