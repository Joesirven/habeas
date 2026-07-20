import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { getNeedsAttention, type NeedsAttentionItem } from '@/lib/api'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function NeedsAttentionTable({ items }: { items: NeedsAttentionItem[] }) {
  if (items.length === 0) {
    return <p className="p-6 text-sm text-ink-soft">Nothing needs attention right now.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="taste-table">
        <thead>
          <tr>
            <th>Received</th>
            <th>Request</th>
            <th>Stage</th>
            <th>Reason</th>
            <th>Source</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.request_id}>
              <td className="whitespace-nowrap tabular-nums text-ink-soft">
                {formatTimestamp(item.received_at ?? item.requested_at)}
              </td>
              <td>
                <Link
                  to="/requests/$requestId"
                  params={{ requestId: item.request_id }}
                  className="taste-link font-mono text-xs"
                >
                  {item.request_id}
                </Link>
              </td>
              <td>
                <span className="taste-frost-chip text-xs capitalize">
                  {item.current_stage.replaceAll('_', ' ')}
                </span>
              </td>
              <td className="text-sm text-ink-soft">{item.reason}</td>
              <td className="text-sm">
                {SOURCE_LABELS[item.intake_source] ?? item.intake_source}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function NeedsAttentionPage() {
  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention'],
    queryFn: () => getNeedsAttention(100),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const loading = attentionQuery.isPending && !attentionQuery.data

  return (
    <section className="space-y-10">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <Micro>Requests</Micro>
          <div className="mt-3 flex flex-wrap items-baseline gap-3">
            <h2 className="font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
              Needs attention
            </h2>
            {attentionQuery.isFetching && !attentionQuery.isPending ? (
              <span className="taste-frost-chip">Refreshing</span>
            ) : null}
            {attentionQuery.data ? (
              <span className="taste-frost-chip tabular-nums">
                {attentionQuery.data.items.length} open
              </span>
            ) : null}
          </div>
          <p className="mt-3 max-w-md text-sm text-ink-soft">
            Human gates and blockers — pending matching review and other approval queues.
          </p>
        </div>
        <p className="max-w-sm border-l border-line pl-5 text-sm leading-relaxed text-ink-soft">
          Request ids and stage labels only. Open a row to see the full journey rail.
        </p>
      </header>

      <div className="taste-panel overflow-hidden">
        {loading ? (
          <div className="p-6">
            <SkeletonLines lines={6} />
          </div>
        ) : null}
        {attentionQuery.isError ? (
          <p className="p-6 text-sm text-red-700">Could not load needs-attention queue.</p>
        ) : null}
        {!loading && !attentionQuery.isError && attentionQuery.data ? (
          <NeedsAttentionTable items={attentionQuery.data.items} />
        ) : null}
      </div>
    </section>
  )
}
