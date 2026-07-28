import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  DataOwnerQueues,
  DateToolbar,
  DeadlineRiskBand,
  FulfillmentBatchList,
  OpenRequestsHeatmap,
  OperationsPulse,
  PipelineFunnel,
  type HomeWindow,
} from '@/components/legal/home'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { LegalChromeActions } from '@/components/UploadMenu'
import { useMe, isLegalAdminPersona } from '@/lib/auth'
import {
  getDropGlobalStats,
  getDropPipeline,
  getHealth,
  getLegalPortfolio,
  getNeedsAttention,
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

function HomeModuleHeader({
  title,
  hint,
  compact = false,
}: {
  title: string
  hint?: string
  compact?: boolean
}) {
  return (
    <div className={compact ? 'mb-2' : 'mb-3'}>
      <h3 className={compact ? 'text-xs font-semibold text-ink' : 'text-sm font-semibold text-ink'}>
        {title}
      </h3>
      {hint ? (
        <p className={compact ? 'mt-0.5 text-[0.65rem] text-mute' : 'mt-1 text-xs text-mute'}>
          {hint}
        </p>
      ) : null}
    </div>
  )
}

function LegalHome() {
  const search = useSearch({ from: '/' })
  const navigate = useNavigate()
  const homeWindow: HomeWindow = search.home_window ?? '30'
  const [selectedBatch, setSelectedBatch] = useState<string | null>(null)

  function setHomeWindow(next: HomeWindow) {
    void navigate({
      to: '/',
      search: {
        tab: search.tab,
        process: search.process,
        stage: search.stage,
        home_window: next === '30' ? undefined : next,
      },
      replace: true,
    })
  }

  useEffect(() => {
    setSelectedBatch(null)
  }, [homeWindow])

  const portfolioQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'home', 'portfolio', homeWindow, selectedBatch],
    queryFn: () =>
      getLegalPortfolio({
        window_days: homeWindow,
        batch_key: selectedBatch ?? undefined,
      }),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })
  const portfolio = portfolioQuery.data

  useEffect(() => {
    if (!portfolio || selectedBatch == null) return
    const batchKeys = (portfolio.fulfillment_batches ?? []).map((batch) => batch.batch_key)
    if (!batchKeys.includes(selectedBatch)) {
      setSelectedBatch(null)
    }
  }, [portfolio, selectedBatch])

  const hasVariationB =
    portfolio != null &&
    portfolio.operations_pulse != null &&
    portfolio.fulfillment_batches != null &&
    portfolio.stage_reach_counts != null &&
    portfolio.heatmap_cells != null &&
    portfolio.deadline_risk != null

  const selectedBatchRow =
    selectedBatch != null
      ? (portfolio?.fulfillment_batches ?? []).find((batch) => batch.batch_key === selectedBatch) ??
        null
      : null

  return (
    <section className="space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <p className="taste-micro">Legal</p>
          <h2 className="mt-1 font-display text-2xl font-medium tracking-tight text-ink">Home</h2>
          <p className="mt-1 max-w-xl text-sm text-ink-soft">
            Portfolio health and pipeline flow. Work queues show all open items.
          </p>
        </div>
        <LegalChromeActions />
      </header>

      {portfolioQuery.isError ? (
        <p className="text-sm text-red-700">Could not load portfolio — retrying automatically.</p>
      ) : null}

      {portfolio && !hasVariationB ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-950">
          Legal Home modules need a newer admin-api (portfolio enrichment not deployed yet). Inbox
          and All requests still work.
        </p>
      ) : null}

      {portfolio && hasVariationB ? (
        <div className="divide-y divide-line rounded-lg border border-line">
          {portfolio.operations_pulse ? (
            <section className="px-4 py-2">
              <OperationsPulse pulse={portfolio.operations_pulse} embedded />
            </section>
          ) : null}

          <section className="px-4 py-2">
            <DateToolbar value={homeWindow} onChange={setHomeWindow} />
          </section>

          <section className="px-4 py-2.5">
            <HomeModuleHeader
              compact
              title="Fulfillment batches"
              hint="Intake batches by source + received datetime. Select a batch to scope the funnel below."
            />
            <FulfillmentBatchList
              batches={portfolio.fulfillment_batches!}
              selectedKey={selectedBatch}
              onSelect={setSelectedBatch}
            />
          </section>

          <section className="px-4 py-2.5">
            <HomeModuleHeader
              compact
              title="Pipeline — Mixpanel-style funnel"
              hint="Reached-stage funnel with held-upstream stacks — scoped by batch selection above."
            />
            <PipelineFunnel
              stages={portfolio.stage_reach_counts!}
              selectedBatch={selectedBatchRow}
              onClearBatch={() => setSelectedBatch(null)}
            />
          </section>

          <div className="grid lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:divide-x divide-line">
            <section className="px-4 py-4">
              <HomeModuleHeader title="Open requests" />
              <OpenRequestsHeatmap cells={portfolio.heatmap_cells!} />
            </section>
            <section className="px-4 py-4">
              <HomeModuleHeader title="Cycle time & deadline" />
              <DeadlineRiskBand risk={portfolio.deadline_risk!} />
            </section>
          </div>

          {portfolio.data_owner_queues ? (
            <section className="px-4 py-4">
              <HomeModuleHeader
                title="Data owner review queues"
                hint="Compact workload rows — top queues by pending review."
              />
              <DataOwnerQueues queues={portfolio.data_owner_queues} />
            </section>
          ) : null}

          {portfolio.schedule_excerpt ? (
            <section className="px-4 py-4 text-sm text-ink-soft">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                DROP schedule
              </p>
              <p className="mt-1 text-ink">
                Weekly — {portfolio.schedule_excerpt.label}
                {portfolio.schedule_excerpt.next_run_at
                  ? ` · next ${new Date(portfolio.schedule_excerpt.next_run_at).toLocaleString()}`
                  : ''}
              </p>
            </section>
          ) : null}
        </div>
      ) : portfolioQuery.isPending ? (
        <SkeletonLines lines={6} />
      ) : null}

      <div className="flex flex-wrap gap-2">
        <Link
          to="/requests/needs-attention"
          search={{ filter: 'unassigned' }}
          className="taste-btn text-xs"
        >
          Unassigned inbox
        </Link>
        <Link
          to="/requests/needs-attention"
          search={{ filter: 'assignment_to_legal' }}
          className="taste-btn text-xs"
        >
          Assignment to legal
        </Link>
        <Button asChild size="sm">
          <Link to="/requests/needs-attention">Open Inbox</Link>
        </Button>
        <Button asChild size="sm" variant="outline">
          <Link to="/requests">All requests</Link>
        </Button>
      </div>
    </section>
  )
}

function DataOwnerHome() {
  const attentionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'do-home'],
    queryFn: () => getNeedsAttention({ limit: 1000, kind: 'matching' }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })
  const assignedQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', 'needs-attention', 'do-assigned'],
    queryFn: () =>
      getNeedsAttention({ limit: 1000, kind: 'matching', assignee: 'me' }),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })
  const items = attentionQuery.data?.items ?? []
  const mine = assignedQuery.data?.items.length ?? 0

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
          search={{ kind: 'matching' }}
          className="taste-panel-soft block space-y-1 p-4"
        >
          <p className="text-[0.65rem] uppercase tracking-wide text-mute">Matching review</p>
          <p className="font-display text-3xl tabular-nums text-ink">
            {attentionQuery.isPending && !attentionQuery.data ? '—' : items.length}
          </p>
        </Link>
        <Link
          to="/requests/needs-attention"
          search={{ kind: 'pending_tasks' }}
          className="taste-panel-soft block space-y-1 p-4"
        >
          <p className="text-[0.65rem] uppercase tracking-wide text-mute">Assigned to me</p>
          <p className="font-display text-3xl tabular-nums text-ink">
            {assignedQuery.isPending && !assignedQuery.data ? '—' : mine}
          </p>
        </Link>
      </div>
      <Button asChild size="sm">
        <Link to="/requests/needs-attention" search={{ kind: 'matching' }}>
          Open Inbox
        </Link>
      </Button>
    </section>
  )
}

export function DashboardPage() {
  const { isSuperAdmin, isLoading, role } = useMe()

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

  if (isLegalAdminPersona(role)) {
    return <LegalHome />
  }

  if (role === 'data_owner') {
    return <DataOwnerHome />
  }

  return <OperatorDashboardHome />
}
