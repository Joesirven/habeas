import { useState } from 'react'

import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import {
  ResultMatchMeta,
  applyNeedsPeople,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import {
  matchingLabItemKey,
  type MatchingResultsViewProps,
} from '../matching-results-lab-types'

type StepId = 'disposition' | 'people' | 'review'

const STEPS: { id: StepId; n: number; label: string }[] = [
  { id: 'disposition', n: 1, label: 'Disposition' },
  { id: 'people', n: 2, label: 'People' },
  { id: 'review', n: 3, label: 'Review' },
]

function skipPeopleStep(statusId: string | null, contactCount: number): boolean {
  return statusId === '5' || contactCount === 0
}

/** Linear wizard — disposition, then people, then review/apply. */
export function StepperConfirmView(props: MatchingResultsViewProps) {
  const empty = resultViewEmpty(props.loading, Boolean(props.item))
  if (empty) return empty
  return <StepperConfirmDraft key={matchingLabItemKey(props.item!)} {...props} />
}

function StepperConfirmDraft({
  item,
  detail,
  contacts,
  ownerLanguage,
  statusOptions,
  onStatusChange,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
}: MatchingResultsViewProps) {
  const [step, setStep] = useState<StepId>('disposition')
  const [draftStatus, setDraftStatus] = useState<string | null>(null)
  const [draftDwids, setDraftDwids] = useState<string[]>([])

  const skipPeople = skipPeopleStep(draftStatus, contacts.length)
  const path: StepId[] = skipPeople
    ? ['disposition', 'review']
    : ['disposition', 'people', 'review']
  const statusLabel =
    statusOptions.find((option) => option.id === draftStatus)?.label ?? null
  const peopleRequired = applyNeedsPeople(draftStatus, draftDwids)
  const canLeavePeople = !peopleRequired
  const applyBlocked = disabled || pending || draftStatus == null || peopleRequired

  function goTo(next: StepId) {
    const currentIdx = path.indexOf(step)
    const nextIdx = path.indexOf(next)
    if (nextIdx === -1 || nextIdx > currentIdx) return
    setStep(next)
  }

  function goNext() {
    if (step === 'disposition') {
      if (draftStatus == null) return
      setStep(skipPeopleStep(draftStatus, contacts.length) ? 'review' : 'people')
      return
    }
    if (step === 'people' && canLeavePeople) setStep('review')
  }

  function goBack() {
    if (step === 'review') {
      setStep(skipPeople ? 'disposition' : 'people')
      return
    }
    if (step === 'people') setStep('disposition')
  }

  function commitAndApply() {
    if (draftStatus == null || applyNeedsPeople(draftStatus, draftDwids)) return
    const nextDwids = draftStatus === '5' ? [] : draftDwids
    onStatusChange(draftStatus)
    onSelectedDwidsChange(nextDwids)
    onApply({ statusId: draftStatus, selectedDwids: nextDwids })
  }

  return (
    <div className="space-y-3">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />

      <ol className="flex flex-wrap items-center gap-1" aria-label="Wizard steps">
        {STEPS.map((entry, index) => {
          const current = step === entry.id
          const skipped = entry.id === 'people' && skipPeople
          const reachable = path.includes(entry.id) && path.indexOf(entry.id) <= path.indexOf(step)
          return (
            <li key={entry.id} className="flex items-center gap-1">
              {index > 0 ? (
                <span className="px-0.5 text-[0.6rem] text-mute" aria-hidden>
                  —
                </span>
              ) : null}
              <button
                type="button"
                disabled={disabled || pending || !reachable || skipped}
                onClick={() => goTo(entry.id)}
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[0.65rem]',
                  current
                    ? 'bg-habeas-navy/10 font-medium text-habeas-navy'
                    : skipped
                      ? 'text-mute line-through'
                      : reachable
                        ? 'text-ink-soft hover:text-ink'
                        : 'text-mute',
                )}
              >
                <span
                  className={cn(
                    'inline-flex size-4 items-center justify-center rounded-full text-[0.55rem] tabular-nums',
                    current
                      ? 'bg-habeas-navy text-white'
                      : reachable && !skipped
                        ? 'border border-habeas-navy/40 text-habeas-navy'
                        : 'border border-line text-mute',
                  )}
                >
                  {entry.n}
                </span>
                {entry.label}
              </button>
            </li>
          )
        })}
      </ol>

      {step === 'disposition' ? (
        <div className="space-y-2">
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Step 1 · Choose disposition
          </p>
          <div className="space-y-1" role="radiogroup" aria-label="Choose disposition">
            {statusOptions.map((option) => {
              const selected = draftStatus === option.id
              return (
                <button
                  key={option.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={disabled || pending}
                  onClick={() => setDraftStatus(option.id)}
                  className={cn(
                    'flex w-full items-center justify-between rounded-md border px-2.5 py-1.5 text-left text-xs',
                    selected
                      ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                      : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                  )}
                >
                  {option.label}
                  {selected ? <span className="text-[0.6rem] text-mute">selected</span> : null}
                </button>
              )
            })}
          </div>
          <Button
            type="button"
            size="sm"
            disabled={disabled || pending || draftStatus == null}
            onClick={goNext}
          >
            Next
          </Button>
        </div>
      ) : null}

      {step === 'people' ? (
        <div className="space-y-2">
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Step 2 · Choose people
          </p>
          <ul className="space-y-1 rounded-md border border-line px-2 py-1.5">
            {contacts.map((contact) => {
              const checked = draftDwids.includes(contact.dwid)
              return (
                <li key={contact.dwid}>
                  <label className="flex cursor-pointer items-center gap-2 text-xs">
                    <input
                      type="checkbox"
                      className="accent-habeas-navy"
                      checked={checked}
                      disabled={disabled || pending}
                      onChange={() => setDraftDwids(toggleDwid(draftDwids, contact.dwid))}
                    />
                    {formatMatchedContactLabel(contact)}
                  </label>
                </li>
              )
            })}
          </ul>
          {peopleRequired && draftDwids.length === 0 ? (
            <p className="text-[0.65rem] text-mute">Select at least one person to continue.</p>
          ) : null}
          <div className="flex gap-1.5">
            <Button
              type="button"
              size="sm"
              disabled={disabled || pending || !canLeavePeople}
              onClick={goNext}
            >
              Next
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={goBack}>
              Back
            </Button>
          </div>
        </div>
      ) : null}

      {step === 'review' ? (
        <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2.5">
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Step 3 · Review and apply
          </p>
          <dl className="space-y-1 text-xs text-ink">
            <div>
              <dt className="text-[0.65rem] text-mute">Disposition</dt>
              <dd className="font-medium">{statusLabel ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-[0.65rem] text-mute">People</dt>
              <dd>
                {draftStatus === '5' || draftDwids.length === 0
                  ? 'None sent'
                  : contacts
                      .filter((contact) => draftDwids.includes(contact.dwid))
                      .map((contact) => formatMatchedContactLabel(contact))
                      .join(' · ')}
              </dd>
            </div>
          </dl>
          <div className="flex gap-1.5">
            <Button
              type="button"
              size="sm"
              disabled={applyBlocked}
              onClick={commitAndApply}
            >
              {pending ? 'Applying…' : 'Confirm apply'}
            </Button>
            <Button type="button" variant="ghost" size="sm" disabled={pending} onClick={goBack}>
              Back
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
