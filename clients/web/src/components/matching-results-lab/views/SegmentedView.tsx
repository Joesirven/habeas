import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { cn } from '@/lib/utils'

import {
  ResultApplyBar,
  ResultMatchMeta,
  applyNeedsPeople,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

/** Decision cards: large status choices; people list sits under the chosen card. */
export function SegmentedView({
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

  const locked = disabled || pending

  function chooseStatus(next: string) {
    onStatusChange(next)
    if (next === '5') onSelectedDwidsChange([])
  }

  return (
    <div className="space-y-2">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      <div role="radiogroup" aria-label="Match status" className="space-y-2">
        {statusOptions.map((option) => {
          const selected = statusId === option.id
          const notFound = option.id === '5'
          return (
            <div
              key={option.id}
              className={cn(
                'rounded-md border',
                selected
                  ? 'border-habeas-navy bg-habeas-navy/10'
                  : 'border-line bg-paper',
                locked && 'opacity-50',
              )}
            >
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                disabled={locked}
                onClick={() => chooseStatus(option.id)}
                className="flex w-full items-start gap-3 px-3 py-3 text-left"
              >
                <span
                  aria-hidden
                  className={cn(
                    'mt-0.5 inline-block size-3.5 shrink-0 rounded-full border',
                    selected
                      ? 'border-habeas-navy bg-habeas-navy'
                      : 'border-line bg-paper',
                  )}
                />
                <span className="min-w-0 flex-1">
                  <span
                    className={cn(
                      'block text-sm font-medium',
                      selected ? 'text-habeas-navy' : 'text-ink',
                    )}
                  >
                    {option.label}
                  </span>
                  <span className="mt-0.5 block text-[0.65rem] text-mute">
                    {selected
                      ? notFound
                        ? 'No people applied to this result.'
                        : contacts.length === 0
                          ? 'No matched people for this result.'
                          : `${selectedDwids.length} of ${contacts.length} included`
                      : 'Choose this card to assign people.'}
                  </span>
                </span>
              </button>
              {selected && !notFound && contacts.length > 0 ? (
                <ul className="border-t border-habeas-navy/20 px-3 py-1.5" aria-label="Matched people">
                  {contacts.map((contact) => {
                    const included = selectedDwids.includes(contact.dwid)
                    return (
                      <li key={contact.dwid}>
                        <button
                          type="button"
                          disabled={locked}
                          onClick={() =>
                            onSelectedDwidsChange(toggleDwid(selectedDwids, contact.dwid))
                          }
                          className="flex w-full items-center justify-between gap-2 py-1.5 text-left text-xs"
                        >
                          <span className="min-w-0 truncate text-ink">
                            {formatMatchedContactLabel(contact)}
                          </span>
                          <span
                            className={cn(
                              'shrink-0 text-[0.65rem]',
                              included ? 'font-medium text-habeas-navy' : 'text-mute',
                            )}
                          >
                            {included ? 'Included' : 'Skip'}
                          </span>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              ) : null}
            </div>
          )
        })}
      </div>
      <ResultApplyBar
        pending={pending}
        disabled={disabled || statusId == null || applyNeedsPeople(statusId, selectedDwids)}
        onApply={onApply}
      />
    </div>
  )
}
