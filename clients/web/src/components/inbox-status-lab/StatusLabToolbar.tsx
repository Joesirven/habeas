import { useId } from 'react'

import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/utils'

import {
  MATCHING_RESULT_LAB_METHODS,
  OWNER_MATCHING_REVIEW_METHODS,
  type MatchingResultLabMethodId,
  type OwnerMatchingReviewMethodId,
  writeMatchingResultLabMethod,
  writeOwnerMatchingReviewMethod,
} from './status-selector-types'

/** Matching-results lab — 10-option DWID-select dropdown. Default option 9 `two-tier`. */
export function MatchingResultsMethodToolbar({
  method,
  onMethodChange,
  className,
}: {
  method: MatchingResultLabMethodId
  onMethodChange: (method: MatchingResultLabMethodId) => void
  className?: string
}) {
  const labelId = useId()
  const active = MATCHING_RESULT_LAB_METHODS.find((row) => row.id === method)
  const activeLabel = active?.label ?? method
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={cn(
        'flex shrink-0 flex-wrap items-center gap-2 border border-line bg-canvas px-2.5 py-2',
        className,
      )}
    >
      <span id={labelId} className="text-xs font-semibold text-ink">
        DWID select view
      </span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="default"
            className="h-8 min-w-[16rem] justify-between border-habeas-navy px-3 text-xs font-medium text-ink"
          >
            <span className="truncate">{activeLabel}</span>
            <span aria-hidden className="text-mute">
              ▾
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel>Matching results view</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {MATCHING_RESULT_LAB_METHODS.map((row) => {
            const selected = row.id === method
            return (
              <DropdownMenuItem
                key={row.id}
                className={cn('text-xs', selected && 'font-semibold text-habeas-navy')}
                onSelect={() => {
                  onMethodChange(row.id)
                  writeMatchingResultLabMethod(row.id)
                }}
              >
                <span aria-hidden className="w-4 shrink-0">
                  {selected ? '✓' : ''}
                </span>
                {row.label}
              </DropdownMenuItem>
            )
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** Results lab — 10-option owner matching-review dropdown. Default v10 two-tier. */
export function OwnerMatchingReviewMethodToolbar({
  method,
  onMethodChange,
  className,
}: {
  method: OwnerMatchingReviewMethodId
  onMethodChange: (method: OwnerMatchingReviewMethodId) => void
  className?: string
}) {
  const labelId = useId()
  const active = OWNER_MATCHING_REVIEW_METHODS.find((row) => row.id === method)
  const activeLabel = active?.label ?? method
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      className={cn(
        'flex shrink-0 flex-wrap items-center gap-2 border border-line bg-canvas px-2.5 py-2',
        className,
      )}
    >
      <span id={labelId} className="text-xs font-semibold text-ink">
        Review view
      </span>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="default"
            className="h-8 min-w-[16rem] justify-between border-habeas-navy px-3 text-xs font-medium text-ink"
          >
            <span className="truncate">{activeLabel}</span>
            <span aria-hidden className="text-mute">
              ▾
            </span>
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="w-72">
          <DropdownMenuLabel>Owner matching review</DropdownMenuLabel>
          <DropdownMenuSeparator />
          {OWNER_MATCHING_REVIEW_METHODS.map((row) => {
            const selected = row.id === method
            return (
              <DropdownMenuItem
                key={row.id}
                className={cn('text-xs', selected && 'font-semibold text-habeas-navy')}
                onSelect={() => {
                  onMethodChange(row.id)
                  writeOwnerMatchingReviewMethod(row.id)
                }}
              >
                <span aria-hidden className="w-4 shrink-0">
                  {selected ? '✓' : ''}
                </span>
                {row.label}
              </DropdownMenuItem>
            )
          })}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
