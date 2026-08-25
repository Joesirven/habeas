import { useId, useState } from 'react'

import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

import {
  ResultApplyBar,
  ResultMatchMeta,
  applyNeedsPeople,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

/** Scan-first one-line summary; status radios live in a popover so the pane stays short. */
export function RadioPopoverView({
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
  const [open, setOpen] = useState(false)
  const statusName = useId()

  if (empty) return empty

  const locked = disabled || pending
  const notFound = statusId === '5'
  const statusLabel =
    statusOptions.find((option) => option.id === statusId)?.label ?? 'No status'

  function chooseStatus(next: string) {
    onStatusChange(next)
    if (next === '5') onSelectedDwidsChange([])
    setOpen(false)
  }

  return (
    <div className="space-y-2">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1 space-y-1.5 text-xs text-ink">
          <p className="font-medium text-habeas-navy">{statusLabel}</p>
          {notFound || contacts.length === 0 ? (
            <p className="text-mute">No people</p>
          ) : (
            <ul className="flex flex-wrap gap-x-2 gap-y-1" aria-label="Matched people">
              {contacts.map((contact) => {
                const included = selectedDwids.includes(contact.dwid)
                return (
                  <li key={contact.dwid}>
                    <button
                      type="button"
                      disabled={locked}
                      onClick={() => onSelectedDwidsChange(toggleDwid(selectedDwids, contact.dwid))}
                      className={cn(
                        'underline-offset-2 hover:underline',
                        included ? 'font-medium text-ink' : 'text-mute line-through',
                      )}
                    >
                      {formatMatchedContactLabel(contact)}
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
        <Popover open={open} onOpenChange={setOpen}>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={locked}
              aria-haspopup="dialog"
              aria-expanded={open}
              aria-label={`Change status, currently ${statusLabel}`}
            >
              Status
            </Button>
          </PopoverTrigger>
          <PopoverContent className="w-56 p-2" align="end">
            <fieldset disabled={locked} className="space-y-0.5">
              <legend className="px-2 pb-1 text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Status
              </legend>
              <div role="radiogroup" aria-label="Match status" className="space-y-0.5">
                {statusOptions.map((option) => {
                  const selected = statusId === option.id
                  return (
                    <label
                      key={option.id}
                      className={cn(
                        'flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs',
                        selected
                          ? 'bg-habeas-navy/10 font-medium text-habeas-navy'
                          : 'text-ink hover:bg-canvas',
                      )}
                    >
                      <input
                        type="radio"
                        name={statusName}
                        value={option.id}
                        checked={selected}
                        onChange={() => chooseStatus(option.id)}
                        className="accent-habeas-navy"
                      />
                      {option.label}
                    </label>
                  )
                })}
              </div>
            </fieldset>
          </PopoverContent>
        </Popover>
      </div>
      <ResultApplyBar
        pending={pending}
        disabled={disabled || statusId == null || applyNeedsPeople(statusId, selectedDwids)}
        onApply={onApply}
      />
    </div>
  )
}
