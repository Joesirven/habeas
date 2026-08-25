import {
  getDropMatchingResultDetail,
  getOwnerVerticalMatchingResults,
  postDropMatchingResultPromote,
  type DropResponseStatusCode,
} from '@/lib/api'
import { catalogSystemDisplayLabel, verticalLabel } from '@/lib/legalJourneyLabels'
import { filterRequestUuids, isRequestUuid } from '@/lib/utils'

export type InboxStatusLabRow = {
  request_id: string
  bulk_process_id?: number | null
}

export type InboxItemChannel = 'email' | 'phone' | 'ndz'

const INBOX_ITEM_CHANNELS: InboxItemChannel[] = ['email', 'phone', 'ndz']

export type InboxReviewConnection = {
  system: string | null
  system_label?: string | null
  vertical?: string | null
  color_token?: string | null
  current_stage?: string | null
  match_type?: string | null
  kind?: string | null
  matched_via?: string | null
}

export type InboxReviewItemIdentity = {
  request_id: string
  vertical?: string | null
  vertical_label?: string | null
  system?: string | null
  system_label?: string | null
  color_token?: string | null
  current_stage?: string | null
  match_type?: string | null
  kind?: string | null
  /** Non-PII match method, e.g. drop_hash_email / email / phone / ndz. */
  matched_via?: string | null
  /** Optional allowlisted channels from matching detail — not emails/phones. */
  matched_channels?: InboxItemChannel[] | null
  /** Unioned chips after coalesce — email / phone / ndz only. */
  channels?: InboxItemChannel[]
  /**
   * Owner/lab-as-owner coalesce — systems on this request.
   * When set, list identity is `request_id` (never POST this as request_id).
   */
  connections?: InboxReviewConnection[]
}

const REVIEW_ITEM_KEY_SEP = '::'

export function inboxItemConnections(
  item: InboxReviewItemIdentity,
): InboxReviewConnection[] {
  if (item.connections && item.connections.length > 0) {
    return item.connections
  }
  const system = item.system?.trim() || null
  if (!system && !item.system_label?.trim()) return []
  return [
    {
      system,
      system_label: item.system_label,
      vertical: item.vertical,
      color_token: item.color_token,
      current_stage: item.current_stage,
      match_type: item.match_type,
      kind: item.kind,
      matched_via: item.matched_via,
    },
  ]
}

function connectionFromItem(item: InboxReviewItemIdentity): InboxReviewConnection {
  return {
    system: item.system?.trim() || null,
    system_label: item.system_label,
    vertical: item.vertical,
    color_token: item.color_token,
    current_stage: item.current_stage,
    match_type: item.match_type,
    kind: item.kind,
    matched_via: item.matched_via,
  }
}

function mergeConnections(
  existing: InboxReviewConnection[],
  next: InboxReviewConnection,
): InboxReviewConnection[] {
  const system = next.system?.trim() || ''
  const already = existing.some((row) => (row.system?.trim() || '') === system)
  if (already) return existing
  return [...existing, next]
}

/**
 * UI identity — never a POST id.
 * Owner coalesce (`connections` set): `request_id` only.
 * Otherwise `${uuid}::${vertical}::${system}` when both scoped fields are present;
 * `${uuid}::${vertical}` if only vertical; uuid if neither.
 */
export function inboxReviewItemKey(item: InboxReviewItemIdentity): string {
  if (item.connections && item.connections.length > 0) {
    return item.request_id
  }
  const vertical = item.vertical?.trim() ?? ''
  const system = item.system?.trim() ?? ''
  if (vertical && system) {
    return `${item.request_id}${REVIEW_ITEM_KEY_SEP}${vertical}${REVIEW_ITEM_KEY_SEP}${system}`
  }
  if (vertical) {
    return `${item.request_id}${REVIEW_ITEM_KEY_SEP}${vertical}`
  }
  return item.request_id
}

export function isInboxReviewItemKey(key: string): boolean {
  if (isRequestUuid(key)) return true
  const parts = key.split(REVIEW_ITEM_KEY_SEP)
  if (parts.length !== 2 && parts.length !== 3) return false
  const [requestId, vertical, system] = parts
  if (!isRequestUuid(requestId) || !(vertical?.trim())) return false
  if (parts.length === 3 && !(system?.trim())) return false
  return true
}

function isInboxItemChannel(value: unknown): value is InboxItemChannel {
  return value === 'email' || value === 'phone' || value === 'ndz'
}

function channelsFromMatchedVia(value: string | null | undefined): InboxItemChannel[] {
  if (typeof value !== 'string') return []
  const text = value.trim().toLowerCase()
  if (!text) return []
  return INBOX_ITEM_CHANNELS.filter(
    (channel) =>
      text === channel ||
      text.startsWith(`drop_hash_${channel}`) ||
      text.includes(channel),
  )
}

/** Channel chips for one inbox/lab row — never PII, hashes, or DWIDs. */
export function inboxItemChannels(item: InboxReviewItemIdentity): InboxItemChannel[] {
  const seen = new Set<InboxItemChannel>()
  const add = (channel: InboxItemChannel | null | undefined) => {
    if (channel && isInboxItemChannel(channel)) seen.add(channel)
  }
  if (Array.isArray(item.channels)) {
    for (const channel of item.channels) add(channel)
  }
  if (Array.isArray(item.matched_channels)) {
    for (const channel of item.matched_channels) add(channel)
  }
  for (const channel of channelsFromMatchedVia(item.matched_via)) add(channel)
  return INBOX_ITEM_CHANNELS.filter((channel) => seen.has(channel))
}

export type InboxSourceFilterFields = {
  intake_source?: string | null
  matched_via?: string | null
  matched_channels?: InboxItemChannel[] | null
  channels?: InboxItemChannel[]
}

/** Email / phone / NDZ are identifier surfaces — not inbox source or queue dimensions. */
export function isInboxIdentifierSurface(id: string): boolean {
  return id === 'email' || id === 'phone' || id === 'ndz'
}

/**
 * Source filter identity — intake only (CA DROP, portal, agent).
 * Never email/phone/ndz. Not catalog system. Never a POST key.
 */
export function inboxItemSourceFilterKey(item: InboxSourceFilterFields): string {
  const source = (item.intake_source ?? '').trim()
  return source || 'unknown'
}

/**
 * Owner inbox: one matching-review row per system so each attempt is verified
 * separately. Expands API `connections` onto distinct rows.
 */
export function expandInboxReviewBySystem<T extends InboxReviewItemIdentity>(
  items: T[],
): T[] {
  const expanded: T[] = []
  for (const item of items) {
    const connections = item.connections
    if (!connections || connections.length <= 1) {
      expanded.push(item)
      continue
    }
    for (const connection of connections) {
      expanded.push({
        ...item,
        vertical: connection.vertical ?? item.vertical,
        system: connection.system,
        system_label: connection.system_label,
        color_token: connection.color_token ?? item.color_token,
        current_stage: connection.current_stage ?? item.current_stage,
        match_type: connection.match_type ?? item.match_type,
        kind: connection.kind ?? item.kind,
        matched_via: connection.matched_via ?? item.matched_via,
        connections: undefined,
      })
    }
  }
  return expanded
}

/**
 * Inbox/lab rows.
 * Default: one row per (request_id, vertical, system) — unions email/phone/ndz chips.
 * `byRequest`: one row per request_id. Prefer `expandInboxReviewBySystem` for
 * owners so each system is its own matching review.
 */
export function coalesceInboxReviewItems<T extends InboxReviewItemIdentity>(
  items: T[],
  options?: { byRequest?: boolean },
): Array<T & { channels: InboxItemChannel[]; connections?: InboxReviewConnection[] }> {
  const firstByKey = new Map<string, T>()
  const channelsByKey = new Map<string, Set<InboxItemChannel>>()
  const connectionsByKey = new Map<string, InboxReviewConnection[]>()
  const byRequest = options?.byRequest === true

  for (const item of items) {
    const key = byRequest ? item.request_id : inboxReviewItemKey(item)
    if (!firstByKey.has(key)) firstByKey.set(key, item)
    const seen = channelsByKey.get(key) ?? new Set<InboxItemChannel>()
    for (const channel of inboxItemChannels(item)) seen.add(channel)
    channelsByKey.set(key, seen)
    if (byRequest) {
      let existing = connectionsByKey.get(key) ?? []
      const fromItem =
        item.connections && item.connections.length > 0
          ? item.connections
          : [connectionFromItem(item)]
      for (const connection of fromItem) {
        existing = mergeConnections(existing, connection)
      }
      connectionsByKey.set(key, existing)
    }
  }

  return [...firstByKey.entries()].map(([key, first]) => {
    const connections = connectionsByKey.get(key)
    return {
      ...first,
      channels: INBOX_ITEM_CHANNELS.filter((channel) => channelsByKey.get(key)?.has(channel)),
      ...(connections && connections.length > 0 ? { connections } : {}),
    }
  })
}

/** Visible vertical affordance — API `vertical_label`, then catalog fallback. */
export function inboxReviewItemVerticalLabel(
  item: InboxReviewItemIdentity,
): string | null {
  const label = item.vertical_label?.trim()
  if (label) return label
  const id = item.vertical?.trim()
  if (!id) return null
  return verticalLabel(id)
}

/** Visible system / connection name — never CA DROP. Test vertical uses A / B. */
export function inboxReviewItemSystemLabel(
  item: InboxReviewItemIdentity,
): string | null {
  return catalogSystemDisplayLabel(item.system, {
    vertical: item.vertical,
    systemLabel: item.system_label,
  })
}

/** Connections shown as system chips — omits CA DROP (source, not a system). */
export function inboxDisplayConnections(
  item: InboxReviewItemIdentity,
): InboxReviewConnection[] {
  return inboxItemConnections(item).filter((connection) =>
    Boolean(
      catalogSystemDisplayLabel(connection.system, {
        vertical: connection.vertical ?? item.vertical,
        systemLabel: connection.system_label,
      }),
    ),
  )
}

/** System filter options — remap test vertical to A/B; drop CA DROP as a system. */
export function inboxSystemFilterOptions<
  T extends { id: string; label: string; vertical?: string },
>(options: readonly T[], verticalFilter?: string | null): T[] {
  const scoped = verticalFilter?.trim() || undefined
  return options
    .filter((row) => !scoped || !row.vertical || row.vertical === scoped)
    .flatMap((row) => {
      const label = catalogSystemDisplayLabel(row.id, {
        vertical: row.vertical ?? scoped,
        systemLabel: row.label,
      })
      if (!label) return []
      return [{ ...row, label }]
    })
}

/** True when the row (or any owner connection on it) is this catalog system. */
export function inboxItemHasSystem(
  item: InboxReviewItemIdentity,
  systemId: string,
): boolean {
  const wanted = systemId.trim()
  if (!wanted) return false
  return inboxItemConnections(item).some((connection) => connection.system === wanted)
}

/** Request UUIDs for apply — from checked review items, not the whole request. */
export function requestIdsFromSelectedReviewItems(
  items: InboxReviewItemIdentity[],
  selectedKeys: Set<string>,
): string[] {
  return filterRequestUuids(
    items
      .filter((item) => selectedKeys.has(inboxReviewItemKey(item)))
      .map((item) => item.request_id),
  )
}

export type MatchingReviewTarget = {
  request_id: string
  vertical?: string | null
  system?: string | null
}

/** POST fields — UUID + vertical + system separately; never the composite UI key. */
export function matchingReviewPostFields(target: MatchingReviewTarget): {
  request_id: string
  vertical: string | null
  system: string | null
} {
  return {
    request_id: target.request_id,
    vertical: target.vertical?.trim() || null,
    system: target.system?.trim() || null,
  }
}

/** One promote/decline target per connection on the row — never composite request_id. */
export function reviewTargetsFromItem(item: InboxReviewItemIdentity): MatchingReviewTarget[] {
  if (!isRequestUuid(item.request_id)) return []
  const connections = item.connections
  if (connections && connections.length > 0) {
    return connections.map((connection) =>
      matchingReviewPostFields({
        request_id: item.request_id,
        vertical: connection.vertical ?? item.vertical,
        system: connection.system,
      }),
    )
  }
  return [matchingReviewPostFields(item)]
}

/** One promote/decline target per checked row — same request, two systems = two items. */
export function selectedReviewTargets(
  items: InboxReviewItemIdentity[],
  selectedKeys: Set<string>,
): MatchingReviewTarget[] {
  return items
    .filter((item) => selectedKeys.has(inboxReviewItemKey(item)))
    .flatMap((item) => reviewTargetsFromItem(item))
}

export type ApplyInboxStatusInput = {
  requestIds: string[]
  statusId: string
}

export type ApplyInboxStatusPayload = {
  requestIds: string[]
  statusId: string
  responseStatus: DropResponseStatusCode
}

export type ApplyInboxStatusResult =
  | { ok: true; payload: ApplyInboxStatusPayload }
  | { ok: false; reason: 'empty_request_ids' | 'missing_status' | 'invalid_status' }

const VALID_STATUS_IDS = new Set(['3', '4', '5'])

/** Stable, deduped UUIDs from the current selection set (stack keys dropped). */
export function listSelectedRequestIds(selectedIds: Set<string>): string[] {
  return filterRequestUuids([...selectedIds]).sort()
}

/** Selection toolbox visibility — shown when at least one row is checked. */
export function selectionToolbarVisible(count: number): boolean {
  return count >= 1
}

/** Checked UUIDs within a stack — never the whole stack unless every member is selected. */
export function selectedStackMemberIds(
  selectedIds: Set<string>,
  memberIds: string[],
): string[] {
  const validMembers = filterRequestUuids(memberIds)
  return validMembers.filter((id) => selectedIds.has(id)).sort()
}

/** Build apply payload from checked rows — UUIDs only; stack keys are dropped. */
export function buildApplySelectionPayload(
  selectedIds: Set<string>,
  statusId: string,
): ApplyInboxStatusResult {
  return applyInboxStatuses({
    requestIds: listSelectedRequestIds(selectedIds),
    statusId,
  })
}

export function toggleSelectedRequestId(
  selectedIds: Set<string>,
  requestId: string,
): Set<string> {
  const next = new Set(selectedIds)
  if (next.has(requestId)) next.delete(requestId)
  else next.add(requestId)
  return next
}

export function toggleSelectedRequestGroup(
  selectedIds: Set<string>,
  requestIds: string[],
): Set<string> {
  if (requestIds.length === 0) return selectedIds
  const allSelected = requestIds.every((id) => selectedIds.has(id))
  const next = new Set(selectedIds)
  if (allSelected) {
    for (const id of requestIds) next.delete(id)
  } else {
    for (const id of requestIds) next.add(id)
  }
  return next
}

export function setAllSelectedRequestIds(
  selectedIds: Set<string>,
  requestIds: string[],
  selected: boolean,
): Set<string> {
  const next = new Set(selectedIds)
  if (selected) {
    for (const id of requestIds) next.add(id)
  } else {
    for (const id of requestIds) next.delete(id)
  }
  return next
}

export function allRequestIdsSelected(
  selectedIds: Set<string>,
  requestIds: string[],
): boolean {
  return requestIds.length > 0 && requestIds.every((id) => selectedIds.has(id))
}

export function someRequestIdsSelected(
  selectedIds: Set<string>,
  requestIds: string[],
): boolean {
  return requestIds.some((id) => selectedIds.has(id))
}

export type SelectedRequestGroup = {
  batchKey: string
  batchLabel: string
  requestIds: string[]
}

/** Group selected rows by bulk process (batch stacks) or individual request. */
export function groupSelectedRequestIds(
  rows: InboxStatusLabRow[],
  selectedIds: Set<string>,
): SelectedRequestGroup[] {
  const groups = new Map<string, string[]>()

  for (const row of rows) {
    if (!selectedIds.has(row.request_id)) continue
    const batchKey =
      row.bulk_process_id != null
        ? `batch:${row.bulk_process_id}`
        : `request:${row.request_id}`
    const list = groups.get(batchKey) ?? []
    list.push(row.request_id)
    groups.set(batchKey, list)
  }

  return [...groups.entries()]
    .map(([batchKey, requestIds]) => ({
      batchKey,
      batchLabel: batchKey.startsWith('batch:')
        ? `Batch #${batchKey.slice('batch:'.length)}`
        : 'Individual',
      requestIds: [...requestIds].sort(),
    }))
    .sort((left, right) => left.batchLabel.localeCompare(right.batchLabel))
}

export function parseInboxStatusId(statusId: string): DropResponseStatusCode | null {
  if (!VALID_STATUS_IDS.has(statusId)) return null
  return Number(statusId) as DropResponseStatusCode
}

/**
 * Validate and normalize apply payload for inbox status lab mutations.
 *
 * Page wiring (Results lab apply callback):
 * ```ts
 * const result = applyInboxStatuses({ requestIds: [...selectedIds], statusId })
 * if (!result.ok) return
 * // Reuse needs-attention bulk fulfill — postDropMatchingResultPromote per id:
 * await Promise.allSettled(
 *   result.payload.requestIds.map((requestId) =>
 *     postDropMatchingResultPromote(requestId, {
 *       response_status: result.payload.responseStatus,
 *     }),
 *   ),
 * )
 * ```
 */
export function applyInboxStatuses(input: ApplyInboxStatusInput): ApplyInboxStatusResult {
  const requestIds = filterRequestUuids(input.requestIds)
  if (requestIds.length === 0) {
    return { ok: false, reason: 'empty_request_ids' }
  }

  const statusId = input.statusId.trim()
  if (!statusId) {
    return { ok: false, reason: 'missing_status' }
  }

  const responseStatus = parseInboxStatusId(statusId)
  if (responseStatus == null) {
    return { ok: false, reason: 'invalid_status' }
  }

  return {
    ok: true,
    payload: {
      requestIds,
      statusId,
      responseStatus,
    },
  }
}

function applyInboxStatusesErrorMessage(
  reason: 'empty_request_ids' | 'missing_status' | 'invalid_status',
): string {
  switch (reason) {
    case 'empty_request_ids':
      return 'Select at least one request with a valid id.'
    case 'missing_status':
    case 'invalid_status':
      return 'Pick a valid CA DROP status (3, 4, or 5).'
  }
}

/** DWIDs for promote body: explicit list for 3/4, empty for 5, omit otherwise. */
export function promoteDwidsForStatus(
  status: DropResponseStatusCode,
  dwids: string[] | undefined,
): { dwids?: string[] } {
  if (status === 5) return { dwids: [] }
  if ((status === 3 || status === 4) && dwids != null && dwids.length > 0) {
    return { dwids }
  }
  return {}
}

/** Status 3/4 must carry a selection — never POST promote without DWIDs. */
export function requirePromoteDwidsForStatus(
  status: DropResponseStatusCode,
  dwids: string[] | undefined,
): string[] {
  if (status === 5) return []
  if (status === 3 || status === 4) {
    if (dwids == null || dwids.length === 0) {
      throw new Error('status 3/4 requires at least one person id')
    }
    return dwids
  }
  return dwids ?? []
}

async function resolvePromoteDwids(
  requestId: string,
  status: DropResponseStatusCode,
  vertical?: string | null,
  system?: string | null,
): Promise<string[] | undefined> {
  if (!isRequestUuid(requestId)) return undefined
  if (status === 5) return []
  if (status !== 3 && status !== 4) return undefined
  const scopedVertical = vertical?.trim() || ''
  const scopedSystem = system?.trim() || undefined
  const detail = scopedVertical
    ? await getOwnerVerticalMatchingResults(
        requestId,
        scopedVertical,
        scopedSystem,
      )
    : await getDropMatchingResultDetail(requestId)
  return (detail.matched_contacts ?? []).map((contact) => contact.dwid)
}

export type InboxStatusLabApplyResult = {
  succeeded: number
  failed: number
  requestIds: string[]
  statusId: string
}

/** Promote matching review with CA DROP response_status — UUID inputs only. */
export async function inboxStatusLabApplyStatus(
  requestIds: string[],
  statusId: string,
  targets?: MatchingReviewTarget[],
): Promise<InboxStatusLabApplyResult> {
  const prepared = applyInboxStatuses({ requestIds, statusId })
  if (!prepared.ok) {
    throw new Error(applyInboxStatusesErrorMessage(prepared.reason))
  }

  const {
    requestIds: validRequestIds,
    statusId: normalizedStatusId,
    responseStatus,
  } = prepared.payload

  const promoteTargets: MatchingReviewTarget[] =
    targets && targets.length > 0
      ? targets.filter((target) => isRequestUuid(target.request_id))
      : validRequestIds.map((request_id) => ({ request_id }))

  const results = await Promise.allSettled(
    promoteTargets.map(async (target) => {
      const scope = matchingReviewPostFields(target)
      const resolved = await resolvePromoteDwids(
        scope.request_id,
        responseStatus,
        scope.vertical,
        scope.system,
      )
      const dwids = requirePromoteDwidsForStatus(responseStatus, resolved)
      const body = {
        response_status: responseStatus,
        ...promoteDwidsForStatus(responseStatus, dwids),
        ...(scope.vertical ? { vertical: scope.vertical } : {}),
        ...(scope.system ? { system: scope.system } : {}),
      }
      return postDropMatchingResultPromote(scope.request_id, body)
    }),
  )
  const failed = results.filter((result) => result.status === 'rejected').length
  return {
    succeeded: results.length - failed,
    failed,
    requestIds: validRequestIds,
    statusId: normalizedStatusId,
  }
}

export type MatchingReviewDecisionResult = {
  review_status?: string | null
  disposition?: { recorded?: boolean } | null
}

export type MatchingReviewToastCopy = {
  variant: 'success' | 'warning'
  title: string
  description?: string
}

/** Inbox / overlay copy — never claim fulfilled or matching-complete while pending. */
export function matchingReviewPromoteToast(
  result: MatchingReviewDecisionResult,
): MatchingReviewToastCopy {
  const pending = result.review_status === 'pending'
  if (result.disposition?.recorded === false) {
    return {
      variant: 'warning',
      title: pending
        ? 'Matching confirmed — disposition incomplete'
        : 'Matching approved — disposition incomplete',
      description:
        'No person id recorded for status 3/4. Select matched people and set disposition again before fulfillment kickoff.',
    }
  }
  if (pending) {
    return {
      variant: 'success',
      title: 'System confirmed',
      description: 'Matching review stays open until remaining systems are decided.',
    }
  }
  return {
    variant: 'success',
    title: 'Matching review approved',
  }
}

export function matchingReviewBulkPromoteToast(
  results: MatchingReviewDecisionResult[],
): MatchingReviewToastCopy {
  const pending = results.filter((row) => row.review_status === 'pending').length
  const approved = results.filter((row) => row.review_status === 'approved').length
  const total = results.length
  if (total === 0) {
    return { variant: 'success', title: 'Systems confirmed', description: '0 confirmed' }
  }
  if (pending === total) {
    return {
      variant: 'success',
      title: 'Systems confirmed',
      description: `${total} confirmed — matching review still open`,
    }
  }
  if (pending > 0) {
    return {
      variant: 'success',
      title: 'Matching confirms recorded',
      description: `${approved} matching review closed, ${pending} still open`,
    }
  }
  return {
    variant: 'success',
    title: 'Matching review approved',
    description: `${total} approved`,
  }
}
