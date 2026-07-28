import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { cn } from '@/lib/utils'

const HOME_BATCH_CAP = 5

type FulfillmentBatchListProps = {
  batches: NonNullable<LegalPortfolio['fulfillment_batches']>
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

function sourceShort(label: string): string {
  if (label.length <= 10) return label
  if (label.toLowerCase().includes('drop')) return 'DROP'
  if (label.toLowerCase().includes('manual')) return 'Manual'
  if (label.toLowerCase().includes('webform')) return 'Webform'
  if (label.toLowerCase().includes('agent')) return 'Agent'
  if (label.toLowerCase().includes('csv')) return 'CSV'
  if (label.toLowerCase().includes('email')) return 'Email'
  return label.split(/\s+/)[0] ?? label
}

export function FulfillmentBatchList({
  batches,
  selectedKey,
  onSelect,
}: FulfillmentBatchListProps) {
  const deduped = batches.reduce<NonNullable<LegalPortfolio['fulfillment_batches']>>(
    (acc, batch) => {
      const existing = acc.find((row) => row.batch_key === batch.batch_key)
      if (existing) {
        existing.request_count += batch.request_count
        return acc
      }
      acc.push({ ...batch })
      return acc
    },
    [],
  )
  const visible = deduped.slice(0, HOME_BATCH_CAP)
  const hasSelection = selectedKey != null

  if (visible.length === 0) {
    return <p className="text-xs text-mute">No intake batches in this window.</p>
  }

  return (
    <div className="space-y-3">
      <ul className="text-xs" aria-label="Fulfillment batches">
        {visible.map((batch, index) => {
          const selected = selectedKey === batch.batch_key
          const previousSelected =
            index > 0 && selectedKey === visible[index - 1]!.batch_key
          return (
            <li key={batch.batch_key}>
              <button
                type="button"
                className={cn(
                  'flex w-full items-center gap-2.5 py-1.5 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
                  index > 0 && !selected && !previousSelected && 'border-t border-line/50',
                  selected && 'rounded-md bg-panel px-1.5',
                  hasSelection && !selected && 'opacity-55',
                )}
                aria-pressed={selected}
                onClick={() => onSelect(selected ? null : batch.batch_key)}
              >
                <span className="inline-flex min-w-[4.25rem] shrink-0 justify-center rounded-full border border-line bg-panel px-2 py-0.5 text-[0.65rem] font-medium text-ink-soft">
                  {sourceShort(batch.source_label)}
                </span>
                <span
                  className={cn(
                    'min-w-0 flex-1 truncate',
                    selected ? 'font-semibold text-ink' : 'font-medium text-ink-soft',
                  )}
                >
                  Received {formatReceivedAt(batch.received_at)}
                </span>
                <span className="shrink-0 tabular-nums text-ink-soft">
                  {batch.request_count.toLocaleString()} requests
                </span>
              </button>
            </li>
          )
        })}
      </ul>

      <div className="flex flex-wrap items-center justify-between gap-2 text-[0.65rem] text-mute">
        <span>
          {hasSelection
            ? 'Funnel below is scoped to the selected batch — click the row again or Clear to show all batches.'
            : 'Click a batch to scope the funnel below to that intake only · source + received datetime'}
        </span>
        <div className="flex items-center gap-2">
          {hasSelection ? (
            <button
              type="button"
              className="rounded-full border border-line bg-panel px-2 py-0.5 text-[0.65rem] font-medium text-ink-soft transition-colors hover:border-habeas-navy/35 hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
              onClick={() => onSelect(null)}
            >
              Clear ✕
            </button>
          ) : null}
          <Link
            to="/requests"
            className="text-xs text-habeas-navy hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
          >
            See all
          </Link>
        </div>
      </div>
    </div>
  )
}
