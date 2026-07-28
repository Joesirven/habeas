import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { cn } from '@/lib/utils'

type DeadlineRiskBandProps = {
  risk: NonNullable<LegalPortfolio['deadline_risk']>
}

const SEGMENTS = [
  {
    key: 'overdue',
    countKey: 'overdue' as const,
    label: 'Overdue',
    className: 'bg-red-500',
    search: { due: 'overdue' as const },
  },
  {
    key: 'due7',
    countKey: 'due_within_7_days' as const,
    label: 'Due ≤7d',
    className: 'bg-amber-400',
    search: { due: 'due_soon' as const },
  },
  {
    key: 'on_track',
    countKey: 'on_track' as const,
    label: 'On track',
    className: 'bg-emerald-500',
    search: { due: 'on_track' as const },
  },
] as const

export function DeadlineRiskBand({ risk }: DeadlineRiskBandProps) {
  const openTotal = risk.overdue + risk.due_within_7_days + risk.on_track
  const barTotal = openTotal || 1

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="taste-frost-chip tabular-nums normal-case tracking-normal">
          Closed YTD: {risk.closed_ytd}
        </span>
      </div>

      {openTotal === 0 ? (
        <p className="text-xs text-mute">No open requests with due dates in this window.</p>
      ) : (
        <>
          <div
            className="flex h-2 overflow-hidden rounded-full bg-line/40"
            role="img"
            aria-label={`Deadline risk: ${risk.overdue} overdue, ${risk.due_within_7_days} due within 7 days, ${risk.on_track} on track`}
          >
            {SEGMENTS.map((segment) => {
              const count = risk[segment.countKey]
              if (count <= 0) return null
              return (
                <Link
                  key={segment.key}
                  to="/requests"
                  search={segment.search}
                  className={cn(segment.className, 'transition-opacity hover:opacity-90')}
                  style={{ width: `${(count / barTotal) * 100}%` }}
                  title={`${segment.label}: ${count}`}
                />
              )
            })}
          </div>

          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft">
            {SEGMENTS.map((segment) => (
              <Link
                key={segment.key}
                to="/requests"
                search={segment.search}
                className="inline-flex items-center gap-1.5 hover:text-ink"
              >
                <span className={cn('inline-block h-2 w-2 rounded-full', segment.className)} />
                <span>
                  {segment.label}: <span className="tabular-nums font-medium">{risk[segment.countKey]}</span>
                </span>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
