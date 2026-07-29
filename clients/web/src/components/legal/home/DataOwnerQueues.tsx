import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { cn } from '@/lib/utils'

const QUEUE_CAP = 5

type DataOwnerQueuesProps = {
  queues: LegalPortfolio['data_owner_queues']
}

function initialsFor(identity: string | null): string {
  if (!identity) return '—'
  const local = identity.split('@')[0] ?? identity
  const parts = local.split(/[._-]+/).filter(Boolean)
  if (parts.length >= 2) {
    return `${parts[0]![0] ?? ''}${parts[1]![0] ?? ''}`.toUpperCase()
  }
  return local.slice(0, 2).toUpperCase()
}

function displayName(identity: string | null): string {
  if (!identity) return 'Unassigned'
  return identity.split('@')[0] ?? identity
}

export function DataOwnerQueues({ queues }: DataOwnerQueuesProps) {
  const top = queues.slice(0, QUEUE_CAP)
  const maxPending = Math.max(1, ...top.map((row) => row.pending_count))

  if (top.length === 0) {
    return <p className="text-xs text-mute">No pending data-owner review work.</p>
  }

  return (
    <ul className="space-y-0.5" aria-label="Data owner review queues">
      {top.map((row) => {
        const key = row.assignee_identity ?? 'unassigned'
        const barWidth = (row.pending_count / maxPending) * 100
        return (
          <li key={key}>
            <Link
              to="/requests/needs-attention"
              search={{
                kind: 'matching',
                ...(row.assignee_identity ? { assignee: row.assignee_identity } : {}),
              }}
              className="flex items-center gap-2 rounded px-0.5 py-1 text-[0.65rem] transition-colors hover:bg-panel/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
            >
              <Avatar className="h-5 w-5">
                <AvatarFallback className="bg-habeas-light/30 text-[0.5rem] font-medium text-habeas-navy">
                  {initialsFor(row.assignee_identity)}
                </AvatarFallback>
              </Avatar>
              <div className="w-[5.5rem] shrink-0 truncate font-medium text-ink">
                {displayName(row.assignee_identity)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="h-1 overflow-hidden rounded-full bg-line/40">
                  <div
                    className={cn(
                      'h-full rounded-full',
                      row.pending_count > maxPending * 0.7
                        ? 'bg-amber-400'
                        : 'bg-habeas-navy/70',
                    )}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
              <span className="shrink-0 tabular-nums text-ink-soft">
                {row.pending_count}
              </span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
