import { useEffect, useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'

import type { MatchingResultsViewProps } from '@/components/matching-results-lab/matching-results-lab-types'
import {
  applyNeedsPeople,
  ResultContactPii,
  ResultPeopleSearch,
  ResultSystemLabel,
  resultViewEmpty,
} from '@/components/matching-results-lab/ResultViewChrome'
import { matchingDetailIsNotLive, redactHashHex, safeMatchedContacts } from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  suggestedDropResponseStatus,
  type MatchedPersonContact,
  type MatchingResultDetail,
  type NeedsAttentionItem,
} from '@/lib/api'
import {
  isDataCatalogVertical,
  isMatchingGateBlockedDisplayStatus,
  matchingGateFromAttempts,
  ownerConnectorsSearch,
} from '@/lib/connection-display'
import { inboxIntakeSourceLabel } from '@/lib/inbox-batch-status'
import { catalogSystemDisplayLabel } from '@/lib/legalJourneyLabels'
import { isOwnerWizardHiddenSystem } from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

/** Product/consumer — hero person for 1:1; carousel/stack for multi; large type, few chrome bits. */
export const OWNER_MATCHING_REVIEW_V08_PHILOSOPHY =
  'Hero person for 1:1; carousel/stack for multi; large type, few chrome bits.'

const STATUS_DELETE = '3'
const STATUS_OPT_IN = '4'
const STATUS_NOT_A_MATCH = '5'

function hidesCassandra(value: string | null | undefined): boolean {
  const text = value?.trim() ?? ''
  if (!text) return true
  if (isOwnerWizardHiddenSystem(text) || isDataCatalogVertical(text)) return true
  return /cassandra/i.test(text)
}

function safeSupportText(value: string | null | undefined): string | null {
  const text = value?.trim()
  if (!text || hidesCassandra(text)) return null
  return text
}

function visibleSystemLabel(
  item: NeedsAttentionItem | null | undefined,
  detail: MatchingResultDetail | null | undefined,
): string | null {
  const systemId = detail?.system ?? item?.system ?? item?.system_id
  if (hidesCassandra(systemId)) {
    const labeled = catalogSystemDisplayLabel(systemId, {
      vertical: detail?.vertical ?? item?.vertical,
      systemLabel: detail?.system_label ?? item?.system_label,
    })
    return labeled && !hidesCassandra(labeled) ? labeled : null
  }
  const labeled = catalogSystemDisplayLabel(systemId, {
    vertical: detail?.vertical ?? item?.vertical,
    systemLabel: detail?.system_label ?? item?.system_label,
  })
  if (labeled && !hidesCassandra(labeled)) return labeled
  const fallback = detail?.system_label ?? item?.system_label
  return fallback && !hidesCassandra(fallback) ? fallback : null
}

function connectorsVerticalId(
  item: NeedsAttentionItem | null | undefined,
  detail: MatchingResultDetail | null | undefined,
): string | null {
  const vertical = detail?.vertical ?? item?.vertical
  if (!vertical?.trim() || hidesCassandra(vertical)) return null
  return vertical.trim()
}

type HeroGate = { title: 'Needs refresh' | 'Needs connection'; support: string }

/** Connect / refresh hard-gate — owner language only; never a channel chip. */
function heroMatchingGate(detail: MatchingResultDetail | null): HeroGate | null {
  const gate = matchingGateFromAttempts(detail?.attempts)
  if (gate?.blocked) {
    const refresh =
      gate.displayStatus === 'needs_refresh' || gate.gateCode === 'upload_stale'
    return {
      title: refresh ? 'Needs refresh' : 'Needs connection',
      support: refresh
        ? 'Upload data is stale. Matching stays gated until this system has a fresh file.'
        : 'This system is not ready. Matching stays gated until it is connected.',
    }
  }
  if (matchingDetailIsNotLive(detail)) {
    const reason = safeSupportText(detail?.not_live_reason)
    const refresh = /stale|refresh|reupload|upload/i.test(reason ?? '')
    return {
      title: refresh ? 'Needs refresh' : 'Needs connection',
      support: reason ?? 'Connect or refresh this system before matching.',
    }
  }
  const errorCode = detail?.matched_contacts_error?.code?.trim().toLowerCase()
  if (errorCode === 'gate_blocked' || isMatchingGateBlockedDisplayStatus(errorCode)) {
    const refresh = errorCode === 'needs_refresh'
    return {
      title: refresh ? 'Needs refresh' : 'Needs connection',
      support:
        safeSupportText(detail?.matched_contacts_error?.message) ??
        'Matching is blocked until this system is connected or refreshed.',
    }
  }
  return null
}

function personInitials(contact: MatchedPersonContact): string {
  const first = contact.first_initial?.trim() || ''
  const last = contact.last_initial?.trim() || contact.last_name?.trim()?.slice(0, 1) || ''
  const letters = `${first}${last}`.toUpperCase()
  return letters || '·'
}

function personDisplayName(contact: MatchedPersonContact): string {
  const lastName = contact.last_name?.trim()
  const first = contact.first_initial?.trim()
  if (lastName && first) return `${first} ${lastName}`
  if (lastName) return lastName
  return personInitials(contact)
}

function formatDob(dob: string | null | undefined): string | null {
  const raw = dob?.trim()
  if (!raw) return null
  const match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!match) return raw
  const date = new Date(`${match[1]}-${match[2]}-${match[3]}T00:00:00`)
  if (Number.isNaN(date.getTime())) return raw
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function firstPhone(contact: MatchedPersonContact): string | null {
  for (const row of contact.phones ?? []) {
    const number = row.number?.trim()
    if (!number) continue
    const safe = redactHashHex(number)
    if (safe && safe !== '—') return safe
  }
  return null
}

function safeEmail(contact: MatchedPersonContact): string | null {
  const email = contact.email?.trim()
  if (!email) return null
  const safe = redactHashHex(email)
  return safe === '—' ? null : safe
}

function ndzLine(contact: MatchedPersonContact): string | null {
  const state = contact.state?.trim() || null
  const dob = formatDob(contact.dob)
  const parts = [state, dob].filter(Boolean)
  return parts.length > 0 ? parts.join(' · ') : null
}

/** One person, one card — merge duplicate DWID rows from email / phone / NDZ hits. */
function unifyPeople(contacts: MatchedPersonContact[]): MatchedPersonContact[] {
  const people: MatchedPersonContact[] = []
  const indexByDwid = new Map<string, number>()
  for (const contact of contacts) {
    const dwid = contact.dwid?.trim()
    if (dwid && indexByDwid.has(dwid)) {
      const at = indexByDwid.get(dwid)!
      people[at] = mergePerson(people[at]!, contact)
      continue
    }
    const next: MatchedPersonContact = {
      ...contact,
      phones: [...(contact.phones ?? [])],
    }
    if (dwid) indexByDwid.set(dwid, people.length)
    people.push(next)
  }
  return people
}

function mergePerson(left: MatchedPersonContact, right: MatchedPersonContact): MatchedPersonContact {
  const phones = [...(left.phones ?? [])]
  for (const phone of right.phones ?? []) {
    const number = phone.number?.trim()
    if (!number) continue
    if (phones.some((row) => row.number?.trim() === number)) continue
    phones.push(phone)
  }
  return {
    ...left,
    first_initial: left.first_initial || right.first_initial,
    last_initial: left.last_initial || right.last_initial,
    last_name: left.last_name || right.last_name,
    dob: left.dob || right.dob,
    state: left.state || right.state,
    email: left.email || right.email,
    phones,
  }
}

type PersonSurface = { kind: 'email' | 'phone' | 'ndz'; value: string }

const SURFACE_LABEL: Record<PersonSurface['kind'], string> = {
  email: 'email',
  phone: 'phone',
  ndz: 'NDZ',
}

/** Identifier surfaces on this person — lines, not match-count chips. */
function personSurfaces(contact: MatchedPersonContact): PersonSurface[] {
  const surfaces: PersonSurface[] = []
  const email = safeEmail(contact)
  if (email) surfaces.push({ kind: 'email', value: email })
  const phone = firstPhone(contact)
  if (phone) surfaces.push({ kind: 'phone', value: phone })
  const ndz = ndzLine(contact)
  if (ndz) surfaces.push({ kind: 'ndz', value: ndz })
  return surfaces
}

function shortRequestId(requestId: string | undefined): string | null {
  const id = requestId?.trim()
  if (!id) return null
  return id.length > 8 ? `${id.slice(0, 8)}…` : id
}

function formatReceived(item: MatchingResultsViewProps['item']): string | null {
  const raw = item?.requested_at?.trim() || item?.received_at?.trim()
  if (!raw) return null
  const date = new Date(raw)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function optionLabel(
  statusOptions: MatchingResultsViewProps['statusOptions'],
  id: string,
  fallback: string,
): string {
  return statusOptions.find((row) => row.id === id)?.label ?? fallback
}

function RequestFactsLine({
  item,
  detail,
}: Pick<MatchingResultsViewProps, 'item' | 'detail'>) {
  const source = inboxIntakeSourceLabel(item?.intake_source ?? 'drop')
  const received = formatReceived(item)
  const requestId = shortRequestId(item?.request_id)
  const system = visibleSystemLabel(item, detail)
  const parts = [source, system, received ? `Received ${received}` : null, requestId].filter(Boolean)
  if (parts.length === 0) return null
  return (
    <div className="flex flex-col items-center gap-1.5">
      <ResultSystemLabel item={item} detail={detail} />
      <p className="text-center text-xs text-mute">{parts.join(' · ')}</p>
    </div>
  )
}

function HeroAvatar({ contact, size }: { contact: MatchedPersonContact; size: 'hero' | 'card' }) {
  return (
    <div
      aria-hidden
      className={cn(
        'flex shrink-0 items-center justify-center rounded-md bg-habeas-navy font-semibold text-white',
        size === 'hero' ? 'size-24 text-3xl' : 'size-16 text-xl',
      )}
    >
      {personInitials(contact)}
    </div>
  )
}

function PersonFacts({ contact, large }: { contact: MatchedPersonContact; large: boolean }) {
  const surfaces = personSurfaces(contact)
  const ndz = surfaces.find((surface) => surface.kind === 'ndz')
  return (
    <div className="min-w-0 text-center">
      <p className={cn('truncate font-semibold text-ink', large ? 'text-3xl leading-tight' : 'text-xl')}>
        {personDisplayName(contact)}
      </p>
      <div className={cn('mt-2', large ? 'mx-auto max-w-xs text-left' : 'text-left')}>
        <ResultContactPii contact={contact} compact={!large} />
      </div>
      {ndz ? (
        <p className={cn('mt-1 truncate text-ink-soft', large ? 'text-base' : 'text-sm')}>
          <span className="text-mute">{SURFACE_LABEL.ndz} </span>
          {ndz.value}
        </p>
      ) : null}
    </div>
  )
}

function DispositionSelectors({
  value,
  emphasize,
  locked,
  onChange,
}: {
  value: typeof STATUS_DELETE | typeof STATUS_OPT_IN
  emphasize: typeof STATUS_DELETE | typeof STATUS_OPT_IN
  locked: boolean
  onChange: (statusId: typeof STATUS_DELETE | typeof STATUS_OPT_IN) => void
}) {
  return (
    <div
      className="flex w-full gap-2"
      role="radiogroup"
      aria-label="Disposition for this person"
    >
      {(
        [
          { id: STATUS_DELETE, label: 'Delete' },
          { id: STATUS_OPT_IN, label: 'Opt-in' },
        ] as const
      ).map((option) => {
        const selected = value === option.id
        const suggested = emphasize === option.id
        return (
          <button
            key={option.id}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={locked}
            onClick={() => onChange(option.id)}
            className={cn(
              'flex-1 rounded-md border px-3 py-2 text-sm font-medium',
              selected
                ? 'border-habeas-navy bg-habeas-navy/10 text-habeas-navy'
                : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
              !selected && suggested && 'ring-1 ring-habeas-navy/25',
            )}
          >
            {option.label}
            {suggested && !selected ? (
              <span className="mt-0.5 block text-[0.65rem] font-normal text-mute">suggested</span>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

function HeroPersonCard({
  contact,
  disposition,
  emphasize,
  locked,
  onDispositionChange,
  onRemove,
}: {
  contact: MatchedPersonContact
  disposition: typeof STATUS_DELETE | typeof STATUS_OPT_IN
  emphasize: typeof STATUS_DELETE | typeof STATUS_OPT_IN
  locked: boolean
  onDispositionChange: (statusId: typeof STATUS_DELETE | typeof STATUS_OPT_IN) => void
  onRemove: () => void
}) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-md border border-line bg-paper px-5 py-8">
      <HeroAvatar contact={contact} size="hero" />
      <PersonFacts contact={contact} large />
      <DispositionSelectors
        value={disposition}
        emphasize={emphasize}
        locked={locked}
        onChange={onDispositionChange}
      />
      <button
        type="button"
        disabled={locked}
        onClick={onRemove}
        className="text-sm font-medium text-mute underline-offset-2 hover:underline"
      >
        Remove this person
      </button>
    </div>
  )
}

function PersonCarousel({
  contacts,
  focusIndex,
  onFocusIndexChange,
  disposition,
  emphasize,
  onDispositionChange,
  onRemove,
  locked,
}: {
  contacts: MatchedPersonContact[]
  focusIndex: number
  onFocusIndexChange: (index: number) => void
  disposition: typeof STATUS_DELETE | typeof STATUS_OPT_IN
  emphasize: typeof STATUS_DELETE | typeof STATUS_OPT_IN
  onDispositionChange: (statusId: typeof STATUS_DELETE | typeof STATUS_OPT_IN) => void
  onRemove: (dwid: string) => void
  locked: boolean
}) {
  const focused = contacts[focusIndex]
  if (!focused) return null

  return (
    <div className="space-y-3">
      <div
        className="relative mx-auto h-[30rem] w-full max-w-sm"
        role="group"
        aria-label="Matched people"
        aria-roledescription="carousel"
      >
        {contacts.map((contact, index) => {
          const delta = index - focusIndex
          if (Math.abs(delta) > 2) return null
          const active = delta === 0
          return (
            <article
              key={contact.dwid}
              className="absolute inset-x-0 top-4 transition-transform duration-200"
              style={{
                transform: `translateY(${delta * 12}px) scale(${1 - Math.abs(delta) * 0.05})`,
                zIndex: 10 - Math.abs(delta),
                opacity: active ? 1 : 0.28,
              }}
            >
              {active ? (
                <HeroPersonCard
                  contact={contact}
                  disposition={disposition}
                  emphasize={emphasize}
                  locked={locked}
                  onDispositionChange={onDispositionChange}
                  onRemove={() => onRemove(contact.dwid)}
                />
              ) : (
                <button
                  type="button"
                  disabled={locked}
                  onClick={() => onFocusIndexChange(index)}
                  className="flex w-full items-center justify-center rounded-md border border-line bg-paper py-6"
                  aria-label={`Show ${personDisplayName(contact)}`}
                >
                  <HeroAvatar contact={contact} size="card" />
                </button>
              )}
            </article>
          )
        })}
      </div>
      <div className="flex items-center justify-center gap-4 text-sm">
        <Button
          type="button"
          variant="ghost"
          size="lg"
          disabled={locked || focusIndex === 0}
          onClick={() => onFocusIndexChange(focusIndex - 1)}
          aria-label="Previous person"
        >
          Previous
        </Button>
        <p className="min-w-[4.5rem] text-center tabular-nums text-mute">
          {focusIndex + 1} of {contacts.length}
        </p>
        <Button
          type="button"
          variant="ghost"
          size="lg"
          disabled={locked || focusIndex >= contacts.length - 1}
          onClick={() => onFocusIndexChange(focusIndex + 1)}
          aria-label="Next person"
        >
          Next
        </Button>
      </div>
    </div>
  )
}

function EmptyHero({ title, support }: { title: string; support: string }) {
  return (
    <div className="flex flex-col items-center gap-2 py-10 text-center">
      <p className="text-3xl font-semibold text-ink">{title}</p>
      <p className="max-w-sm text-base text-mute">{support}</p>
    </div>
  )
}

function GateHero({
  gate,
  verticalId,
}: {
  gate: HeroGate
  verticalId: string | null
}) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-md border border-line bg-paper px-5 py-10 text-center">
      <Badge variant="fail" className="normal-case tracking-normal">
        {gate.title}
      </Badge>
      <p className="text-3xl font-semibold text-ink">{gate.title}</p>
      <p className="max-w-sm text-base text-mute">{gate.support}</p>
      <Button asChild size="lg" className="h-12 w-full max-w-xs text-base">
        <Link to="/owner/connectors" search={ownerConnectorsSearch(verticalId)}>
          Open connectors
        </Link>
      </Button>
    </div>
  )
}

function AddPersonCard({
  locked,
  onAdd,
  onSearchPeople,
  localContacts,
  excludeDwids,
  item,
  detail,
}: {
  locked: boolean
  onAdd: (contact: MatchedPersonContact) => void
  onSearchPeople?: MatchingResultsViewProps['onSearchPeople']
  localContacts: MatchedPersonContact[]
  excludeDwids: string[]
  item: MatchingResultsViewProps['item']
  detail: MatchingResultsViewProps['detail']
}) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-md border border-dashed border-line bg-paper px-5 py-6">
      <p className="text-sm font-medium text-ink">Add a person</p>
      <div className="w-full">
        <ResultPeopleSearch
          onSearchPeople={onSearchPeople}
          localContacts={localContacts}
          excludeDwids={excludeDwids}
          onAddPerson={onAdd}
          disabled={locked}
          item={item}
          detail={detail}
        />
      </div>
    </div>
  )
}

/**
 * Owner matching review — product/consumer hero.
 * 1:1 is one large person; multi is a stacked carousel. Request facts stay one line.
 * Email / phone / NDZ are surfaces on that person — never extra heroes or attempts.
 */
export function OwnerMatchingReviewV08({
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
}: MatchingResultsViewProps) {
  const [extraContacts, setExtraContacts] = useState<MatchedPersonContact[]>([])
  const people = useMemo(
    () => unifyPeople(safeMatchedContacts([...contacts, ...extraContacts])),
    [contacts, extraContacts],
  )
  const [focusIndex, setFocusIndex] = useState(0)
  const [pendingFocusDwid, setPendingFocusDwid] = useState<string | null>(null)
  const contactKey = people.map((row) => row.dwid).join('|')

  useEffect(() => {
    setFocusIndex(0)
    setPendingFocusDwid(null)
    if (people.length > 0 && selectedDwids.length === 0 && statusId !== STATUS_NOT_A_MATCH) {
      onSelectedDwidsChange(people.map((row) => row.dwid).filter(Boolean))
    }
    if (people.length > 0 && (!statusId || statusId === STATUS_NOT_A_MATCH)) {
      const suggested = String(
        suggestedDropResponseStatus(
          detail?.match_type ?? item?.match_type,
          people.length,
        ),
      )
      if (suggested === STATUS_DELETE || suggested === STATUS_OPT_IN) {
        onStatusChange(suggested)
      }
    }
  }, [contactKey])

  const includedPeople = useMemo(() => {
    if (selectedDwids.length === 0) return []
    const selected = new Set(selectedDwids)
    return people.filter((row) => selected.has(row.dwid))
  }, [people, selectedDwids])

  useEffect(() => {
    if (!pendingFocusDwid) return
    const index = includedPeople.findIndex((row) => row.dwid === pendingFocusDwid)
    if (index >= 0) {
      setFocusIndex(index)
      setPendingFocusDwid(null)
    }
  }, [pendingFocusDwid, includedPeople])

  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty

  const locked = Boolean(disabled || pending)
  const gate = heroMatchingGate(detail)
  const suggestedCode = suggestedDropResponseStatus(
    detail?.match_type ?? item?.match_type,
    includedPeople.length || people.length,
  )
  const recommended = detail?.recommended_response_status ?? item?.recommended_response_status
  const emphasize: typeof STATUS_DELETE | typeof STATUS_OPT_IN =
    recommended === 4 || (recommended == null && suggestedCode === 4)
      ? STATUS_OPT_IN
      : STATUS_DELETE
  const disposition: typeof STATUS_DELETE | typeof STATUS_OPT_IN =
    statusId === STATUS_OPT_IN ? STATUS_OPT_IN : STATUS_DELETE
  const isMulti = includedPeople.length > 1
  const safeFocus = Math.min(focusIndex, Math.max(includedPeople.length - 1, 0))
  const declineLabel = optionLabel(
    statusOptions,
    STATUS_NOT_A_MATCH,
    ownerLanguage ? 'Not a match' : 'Not found',
  )
  const applyLabel = disposition === STATUS_OPT_IN ? 'Apply Opt-in' : 'Apply Delete'
  const confirmDwids = includedPeople.map((row) => row.dwid).filter(Boolean)
  const canConfirm = confirmDwids.length > 0 && !applyNeedsPeople(disposition, confirmDwids)

  function applyDecision(nextStatusId: string, dwids: string[]) {
    onSelectedDwidsChange(dwids)
    onApply({ statusId: nextStatusId, selectedDwids: dwids })
  }

  function setDisposition(next: typeof STATUS_DELETE | typeof STATUS_OPT_IN) {
    onStatusChange(next)
  }

  function removePerson(dwid: string) {
    const next = selectedDwids.filter((id) => id !== dwid)
    onSelectedDwidsChange(next)
    const nextIncluded = includedPeople.filter((row) => row.dwid !== dwid)
    setFocusIndex((current) => Math.min(current, Math.max(nextIncluded.length - 1, 0)))
  }

  function addPerson(contact: MatchedPersonContact) {
    const dwid = contact.dwid?.trim()
    if (!dwid) return
    if (!contacts.some((row) => row.dwid?.trim() === dwid)) {
      setExtraContacts((current) =>
        current.some((row) => row.dwid?.trim() === dwid) ? current : [...current, contact],
      )
    }
    if (!selectedDwids.includes(dwid)) {
      onSelectedDwidsChange([...selectedDwids, dwid])
    }
    setPendingFocusDwid(dwid)
  }

  return (
    <div className="mx-auto flex max-w-md flex-col gap-6 px-2 py-4">
      <RequestFactsLine item={item} detail={detail} />

      {gate ? (
        <GateHero gate={gate} verticalId={connectorsVerticalId(item, detail)} />
      ) : includedPeople.length === 0 ? (
        <div className="space-y-3">
          <EmptyHero
            title={people.length === 0 ? (ownerLanguage ? 'No one matched' : 'Not found') : 'No one selected'}
            support={
              people.length === 0
                ? 'Confirm that this request is not a match for this system, or add a person.'
                : 'Remove is undone by searching this system’s matches.'
            }
          />
          <AddPersonCard
            locked={locked}
            onAdd={addPerson}
            onSearchPeople={onSearchPeople}
            localContacts={people}
            excludeDwids={selectedDwids}
            item={item}
            detail={detail}
          />
        </div>
      ) : includedPeople.length === 1 && !isMulti ? (
        <div className="space-y-3">
          <p className="text-center text-lg text-mute">Is this the person?</p>
          <HeroPersonCard
            contact={includedPeople[0]!}
            disposition={disposition}
            emphasize={emphasize}
            locked={locked}
            onDispositionChange={setDisposition}
            onRemove={() => removePerson(includedPeople[0]!.dwid)}
          />
          <AddPersonCard
            locked={locked}
            onAdd={addPerson}
            onSearchPeople={onSearchPeople}
            localContacts={people}
            excludeDwids={selectedDwids}
            item={item}
            detail={detail}
          />
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-center text-lg text-mute">
            {includedPeople.length} people — include who belongs
          </p>
          <PersonCarousel
            contacts={includedPeople}
            focusIndex={safeFocus}
            onFocusIndexChange={setFocusIndex}
            disposition={disposition}
            emphasize={emphasize}
            onDispositionChange={setDisposition}
            onRemove={removePerson}
            locked={locked}
          />
          <AddPersonCard
            locked={locked}
            onAdd={addPerson}
            onSearchPeople={onSearchPeople}
            localContacts={people}
            excludeDwids={selectedDwids}
            item={item}
            detail={detail}
          />
        </div>
      )}

      {gate ? null : (
        <div className="flex flex-col gap-2">
          {includedPeople.length > 0 ? (
            <Button
              type="button"
              size="lg"
              className="h-12 w-full text-base"
              disabled={locked || !canConfirm}
              onClick={() => applyDecision(disposition, confirmDwids)}
            >
              {pending ? 'Saving…' : applyLabel}
            </Button>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="lg"
            className="h-12 w-full text-base"
            disabled={locked}
            onClick={() => applyDecision(STATUS_NOT_A_MATCH, [])}
          >
            {pending ? 'Saving…' : declineLabel}
          </Button>
        </div>
      )}
    </div>
  )
}
