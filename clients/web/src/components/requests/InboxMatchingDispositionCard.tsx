import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

import { matchingDispositionCopy } from './RequestTriageDialog'

export const INBOX_MATCHING_DISPOSITION_HINT =
  'Confirm the match disposition, or send to legal if you need help.'

type InboxMatchingDispositionCardProps = {
  canReviewActions?: boolean
  actionPending?: boolean
  dataOwnerPersona?: boolean
  onConfirm: () => void
  onDecline: () => void
  onEscalate: () => void
  onSeeMoreDetails?: (trigger: HTMLElement) => void
  hint?: string
  /** Batch omits legal-help hint and Assign to legal (bulk assign lives on the pane). */
  variant?: 'single' | 'batch'
  className?: string
}

/** Next-step card — matching disposition (Confirm · Decline · Assign to legal · See more details). */
export function InboxMatchingDispositionCard({
  canReviewActions = false,
  actionPending = false,
  dataOwnerPersona = false,
  onConfirm,
  onDecline,
  onEscalate,
  onSeeMoreDetails,
  hint = INBOX_MATCHING_DISPOSITION_HINT,
  variant = 'single',
  className,
}: InboxMatchingDispositionCardProps) {
  const confirmLabel = dataOwnerPersona
    ? matchingDispositionCopy('data_owner').confirmLabel
    : matchingDispositionCopy('ops').confirmLabel
  const showHint = variant === 'single'
  const showEscalate = variant === 'single'

  return (
    <div
      className={cn(
        'rounded-md border border-habeas-navy/20 bg-habeas-navy/[0.03] px-3 py-2',
        className,
      )}
    >
      {showHint ? (
        <p className="text-[0.7rem] leading-snug text-ink-soft">{hint}</p>
      ) : null}
      <div
        className={cn(
          'flex flex-wrap items-center gap-2',
          showHint && 'mt-1.5',
        )}
      >
        {canReviewActions ? (
          <>
            <Button
              type="button"
              size="sm"
              disabled={actionPending}
              onClick={onConfirm}
            >
              {confirmLabel}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={actionPending}
              onClick={onDecline}
            >
              Decline
            </Button>
            {showEscalate ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={actionPending}
                onClick={onEscalate}
              >
                Assign to legal
              </Button>
            ) : null}
          </>
        ) : null}
        {onSeeMoreDetails ? (
          <button
            type="button"
            className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
            aria-label="See more details"
            onClick={(event) => onSeeMoreDetails(event.currentTarget)}
          >
            See more details
          </button>
        ) : null}
      </div>
    </div>
  )
}
