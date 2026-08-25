import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'

import {
  formatMatchedContactLabel,
  matchedChannelsFromDetail,
  matchingDetailIsNotLive,
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
import {
  getRequest,
  listOwnerConnectors,
  suggestedDropResponseStatus,
  type MatchedPersonContact,
  type MatchingResultDetail,
  type NeedsAttentionItem,
} from '@/lib/api'
import { useMe } from '@/lib/auth'
import {
  isDataCatalogVertical,
  isMatchingGateBlockedDisplayStatus,
  matchingConnectorGateChip,
  matchingGateFromReminders,
  ownerConnectorsSearch,
  resolveMatchingConnectorGate,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import {
  inboxIntakeSourceLabel,
  inboxItemSystemId,
  matchTypeLabel,
} from '@/lib/inbox-batch-status'
import {
  inboxItemChannels,
  inboxItemConnections,
  type InboxReviewConnection,
} from '@/lib/inbox-status-lab'
import { DROP_HASH_SYSTEM_ID, catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

import {
  ResultApplyBar,
  applyNeedsPeople,
  resultViewEmpty,
  statusSelectClass,
} from '../matching-results-lab/ResultViewChrome'
import {
  matchingLabRequestId,
  matchingLabSystemId,
  type MatchingResultsViewProps,
} from '../matching-results-lab/matching-results-lab-types'

/** Mirrors admin-api APPROACHING_SLA_THRESHOLD_HOURS.matching_review */
const MATCHING_REVIEW_SLA_HOURS = 48

type PersonAction = '3' | '4'

function isHiddenSystemId(system: string | null | undefined): boolean {
  const id = (system ?? '').trim().toLowerCase()
  return id === DROP_HASH_SYSTEM_ID || id === 'cassandra'
}

function shortRequestId(requestId: string): string {
  const trimmed = requestId.trim()
  return trimmed.length <= 8 ? trimmed : `${trimmed.slice(0, 8)}…`
}

function deriveDueAt(item: NeedsAttentionItem): Date | null {
  const anchor = item.requested_at ?? item.received_at
  if (!anchor) return null
  const start = new Date(anchor)
  if (Number.isNaN(start.getTime())) return null
  return new Date(start.getTime() + MATCHING_REVIEW_SLA_HOURS * 60 * 60 * 1000)
}

function formatDueCompact(item: NeedsAttentionItem): { label: string; tone: 'fail' | 'wait' | 'default' } {
  const due = deriveDueAt(item)
  if (!due) return { label: 'No due', tone: 'default' }
  const msLeft = due.getTime() - Date.now()
  const when = due.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
  if (msLeft < 0) return { label: `Overdue · ${when}`, tone: 'fail' }
  if (msLeft <= 12 * 60 * 60 * 1000) return { label: `Soon · ${when}`, tone: 'wait' }
  return { label: `Due ${when}`, tone: 'default' }
}

function systemLabel(item: NeedsAttentionItem, connection?: InboxReviewConnection): string {
  const system = connection?.system ?? inboxItemSystemId(item)
  if (isHiddenSystemId(system)) {
    return (
      catalogSystemDisplayLabel(system, {
        vertical: connection?.vertical ?? item.vertical,
        systemLabel: connection?.system_label ?? item.system_label,
      }) || 'This system'
    )
  }
  return (
    catalogSystemDisplayLabel(system, {
      vertical: connection?.vertical ?? item.vertical,
      systemLabel: connection?.system_label ?? item.system_label,
    }) ||
    connection?.system_label ||
    item.system_label ||
    system ||
    'Unassigned'
  )
}

function isSystemPending(connection: InboxReviewConnection): boolean {
  const kind = (connection.kind ?? '').trim().toLowerCase()
  const stage = (connection.current_stage ?? '').trim().toLowerCase()
  if (kind && kind !== 'matching') return false
  if (!stage) return true
  if (stage === 'fulfill' || stage === 'fulfillment' || stage === 'notice' || stage === 'delivery') {
    return false
  }
  return (
    stage === 'review' ||
    stage === 'matching' ||
    stage === 'data_owner_review' ||
    stage.includes('match') ||
    stage.includes('review')
  )
}

function mixKind(matchType: string | null | undefined): 'one_to_one' | 'multi' | 'not_found' | 'unknown' {
  if (matchType === 'single_match') return 'one_to_one'
  if (matchType === 'multi_match') return 'multi'
  if (matchType === 'not_found') return 'not_found'
  return 'unknown'
}

function mixLabel(kind: ReturnType<typeof mixKind>): string {
  if (kind === 'one_to_one') return '1:1'
  if (kind === 'multi') return 'Multi'
  if (kind === 'not_found') return 'None'
  return '—'
}

/** Identifier surfaces on one matching attempt — not separate attempts or KPI channels. */
type IdentifierSurface = 'email' | 'phone' | 'ndz'

const SURFACE_ORDER: IdentifierSurface[] = ['email', 'phone', 'ndz']
const SURFACE_MARK: Record<IdentifierSurface, string> = {
  email: 'Em',
  phone: 'Ph',
  ndz: 'Nz',
}
const SURFACE_LABEL: Record<IdentifierSurface, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

function isIdentifierSurface(value: string): value is IdentifierSurface {
  return value === 'email' || value === 'phone' || value === 'ndz'
}

function attemptSurfaces(
  item: NeedsAttentionItem,
  detail: MatchingResultDetail | null | undefined,
): IdentifierSurface[] {
  const seen = new Set<IdentifierSurface>()
  const add = (value: string | null | undefined) => {
    if (value && isIdentifierSurface(value)) seen.add(value)
  }
  for (const surface of inboxItemChannels({
    request_id: item.request_id,
    matched_via: detail?.matched_via ?? item.matched_via,
    matched_channels: detail?.matched_channels ?? item.channels,
    channels: item.channels,
  })) {
    add(surface)
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
  attempt: IdentifierSurface[],
): IdentifierSurface[] {
  const seen = new Set<IdentifierSurface>(attempt)
  if (contact.email?.trim()) seen.add('email')
  if (Array.isArray(contact.phones) && contact.phones.some((phone) => phone?.number?.trim())) {
    seen.add('phone')
  }
  return SURFACE_ORDER.filter((surface) => seen.has(surface))
}

function SurfaceMarks({ surfaces }: { surfaces: IdentifierSurface[] }) {
  if (surfaces.length === 0) {
    return <span className="text-mute">—</span>
  }
  const label = surfaces.map((surface) => SURFACE_LABEL[surface]).join(', ')
  return (
    <span
      className="font-mono text-[0.65rem] uppercase tracking-wide text-ink-soft"
      aria-label={`Surfaces: ${label}`}
    >
      {surfaces.map((surface) => SURFACE_MARK[surface]).join(' · ')}
    </span>
  )
}

type Kpi = { label: string; value: string; hint?: string; tone?: 'navy' | 'wait' | 'fail' | 'ok' }

function KpiStrip({ items }: { items: Kpi[] }) {
  return (
    <dl className="grid grid-cols-2 border border-line bg-paper sm:grid-cols-4">
      {items.map((kpi, index) => (
        <div
          key={kpi.label}
          className={cn(
            'min-w-0 px-2.5 py-1.5',
            index > 0 && 'border-l border-line',
            index === 2 && 'max-sm:border-t max-sm:border-l-0',
            index === 3 && 'max-sm:border-t',
          )}
        >
          <dt className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">{kpi.label}</dt>
          <dd
            className={cn(
              'text-sm font-semibold tabular-nums leading-tight text-ink',
              kpi.tone === 'navy' && 'text-habeas-navy',
              kpi.tone === 'wait' && 'text-amber-800',
              kpi.tone === 'fail' && 'text-red-800',
              kpi.tone === 'ok' && 'text-emerald-800',
            )}
          >
            {kpi.value}
          </dd>
          {kpi.hint ? <p className="truncate text-[0.65rem] text-ink-soft">{kpi.hint}</p> : null}
        </div>
      ))}
    </dl>
  )
}

function requestTypeEmphasis(requestType: string | null | undefined): {
  delete: boolean
  optIn: boolean
} {
  const type = (requestType ?? '').trim().toLowerCase()
  const isDelete = type === 'delete' || type === 'deletion' || type.includes('delete')
  const isOptIn =
    type === 'opt_out' ||
    type === 'opt-out' ||
    type === 'opt_in' ||
    type === 'opt-in' ||
    type.includes('opt')
  if (type === 'combined' || (isDelete && isOptIn)) return { delete: true, optIn: true }
  if (isOptIn) return { delete: false, optIn: true }
  if (isDelete) return { delete: true, optIn: false }
  return { delete: true, optIn: true }
}

function defaultPersonAction(
  statusId: string | null,
  matchType: string | null | undefined,
  matchCount: number | null | undefined,
  requestType: string | null | undefined,
): PersonAction | null {
  if (statusId === '5') return null
  if (statusId === '3' || statusId === '4') return statusId
  const emphasis = requestTypeEmphasis(requestType)
  const suggested = suggestedDropResponseStatus(matchType, matchCount)
  if (suggested === 5) return null
  if (emphasis.optIn && !emphasis.delete) return '4'
  if (emphasis.delete && !emphasis.optIn) return '3'
  return suggested === 4 ? '4' : '3'
}

function gateMatchesSystem(
  gate: MatchingConnectorGate | null,
  systemId: string | null,
): MatchingConnectorGate | null {
  if (!gate?.blocked) return null
  if (isHiddenSystemId(gate.system)) return null
  if (systemId && gate.system && gate.system.trim() !== systemId.trim()) return null
  return gate
}

function blockedMatchingCopy(
  gate: MatchingConnectorGate | null,
  needsConnection: boolean,
): { title: string; description: string; chipLabel: string; chipVariant: 'fail' | 'wait' } {
  if (gate) {
    const chip = matchingConnectorGateChip(gate)
    if (gate.displayStatus === 'needs_refresh' || gate.gateCode === 'upload_stale') {
      return {
        title: 'Needs refresh',
        description: 'Reupload or refresh this system before matching can proceed.',
        chipLabel: chip.label,
        chipVariant: 'fail',
      }
    }
    if (gate.displayStatus === 'needs_setup' || gate.gateCode === 'wizard_incomplete') {
      return {
        title: 'Needs connection',
        description: 'Finish connecting this system before matching can proceed.',
        chipLabel: chip.label,
        chipVariant: 'fail',
      }
    }
    return {
      title: 'Action required',
      description: 'Refresh credentials or reupload this system before matching can proceed.',
      chipLabel: chip.label,
      chipVariant: 'fail',
    }
  }
  if (needsConnection) {
    return {
      title: 'Needs connection',
      description: 'Connect or upload this system before matching can proceed.',
      chipLabel: 'Needs connection',
      chipVariant: 'wait',
    }
  }
  return {
    title: 'Matching blocked',
    description: 'This system needs a connect or refresh before matching can proceed.',
    chipLabel: 'Blocked',
    chipVariant: 'fail',
  }
}

function DispositionToggle({
  label,
  pressed,
  emphasized,
  disabled,
  onClick,
}: {
  label: string
  pressed: boolean
  emphasized: boolean
  disabled: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      aria-pressed={pressed}
      onClick={onClick}
      className={cn(
        'h-6 min-w-[3.5rem] rounded border px-1.5 text-[0.65rem] font-medium',
        pressed
          ? 'border-habeas-navy bg-habeas-navy text-white'
          : emphasized
            ? 'border-habeas-navy/50 bg-white text-habeas-navy'
            : 'border-line bg-white text-ink-soft',
        disabled && 'opacity-50',
      )}
    >
      {label}
    </button>
  )
}

/** Systems operator — compact KPI strip (people, 1:1 vs multi, systems pending) plus table. */
export function OwnerMatchingReviewV02({
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
  onSearchPeople,
  peopleSearchBlocked,
  peopleSearchPending,
}: MatchingResultsViewProps) {
  const { me } = useMe()
  const requestUuid = item ? matchingLabRequestId(item.request_id) : null
  const systemId = item ? matchingLabSystemId(item) ?? inboxItemSystemId(item) ?? detail?.system?.trim() ?? null : null
  const verticalId = (item?.vertical ?? detail?.vertical)?.trim() || null
  const catalogVertical = isDataCatalogVertical(verticalId) || isHiddenSystemId(systemId)

  const [addedPeople, setAddedPeople] = useState<MatchedPersonContact[]>([])
  const [removedDwids, setRemovedDwids] = useState<string[]>([])
  const [personActions, setPersonActions] = useState<Record<string, PersonAction>>({})
  const [searchQuery, setSearchQuery] = useState('')
  const [searchHits, setSearchHits] = useState<MatchedPersonContact[]>([])
  const [searchBusy, setSearchBusy] = useState(false)
  const [searchFailed, setSearchFailed] = useState(false)
  const searchFnRef = useRef(onSearchPeople)
  searchFnRef.current = onSearchPeople

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestUuid, 'matching-review-v02'],
    queryFn: () => getRequest(requestUuid!),
    enabled: Boolean(requestUuid),
    staleTime: 60_000,
    retry: false,
  })

  const connectorsQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connectors', verticalId, 'matching-review-v02'],
    queryFn: () => listOwnerConnectors(verticalId!),
    enabled: Boolean(verticalId) && !catalogVertical,
    staleTime: 60_000,
    retry: false,
  })

  const trimmedSearch = searchQuery.trim()

  const empty = resultViewEmpty(loading, Boolean(item))
  const matchType = detail?.match_type ?? item?.match_type
  const matchCount = detail?.match_count ?? item?.match_count ?? contacts.length
  const requestType = requestQuery.data?.request_type
  const emphasis = requestTypeEmphasis(requestType)

  const contactKey = contacts.map((contact) => contact.dwid).filter(Boolean).join('|')

  useEffect(() => {
    setAddedPeople([])
    setRemovedDwids([])
    setSearchQuery('')
    setPersonActions({})
    setSearchHits([])
    setSearchFailed(false)
  }, [item?.request_id, systemId, contactKey])

  useEffect(() => {
    const action = defaultPersonAction(null, matchType, matchCount, requestType)
    if (!action) return
    setPersonActions((current) => {
      const next = { ...current }
      for (const contact of contacts) {
        if (contact.dwid && next[contact.dwid] == null && !removedDwids.includes(contact.dwid)) {
          next[contact.dwid] = action
        }
      }
      return next
    })
  }, [contactKey, contacts, matchType, matchCount, requestType, removedDwids])

  const reminderGate = useMemo(() => {
    const reminders = (me?.connector_reminders ?? []).filter((reminder) => {
      if (isHiddenSystemId(reminder.system)) return false
      if (systemId && reminder.system && reminder.system !== systemId) return false
      if (verticalId && reminder.vertical_id && reminder.vertical_id !== verticalId) return false
      return true
    })
    return matchingGateFromReminders(reminders)
  }, [me?.connector_reminders, systemId, verticalId])

  const connectorGate = useMemo(() => {
    const connector = (connectorsQuery.data?.connectors ?? []).find((row) => {
      if (isHiddenSystemId(row.system)) return false
      return !systemId || row.system === systemId
    })
    if (!connector || connector.gate_allowed !== false) return null
    const displayStatus = connector.display_status?.trim() || connector.status || 'action_required'
    return {
      blocked: true as const,
      displayStatus: isMatchingGateBlockedDisplayStatus(displayStatus)
        ? displayStatus
        : 'action_required',
      gateCode: connector.gate_code,
      system: connector.system,
      source: 'connection' as const,
    }
  }, [connectorsQuery.data?.connectors, systemId])

  const attemptGate = useMemo(
    () =>
      resolveMatchingConnectorGate({
        attempts: detail?.attempts,
        connections: null,
        reminders: null,
      }),
    [detail?.attempts],
  )

  const localGate = gateMatchesSystem(attemptGate ?? connectorGate ?? reminderGate, systemId)
  const gate = peopleSearchBlocked ?? localGate
  const needsConnection =
    !gate &&
    !catalogVertical &&
    matchingDetailIsNotLive(detail) &&
    !isHiddenSystemId(systemId)
  const matchingBlocked = Boolean(gate || needsConnection)
  const searchGated = matchingBlocked
  const searchPendingSetup = !searchGated && (Boolean(peopleSearchPending) || !onSearchPeople)
  const directorySearchOpen =
    Boolean(onSearchPeople) && !searchGated && !searchPendingSetup && !disabled && !pending
  const showConnectorsButton = matchingBlocked && !catalogVertical

  const peopleDirectory = useMemo(() => {
    const byDwid = new Map<string, MatchedPersonContact>()
    for (const contact of [...contacts, ...addedPeople]) {
      if (contact.dwid && !byDwid.has(contact.dwid)) byDwid.set(contact.dwid, contact)
    }
    return [...byDwid.values()]
  }, [addedPeople, contacts])

  const rows = useMemo(
    () => peopleDirectory.filter((contact) => contact.dwid && !removedDwids.includes(contact.dwid)),
    [peopleDirectory, removedDwids],
  )

  useEffect(() => {
    const needle = trimmedSearch
    if (!directorySearchOpen || needle.length < 2) {
      setSearchHits([])
      setSearchBusy(false)
      setSearchFailed(false)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        setSearchBusy(true)
        setSearchFailed(false)
        try {
          const result = (await searchFnRef.current?.(needle)) ?? []
          if (cancelled) return
          setSearchHits(result)
        } catch {
          if (cancelled) return
          setSearchHits([])
          setSearchFailed(true)
        } finally {
          if (!cancelled) setSearchBusy(false)
        }
      })()
    }, 200)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [directorySearchOpen, trimmedSearch])

  if (empty) return empty
  if (!item) return null

  const connections = inboxItemConnections(item).filter((connection) => !isHiddenSystemId(connection.system))
  const systems =
    connections.length > 0
      ? connections
      : isHiddenSystemId(inboxItemSystemId(item))
        ? []
        : [
            {
              system: inboxItemSystemId(item),
              system_label: item.system_label,
              vertical: item.vertical,
              current_stage: item.current_stage,
              match_type: item.match_type,
              kind: item.kind,
            },
          ]
  const pendingSystems = systems.filter(isSystemPending)
  const mixCounts = { one_to_one: 0, multi: 0, not_found: 0, unknown: 0 }
  for (const connection of systems) {
    mixCounts[mixKind(connection.match_type ?? item.match_type)] += 1
  }

  const peopleCount = matchCount
  const currentMix = mixKind(matchType)
  const notFound = statusId === '5' || currentMix === 'not_found'
  const due = formatDueCompact(item)
  const locked = Boolean(disabled || pending || matchingBlocked)
  const activeSystem = systemLabel(item)
  const selectedCount = notFound ? 0 : selectedDwids.length
  const surfaces = attemptSurfaces(item, detail)
  const selectedActions = selectedDwids
    .map((dwid) => personActions[dwid])
    .filter((action): action is PersonAction => action === '3' || action === '4')
  const mixedActions = new Set(selectedActions).size > 1
  const blockedCopy = matchingBlocked ? blockedMatchingCopy(gate, needsConnection) : null
  const visibleIds = new Set(rows.map((contact) => contact.dwid))
  const addableHits = searchHits.filter(
    (contact) => Boolean(contact.dwid) && !visibleIds.has(contact.dwid),
  )
  const pendingSearchCopy = peopleSearchPending ?? {
    title: 'Needs connection',
    support: 'This system is not connected for people search yet.',
  }

  const kpis: Kpi[] = [
    {
      label: 'People',
      value: String(peopleCount),
      hint: selectedCount > 0 ? `${selectedCount} selected` : 'None selected',
      tone: peopleCount > 0 ? 'navy' : undefined,
    },
    {
      label: '1:1 vs multi',
      value: `${mixCounts.one_to_one} · ${mixCounts.multi}`,
      hint:
        mixCounts.not_found > 0
          ? `${mixLabel(currentMix)} here · ${mixCounts.not_found} none`
          : `${mixLabel(currentMix)} this system`,
      tone: currentMix === 'multi' ? 'wait' : currentMix === 'not_found' ? undefined : 'navy',
    },
    {
      label: 'Systems pending',
      value: `${pendingSystems.length}/${systems.length || 1}`,
      hint:
        pendingSystems.length === 0
          ? 'All reviewed'
          : pendingSystems.map((row) => systemLabel(item, row)).join(' · ') || 'Matching open',
      tone: pendingSystems.length > 0 ? 'wait' : 'ok',
    },
    {
      label: 'This system',
      value: activeSystem,
      hint: matchTypeLabel(matchType, ownerLanguage),
    },
  ]

  function handleStatusChange(next: string) {
    if (!next) return
    onStatusChange(next)
    if (next === '5') {
      onSelectedDwidsChange([])
      setPersonActions({})
      return
    }
    if (next === '3' || next === '4') {
      const action = next as PersonAction
      const nextActions: Record<string, PersonAction> = {}
      for (const contact of rows) {
        if (contact.dwid) nextActions[contact.dwid] = action
      }
      setPersonActions(nextActions)
      onSelectedDwidsChange(rows.map((contact) => contact.dwid).filter(Boolean))
    }
  }

  function setPersonDisposition(contact: MatchedPersonContact, action: PersonAction) {
    if (!contact.dwid || locked) return
    const nextActions = { ...personActions, [contact.dwid]: action }
    setPersonActions(nextActions)
    setRemovedDwids((current) => current.filter((dwid) => dwid !== contact.dwid))
    const nextSelected = selectedDwids.includes(contact.dwid)
      ? selectedDwids
      : [...selectedDwids, contact.dwid]
    onSelectedDwidsChange(nextSelected)
    const unique = new Set(
      nextSelected
        .map((dwid) => nextActions[dwid])
        .filter((value): value is PersonAction => value === '3' || value === '4'),
    )
    if (unique.size === 1) onStatusChange([...unique][0]!)
  }

  function removePerson(dwid: string) {
    if (!dwid || locked) return
    onSelectedDwidsChange(selectedDwids.filter((id) => id !== dwid))
    setPersonActions((current) => {
      const next = { ...current }
      delete next[dwid]
      return next
    })
    setRemovedDwids((current) => (current.includes(dwid) ? current : [...current, dwid]))
    setAddedPeople((current) => current.filter((contact) => contact.dwid !== dwid))
  }

  function addPerson(contact: MatchedPersonContact) {
    if (!contact.dwid || locked) return
    const action =
      defaultPersonAction(statusId, matchType, matchCount, requestType) ??
      (emphasis.optIn && !emphasis.delete ? '4' : '3')
    if (!contacts.some((row) => row.dwid === contact.dwid)) {
      setAddedPeople((current) =>
        current.some((row) => row.dwid === contact.dwid) ? current : [...current, contact],
      )
    }
    setPersonDisposition({ ...contact, dwid: contact.dwid }, action)
    setSearchQuery('')
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1.5 text-[0.7rem] text-ink-soft">
        <Badge variant="default" className="normal-case tracking-normal">
          {inboxIntakeSourceLabel(item.intake_source)}
        </Badge>
        <span className="font-mono tabular-nums text-ink">{shortRequestId(item.request_id)}</span>
        <span aria-hidden>·</span>
        <Badge
          variant={due.tone === 'fail' ? 'fail' : due.tone === 'wait' ? 'wait' : 'default'}
          className="normal-case tracking-normal tabular-nums"
        >
          {due.label}
        </Badge>
      </div>

      {blockedCopy ? (
        <div
          className="flex flex-wrap items-center gap-2 border border-red-200 bg-red-50/80 px-2.5 py-1.5"
          role="status"
        >
          <Badge variant={blockedCopy.chipVariant} className="normal-case tracking-normal">
            {blockedCopy.chipLabel}
          </Badge>
          <div className="min-w-0 flex-1">
            <p className="text-[0.7rem] font-medium text-red-950">{blockedCopy.title}</p>
            <p className="text-[0.65rem] leading-snug text-red-900/90">{blockedCopy.description}</p>
          </div>
          {showConnectorsButton ? (
            <Button asChild size="sm" variant="outline">
              <Link to="/owner/connectors" search={ownerConnectorsSearch(verticalId)}>
                Open connectors
              </Link>
            </Button>
          ) : null}
        </div>
      ) : null}

      <KpiStrip items={kpis} />

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[4.5rem]">Delete</TableHead>
            <TableHead className="w-[4.5rem]">Opt-in</TableHead>
            <TableHead>Person</TableHead>
            <TableHead>Surfaces</TableHead>
            <TableHead>State</TableHead>
            <TableHead>System</TableHead>
            <TableHead className="w-12">
              <span className="sr-only">Remove</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow>
              <TableCell colSpan={7} className="text-xs text-mute">
                {notFound ? 'No matched persons (not found).' : 'No person rows for this system.'}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((contact, index) => {
              const action = contact.dwid ? personActions[contact.dwid] : undefined
              return (
                <TableRow key={contact.dwid || `row-${index}`}>
                  <TableCell>
                    <DispositionToggle
                      label="Delete"
                      pressed={action === '3'}
                      emphasized={emphasis.delete}
                      disabled={locked || !contact.dwid}
                      onClick={() => setPersonDisposition(contact, '3')}
                    />
                  </TableCell>
                  <TableCell>
                    <DispositionToggle
                      label="Opt-in"
                      pressed={action === '4'}
                      emphasized={emphasis.optIn}
                      disabled={locked || !contact.dwid}
                      onClick={() => setPersonDisposition(contact, '4')}
                    />
                  </TableCell>
                  <TableCell className="max-w-[11rem] truncate text-xs text-ink">
                    {formatMatchedContactLabel(contact)}
                  </TableCell>
                  <TableCell>
                    <SurfaceMarks surfaces={personSurfaces(contact, surfaces)} />
                  </TableCell>
                  <TableCell className="text-xs text-ink-soft">{contact.state || '—'}</TableCell>
                  <TableCell className="text-xs text-ink-soft">{activeSystem}</TableCell>
                  <TableCell>
                    <button
                      type="button"
                      disabled={locked || !contact.dwid}
                      className="text-[0.65rem] text-mute hover:text-ink disabled:opacity-50"
                      aria-label={`Remove person ${index + 1}`}
                      onClick={() => contact.dwid && removePerson(contact.dwid)}
                    >
                      Remove
                    </button>
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>

      <div className="space-y-1.5 border border-line bg-paper px-2.5 py-2">
        <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          Add from this system
        </label>
        <input
          type="search"
          value={searchQuery}
          disabled={locked || searchGated || searchPendingSetup}
          placeholder="Search this system…"
          aria-label="Search people in this system"
          className={cn(statusSelectClass(), 'w-full max-w-md')}
          onChange={(event) => setSearchQuery(event.target.value)}
        />
        {searchGated ? null : searchPendingSetup ? (
          <p className="text-[0.65rem] text-mute">
            {pendingSearchCopy.title}
            {pendingSearchCopy.support ? ` · ${pendingSearchCopy.support}` : ''}
          </p>
        ) : trimmedSearch.length >= 2 ? (
          <div className="space-y-1">
            {addableHits.map((contact) => (
              <div
                key={contact.dwid}
                className="flex flex-wrap items-center justify-between gap-2 text-xs"
              >
                <span className="truncate text-ink">{formatMatchedContactLabel(contact)}</span>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={locked}
                  onClick={() => addPerson(contact)}
                >
                  Add
                </Button>
              </div>
            ))}
            {searchBusy ? (
              <p className="text-[0.65rem] text-mute">Searching this system…</p>
            ) : null}
            {searchFailed ? (
              <p className="text-[0.65rem] text-mute">Could not search this system.</p>
            ) : null}
            {!searchBusy && !searchFailed && addableHits.length === 0 ? (
              <p className="text-[0.65rem] text-mute">
                No people from this system match that search.
              </p>
            ) : null}
          </div>
        ) : (
          <p className="text-[0.65rem] text-mute">Type two or more characters to search this system.</p>
        )}
      </div>

      <div className="space-y-2">
        <div className="min-w-[10rem] max-w-xs space-y-1">
          <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Disposition
          </label>
          <select
            className={statusSelectClass()}
            value={statusId ?? ''}
            disabled={locked}
            aria-label="Match disposition"
            onChange={(event) => handleStatusChange(event.target.value)}
          >
            <option value="" disabled>
              Choose…
            </option>
            {statusOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        {mixedActions ? (
          <p className="text-[0.65rem] text-amber-800">
            Choose Delete or Opt-in for every selected person before applying.
          </p>
        ) : null}
        <ResultApplyBar
          pending={pending}
          disabled={
            disabled ||
            matchingBlocked ||
            mixedActions ||
            statusId == null ||
            applyNeedsPeople(statusId, selectedDwids)
          }
          onApply={onApply}
        />
      </div>
    </div>
  )
}
