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
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="taste-frost-chip tabular-nums text-[0.65rem] normal-case tracking-normal">
          Closed YTD: {risk.closed_ytd}
        </span>
      </div>

      <div
        className="flex h-1.5 overflow-hidden rounded-full bg-line/40"
        role="img"
        aria-label={`Deadline risk: ${risk.overdue} overdue, ${risk.due_within_7_days} due within 7 days, ${risk.on_track} on track`}
      >
        {SEGMENTS.map((segment) => {
          const count = risk[segment.countKey]
          const width = openTotal === 0 ? 100 / SEGMENTS.length : (count / barTotal) * 100
          return (
            <Link
              key={segment.key}
              to="/requests"
              search={segment.search}
              className={cn(
                segment.className,
                'transition-opacity hover:opacity-90',
                openTotal === 0 && 'opacity-30',
              )}
              style={{ width: `${width}%` }}
              title={`${segment.label}: ${count}`}
            />
          )
        })}
      </div>

      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[0.65rem] text-ink-soft">
        {SEGMENTS.map((segment) => (
          <Link
            key={segment.key}
            to="/requests"
            search={segment.search}
            className="inline-flex items-center gap-1 hover:text-ink"
          >
            <span className={cn('inline-block h-1.5 w-1.5 rounded-full', segment.className)} />
            <span>
              {segment.label}:{' '}
              <span className="tabular-nums font-medium">{risk[segment.countKey]}</span>
            </span>
          </Link>
        ))}
      </div>

      {openTotal === 0 ? (
        <p className="text-[0.65rem] text-mute">No open requests with due dates in this window.</p>
      ) : null}
    </div>
  )
}
