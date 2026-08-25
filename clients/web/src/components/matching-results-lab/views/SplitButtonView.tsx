import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

import {
  applyNeedsPeople,
  ResultMatchMeta,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

/** One primary Confirm/Apply + overflow for alternate dispositions (3/4/5). */
export function SplitButtonView({
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

  const primaryStatus =
    statusOptions.find((option) => option.id === statusId) ?? statusOptions[0] ?? null
  const otherStatuses = primaryStatus
    ? statusOptions.filter((option) => option.id !== primaryStatus.id)
    : statusOptions
  const notFound = (statusId ?? primaryStatus?.id) === '5'
  const primaryBlocked = applyNeedsPeople(primaryStatus?.id, selectedDwids)

  function applyDisposition(nextStatusId: string) {
    if (applyNeedsPeople(nextStatusId, selectedDwids)) return
    const nextDwids = nextStatusId === '5' ? [] : selectedDwids
    onStatusChange(nextStatusId)
    onApply({ statusId: nextStatusId, selectedDwids: nextDwids })
  }

  const primaryLabel = pending
    ? 'Applying…'
    : primaryStatus
      ? `Confirm ${primaryStatus.label}`
      : 'Confirm'

  return (
    <div className="space-y-3">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      {contacts.length === 0 ? (
        <p className="text-xs text-mute">No matched people.</p>
      ) : (
        <>
          {notFound ? (
            <p className="text-xs text-mute">Not found clears selected people on apply.</p>
          ) : null}
          <ul className="space-y-0.5" aria-label="People to include">
            {contacts.map((contact) => {
              const selected = selectedDwids.includes(contact.dwid)
              return (
                <li key={contact.dwid}>
                  <button
                    type="button"
                    disabled={disabled || pending}
                    aria-pressed={selected}
                    onClick={() => onSelectedDwidsChange(toggleDwid(selectedDwids, contact.dwid))}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-xs',
                      selected
                        ? 'bg-habeas-navy/8 font-medium text-habeas-navy'
                        : 'text-ink-soft hover:bg-panel/70 hover:text-ink',
                    )}
                  >
                    <span
                      className={cn(
                        'flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-sm border text-[0.55rem]',
                        selected
                          ? 'border-habeas-navy bg-habeas-navy text-white'
                          : 'border-line bg-paper text-transparent',
                      )}
                      aria-hidden
                    >
                      ✓
                    </span>
                    <span className="truncate">{formatMatchedContactLabel(contact)}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </>
      )}

      <div
        className="inline-flex min-w-0 max-w-full items-stretch overflow-hidden rounded-md border border-line"
        role="group"
        aria-label="Confirm disposition"
      >
        <Button
          type="button"
          size="sm"
          disabled={disabled || pending || !primaryStatus || primaryBlocked}
          onClick={() => {
            if (primaryStatus) applyDisposition(primaryStatus.id)
          }}
          className="h-7 rounded-none border-0 px-2.5 text-[0.65rem]"
        >
          {primaryLabel}
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={disabled || pending || otherStatuses.length === 0}
              className="h-7 rounded-none border-0 border-l border-line bg-white px-1.5 text-mute hover:bg-canvas"
              aria-label="Alternate dispositions"
            >
              ▼
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="min-w-[11rem]">
            <DropdownMenuLabel>Other dispositions</DropdownMenuLabel>
            {otherStatuses.map((option) => {
              const overflowBlocked = applyNeedsPeople(option.id, selectedDwids)
              return (
                <DropdownMenuItem
                  key={option.id}
                  className="text-xs"
                  disabled={overflowBlocked}
                  onSelect={() => applyDisposition(option.id)}
                >
                  Apply {option.label}
                </DropdownMenuItem>
              )
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
