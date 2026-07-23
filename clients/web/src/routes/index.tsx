import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { SkeletonLines } from '@/components/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useMe } from '@/lib/auth'
import {
  getDropGlobalStats,
  getDropPipeline,
  getHealth,
  getLegalNeedsAttention,
  getNeedsAttention,
  type NeedsAttentionItemKind,
} from '@/lib/api'
import { DropPipelinePage } from '@/routes/ops/drop-pipeline'

function OperatorDashboardHome() {
  const { isAdmin } = useMe()

  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'home'],
    queryFn: () => getNeedsAttention(200),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const healthQuery = useQuery({
    queryKey: ['admin-api', 'health'],
    queryFn: getHealth,
    refetchInterval: 30_000,
    retry: 3,
    retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
    placeholderData: (previous) => previous,
  })

  const dropStatsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-stats-global'],
    queryFn: getDropGlobalStats,
    refetchInterval: 15_000,
    enabled: isAdmin,
    retry: 2,
    placeholderData: (previous) => previous,
  })

  const pipelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop-pipeline', 'home-viz'],
    queryFn: getDropPipeline,
    refetchInterval: 15_000,
    enabled: isAdmin,
    retry: 2,
    placeholderData: (previous) => previous,
  })

  const attentionCount = attentionQuery.data?.items.length ?? 0
  const dropStats = dropStatsQuery.data
  const approaching = pipelineQuery.data?.approaching_sla
  const loading = attentionQuery.isPending && !attentionQuery.data

  const matchCounts = { single_match: 0, multi_match: 0, not_found: 0 }
  for (const row of pipelineQuery.data?.matching_results_recent ?? []) {
    const matchType = row.match_type
    if (matchType && matchType in matchCounts) {
      matchCounts[matchType as keyof typeof matchCounts] += 1
    }
  }
  const matchMax = Math.max(
    1,
    matchCounts.single_match,
    matchCounts.multi_match,
    matchCounts.not_found,
  )

  const slaBars = approaching
    ? [
        { key: 'Download', value: approaching.connector },
        { key: 'Ingest', value: approaching.ingest },
        { key: 'Matching', value: approaching.matching },
        { key: 'Review', value: approaching.matching_review },
      ]
    : []
  const slaMax = Math.max(1, ...slaBars.map((bar) => bar.value), 1)

  return (
    <section className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">Home</p>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-ink">Dashboard</h2>
        </div>
        <div className="flex items-center gap-2">
          {healthQuery.data ? (
            <Badge variant="ok" className="normal-case tracking-normal">
              API {healthQuery.data.status}
            </Badge>
          ) : null}
        </div>
      </header>

      {loading ? (
        <div className="rounded-lg border border-line bg-paper p-5">
          <SkeletonLines lines={4} />
        </div>
      ) : null}

      {!loading ? (
        <>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Inbox
              </p>
              <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">{attentionCount}</p>
              <Button asChild size="sm" className="mt-3">
                <Link to="/requests/needs-attention">Open inbox</Link>
              </Button>
            </div>
            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Review pending
              </p>
              <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">
                {dropStats?.matching_review_pending ?? '—'}
              </p>
              <p className="mt-2 text-xs text-ink-soft">matching.review gates</p>
            </div>
            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Spine requests
              </p>
              <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">
                {dropStats?.open_drop_requests ?? '—'}
              </p>
              <p className="mt-2 text-xs text-ink-soft">Thin DROP requests on the spine</p>
            </div>
            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Approaching deadline
              </p>
              <p className="mt-2 text-3xl font-semibold tabular-nums text-ink">
                {approaching
                  ? approaching.connector +
                    approaching.ingest +
                    approaching.matching +
                    approaching.matching_review
                  : '—'}
              </p>
              <p className="mt-2 text-xs text-ink-soft">
                Needs review · gate {approaching?.matching_review ?? '—'}
              </p>
            </div>
          </div>

          {isAdmin && pipelineQuery.data?.ca_drop_schedule ? (
            <div className="rounded-lg border border-line bg-paper p-4">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Next CA DROP retrieval
              </p>
              <p className="mt-2 text-lg font-semibold tabular-nums text-ink">
                {new Date(pipelineQuery.data.ca_drop_schedule.next_run_at).toLocaleString()}
              </p>
              <p className="mt-1 text-xs text-ink-soft">
                {pipelineQuery.data.ca_drop_schedule.cadence} ·{' '}
                {pipelineQuery.data.ca_drop_schedule.schedule_utc} UTC
              </p>
            </div>
          ) : null}

          {isAdmin ? (
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-line bg-paper p-4">
                <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                  Approaching age policy
                </p>
                <p className="mt-1 text-xs text-ink-soft">
                  Open rows past stage attention thresholds.
                </p>
                {slaBars.length === 0 ? (
                  <p className="mt-4 text-xs text-mute">No pipeline snapshot yet.</p>
                ) : (
                  <div className="mt-4 space-y-2.5">
                    {slaBars.map((bar) => (
                      <div
                        key={bar.key}
                        className="grid grid-cols-[5rem_1fr_2rem] items-center gap-2"
                      >
                        <span className="text-[0.7rem] text-ink-soft">{bar.key}</span>
                        <div className="h-2 overflow-hidden rounded-full bg-panel">
                          <div
                            className="h-full rounded-full bg-habeas-mid"
                            style={{ width: `${(bar.value / slaMax) * 100}%` }}
                          />
                        </div>
                        <span className="text-right text-[0.7rem] tabular-nums text-ink">
                          {bar.value}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="rounded-lg border border-line bg-paper p-4">
                <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                  Recent match mix
                </p>
                <p className="mt-1 text-xs text-ink-soft">Latest matching_results sample.</p>
                <div className="mt-4 flex items-end gap-3" style={{ height: '7rem' }}>
                  {(
                    [
                      ['Single', matchCounts.single_match],
                      ['Multi', matchCounts.multi_match],
                      ['Not found', matchCounts.not_found],
                    ] as const
                  ).map(([label, count]) => (
                    <div key={label} className="flex min-w-0 flex-1 flex-col items-center gap-1">
                      <span className="text-[0.65rem] tabular-nums text-mute">{count}</span>
                      <div className="flex w-full flex-1 items-end">
                        <div
                          className="w-full rounded-t-md bg-habeas-navy/80"
                          style={{
                            height: `${Math.max((count / matchMax) * 100, count > 0 ? 8 : 0)}%`,
                          }}
                        />
                      </div>
                      <span className="truncate text-[0.65rem] text-ink-soft">{label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : null}
        </>
      ) : null}

      {healthQuery.isError && !healthQuery.data ? (
        <p className="text-sm text-red-700">
          Admin API unreachable — retries automatically.
          {healthQuery.error instanceof Error ? ` ${healthQuery.error.message}` : ''}
        </p>
      ) : null}
    </section>
  )
}

function LegalHome() {
  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'legal'],
    queryFn: () => getLegalNeedsAttention(1000),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })
  const items = attentionQuery.data?.items ?? []
  const triage = items.filter(
    (item) => item.kind === 'triage' || item.assignment?.kind === 'triage',
  ).length
  const escalations = items.filter(
    (item) => item.kind === 'escalations' || item.assignment?.kind === 'escalate',
  ).length
  const notice = items.filter(
    (item) => item.kind === 'notice' || item.reason === 'notice.review',
  ).length
  const delivery = items.filter(
    (item) =>
      item.kind === 'delivery' ||
      item.reason === 'access.delivery' ||
      item.reason === 'delivery.confirm',
  ).length

  const cards: {
    label: string
    kind: NeedsAttentionItemKind
    count: number
    hint: string
  }[] = [
    { label: 'Triage', kind: 'triage', count: triage, hint: 'Condition holds' },
    {
      label: 'Escalations',
      kind: 'escalations',
      count: escalations,
      hint: 'From data owners',
    },
    {
      label: 'Notice',
      kind: 'notice',
      count: notice,
      hint: 'DROP notice.review',
    },
    {
      label: 'Delivery',
      kind: 'delivery',
      count: delivery,
      hint:
        delivery === 0 ? 'Access handoff (empty until packs land)' : 'Access handoff',
    },
  ]

  return (
    <section className="space-y-6">
      <header>
        <p className="taste-micro">Legal</p>
        <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">
          Command Center
        </h2>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Clear Triage and Escalations first. Notice and Delivery light up after
          data-vertical fulfill. Upload agent batches when ready.
        </p>
      </header>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <Link
            key={card.label}
            to="/requests/needs-attention"
            search={{ kind: card.kind }}
            className="taste-panel-soft block space-y-1 p-4 transition-colors hover:border-habeas-navy/30"
          >
            <p className="text-[0.65rem] uppercase tracking-wide text-mute">{card.label}</p>
            <p className="font-display text-3xl tabular-nums text-ink">
              {attentionQuery.isPending && !attentionQuery.data ? '—' : card.count}
            </p>
            <p className="text-[0.7rem] text-ink-soft">{card.hint}</p>
          </Link>
        ))}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm">
          <Link to="/requests/needs-attention" search={{ kind: 'triage' }}>
            Open Inbox
          </Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link to="/requests/conditions">Conditions</Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link to="/requests/new">Upload / New</Link>
        </Button>
      </div>
    </section>
  )
}

function DataOwnerHome() {
  const { me } = useMe()
  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'do-home'],
    queryFn: () => getNeedsAttention({ limit: 1000, kind: 'matching' }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })
  const items = attentionQuery.data?.items ?? []
  const mine = items.filter((item) => {
    const assignee = item.assignment?.assignee_identity?.trim().toLowerCase()
    return Boolean(me?.email && assignee === me.email.trim().toLowerCase())
  }).length

  return (
    <section className="space-y-6">
      <header>
        <p className="taste-micro">Data owner</p>
        <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">
          My work
        </h2>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Approve recommended CA DROP statuses, comment, escalate to Legal, or assign an
          employee.
        </p>
      </header>
      <div className="grid gap-3 sm:grid-cols-2">
        <Link
          to="/requests/needs-attention"
          className="taste-panel-soft block space-y-1 p-4"
        >
          <p className="text-[0.65rem] uppercase tracking-wide text-mute">Matching review</p>
          <p className="font-display text-3xl tabular-nums text-ink">
            {attentionQuery.isPending && !attentionQuery.data ? '—' : items.length}
          </p>
        </Link>
        <Link
          to="/requests/needs-attention"
          className="taste-panel-soft block space-y-1 p-4"
        >
          <p className="text-[0.65rem] uppercase tracking-wide text-mute">Assigned to me</p>
          <p className="font-display text-3xl tabular-nums text-ink">
            {attentionQuery.isPending && !attentionQuery.data ? '—' : mine}
          </p>
        </Link>
      </div>
      <Button asChild size="sm">
        <Link to="/requests/needs-attention">Open Inbox</Link>
      </Button>
    </section>
  )
}

export function DashboardPage() {
  const { isSuperAdmin, isLegal, isLoading, role } = useMe()

  if (isLoading) {
    return (
      <section className="space-y-4">
        <SkeletonLines lines={5} />
      </section>
    )
  }

  if (isSuperAdmin) {
    return <DropPipelinePage />
  }

  if (isLegal || role === 'legal') {
    return <LegalHome />
  }

  if (role === 'data_owner') {
    return <DataOwnerHome />
  }

  return <OperatorDashboardHome />
}
