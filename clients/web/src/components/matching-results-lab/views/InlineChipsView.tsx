import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { cn } from '@/lib/utils'

import {
  ResultApplyBar,
  ResultMatchMeta,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

function chipClass(selected: boolean, filled: boolean) {
  return cn(
    'inline-flex max-w-full items-center truncate rounded-md border px-1.5 py-0.5 text-[0.6rem] leading-4 transition-colors',
    selected
      ? filled
        ? 'border-habeas-navy bg-habeas-navy font-medium text-white'
        : 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
      : 'border-line bg-paper text-ink-soft hover:border-habeas-navy/40 hover:text-ink',
  )
}

/** Dense chip toggles for status and people — no tables. */
export function InlineChipsView({
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
}: MatchingResultsViewProps) {
  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty

  const peopleLocked = statusId === '5'
  const busy = disabled || pending

  return (
    <div className="space-y-2">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      <div className="rounded-md border border-line bg-canvas/60 px-2 py-1.5">
        <div className="flex flex-wrap items-center gap-1" role="radiogroup" aria-label="Status">
          <span className="mr-0.5 text-[0.55rem] font-medium uppercase tracking-wide text-mute">
            Status
          </span>
          {statusOptions.map((option) => {
            const selected = statusId === option.id
            return (
              <button
                key={option.id}
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={busy}
                onClick={() => onStatusChange(option.id)}
                className={chipClass(selected, true)}
              >
                {option.label}
              </button>
            )
          })}
        </div>
        <div
          className="mt-1 flex flex-wrap items-center gap-1 border-t border-line/80 pt-1"
          role="group"
          aria-label="People"
        >
          <span className="mr-0.5 text-[0.55rem] font-medium uppercase tracking-wide text-mute">
            People
          </span>
          {peopleLocked ? (
            <span className="text-[0.6rem] text-mute">Cleared for not found.</span>
          ) : contacts.length === 0 ? (
            <span className="text-[0.6rem] text-mute">None matched.</span>
          ) : (
            contacts.map((contact) => {
              const selected = selectedDwids.includes(contact.dwid)
              return (
                <button
                  key={contact.dwid}
                  type="button"
                  disabled={busy}
                  aria-pressed={selected}
                  onClick={() => onSelectedDwidsChange(toggleDwid(selectedDwids, contact.dwid))}
                  className={chipClass(selected, false)}
                >
                  {formatMatchedContactLabel(contact)}
                </button>
              )
            })
          )}
        </div>
      </div>
      <ResultApplyBar
        pending={pending}
        disabled={disabled || statusId == null}
        statusId={statusId}
        selectedDwids={selectedDwids}
        onApply={onApply}
      />
    </div>
  )
}
