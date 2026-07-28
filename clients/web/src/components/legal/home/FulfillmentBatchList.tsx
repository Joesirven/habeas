import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { cn } from '@/lib/utils'

const HOME_BATCH_CAP = 5

type FulfillmentBatchListProps = {
  batches: LegalPortfolio['fulfillment_batches']
  selectedKey: string | null
  onSelect: (batchKey: string | null) => void
}

function formatReceivedAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function FulfillmentBatchList({
  batches,
  selectedKey,
  onSelect,
}: FulfillmentBatchListProps) {
  const visible = batches.slice(0, HOME_BATCH_CAP)

  if (visible.length === 0) {
    return <p className="text-xs text-mute">No intake batches in this window.</p>
  }

  return (
    <div className="space-y-3">
      <ul className="divide-y divide-line/60 text-xs" aria-label="Fulfillment batches">
        {visible.map((batch) => {
          const selected = selectedKey === batch.batch_key
          return (
            <li key={batch.batch_key}>
              <button
                type="button"
                className={cn(
                  'flex w-full items-center justify-between gap-3 py-2.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
                  selected ? 'font-medium text-ink' : 'text-ink-soft hover:text-ink',
                )}
                aria-pressed={selected}
                onClick={() => onSelect(selected ? null : batch.batch_key)}
              >
                <span className="min-w-0 truncate">
                  <span className="text-ink">{batch.source_label}</span>
                  <span className="text-mute"> · </span>
                  <span className="tabular-nums">{formatReceivedAt(batch.received_at)}</span>
                </span>
                <span className="shrink-0 tabular-nums text-mute">{batch.request_count}</span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-2">
        {selectedKey ? (
          <button
            type="button"
            className="text-xs text-habeas-navy hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
            onClick={() => onSelect(null)}
          >
            Clear batch filter
          </button>
        ) : (
          <span className="text-[0.65rem] text-mute">Select a batch to scope the funnel</span>
        )}
        <Link
          to="/requests"
          className="text-xs text-habeas-navy hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
        >
          See all
        </Link>
      </div>
    </div>
  )
}
