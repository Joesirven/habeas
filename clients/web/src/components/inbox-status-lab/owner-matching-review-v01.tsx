/**
 * Owner matching review · v01
 * Philosophy: Systems operator — dense, scannable, table-first.
 * Email / phone / NDZ are surfaces of one matching attempt — not separate matches.
 */
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import {
  formatMatchedContactLabel,
  matchedChannelsFromDetail,
  matchingDetailIsNotLive,
  safeMatchedContacts,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { useMe } from '@/lib/auth'
import {
  getRequest,
  listConnections,
  listOwnerConnectors,
  type ConnectionRecord,
  type ConnectorReminder,
  type MatchedPersonContact,
  type MatchingAttemptRow,
  type NeedsAttentionItem,
  type OwnerConnectorSystem,
} from '@/lib/api'
import {
  isDataCatalogVertical,
  matchingGateFromAttempts,
  matchingGateFromConnection,
  matchingGateFromReminder,
  ownerConnectorsSearch,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { inboxIntakeSourceLabel, matchTypeLabel } from '@/lib/inbox-batch-status'
import {
  inboxDisplayConnections,
  inboxItemChannels,
  inboxReviewItemSystemLabel,
  type InboxReviewConnection,
} from '@/lib/inbox-status-lab'
import { catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { cn, isRequestUuid } from '@/lib/utils'

import {
  ResultApplyBar,
  ResultContactPii,
  ResultPeopleSearch,
  ResultSystemLabel,
  applyNeedsPeople,
  resultViewEmpty,
  statusSelectClass,
  toggleDwid,
} from '../matching-results-lab/ResultViewChrome'
import {
  matchingLabSystemId,
  type MatchingResultsViewProps,
} from '../matching-results-lab/matching-results-lab-types'

export const OWNER_MATCHING_REVIEW_V01_PHILOSOPHY =
  'Systems operator — dense, scannable, table-first.'

/** Same floor as Inbox matching.review SLA — display only, not a second product rule. */
const MATCHING_REVIEW_SLA_HOURS = 48
const DUE_SOON_HOURS = 12

const PEOPLE_TABLE_COLS = 9

export type OwnerMatchingReviewV01Props = MatchingResultsViewProps & {
  /** Catalog system id currently loaded in `detail` / `contacts`. */
  activeSystem?: string | null
  onSystemChange?: (system: string) => void
  /** Lab page alias — same as `onSystemChange`. */
  onSelectSystem?: (system: string) => void
}

type BlockedMatchingKind = 'needs_connection' | 'needs_refresh'
type OptInChoice = 'in' | 'out'
type PersonDisposition = { delete: boolean; optIn: OptInChoice }
type RequestDispositionKind = 'delete' | 'opt_out' | 'other'

function shortRequestId(requestId: string | null | undefined): string {
  const id = requestId?.trim() ?? ''
  if (!id) return '—'
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

function deriveDueAt(item: NeedsAttentionItem): Date | null {
  const anchor = item.requested_at ?? item.received_at
  if (!anchor) return null
  const start = new Date(anchor)
  if (Number.isNaN(start.getTime())) return null
  return new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
}

function formatDueCell(item: NeedsAttentionItem): {
  label: string
  tone: 'fail' | 'wait' | 'default'
} {
  const due = deriveDueAt(item)
  if (!due) return { label: 'No due', tone: 'default' }
  const when = due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  const msLeft = due.getTime() - Date.now()
  if (msLeft < 0) return { label: `Overdue · ${when}`, tone: 'fail' }
  if (msLeft <= DUE_SOON_HOURS * 60 * 60 * 1000) {
    return { label: `Soon · ${when}`, tone: 'wait' }
  }
  return { label: `Due ${when}`, tone: 'default' }
}

function scanMatchLabel(
  matchType: string | null | undefined,
  ownerLanguage: boolean,
): string {
  if (matchType === 'single_match') return '1:1'
  if (matchType === 'multi_match') return 'Multi'
  if (matchType === 'not_found') return ownerLanguage ? 'None' : 'None'
  return matchTypeLabel(matchType, ownerLanguage)
}

function looksLikeCassandra(value: string | null | undefined): boolean {
  const text = (value ?? '').trim().toLowerCase()
  return text === 'cassandra'
}

/** Visible system name — never the infra id `cassandra`. Test vertical uses System A / B. */
function connectionSystemLabel(
  item: NeedsAttentionItem,
  connection: InboxReviewConnection,
): string {
  const labeled =
    catalogSystemDisplayLabel(connection.system, {
      vertical: connection.vertical ?? item.vertical,
      systemLabel: connection.system_label,
    }) ||
    inboxReviewItemSystemLabel({
      request_id: item.request_id,
      system: connection.system,
      system_label: connection.system_label,
      vertical: connection.vertical ?? item.vertical,
    }) ||
    connection.system_label?.trim() ||
    ''
  if (labeled && !looksLikeCassandra(labeled)) return labeled
  if (looksLikeCassandra(connection.system)) return 'Unassigned'
  return connection.system?.trim() && !looksLikeCassandra(connection.system)
    ? connection.system
    : 'Unassigned'
}

function connectionKey(connection: InboxReviewConnection, index: number): string {
  return connection.system?.trim() || `system-${index}`
}

const MATCH_SURFACES = ['email', 'phone', 'ndz'] as const
type MatchSurface = (typeof MATCH_SURFACES)[number]

const SURFACE_LABEL: Record<MatchSurface, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

function isMatchSurface(value: string): value is MatchSurface {
  return value === 'email' || value === 'phone' || value === 'ndz'
}

function unionSurfaces(...lists: Array<readonly string[] | undefined>): MatchSurface[] {
  const seen = new Set<MatchSurface>()
  for (const list of lists) {
    for (const value of list ?? []) {
      if (isMatchSurface(value)) seen.add(value)
    }
  }
  return MATCH_SURFACES.filter((surface) => seen.has(surface))
}

/** One matching attempt’s identifier surfaces — never a Via chip or per-channel row. */
function attemptSurfaces(
  item: NeedsAttentionItem,
  detail: OwnerMatchingReviewV01Props['detail'],
): MatchSurface[] {
  return unionSurfaces(
    inboxItemChannels({
      request_id: item.request_id,
      matched_via: detail?.matched_via ?? item.matched_via,
      matched_channels: detail?.matched_channels,
      channels: item.channels,
    }),
    matchedChannelsFromDetail(detail),
  )
}

function personSurfaces(
  contact: MatchedPersonContact,
  attemptHits: readonly MatchSurface[],
): Set<MatchSurface> {
  const hits = new Set<MatchSurface>(attemptHits)
  if (typeof contact.email === 'string' && contact.email.trim()) hits.add('email')
  if (Array.isArray(contact.phones) && contact.phones.length > 0) hits.add('phone')
  return hits
}

function SurfaceHeads() {
  return (
    <>
      {MATCH_SURFACES.map((surface) => (
        <TableHead key={surface} className="w-10 text-center">
          {SURFACE_LABEL[surface]}
        </TableHead>
      ))}
    </>
  )
}

function SurfaceMarks({ hits }: { hits: Iterable<MatchSurface> }) {
  const set = hits instanceof Set ? hits : new Set(hits)
  return (
    <>
      {MATCH_SURFACES.map((surface) => {
        const hit = set.has(surface)
        const label = SURFACE_LABEL[surface]
        return (
          <TableCell key={surface} className="w-10 text-center">
            <span
              className={cn(
                'inline-block text-[0.65rem] tabular-nums',
                hit ? 'text-habeas-navy' : 'text-mute',
              )}
              aria-label={hit ? `${label} surface` : `${label} none`}
              title={hit ? label : `${label} —`}
            >
              {hit ? '●' : '—'}
            </span>
          </TableCell>
        )
      })}
    </>
  )
}

function requestDispositionKind(requestType: string | null | undefined): RequestDispositionKind {
  const normalized = (requestType ?? '').trim().toLowerCase().replace(/[\s-]+/g, '_')
  if (normalized === 'delete' || normalized === 'deletion' || normalized === 'erasure') {
    return 'delete'
  }
  if (normalized === 'opt_out' || normalized === 'optout' || normalized === 'unsubscribe') {
    return 'opt_out'
  }
  return 'other'
}

function defaultPersonDisposition(
  kind: RequestDispositionKind,
  recommended: number | null | undefined,
): PersonDisposition {
  if (kind === 'delete' || recommended === 3) return { delete: true, optIn: 'out' }
  if (kind === 'opt_out' || recommended === 4) return { delete: false, optIn: 'out' }
  return { delete: false, optIn: 'in' }
}

function ownerBlockedMatchingLabel(kind: BlockedMatchingKind): string {
  return kind === 'needs_refresh' ? 'Needs refresh' : 'Needs connection'
}

function blockedKindFromGate(gate: MatchingConnectorGate): BlockedMatchingKind {
  const status = gate.displayStatus.trim().toLowerCase()
  const code = (gate.gateCode ?? '').trim().toLowerCase()
  if (code === 'wizard_incomplete' || status === 'needs_setup') return 'needs_connection'
  if (
    status === 'needs_refresh' ||
    status === 'action_required' ||
    code === 'upload_stale' ||
    code === 'upload_approaching' ||
    code === 'rotation_overdue' ||
    code === 'rotation_approaching'
  ) {
    return 'needs_refresh'
  }
  return 'needs_connection'
}

function sameSystem(left: string | null | undefined, right: string | null | undefined): boolean {
  const a = left?.trim() ?? ''
  const b = right?.trim() ?? ''
  return Boolean(a) && a === b
}

function gateFromOwnerConnector(row: OwnerConnectorSystem): MatchingConnectorGate | null {
  if (row.gate_allowed === false) {
    return {
      blocked: true,
      displayStatus: row.display_status || 'action_required',
      gateCode: row.gate_code,
      system: row.system,
      source: 'connection',
    }
  }
  const status = row.display_status?.trim().toLowerCase()
  if (status === 'needs_refresh' || status === 'action_required' || status === 'needs_setup') {
    return {
      blocked: true,
      displayStatus: row.display_status,
      gateCode: row.gate_code,
      system: row.system,
      source: 'connection',
    }
  }
  if (!row.connection_id && (row.status == null || row.status === 'pending' || row.status === 'invited')) {
    return {
      blocked: true,
      displayStatus: 'needs_setup',
      gateCode: 'wizard_incomplete',
      system: row.system,
      source: 'connection',
    }
  }
  return null
}

function blockedGateForSystem(options: {
  systemId: string | null
  selected: boolean
  attempts?: MatchingAttemptRow[] | null
  reminders?: ConnectorReminder[] | null
  connections?: ConnectionRecord[] | null
  ownerConnectors?: OwnerConnectorSystem[] | null
}): MatchingConnectorGate | null {
  const systemId = options.systemId?.trim() || null
  if (options.selected) {
    const fromAttempts = matchingGateFromAttempts(options.attempts)
    if (fromAttempts && (!fromAttempts.system || !systemId || sameSystem(fromAttempts.system, systemId))) {
      return fromAttempts
    }
  }
  if (systemId) {
    const ownerRow = options.ownerConnectors?.find((row) => sameSystem(row.system, systemId))
    const fromOwner = ownerRow ? gateFromOwnerConnector(ownerRow) : null
    if (fromOwner) return fromOwner
    const connection = options.connections?.find((row) => sameSystem(row.system, systemId))
    const fromConnection = connection ? matchingGateFromConnection(connection) : null
    if (fromConnection) return fromConnection
    const reminder = options.reminders?.find((row) => sameSystem(row.system, systemId))
    const fromReminder = reminder ? matchingGateFromReminder(reminder) : null
    if (fromReminder) return fromReminder
  }
  return null
}

function mergePeopleByDwid(
  primary: readonly MatchedPersonContact[],
  extra: readonly MatchedPersonContact[],
): MatchedPersonContact[] {
  const byDwid = new Map<string, MatchedPersonContact>()
  for (const contact of [...primary, ...extra]) {
    const dwid = contact.dwid?.trim()
    if (dwid && !byDwid.has(dwid)) byDwid.set(dwid, contact)
  }
  return [...byDwid.values()]
}

function dispositionSelectClass(emphasized: boolean): string {
  return cn(
    statusSelectClass(true),
    emphasized && 'border-habeas-navy font-medium text-habeas-navy',
  )
}

/** Systems operator: request strip + systems table + people/DWID table. */
export function OwnerMatchingReviewV01({
  item,
  detail,
  contacts,
  loading,
  ownerLanguage,
  statusId,
  onStatusChange,
  selectedDwids,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
  onSearchPeople,
  activeSystem,
  onSystemChange,
  onSelectSystem,
}: OwnerMatchingReviewV01Props) {
  const { me } = useMe()
  const selectSystem = onSystemChange ?? onSelectSystem
  const currentSystemId =
    activeSystem?.trim() ||
    (item ? matchingLabSystemId(item) : null) ||
    detail?.system?.trim() ||
    null
  const verticalId = (detail?.vertical ?? item?.vertical)?.trim() || null
  const requestId = item?.request_id?.trim() ?? ''

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    enabled: isRequestUuid(requestId),
    staleTime: 60_000,
    retry: false,
  })
  const ownerConnectorsQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    queryFn: () => listOwnerConnectors(verticalId!),
    enabled: Boolean(verticalId),
    staleTime: 30_000,
    retry: false,
  })
  const connectionsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'connections', 'matching-gate'],
    queryFn: async () => (await listConnections()).connections,
    staleTime: 60_000,
    retry: false,
  })

  const [addedPeople, setAddedPeople] = useState<MatchedPersonContact[]>([])
  const [hiddenDwids, setHiddenDwids] = useState<string[]>([])
  const [dispositions, setDispositions] = useState<Record<string, PersonDisposition>>({})

  const rosterResetKey = `${requestId}::${currentSystemId ?? ''}::${contacts.map((row) => row.dwid).join(',')}`
  useEffect(() => {
    setAddedPeople([])
    setHiddenDwids([])
    setDispositions({})
  }, [rosterResetKey])

  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty
  if (!item) return null

  const people = mergePeopleByDwid(safeMatchedContacts(contacts), addedPeople)
  const systems = inboxDisplayConnections({
    request_id: item.request_id,
    system: matchingLabSystemId(item),
    system_label: item.system_label,
    vertical: item.vertical,
    color_token: item.color_token,
    current_stage: item.current_stage,
    match_type: item.match_type,
    connections: item.connections,
  })
  const systemRows =
    systems.length > 0
      ? systems
      : [
          {
            system: currentSystemId,
            system_label: detail?.system_label ?? item.system_label,
            vertical: detail?.vertical ?? item.vertical,
            match_type: detail?.match_type ?? item.match_type,
          } satisfies InboxReviewConnection,
        ]

  const matchType = detail?.match_type ?? item.match_type
  const notLive = matchingDetailIsNotLive(detail)
  const notFound = statusId === '5' || matchType === 'not_found'
  const locked = Boolean(disabled || pending)
  const due = formatDueCell(item)
  const currentSystemName =
    catalogSystemDisplayLabel(currentSystemId, {
      vertical: detail?.vertical ?? item.vertical,
      systemLabel: detail?.system_label ?? item.system_label,
    }) ||
    (looksLikeCassandra(detail?.system_label) ? null : detail?.system_label) ||
    (looksLikeCassandra(item.system_label) ? null : item.system_label) ||
    'This system'
  const selectedAttemptSurfaces = attemptSurfaces(item, detail)
  const requestKind = requestDispositionKind(requestQuery.data?.request_type)
  const emphasizeDelete = requestKind === 'delete'
  const emphasizeOpt = requestKind === 'opt_out'
  const recommendedStatus = detail?.recommended_response_status ?? item.recommended_response_status
  const reminders = me?.connector_reminders ?? []
  const ownerConnectors = ownerConnectorsQuery.data?.connectors ?? []
  const connections = connectionsQuery.data ?? []
  const showConnectorsButton = !isDataCatalogVertical(verticalId)
  const hidden = new Set(hiddenDwids)
  const visiblePeople = people.filter((person) => !person.dwid || !hidden.has(person.dwid))

  function personDisposition(dwid: string): PersonDisposition {
    return dispositions[dwid] ?? defaultPersonDisposition(requestKind, recommendedStatus)
  }

  function setPersonDisposition(dwid: string, patch: Partial<PersonDisposition>) {
    setDispositions((current) => ({
      ...current,
      [dwid]: { ...personDisposition(dwid), ...patch },
    }))
  }

  function removePerson(dwid: string) {
    if (!dwid) return
    setHiddenDwids((current) => (current.includes(dwid) ? current : [...current, dwid]))
    if (selectedDwids.includes(dwid)) {
      onSelectedDwidsChange(selectedDwids.filter((id) => id !== dwid))
    }
  }

  function addPerson(contact: MatchedPersonContact) {
    const dwid = contact.dwid?.trim()
    if (!dwid) return
    if (!people.some((row) => row.dwid === dwid)) {
      setAddedPeople((current) =>
        current.some((row) => row.dwid === dwid) ? current : [...current, contact],
      )
    }
    setHiddenDwids((current) => current.filter((id) => id !== dwid))
    if (!selectedDwids.includes(dwid)) {
      onSelectedDwidsChange([...selectedDwids, dwid])
    }
  }

  function deriveApplyDraft(): { statusId: string; selectedDwids: string[] } {
    const included = visiblePeople.filter(
      (person) => person.dwid && selectedDwids.includes(person.dwid),
    )
    if (included.length === 0) return { statusId: '5', selectedDwids: [] }
    const deleteIds = included
      .filter((person) => personDisposition(person.dwid).delete)
      .map((person) => person.dwid)
    const optOutIds = included
      .filter((person) => {
        const row = personDisposition(person.dwid)
        return !row.delete && row.optIn === 'out'
      })
      .map((person) => person.dwid)
    if (emphasizeDelete && deleteIds.length > 0) {
      return { statusId: '3', selectedDwids: deleteIds }
    }
    if (emphasizeOpt && optOutIds.length > 0) {
      return { statusId: '4', selectedDwids: optOutIds }
    }
    if (deleteIds.length > 0 && optOutIds.length === 0) {
      return { statusId: '3', selectedDwids: deleteIds }
    }
    if (optOutIds.length > 0 && deleteIds.length === 0) {
      return { statusId: '4', selectedDwids: optOutIds }
    }
    if (deleteIds.length > 0) return { statusId: '3', selectedDwids: deleteIds }
    if (optOutIds.length > 0) return { statusId: '4', selectedDwids: optOutIds }
    return { statusId: statusId ?? '5', selectedDwids: included.map((person) => person.dwid) }
  }

  function handleApply() {
    const draft = deriveApplyDraft()
    if (draft.statusId !== statusId) onStatusChange(draft.statusId)
    onSelectedDwidsChange(draft.selectedDwids)
    onApply(draft)
  }

  const applyDraft = deriveApplyDraft()
  const currentBlocked = blockedGateForSystem({
    systemId: currentSystemId,
    selected: true,
    attempts: detail?.attempts,
    reminders,
    connections,
    ownerConnectors,
  })
  const currentBlockedKind = currentBlocked ? blockedKindFromGate(currentBlocked) : null

  return (
    <div className="space-y-2">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Source</TableHead>
            <TableHead>Due</TableHead>
            <TableHead>Request</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow className="hover:bg-transparent">
            <TableCell>
              <Badge variant="default" className="normal-case tracking-normal">
                {inboxIntakeSourceLabel(item.intake_source)}
              </Badge>
            </TableCell>
            <TableCell>
              <Badge
                variant={due.tone === 'fail' ? 'fail' : due.tone === 'wait' ? 'wait' : 'default'}
                className="normal-case tracking-normal tabular-nums"
              >
                {due.label}
              </Badge>
            </TableCell>
            <TableCell>
              <span className="font-mono text-xs tabular-nums text-ink" title={item.request_id}>
                {shortRequestId(item.request_id)}
              </span>
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>System</TableHead>
            <TableHead>Match</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">People</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {systemRows.map((connection, index) => {
            const systemId = connection.system?.trim() || null
            const selected = Boolean(systemId && currentSystemId && systemId === currentSystemId)
            const rowMatch = selected
              ? matchType
              : (connection.match_type ?? item.match_type)
            const peopleCount = selected
              ? (detail?.match_count ?? people.length)
              : null
            const label = connectionSystemLabel(item, connection)
            const rowGate = blockedGateForSystem({
              systemId,
              selected,
              attempts: selected ? detail?.attempts : null,
              reminders,
              connections,
              ownerConnectors,
            })
            const blockedKind = rowGate ? blockedKindFromGate(rowGate) : null
            const rowClass = cn(
              selected && 'bg-habeas-navy/[0.06]',
              selectSystem && systemId && 'cursor-pointer',
            )
            const cells = (
              <>
                <TableCell className={cn('text-xs', selected ? 'font-medium text-habeas-navy' : 'text-ink')}>
                  {label}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={rowMatch === 'multi_match' ? 'wait' : 'default'}
                    className="normal-case tracking-normal"
                  >
                    {notLive && selected ? 'Not live' : scanMatchLabel(rowMatch, ownerLanguage)}
                  </Badge>
                </TableCell>
                <TableCell
                  onClick={(event) => {
                    if (blockedKind) event.stopPropagation()
                  }}
                >
                  {blockedKind ? (
                    showConnectorsButton ? (
                      <Button
                        asChild
                        size="sm"
                        variant="outline"
                        className="h-6 px-1.5 text-[0.65rem]"
                      >
                        <Link
                          to="/owner/connectors"
                          search={ownerConnectorsSearch(connection.vertical ?? verticalId)}
                        >
                          {ownerBlockedMatchingLabel(blockedKind)}
                        </Link>
                      </Button>
                    ) : (
                      <Badge variant="fail" className="normal-case tracking-normal">
                        {ownerBlockedMatchingLabel(blockedKind)}
                      </Badge>
                    )
                  ) : (
                    <span className="text-xs text-mute">—</span>
                  )}
                </TableCell>
                <TableCell className="text-right tabular-nums text-xs text-ink-soft">
                  {peopleCount == null ? '—' : peopleCount}
                </TableCell>
              </>
            )
            if (selectSystem && systemId) {
              return (
                <TableRow
                  key={connectionKey(connection, index)}
                  className={rowClass}
                  aria-selected={selected}
                  onClick={() => selectSystem(systemId)}
                >
                  {cells}
                </TableRow>
              )
            }
            return (
              <TableRow
                key={connectionKey(connection, index)}
                className={rowClass}
                aria-selected={selected}
              >
                {cells}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>

      <div className="flex flex-wrap items-center gap-1.5">
        <ResultSystemLabel item={item} detail={detail} />
      </div>

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-14">In</TableHead>
            <TableHead>Person</TableHead>
            <TableHead>DWID</TableHead>
            <TableHead>State</TableHead>
            <SurfaceHeads />
            <TableHead className={cn(emphasizeDelete && 'text-habeas-navy')}>Delete</TableHead>
            <TableHead className={cn(emphasizeOpt && 'text-habeas-navy')}>Opt-in</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {notLive ? (
            <TableRow>
              <TableCell colSpan={PEOPLE_TABLE_COLS} className="text-xs text-mute">
                {detail?.result_kind === 'sheet_stub'
                  ? `${currentSystemName} is catalog-only — matching is not live.`
                  : `${currentSystemName} matching is not live.`}
              </TableCell>
            </TableRow>
          ) : visiblePeople.length === 0 ? (
            <TableRow>
              <TableCell colSpan={PEOPLE_TABLE_COLS} className="text-xs text-mute">
                {notFound
                  ? `No matched persons in ${currentSystemName}.`
                  : `No person rows for ${currentSystemName}.`}
              </TableCell>
            </TableRow>
          ) : (
            visiblePeople.map((contact, index) => {
              const included = Boolean(contact.dwid) && selectedDwids.includes(contact.dwid)
              const row = contact.dwid
                ? personDisposition(contact.dwid)
                : defaultPersonDisposition(requestKind, recommendedStatus)
              return (
                <TableRow key={contact.dwid || `person-${index}`}>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <input
                        type="checkbox"
                        className="size-3.5 rounded border-line text-habeas-navy accent-habeas-navy"
                        checked={included}
                        disabled={locked || !contact.dwid}
                        aria-label={`Include ${formatMatchedContactLabel(contact)}`}
                        onChange={() => {
                          if (!contact.dwid) return
                          onSelectedDwidsChange(toggleDwid(selectedDwids, contact.dwid))
                        }}
                      />
                      <button
                        type="button"
                        className="text-[0.65rem] text-mute hover:text-ink disabled:opacity-50"
                        disabled={locked || !contact.dwid}
                        aria-label={`Remove ${formatMatchedContactLabel(contact)}`}
                        onClick={() => contact.dwid && removePerson(contact.dwid)}
                      >
                        ×
                      </button>
                    </div>
                  </TableCell>
                  <TableCell className="max-w-[14rem] text-xs text-ink">
                    <ResultContactPii contact={contact} compact />
                  </TableCell>
                  <TableCell className="font-mono text-[0.65rem] tabular-nums text-mute">
                    {contact.dwid || '—'}
                  </TableCell>
                  <TableCell className="text-xs text-ink-soft">{contact.state || '—'}</TableCell>
                  <SurfaceMarks hits={personSurfaces(contact, selectedAttemptSurfaces)} />
                  <TableCell>
                    <select
                      className={dispositionSelectClass(emphasizeDelete)}
                      value={row.delete ? 'yes' : 'no'}
                      disabled={locked || !contact.dwid || !included}
                      aria-label={`Delete ${formatMatchedContactLabel(contact)}`}
                      onChange={(event) => {
                        if (!contact.dwid) return
                        setPersonDisposition(contact.dwid, { delete: event.target.value === 'yes' })
                      }}
                    >
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </TableCell>
                  <TableCell>
                    <select
                      className={dispositionSelectClass(emphasizeOpt)}
                      value={row.optIn}
                      disabled={locked || !contact.dwid || !included}
                      aria-label={`Opt-in ${formatMatchedContactLabel(contact)}`}
                      onChange={(event) => {
                        if (!contact.dwid) return
                        setPersonDisposition(contact.dwid, {
                          optIn: event.target.value === 'out' ? 'out' : 'in',
                        })
                      }}
                    >
                      <option value="in">Opt-in</option>
                      <option value="out">Opt-out</option>
                    </select>
                  </TableCell>
                </TableRow>
              )
            })
          )}
          <TableRow className="hover:bg-transparent">
            <TableCell colSpan={PEOPLE_TABLE_COLS}>
              <ResultPeopleSearch
                onSearchPeople={onSearchPeople}
                localContacts={people}
                excludeDwids={visiblePeople.map((person) => person.dwid).filter(Boolean)}
                onAddPerson={addPerson}
                disabled={locked || notLive}
                item={item}
                detail={detail}
              />
            </TableCell>
          </TableRow>
        </TableBody>
      </Table>

      <div className="flex flex-wrap items-end gap-2 border-t border-line pt-2">
        {currentBlockedKind ? (
          showConnectorsButton ? (
            <Button asChild size="sm" variant="outline">
              <Link to="/owner/connectors" search={ownerConnectorsSearch(verticalId)}>
                {ownerBlockedMatchingLabel(currentBlockedKind)}
              </Link>
            </Button>
          ) : (
            <Badge variant="fail" className="normal-case tracking-normal">
              {ownerBlockedMatchingLabel(currentBlockedKind)}
            </Badge>
          )
        ) : (
          <>
            <p className="min-w-[10rem] text-[0.65rem] text-mute">
              {applyDraft.statusId === '3'
                ? `Delete · ${applyDraft.selectedDwids.length}`
                : applyDraft.statusId === '4'
                  ? `Opt-out · ${applyDraft.selectedDwids.length}`
                  : 'Not found'}
            </p>
            <ResultApplyBar
              pending={pending}
              disabled={
                disabled ||
                applyDraft.statusId == null ||
                applyNeedsPeople(applyDraft.statusId, applyDraft.selectedDwids)
              }
              onApply={handleApply}
            />
          </>
        )}
      </div>
    </div>
  )
}
