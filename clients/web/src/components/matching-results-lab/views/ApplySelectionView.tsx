import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import {
  ResultMatchMeta,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

function columnHeaderClass() {
  return 'text-[0.65rem] font-medium uppercase tracking-wide text-mute'
}

/** Full-page columns: disposition, DWID checklist, apply to selected queue rows. */
export function ApplySelectionView({
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
  selectedCount,
  onApplySelection,
}: MatchingResultsViewProps) {
  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty

  const statusLabel = statusOptions.find((option) => option.id === statusId)?.label ?? null
  const peopleCount = statusId === '5' ? 0 : selectedDwids.length
  const applyDisabled = Boolean(disabled || pending || selectedCount === 0 || statusId == null)

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="shrink-0 space-y-2">
        <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
        <p className="text-[0.65rem] text-mute">
          Check rows in the queue, set status and people in these columns, then apply to the
          selection.
        </p>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-3">
        <section
          className="min-h-0 min-w-0 space-y-2 overflow-y-auto border-b border-line pb-3 md:border-b-0 md:border-r md:pb-0 md:pr-3"
          aria-labelledby="apply-selection-status"
        >
          <h3 id="apply-selection-status" className={columnHeaderClass()}>
            Status
          </h3>
          <div role="radiogroup" aria-label="Disposition" className="space-y-1">
            {statusOptions.map((option) => {
              const selected = statusId === option.id
              return (
                <button
                  key={option.id}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={disabled || pending}
                  onClick={() => onStatusChange(option.id)}
                  className={cn(
                    'flex w-full rounded-md border px-2.5 py-1.5 text-left text-xs transition-colors',
                    selected
                      ? 'border-habeas-navy bg-habeas-navy/10 font-medium text-habeas-navy'
                      : 'border-line bg-paper text-ink hover:border-habeas-navy/35',
                    (disabled || pending) && 'opacity-50',
                  )}
                >
                  {option.label}
                </button>
              )
            })}
          </div>
        </section>

        <section
          className="min-h-0 min-w-0 space-y-2 overflow-y-auto border-b border-line py-3 md:border-b-0 md:border-r md:px-3 md:py-0"
          aria-labelledby="apply-selection-people"
        >
          <div className="flex items-baseline justify-between gap-2">
            <h3 id="apply-selection-people" className={columnHeaderClass()}>
              People
            </h3>
            {statusId !== '5' && contacts.length > 0 ? (
              <span className="tabular-nums text-[0.65rem] text-mute">
                {selectedDwids.length}/{contacts.length}
              </span>
            ) : null}
          </div>
          {statusId === '5' ? (
            <p className="text-xs text-mute">Not found clears selected people on apply.</p>
          ) : contacts.length === 0 ? (
            <p className="text-xs text-mute">No matched people on the focused row.</p>
          ) : (
            <ul className="space-y-1 rounded-md border border-line px-2 py-1.5">
              {contacts.map((contact) => {
                const checked = selectedDwids.includes(contact.dwid)
                return (
                  <li key={contact.dwid}>
                    <label
                      className={cn(
                        'flex cursor-pointer items-center gap-2 text-xs',
                        (disabled || pending) && 'opacity-50',
                      )}
                    >
                      <input
                        type="checkbox"
                        className="accent-habeas-navy"
                        checked={checked}
                        disabled={disabled || pending}
                        onChange={() =>
                          onSelectedDwidsChange(toggleDwid(selectedDwids, contact.dwid))
                        }
                      />
                      {formatMatchedContactLabel(contact)}
                    </label>
                  </li>
                )
              })}
            </ul>
          )}
        </section>

        <section
          className="min-h-0 min-w-0 space-y-2 overflow-y-auto pt-3 md:pl-3 md:pt-0"
          aria-labelledby="apply-selection-apply"
        >
          <h3 id="apply-selection-apply" className={columnHeaderClass()}>
            Apply
          </h3>
          <dl className="space-y-1.5 text-xs">
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-mute">Queue selected</dt>
              <dd className="tabular-nums text-ink">{selectedCount}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-mute">People</dt>
              <dd className="tabular-nums text-ink">{peopleCount}</dd>
            </div>
            <div className="flex items-baseline justify-between gap-2">
              <dt className="text-mute">Disposition</dt>
              <dd className="truncate text-ink">{statusLabel ?? '—'}</dd>
            </div>
          </dl>
          <Button
            type="button"
            size="sm"
            disabled={applyDisabled}
            onClick={onApplySelection}
          >
            {pending ? 'Applying…' : `Apply ${selectedCount} selected`}
          </Button>
          {selectedCount === 0 ? (
            <p className="text-[0.65rem] text-mute">Select queue rows to apply this draft.</p>
          ) : statusId == null ? (
            <p className="text-[0.65rem] text-mute">Choose a status before applying.</p>
          ) : null}
        </section>
      </div>
    </div>
  )
}
