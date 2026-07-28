import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { cn } from '@/lib/utils'

const QUEUE_CAP = 5

type DataOwnerQueuesProps = {
  queues: LegalPortfolio['data_owner_queues']
}

function initialsFor(identity: string | null): string {
  if (!identity) return '?'
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
    <ul className="space-y-2" aria-label="Data owner review queues">
      {top.map((row) => {
        const key = row.assignee_identity ?? 'unassigned'
        const barWidth = (row.pending_count / maxPending) * 100
        return (
          <li
            key={key}
            className="rounded-md border border-line/60 bg-white px-3 py-2 text-xs"
          >
            <div className="flex items-center gap-2">
              <Avatar className="h-7 w-7">
                <AvatarFallback className="bg-habeas-light/30 text-[0.6rem] font-medium text-habeas-navy">
                  {initialsFor(row.assignee_identity)}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0 flex-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-medium text-ink">{displayName(row.assignee_identity)}</span>
                  <Link
                    to="/requests/needs-attention"
                    search={{
                      kind: 'matching',
                      ...(row.assignee_identity
                        ? { assignee: row.assignee_identity }
                        : {}),
                    }}
                    className="shrink-0 tabular-nums text-habeas-navy hover:underline"
                  >
                    {row.pending_count} pending
                  </Link>
                </div>
                <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-line/40">
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
                {row.outreach_hint ? (
                  <p className="mt-1 truncate text-[0.65rem] text-mute">{row.outreach_hint}</p>
                ) : null}
              </div>
            </div>
          </li>
        )
      })}
    </ul>
  )
}
