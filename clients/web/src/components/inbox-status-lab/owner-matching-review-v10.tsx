import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import {
  formatMatchedContactLabel,
  formatMatchedContactsSummary,
  matchedChannelsFromDetail,
  matchingDetailIsNotLive,
  MatchedContactsUnavailableCallout,
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
import { isVerticalOperatorRole, useMe } from '@/lib/auth'
import {
  fetchOwnerVerticalMatchingDetailOptional,
  getDropMatchingResultDetail,
  listConnections,
  listOwnerConnectors,
  suggestedDropResponseStatus,
  type ConnectorReminder,
  type ConnectionRecord,
  type MatchedPersonContact,
  type MatchingAttemptRow,
  type NeedsAttentionItem,
  type OwnerConnectorSystem,
} from '@/lib/api'
import {
  matchingConnectorGateChip,
  matchingGateFromAttempts,
  matchingGateFromConnection,
  matchingGateFromReminder,
  ownerConnectorsSearch,
  isDataCatalogVertical,
  isMatchingGateBlockedDisplayStatus,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { inboxIntakeSourceLabel, inboxItemSystemId, matchTypeLabel } from '@/lib/inbox-batch-status'
import {
  inboxDisplayConnections,
  inboxItemChannels,
  inboxReviewItemSystemLabel,
  inboxReviewItemVerticalLabel,
} from '@/lib/inbox-status-lab'
import { matchingSystemColorClass } from '@/lib/legalJourneyLabels'
import { cn, isRequestUuid } from '@/lib/utils'

import {
  applyNeedsPeople,
  ResultApplyBar,
  resultViewEmpty,
  statusSelectClass,
} from '../matching-results-lab/ResultViewChrome'
import {
  matchingLabRequestId,
  type MatchingResultsViewProps,
} from '../matching-results-lab/matching-results-lab-types'

export const OWNER_MATCHING_REVIEW_V10_PHILOSOPHY =
  'Hybrid two-tier: matching-only, per-system sections, thin request facts. Default lab view.'

export type OwnerMatchingReviewV10Props = MatchingResultsViewProps & {
  activeSystem?: string | null
  onSelectSystem?: (system: string) => void
}

/** Identifier surfaces on one matching attempt — never Via chips or per-channel decisions. */
const SURFACE_ORDER = ['email', 'phone', 'ndz'] as const
type MatchSurface = (typeof SURFACE_ORDER)[number]

const SURFACE_LABEL: Record<MatchSurface, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

/** Person-level DROP dispositions — system two-tier stays the apply decision. */
const PERSON_ACTIONS = [
  { id: '3', label: 'Delete' },
  { id: '4', label: 'Opt-in' },
] as const
type PersonActionId = (typeof PERSON_ACTIONS)[number]['id']

function isMatchSurface(value: string): value is MatchSurface {
  return value === 'email' || value === 'phone' || value === 'ndz'
}

function isPersonActionId(value: string | null | undefined): value is PersonActionId {
  return value === '3' || value === '4'
}

function systemIdIsCassandra(system: string | null | undefined): boolean {
  return (system ?? '').trim().toLowerCase() === 'cassandra'
}

function attemptSystemId(attempt: MatchingAttemptRow): string | null {
  const audit = attempt.audit_payload
  if (!audit || typeof audit !== 'object') return null
  const blocking =
    typeof audit.blocking_system === 'string' ? audit.blocking_system.trim() : ''
  const system = typeof audit.system === 'string' ? audit.system.trim() : ''
  return blocking || system || null
}

function gateFromOwnerConnector(
  connector: OwnerConnectorSystem | undefined,
): MatchingConnectorGate | null {
  if (!connector || connector.gate_allowed) return null
  const displayStatus = isMatchingGateBlockedDisplayStatus(connector.display_status)
    ? connector.display_status
    : 'action_required'
  return {
    blocked: true,
    displayStatus,
    gateCode: connector.gate_code,
    system: connector.system,
    source: 'connection',
  }
}

function resolveSystemConnectorGate(options: {
  systemId: string
  applyUnscopedAttempts: boolean
  attempts?: MatchingAttemptRow[] | null
  ownerConnectors?: OwnerConnectorSystem[] | null
  connections?: ConnectionRecord[] | null
  reminders?: ConnectorReminder[] | null
}): MatchingConnectorGate | null {
  const systemId = options.systemId.trim()
  if (!systemId || systemIdIsCassandra(systemId) || isDataCatalogVertical(systemId)) {
    return null
  }

  const scoped: MatchingAttemptRow[] = []
  const unscoped: MatchingAttemptRow[] = []
  for (const attempt of options.attempts ?? []) {
    const mentioned = attemptSystemId(attempt)
    if (!mentioned) unscoped.push(attempt)
    else if (mentioned === systemId) scoped.push(attempt)
  }
  const fromScoped = matchingGateFromAttempts(scoped)
  if (fromScoped && (!fromScoped.system || fromScoped.system === systemId)) {
    return { ...fromScoped, system: systemId }
  }
  if (options.applyUnscopedAttempts) {
    const fromUnscoped = matchingGateFromAttempts(unscoped)
    if (fromUnscoped && (!fromUnscoped.system || fromUnscoped.system === systemId)) {
      return { ...fromUnscoped, system: systemId }
    }
  }

  const ownerGate = gateFromOwnerConnector(
    options.ownerConnectors?.find((row) => row.system === systemId),
  )
  if (ownerGate) return ownerGate

  const connection = options.connections?.find((row) => row.system === systemId)
  const fromConnection = connection ? matchingGateFromConnection(connection) : null
  if (fromConnection) return fromConnection

  const reminder = (options.reminders ?? []).find((row) => row.system === systemId)
  return reminder ? matchingGateFromReminder(reminder) : null
}

function useSystemConnectorGates(options: {
  verticalId: string | null
  activeSystemId: string | null
}) {
  const { me, role } = useMe()
  const ownerPersona = isVerticalOperatorRole(role)
  const verticalId = options.verticalId?.trim() || null

  const ownerQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'verticals', verticalId, 'connectors', 'v10-gate'],
    queryFn: () => listOwnerConnectors(verticalId!),
    enabled: Boolean(verticalId) && ownerPersona,
    staleTime: 60_000,
    retry: false,
  })

  const connectionsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'connections', 'matching-gate', 'v10'],
    queryFn: async () => (await listConnections()).connections,
    enabled: !ownerPersona,
    staleTime: 60_000,
    retry: false,
  })

  return {
    gateFor(systemId: string | null, attempts?: MatchingAttemptRow[] | null) {
      const id = systemId?.trim() || ''
      if (!id) return null
      return resolveSystemConnectorGate({
        systemId: id,
        applyUnscopedAttempts: Boolean(
          options.activeSystemId && id === options.activeSystemId,
        ),
        attempts,
        ownerConnectors: ownerQuery.data?.connectors,
        connections: connectionsQuery.data,
        reminders: me?.connector_reminders,
      })
    },
  }
}

function attemptSurfaces(
  item: NeedsAttentionItem | null | undefined,
  detail: MatchingResultsViewProps['detail'],
): MatchSurface[] {
  const seen = new Set<MatchSurface>()
  const add = (value: string | null | undefined) => {
    if (value && isMatchSurface(value)) seen.add(value)
  }
  if (item) {
    for (const surface of inboxItemChannels(item)) add(surface)
  }
  for (const surface of matchedChannelsFromDetail(detail)) add(surface)
  for (const hash of detail?.matched_hashes ?? []) {
    const via = `${hash.matched_via ?? ''} ${hash.kind ?? ''}`.trim().toLowerCase()
    for (const surface of SURFACE_ORDER) {
      if (via === surface || via.includes(surface)) add(surface)
    }
  }
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function personSurfaces(
  contact: MatchedPersonContact,
  attemptHits: readonly MatchSurface[],
): Set<MatchSurface> {
  const hits = new Set<MatchSurface>(attemptHits)
  if (contact.email?.trim()) hits.add('email')
  if (Array.isArray(contact.phones) && contact.phones.some((phone) => phone?.number?.trim())) {
    hits.add('phone')
  }
  return hits
}

function contactSearchHaystack(contact: MatchedPersonContact): string {
  const phones = (contact.phones ?? [])
    .map((phone) => phone?.number?.trim() ?? '')
    .filter(Boolean)
    .join(' ')
  return [
    formatMatchedContactLabel(contact),
    contact.email,
    contact.state,
    contact.last_name,
    contact.first_initial,
    contact.last_initial,
    phones,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}

function mergeContactsByDwid(
  ...lists: Array<MatchedPersonContact[] | null | undefined>
): MatchedPersonContact[] {
  const byDwid = new Map<string, MatchedPersonContact>()
  const orphans: MatchedPersonContact[] = []
  for (const list of lists) {
    for (const contact of safeMatchedContacts(list)) {
      const dwid = contact.dwid?.trim()
      if (!dwid) {
        orphans.push(contact)
        continue
      }
      if (!byDwid.has(dwid)) byDwid.set(dwid, contact)
    }
  }
  return [...byDwid.values(), ...orphans]
}

function sameDwids(left: string[], right: string[]): boolean {
  if (left.length !== right.length) return false
  return left.every((dwid, index) => dwid === right[index])
}

function SurfaceMarks({ hits }: { hits: Iterable<MatchSurface> }) {
  const set = hits instanceof Set ? hits : new Set(hits)
  return (
    <>
      {SURFACE_ORDER.map((surface) => {
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

function SystemConnectorStatus({
  gate,
  verticalId,
  compact = false,
}: {
  gate: MatchingConnectorGate | null
  verticalId: string | null
  compact?: boolean
}) {
  if (!gate?.blocked) return null
  const chip = matchingConnectorGateChip(gate)
  return (
    <div
      className={cn(
        'flex flex-wrap items-center gap-2 rounded-md border border-red-300/80 bg-red-50/80',
        compact ? 'px-2 py-1.5' : 'px-2.5 py-2',
      )}
      role="status"
    >
      <Badge variant={chip.variant} className="normal-case tracking-normal">
        {chip.label}
      </Badge>
      <p className="min-w-0 flex-1 text-[0.65rem] leading-snug text-red-900/90">
        {chip.label === 'Needs refresh'
          ? 'This system needs a refresh before matching can be confirmed.'
          : 'This system needs to be connected before matching can be confirmed.'}
      </p>
      <Button asChild size="sm">
        <Link to="/owner/connectors" search={ownerConnectorsSearch(verticalId)}>
          Open connectors
        </Link>
      </Button>
    </div>
  )
}

function PeopleList({
  item,
  detail,
  contacts,
  visibleDwids,
  personActions,
  onPersonActionChange,
  onRemovePerson,
  onAddPerson,
  searchableContacts,
  searchPending,
  searchError,
  systemStatus,
  selectable,
  disabled,
}: {
  item: NeedsAttentionItem
  detail: MatchingResultsViewProps['detail']
  contacts: MatchedPersonContact[]
  visibleDwids: string[]
  personActions: Record<string, PersonActionId>
  onPersonActionChange: (dwid: string, action: PersonActionId) => void
  onRemovePerson: (dwid: string) => void
  onAddPerson: (contact: MatchedPersonContact) => void
  searchableContacts: MatchedPersonContact[]
  searchPending: boolean
  searchError: boolean
  systemStatus: string | null
  selectable: boolean
  disabled: boolean
}) {
  const [query, setQuery] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const people = useMemo(() => {
    const byDwid = new Map(
      safeMatchedContacts(contacts).map((contact) => [contact.dwid, contact] as const),
    )
    return visibleDwids
      .map((dwid) => byDwid.get(dwid))
      .filter((contact): contact is MatchedPersonContact => Boolean(contact))
  }, [contacts, visibleDwids])
  const notLive = matchingDetailIsNotLive(detail)
  const attemptHits = attemptSurfaces(item, detail)
  const status = detail?.matched_contacts_status
  const matchType = detail?.match_type ?? item.match_type
  const matchCount =
    typeof detail?.match_count === 'number' ? detail.match_count : people.length
  const visibleSet = new Set(visibleDwids)
  const needle = query.trim().toLowerCase()
  const addable = searchableContacts.filter((contact) => {
    const dwid = contact.dwid?.trim()
    if (!dwid || visibleSet.has(dwid)) return false
    if (!needle) return true
    return contactSearchHaystack(contact).includes(needle)
  })

  if (status === 'unavailable' && people.length === 0 && visibleDwids.length === 0) {
    return <MatchedContactsUnavailableCallout matching={detail ?? undefined} />
  }

  if (notLive) {
    const label =
      inboxReviewItemSystemLabel({
        request_id: item.request_id,
        system: detail?.system,
        system_label: detail?.system_label,
        vertical: detail?.vertical ?? item.vertical,
      }) || 'This system'
    return (
      <p className="text-[0.7rem] text-ink-soft">
        {detail?.result_kind === 'sheet_stub'
          ? `${label} is catalog-only — matching is not live.`
          : `${label} matching is not live.`}
      </p>
    )
  }

  return (
    <div className="space-y-1.5">
      <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
        {people.length === 1 ? 'Person' : `People (${people.length})`}
      </p>
      {people.length === 0 ? (
        <p className="text-[0.7rem] text-mute">
          {matchCount <= 0 || matchType === 'not_found'
            ? 'No matched persons (not found).'
            : 'No person records on this system. Search to add one.'}
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Person</TableHead>
              {SURFACE_ORDER.map((surface) => (
                <TableHead key={surface} className="w-10 text-center">
                  {SURFACE_LABEL[surface]}
                </TableHead>
              ))}
              <TableHead className="w-[7.5rem]">Disposition</TableHead>
              <TableHead className="w-14">
                <span className="sr-only">Remove</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {people.map((contact, index) => {
              const dwid = contact.dwid?.trim() ?? ''
              const action = dwid ? personActions[dwid] : undefined
              const applies = Boolean(
                selectable && dwid && action && action === systemStatus,
              )
              return (
                <TableRow key={dwid || `person-${index}`}>
                  <TableCell
                    className={cn(
                      'max-w-[12rem] truncate text-xs',
                      applies || !selectable ? 'text-ink' : 'text-mute',
                    )}
                  >
                    {formatMatchedContactLabel(contact)}
                  </TableCell>
                  <SurfaceMarks hits={personSurfaces(contact, attemptHits)} />
                  <TableCell>
                    {selectable && dwid ? (
                      <select
                        className={statusSelectClass(true)}
                        value={action ?? ''}
                        disabled={disabled || !dwid}
                        aria-label={`Disposition for ${formatMatchedContactLabel(contact)}`}
                        onChange={(event) => {
                          if (isPersonActionId(event.target.value)) {
                            onPersonActionChange(dwid, event.target.value)
                          }
                        }}
                      >
                        <option value="" disabled>
                          Choose…
                        </option>
                        {PERSON_ACTIONS.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <span className="text-[0.65rem] text-mute">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    {dwid ? (
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        disabled={disabled}
                        aria-label={`Remove ${formatMatchedContactLabel(contact)}`}
                        onClick={() => onRemovePerson(dwid)}
                      >
                        Remove
                      </Button>
                    ) : null}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}

      <div className="space-y-1">
        <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Add from this system
        </label>
        <input
          type="search"
          className={statusSelectClass()}
          value={query}
          disabled={disabled}
          placeholder="Search this system…"
          aria-label="Search people in this system"
          onFocus={() => setSearchOpen(true)}
          onChange={(event) => {
            setSearchOpen(true)
            setQuery(event.target.value)
          }}
        />
        {searchOpen && !disabled ? (
          <div className="space-y-1" role="listbox" aria-label="People to add">
            {searchPending ? (
              <p className="text-[0.65rem] text-mute">Searching this system…</p>
            ) : null}
            {searchError ? (
              <p className="text-[0.65rem] text-red-800">
                Could not search this system. Try again.
              </p>
            ) : null}
            {addable.length === 0 && !searchPending ? (
              <p className="text-[0.65rem] text-mute">
                {needle
                  ? 'No people in this system match that search.'
                  : 'No additional people to add. Removed matches appear here.'}
              </p>
            ) : (
              addable.map((contact) => {
                const dwid = contact.dwid
                return (
                  <button
                    key={dwid}
                    type="button"
                    role="option"
                    className="flex w-full items-center justify-between rounded-md border border-line bg-paper px-2 py-1 text-left text-xs text-ink hover:bg-canvas"
                    onClick={() => {
                      onAddPerson(contact)
                      setQuery('')
                    }}
                  >
                    <span className="truncate">{formatMatchedContactLabel(contact)}</span>
                    <span className="shrink-0 text-[0.65rem] text-habeas-navy">Add</span>
                  </button>
                )
              })
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

function optionLabel(
  options: MatchingResultsViewProps['statusOptions'],
  value: string | null,
): string {
  if (value == null) return 'Choose status…'
  return options.find((option) => option.id === value)?.label ?? value
}

/** Drop slug-style leftovers (source codes, vertical ids) from header chrome. */
function isHumanHeaderLabel(label: string, rawId: string | null | undefined): boolean {
  const trimmed = label.trim()
  if (!trimmed || trimmed === '—' || trimmed === 'Unknown') return false
  const slug = (rawId ?? '').trim()
  if (!slug) return true
  if (trimmed === slug) return false
  const fold = (value: string) => value.toLowerCase().replaceAll(/[\s/_-]+/g, '')
  if (fold(trimmed) === fold(slug) && trimmed === trimmed.toLowerCase()) return false
  return true
}

/** Same 48h matching-review floor as Inbox — display only. */
const MATCHING_REVIEW_SLA_HOURS = 48

function dueFact(item: NeedsAttentionItem): {
  label: string
  tone: 'fail' | 'wait' | 'default'
} | null {
  const anchor = item.requested_at ?? item.received_at
  if (!anchor) return null
  const start = new Date(anchor)
  if (Number.isNaN(start.getTime())) return null
  const due = new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
  const when = due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  const msLeft = due.getTime() - Date.now()
  if (msLeft < 0) return { label: `Overdue · ${when}`, tone: 'fail' }
  if (msLeft <= 12 * 60 * 60 * 1000) return { label: `Due soon · ${when}`, tone: 'wait' }
  return { label: `Due ${when}`, tone: 'default' }
}

function seedPersonAction(
  matchType: string | null | undefined,
  matchCount: number | null | undefined,
): PersonActionId {
  const suggested = suggestedDropResponseStatus(matchType, matchCount)
  return suggested === 4 ? '4' : '3'
}

/** Hybrid two-tier matching review — Jose’s preferred default. */
export function OwnerMatchingReviewV10({
  item,
  detail,
  contacts,
  loading,
  ownerLanguage,
  statusOptions,
  statusId,
  onStatusChange,
  selectedDwids,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
  batchDefaultStatus,
  onBatchDefaultStatusChange,
  useBatchDefault,
  onUseBatchDefaultChange,
  activeSystem,
  onSelectSystem,
}: OwnerMatchingReviewV10Props) {
  const empty = resultViewEmpty(loading, Boolean(item))
  const checkboxId = useId()
  const [visibleDwids, setVisibleDwids] = useState<string[]>([])
  const [personActions, setPersonActions] = useState<Record<string, PersonActionId>>({})
  const [extraContacts, setExtraContacts] = useState<MatchedPersonContact[]>([])
  const lastSystemStatus = useRef<string | null>(null)
  const peopleSeedKey = useRef<string | null>(null)

  const followingDefault = useBatchDefault && batchDefaultStatus != null
  const effectiveStatus = followingDefault ? batchDefaultStatus : statusId
  const peopleCleared = effectiveStatus === '5'
  const sourceLabel = item ? inboxIntakeSourceLabel(item.intake_source) : '—'
  const due = item ? dueFact(item) : null
  const verticalLabel = item ? inboxReviewItemVerticalLabel(item) : null
  const humanSource = item && isHumanHeaderLabel(sourceLabel, item.intake_source) ? sourceLabel : null
  const humanVertical =
    verticalLabel && isHumanHeaderLabel(verticalLabel, item?.vertical) ? verticalLabel : null
  const headerAria = [
    'Matching review',
    humanSource,
    due?.label,
    humanVertical,
    item?.request_id ? `Request ${item.request_id}` : null,
  ]
    .filter(Boolean)
    .join(', ')
  const resolvedSystem =
    activeSystem?.trim() ||
    (item ? inboxItemSystemId(item) : null) ||
    detail?.system?.trim() ||
    null
  const verticalId =
    detail?.vertical?.trim() || item?.vertical?.trim() || null
  const connections = item ? inboxDisplayConnections(item) : []
  const sections = (
    connections.length > 0
      ? connections
      : [
          {
            system: resolvedSystem,
            system_label: item?.system_label,
            vertical: item?.vertical,
            color_token: item?.color_token,
            match_type: item?.match_type,
          },
        ]
  ).filter((connection) => {
    const systemId = connection.system?.trim() || ''
    if (!systemIdIsCassandra(systemId)) return true
    return (connection.vertical ?? item?.vertical ?? '').trim().toLowerCase() === 'test'
  })

  const { gateFor } = useSystemConnectorGates({
    verticalId,
    activeSystemId: resolvedSystem,
  })

  const { role } = useMe()
  const ownerPersona = isVerticalOperatorRole(role)
  const requestId = item ? matchingLabRequestId(item.request_id) : null
  const searchSystem = resolvedSystem && !systemIdIsCassandra(resolvedSystem) ? resolvedSystem : null
  const peopleSearchQuery = useQuery({
    queryKey: ownerPersona
      ? [
          'admin-api',
          'ops',
          'requests',
          requestId,
          'verticals',
          verticalId,
          'matching-results',
          searchSystem,
          'v10-people',
        ]
      : ['admin-api', 'ops', 'drop', 'matching-results', requestId, 'v10-people'],
    queryFn: () => {
      if (!requestId || !isRequestUuid(requestId)) return null
      if (ownerPersona) {
        if (!verticalId) return null
        return fetchOwnerVerticalMatchingDetailOptional(
          requestId,
          verticalId,
          searchSystem ?? undefined,
        )
      }
      return getDropMatchingResultDetail(requestId)
    },
    enabled: Boolean(requestId && searchSystem && (!ownerPersona || verticalId)),
    staleTime: 30_000,
    retry: false,
  })

  const matchedPool = useMemo(
    () =>
      mergeContactsByDwid(
        contacts,
        extraContacts,
        peopleSearchQuery.data?.matched_contacts,
      ),
    [contacts, extraContacts, peopleSearchQuery.data?.matched_contacts],
  )

  useEffect(() => {
    if (!item) return
    const people = safeMatchedContacts(contacts).filter((contact) => contact.dwid?.trim())
    const key = `${item.request_id}:${resolvedSystem ?? ''}:${people.map((row) => row.dwid).join('|')}`
    if (peopleSeedKey.current === key) return
    peopleSeedKey.current = key
    const seed = seedPersonAction(
      detail?.match_type ?? item.match_type,
      detail?.match_count ?? item.match_count,
    )
    const nextActions: Record<string, PersonActionId> = {}
    for (const contact of people) {
      const dwid = contact.dwid.trim()
      nextActions[dwid] = isPersonActionId(effectiveStatus) ? effectiveStatus : seed
    }
    setVisibleDwids(people.map((contact) => contact.dwid.trim()))
    setPersonActions(nextActions)
    setExtraContacts([])
    lastSystemStatus.current = isPersonActionId(effectiveStatus) ? effectiveStatus : seed
  }, [
    item,
    contacts,
    resolvedSystem,
    detail?.match_type,
    detail?.match_count,
    effectiveStatus,
  ])

  useEffect(() => {
    if (!isPersonActionId(effectiveStatus)) {
      lastSystemStatus.current = effectiveStatus
      return
    }
    if (lastSystemStatus.current === effectiveStatus) return
    lastSystemStatus.current = effectiveStatus
    setPersonActions((previous) => {
      const next = { ...previous }
      for (const dwid of visibleDwids) next[dwid] = effectiveStatus
      return next
    })
  }, [effectiveStatus, visibleDwids])

  useEffect(() => {
    if (peopleCleared) {
      if (selectedDwids.length > 0) onSelectedDwidsChange([])
      return
    }
    if (!isPersonActionId(effectiveStatus)) return
    const next = visibleDwids.filter((dwid) => personActions[dwid] === effectiveStatus)
    if (!sameDwids(next, selectedDwids)) onSelectedDwidsChange(next)
  }, [
    effectiveStatus,
    peopleCleared,
    personActions,
    visibleDwids,
    selectedDwids,
    onSelectedDwidsChange,
  ])

  if (empty) return empty
  if (!item) return null
  const reviewItem = item

  function setUseDefault(next: boolean) {
    onUseBatchDefaultChange(next)
    if (next && batchDefaultStatus != null) {
      onStatusChange(batchDefaultStatus)
    }
  }

  function handlePersonActionChange(dwid: string, action: PersonActionId) {
    setPersonActions((previous) => ({ ...previous, [dwid]: action }))
  }

  function handleRemovePerson(dwid: string) {
    setVisibleDwids((previous) => previous.filter((id) => id !== dwid))
  }

  function handleAddPerson(contact: MatchedPersonContact) {
    const dwid = contact.dwid?.trim()
    if (!dwid) return
    setExtraContacts((previous) =>
      previous.some((row) => row.dwid === dwid) ? previous : [...previous, contact],
    )
    setVisibleDwids((previous) => (previous.includes(dwid) ? previous : [...previous, dwid]))
    setPersonActions((previous) => ({
      ...previous,
      [dwid]: isPersonActionId(effectiveStatus)
        ? effectiveStatus
        : seedPersonAction(
            detail?.match_type ?? reviewItem.match_type,
            detail?.match_count ?? reviewItem.match_count,
          ),
    }))
  }

  const locked = Boolean(disabled || pending)

  return (
    <div className="space-y-3">
      <header
        className="flex flex-wrap items-center gap-1.5 border-b border-line pb-2"
        aria-label={headerAria}
      >
        <h2 className="text-sm font-semibold text-ink">Matching review</h2>
        {humanSource ? (
          <Badge variant="default" className="normal-case tracking-normal">
            {humanSource}
          </Badge>
        ) : null}
        {due ? (
          <Badge
            variant={due.tone === 'fail' ? 'fail' : due.tone === 'wait' ? 'wait' : 'default'}
            className={cn(
              'normal-case tracking-normal tabular-nums',
              due.tone === 'fail' && 'border-red-200 bg-red-50 text-red-800',
              due.tone === 'wait' && 'border-amber-200 bg-amber-50 text-amber-900',
            )}
          >
            {due.label}
          </Badge>
        ) : null}
        {humanVertical ? (
          <span className="text-[0.65rem] text-ink-soft">{humanVertical}</span>
        ) : null}
        {item?.request_id ? (
          <span className="sr-only">Request {item.request_id}</span>
        ) : null}
      </header>

      <div className="space-y-2">
        {sections.map((connection) => {
          const systemId = connection.system?.trim() || ''
          const label =
            inboxReviewItemSystemLabel({
              request_id: item.request_id,
              system: systemId || resolvedSystem,
              system_label: connection.system_label,
              vertical: connection.vertical ?? item.vertical,
            }) ??
            connection.system_label ??
            'Unassigned system'
          const isActive =
            sections.length === 1 ||
            Boolean(systemId && resolvedSystem && systemId === resolvedSystem)
          const token = connection.color_token ?? item.color_token
          const sectionMatch = isActive
            ? (detail?.match_type ?? item.match_type)
            : (connection.match_type ?? item.match_type)
          const sectionGate = gateFor(systemId || resolvedSystem, isActive ? detail?.attempts : null)
          const sectionLocked = locked || Boolean(sectionGate)

          return (
            <section
              key={systemId || label}
              className={cn(
                'rounded-md border bg-paper',
                isActive ? 'border-habeas-navy/30' : 'border-line',
              )}
            >
              {onSelectSystem && systemId && !isActive ? (
                <div className="space-y-2 px-2.5 py-2">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 text-left"
                    aria-pressed={false}
                    onClick={() => onSelectSystem(systemId)}
                  >
                    {token ? (
                      <span
                        className={cn(
                          'h-2 w-2 shrink-0 rounded-full border',
                          matchingSystemColorClass(token),
                        )}
                        aria-hidden
                      />
                    ) : null}
                    <span className="text-xs font-medium text-ink">{label}</span>
                    <span className="text-[0.65rem] text-ink-soft">
                      {matchTypeLabel(sectionMatch, ownerLanguage)}
                    </span>
                    <span className="ml-auto text-[0.65rem] text-habeas-navy">Review</span>
                  </button>
                  <SystemConnectorStatus
                    gate={sectionGate}
                    verticalId={connection.vertical ?? verticalId}
                    compact
                  />
                </div>
              ) : (
                <div className="space-y-2 border-b border-line px-2.5 py-2">
                  <div className="flex flex-wrap items-center gap-2">
                    {token ? (
                      <span
                        className={cn(
                          'h-2 w-2 shrink-0 rounded-full border',
                          matchingSystemColorClass(token),
                        )}
                        aria-hidden
                      />
                    ) : null}
                    <h3 className="text-xs font-semibold text-ink">{label}</h3>
                    <Badge variant="default" className="normal-case tracking-normal">
                      {matchTypeLabel(sectionMatch, ownerLanguage)}
                    </Badge>
                    {isActive && detail?.match_count != null ? (
                      <span className="sr-only">
                        {detail.match_count} {detail.match_count === 1 ? 'person' : 'people'}
                      </span>
                    ) : null}
                  </div>
                  <SystemConnectorStatus
                    gate={sectionGate}
                    verticalId={connection.vertical ?? verticalId}
                  />
                </div>
              )}

              {isActive ? (
                <div className="space-y-3 px-2.5 py-2">
                  <div className="space-y-2 rounded-md border border-line bg-canvas px-2.5 py-2">
                    <div className="space-y-1">
                      <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                        Batch default
                      </label>
                      <select
                        className={statusSelectClass()}
                        value={batchDefaultStatus ?? ''}
                        disabled={sectionLocked}
                        aria-label="Batch default status"
                        onChange={(event) => {
                          if (event.target.value) onBatchDefaultStatusChange(event.target.value)
                        }}
                      >
                        <option value="" disabled>
                          Choose status…
                        </option>
                        {statusOptions.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="flex items-start gap-2">
                      <input
                        id={checkboxId}
                        type="checkbox"
                        className="mt-1 size-3.5 rounded border-line text-habeas-navy accent-habeas-navy"
                        checked={useBatchDefault}
                        disabled={sectionLocked || batchDefaultStatus == null}
                        onChange={(event) => setUseDefault(event.target.checked)}
                      />
                      <label htmlFor={checkboxId} className="min-w-0 text-xs text-ink">
                        Use batch default for this system
                        <span className="block text-[0.65rem] text-ink-soft">
                          {batchDefaultStatus != null
                            ? optionLabel(statusOptions, batchDefaultStatus)
                            : 'No batch default set'}
                        </span>
                      </label>
                    </div>

                    {followingDefault ? (
                      <p className="text-[0.65rem] text-ink-soft" aria-live="polite">
                        This system follows the batch default — uncheck to override.
                      </p>
                    ) : (
                      <div className="space-y-1">
                        <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                          System override
                        </label>
                        <select
                          className={statusSelectClass()}
                          value={statusId ?? ''}
                          disabled={sectionLocked}
                          aria-label="System status override"
                          onChange={(event) => {
                            if (event.target.value) onStatusChange(event.target.value)
                          }}
                        >
                          <option value="" disabled>
                            Choose status…
                          </option>
                          {statusOptions.map((option) => (
                            <option key={option.id} value={option.id}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>

                  <div className="rounded-md border border-line bg-canvas px-2.5 py-2">
                    <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                      Summary
                    </p>
                    <p className="text-xs text-ink">
                      {effectiveStatus == null ? (
                        'No status yet'
                      ) : (
                        <>
                          {optionLabel(statusOptions, effectiveStatus)}
                          <span className="text-ink-soft">
                            {followingDefault ? ' · batch default' : ' · system override'}
                          </span>
                        </>
                      )}
                    </p>
                    <p className="text-[0.65rem] text-ink-soft">
                      {peopleCleared
                        ? 'No people sent'
                        : formatMatchedContactsSummary(matchedPool, selectedDwids)}
                    </p>
                  </div>

                  <PeopleList
                    item={item}
                    detail={detail}
                    contacts={matchedPool}
                    visibleDwids={visibleDwids}
                    personActions={personActions}
                    onPersonActionChange={handlePersonActionChange}
                    onRemovePerson={handleRemovePerson}
                    onAddPerson={handleAddPerson}
                    searchableContacts={matchedPool}
                    searchPending={peopleSearchQuery.isFetching}
                    searchError={peopleSearchQuery.isError}
                    systemStatus={effectiveStatus}
                    selectable={!peopleCleared}
                    disabled={sectionLocked || peopleCleared}
                  />

                  <ResultApplyBar
                    pending={pending}
                    disabled={
                      sectionLocked ||
                      effectiveStatus == null ||
                      applyNeedsPeople(effectiveStatus, selectedDwids)
                    }
                    onApply={onApply}
                  />
                </div>
              ) : null}
            </section>
          )
        })}
      </div>
    </div>
  )
}
