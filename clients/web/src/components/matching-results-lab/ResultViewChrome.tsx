import { useEffect, useId, useRef, useState, type ReactNode } from 'react'

import { redactHashHex } from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { MatchedChannel, MatchedPersonContact } from '@/lib/api'
import {
  matchingConnectorGateChip,
  type MatchingConnectorGate,
} from '@/lib/connection-display'
import { matchTypeLabel } from '@/lib/inbox-batch-status'
import { cn } from '@/lib/utils'

import {
  filterMatchedPeople,
  matchingLabResolveSystemId,
  matchingLabSystemDisplay,
  matchedPersonPii,
  type MatchingResultsViewProps,
  type SearchPeopleFn,
} from './matching-results-lab-types'

const CHANNEL_CHIP_LABELS: Record<MatchedChannel, string> = {
  email: 'Email',
  phone: 'Phone',
  ndz: 'NDZ',
}

function isMatchedChannel(value: string | null | undefined): value is MatchedChannel {
  return value === 'email' || value === 'phone' || value === 'ndz'
}

/** Allowlisted email/phone/ndz only — never hashes or matched_via hex. */
function matchChannelChips(
  detailChannels: MatchedChannel[] | undefined,
  matchedVia: string | null | undefined,
): MatchedChannel[] {
  const seen = new Set<MatchedChannel>()
  for (const channel of detailChannels ?? []) {
    if (isMatchedChannel(channel)) seen.add(channel)
  }
  const via = matchedVia?.trim().toLowerCase()
  if (seen.size === 0 && isMatchedChannel(via)) seen.add(via)
  return [...seen]
}

/** Option 10 column workbench — Status | People | Apply. */
export function ResultColumns({
  children,
  className,
}: {
  children: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'grid min-h-0 flex-1 gap-3 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,12rem)]',
        className,
      )}
    >
      {children}
    </div>
  )
}

export function resultViewEmpty(loading: boolean, hasItem: boolean): ReactNode {
  if (loading) {
    return (
      <p className="text-xs text-mute" role="status">
        Loading matching results…
      </p>
    )
  }
  if (!hasItem) {
    return (
      <p className="text-xs text-mute">
        Select a matching item to explore this view.
      </p>
    )
  }
  return null
}

/** True when status 3/4 would apply with no people selected. */
export function applyNeedsPeople(
  statusId: string | null | undefined,
  selectedDwids: string[] | undefined,
): boolean {
  return (statusId === '3' || statusId === '4') && (selectedDwids?.length ?? 0) === 0
}

export function ResultApplyBar({
  pending,
  disabled,
  onApply,
  label,
  statusId,
  selectedDwids,
}: {
  pending?: boolean
  disabled?: boolean
  onApply: () => void
  label?: string
  statusId?: string | null
  selectedDwids?: string[]
}) {
  const needsPeople =
    statusId !== undefined && selectedDwids !== undefined
      ? applyNeedsPeople(statusId, selectedDwids)
      : false
  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-line pt-2">
      <Button size="sm" disabled={disabled || pending || needsPeople} onClick={onApply}>
        {pending ? 'Applying…' : (label ?? 'Apply')}
      </Button>
    </div>
  )
}

export function ResultMatchMeta({
  item,
  detail,
  ownerLanguage,
}: Pick<MatchingResultsViewProps, 'item' | 'detail' | 'ownerLanguage'>) {
  const matchType = detail?.match_type ?? item?.match_type
  const count = detail?.match_count ?? item?.match_count
  const channels = matchChannelChips(
    detail?.matched_channels,
    detail?.matched_via ?? item?.matched_via,
  )
  const enrichError = detail?.matched_contacts_error?.message?.trim()
  const notLive =
    detail?.matched_contacts_status === 'not_live' ||
    detail?.result_kind === 'sheet_stub' ||
    detail?.result_kind === 'saas_stub'
  const statusLabel = notLive
    ? detail?.result_kind === 'sheet_stub'
      ? 'Sheet matching not live'
      : 'System matching not live'
    : matchTypeLabel(matchType, ownerLanguage)
  const system = matchingLabSystemDisplay(item, detail)
  const countLabel =
    !notLive && count != null
      ? `${count} ${count === 1 ? 'match' : 'matches'}`
      : null
  const metaLabel = [
    system.label,
    system.sourceLabel,
    statusLabel,
    countLabel,
    ...channels.map((channel) => CHANNEL_CHIP_LABELS[channel]),
  ]
    .filter(Boolean)
    .join(', ')
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label={metaLabel}>
      <ResultSystemLabel item={item} detail={detail} />
      <Badge variant="default" className="normal-case tracking-normal">
        {statusLabel}
      </Badge>
      {!notLive
        ? channels.map((channel) => (
            <Badge key={channel} variant="ok" className="normal-case tracking-normal">
              {CHANNEL_CHIP_LABELS[channel]}
            </Badge>
          ))
        : null}
      {notLive && detail?.not_live_reason ? (
        <span className="text-[0.65rem] text-ink-soft">{detail.not_live_reason}</span>
      ) : null}
      {enrichError ? (
        <span className="text-[0.65rem] text-red-800">Contact enrichment unavailable.</span>
      ) : null}
    </div>
  )
}

function safePiiValue(value: string | null | undefined): string | null {
  const trimmed = value?.trim()
  if (!trimmed || trimmed === '—') return null
  const safe = redactHashHex(trimmed)
  return safe === '—' ? null : safe
}

/** Owner-facing System A (MDR) vs System B (Auth0). */
export function ResultSystemLabel({
  item,
  detail,
}: Pick<MatchingResultsViewProps, 'item' | 'detail'>) {
  const display = matchingLabSystemDisplay(item, detail)
  if (display.kind === 'other' && !matchingLabResolveSystemId(item, detail)) return null
  const aria = [display.label, display.sourceLabel].filter(Boolean).join(', ')
  return (
    <span className="inline-flex flex-wrap items-center gap-1" aria-label={aria}>
      <Badge
        variant={display.kind === 'b' ? 'run' : 'default'}
        className="normal-case tracking-normal"
      >
        {display.label}
      </Badge>
      {display.sourceLabel ? (
        <Badge variant="ok" className="normal-case tracking-normal">
          {display.sourceLabel}
        </Badge>
      ) : null}
    </span>
  )
}

/** Match-result PII already on MatchedPersonContact — name, email, phone, dob. */
export function ResultContactPii({
  contact,
  compact,
}: {
  contact: MatchedPersonContact
  compact?: boolean
}) {
  const pii = matchedPersonPii(contact)
  const name = safePiiValue(pii.name) ?? '—'
  const facts = [
    { label: 'Email', value: safePiiValue(pii.email) },
    { label: 'Phone', value: safePiiValue(pii.phone) },
    { label: 'DOB', value: safePiiValue(pii.dob) },
  ].filter((row): row is { label: string; value: string } => Boolean(row.value))
  if (compact) {
    return (
      <div className="min-w-0">
        <p className="truncate text-xs text-ink">{name}</p>
        {facts.length > 0 ? (
          <p className="truncate text-[0.65rem] text-ink-soft">
            {facts.map((row) => row.value).join(' · ')}
          </p>
        ) : null}
      </div>
    )
  }
  return (
    <div className="min-w-0 space-y-0.5">
      <p className="truncate text-xs font-medium text-ink">{name}</p>
      {facts.length > 0 ? (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-2 gap-y-0.5 text-[0.65rem]">
          {facts.map((row) => (
            <div key={row.label} className="contents">
              <dt className="text-mute">{row.label}</dt>
              <dd className="min-w-0 truncate text-ink-soft">{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  )
}

/** KD18 chip for gated search — Needs refresh / Action required, never Connected. */
function peopleSearchBlockedChip(gate: MatchingConnectorGate): {
  label: string
  variant: 'ok' | 'fail' | 'run' | 'wait' | 'default'
} {
  const chip = matchingConnectorGateChip(gate)
  if (chip.label === 'Connected') {
    return { label: 'Action required', variant: 'fail' }
  }
  return chip
}

export function ResultPeopleSearch({
  onSearchPeople,
  localContacts,
  excludeDwids,
  onAddPerson,
  disabled,
  item,
  detail,
  peopleSearchBlocked,
  peopleSearchPending,
}: {
  onSearchPeople?: SearchPeopleFn
  localContacts?: readonly MatchedPersonContact[]
  excludeDwids?: readonly string[]
  onAddPerson: (contact: MatchedPersonContact) => void
  disabled?: boolean
  item?: MatchingResultsViewProps['item']
  detail?: MatchingResultsViewProps['detail']
  peopleSearchBlocked?: MatchingConnectorGate | null
  peopleSearchPending?: { title: string; support: string } | null
}) {
  const inputId = useId()
  const searchRef = useRef(onSearchPeople)
  searchRef.current = onSearchPeople
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState(false)
  const [hits, setHits] = useState<MatchedPersonContact[]>([])
  const [pending, setPending] = useState(false)
  const [failed, setFailed] = useState(false)
  const system = matchingLabSystemDisplay(item ?? null, detail ?? null)
  const source = system.sourceLabel
  const directory = source ?? 'this system'
  const excluded = new Set((excludeDwids ?? []).map((dwid) => dwid.trim()).filter(Boolean))
  const blockedChip = peopleSearchBlocked ? peopleSearchBlockedChip(peopleSearchBlocked) : null
  const pendingTitle = peopleSearchPending?.title.trim()
  const pendingLabel =
    pendingTitle && pendingTitle !== 'Connected' ? pendingTitle : 'Needs connection'
  const pendingSupport = peopleSearchPending?.support.trim() || null
  const pendingCopy = !blockedChip && peopleSearchPending
    ? { title: pendingLabel, support: pendingSupport }
    : null
  const gated = Boolean(blockedChip) || Boolean(pendingCopy)
  const canSearch = !gated && (Boolean(onSearchPeople) || (localContacts?.length ?? 0) > 0)
  const searchDisabled = Boolean(disabled) || gated || !canSearch
  const searchHint = blockedChip
    ? blockedChip.label
    : pendingCopy
      ? pendingCopy.title
      : canSearch
        ? `Search ${directory}…`
        : `Search not available for ${directory}`

  useEffect(() => {
    const needle = query.trim()
    if (gated || !needle) {
      setHits([])
      setPending(false)
      setFailed(false)
      return
    }
    let cancelled = false
    const timer = window.setTimeout(() => {
      void (async () => {
        setPending(true)
        setFailed(false)
        try {
          const search = searchRef.current
          const result = search
            ? await search(needle)
            : filterMatchedPeople(localContacts ?? [], needle)
          if (cancelled) return
          setHits(result)
        } catch {
          if (cancelled) return
          setHits([])
          setFailed(true)
        } finally {
          if (!cancelled) setPending(false)
        }
      })()
    }, 200)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [query, localContacts, gated])

  const addable = hits.filter((contact) => {
    const dwid = contact.dwid?.trim()
    return !dwid || !excluded.has(dwid)
  })

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <label htmlFor={inputId} className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
          {source ? `Add from ${source}` : 'Add a person'}
        </label>
        {blockedChip ? (
          <Badge variant={blockedChip.variant} className="normal-case tracking-normal">
            {blockedChip.label}
          </Badge>
        ) : null}
        {pendingCopy ? (
          <Badge variant="wait" className="normal-case tracking-normal">
            {pendingCopy.title}
          </Badge>
        ) : null}
      </div>
      <input
        id={inputId}
        type="search"
        className={statusSelectClass()}
        value={query}
        disabled={searchDisabled}
        placeholder={searchHint}
        aria-label={
          blockedChip
            ? `People search gated — ${blockedChip.label}`
            : pendingCopy
              ? `People search unavailable — ${pendingCopy.title}`
              : canSearch
                ? `Search people in ${directory}`
                : `Search not available for ${directory}`
        }
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setOpen(true)
          setQuery(event.target.value)
        }}
      />
      {pendingCopy?.support ? (
        <p className="text-[0.65rem] text-ink-soft" role="status">
          {pendingCopy.support}
        </p>
      ) : null}
      {open && !searchDisabled && canSearch ? (
        <div className="space-y-1" role="listbox" aria-label={`People in ${directory}`}>
          {pending ? (
            <p className="text-[0.65rem] text-mute" role="status">
              Searching {directory}…
            </p>
          ) : null}
          {failed ? (
            <p className="text-[0.65rem] text-red-800">
              Could not search {directory}. Try again.
            </p>
          ) : null}
          {!pending && !failed && query.trim() && addable.length === 0 ? (
            <p className="text-[0.65rem] text-mute">No people in {directory} match that search.</p>
          ) : null}
          {!pending && !query.trim() ? (
            <p className="text-[0.65rem] text-mute">
              Type a name, email, phone, or date of birth to search {directory}.
            </p>
          ) : null}
          {addable.map((contact, index) => {
            const key = contact.dwid?.trim() || `hit-${index}`
            return (
              <button
                key={key}
                type="button"
                role="option"
                className="flex w-full items-center justify-between gap-2 rounded-md border border-line bg-paper px-2 py-1 text-left hover:bg-canvas"
                onClick={() => {
                  onAddPerson(contact)
                  setQuery('')
                  setHits([])
                  setOpen(false)
                }}
              >
                <ResultContactPii contact={contact} compact />
                <span className="shrink-0 text-[0.65rem] text-habeas-navy">Add</span>
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}

export function toggleDwid(selected: string[], dwid: string): string[] {
  return selected.includes(dwid)
    ? selected.filter((id) => id !== dwid)
    : [...selected, dwid]
}

export function statusSelectClass(compact?: boolean) {
  return cn(
    'rounded-md border border-line bg-paper text-ink outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid disabled:opacity-50',
    compact ? 'h-7 max-w-[9rem] px-2 text-[0.65rem]' : 'h-8 min-w-[10rem] px-2 text-xs',
  )
}
