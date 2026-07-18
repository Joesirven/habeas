import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { opsRunsSearch } from '@/lib/ops-runs-search'

import { SkeletonLines } from '@/components/AppShell'
import { getRequestJourney, type JourneyStageStatus, type RequestJourneyStage } from '@/lib/api'
import { OpsPageChrome, RequireRole, isSuperAdmin, useOpsRole } from '@/lib/auth'

function stageTone(status: JourneyStageStatus): string {
  if (status === 'complete') return 'border-habeas-navy/40 bg-habeas-navy text-white'
  if (status === 'current') {
    return 'border-habeas-mid bg-habeas-mid/10 text-habeas-navy ring-2 ring-habeas-mid/30'
  }
  return 'border-line bg-paper text-ink-soft'
}

function StageRail({ stages }: { stages: RequestJourneyStage[] }) {
  return (
    <ol className="flex flex-wrap items-stretch gap-2">
      {stages.map((stage, index) => (
        <li key={stage.key} className="flex min-w-[7.5rem] flex-1 items-center gap-2">
          <div
            className={`w-full rounded-md border px-3 py-2 ${stageTone(stage.status)}`}
          >
            <p className="text-[0.65rem] font-medium uppercase tracking-[0.08em] opacity-80">
              {index + 1}. {stage.label}
            </p>
            <p className="mt-1 text-[0.7rem] tabular-nums opacity-90">
              {stage.at ? new Date(stage.at).toLocaleString() : '—'}
            </p>
          </div>
          {index < stages.length - 1 ? (
            <span className="hidden text-mute sm:inline" aria-hidden>
              →
            </span>
          ) : null}
        </li>
      ))}
    </ol>
  )
}

export function RequestJourneyPage({ requestId }: { requestId: string }) {
  const role = useOpsRole()
  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'request-journey', requestId],
    queryFn: () => getRequestJourney(requestId),
    retry: 1,
  })

  const journey = journeyQuery.data

  return (
    <RequireRole allow={['super_admin', 'admin', 'data_owner']}>
      <OpsPageChrome
        eyebrow="REQUESTS · JOURNEY"
        title={requestId}
        support="Stage rail for this DROP request — ids and counts only. No PII."
      >
        {journeyQuery.isPending ? (
          <div className="taste-panel p-5">
            <SkeletonLines lines={4} />
          </div>
        ) : null}

        {journeyQuery.isError ? (
          <div className="taste-panel p-5">
            <p className="text-sm text-red-700">
              Could not load journey (forbidden or not found).
            </p>
            <Link to="/requests" className="taste-btn-secondary mt-4 inline-flex text-xs">
              ← Requests
            </Link>
          </div>
        ) : null}

        {journey ? (
          <div className="space-y-5">
            <div className="taste-panel p-5">
              <p className="taste-micro">Stage rail</p>
              <div className="mt-4">
                <StageRail stages={journey.stages} />
              </div>
              <p className="mt-4 text-sm text-ink-soft">
                Current:{' '}
                <span className="font-medium text-ink">{journey.current_stage_key}</span>
                {journey.needs_attention ? (
                  <span className="ml-2 inline-flex items-center rounded-sm border border-amber-600/25 bg-amber-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-amber-900">
                    needs attention
                  </span>
                ) : null}
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <div className="taste-panel-soft p-5">
                <p className="taste-micro">Overview</p>
                <table className="taste-table mt-3">
                  <tbody>
                    <tr>
                      <td className="!px-0 text-ink-soft">Intake</td>
                      <td className="!px-0">{journey.intake_source}</td>
                    </tr>
                    <tr>
                      <td className="!px-0 text-ink-soft">Requestor state</td>
                      <td className="!px-0 font-mono">{journey.requestor_state ?? '—'}</td>
                    </tr>
                    <tr>
                      <td className="!px-0 text-ink-soft">Received</td>
                      <td className="!px-0 tabular-nums">
                        {journey.received_at
                          ? new Date(journey.received_at).toLocaleString()
                          : '—'}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div className="taste-panel-soft p-5">
                <p className="taste-micro">Matching</p>
                {journey.matching ? (
                  <table className="taste-table mt-3">
                    <tbody>
                      <tr>
                        <td className="!px-0 text-ink-soft">Match type</td>
                        <td className="!px-0">{journey.matching.match_type ?? '—'}</td>
                      </tr>
                      <tr>
                        <td className="!px-0 text-ink-soft">Match count</td>
                        <td className="!px-0 tabular-nums">
                          {journey.matching.match_count ?? '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="!px-0 text-ink-soft">Review</td>
                        <td className="!px-0">{journey.matching.review_status ?? '—'}</td>
                      </tr>
                    </tbody>
                  </table>
                ) : (
                  <p className="mt-3 text-sm text-ink-soft">No matching activity yet.</p>
                )}
              </div>
            </div>

            <div className="flex flex-wrap gap-2">
              <Link to="/requests" className="taste-frost-chip">
                ← Requests
              </Link>
              {journey.needs_attention ? (
                <Link to="/requests/needs-attention" className="taste-frost-chip">
                  Needs attention →
                </Link>
              ) : null}
              {isSuperAdmin(role) && journey.matching?.attempt_id != null ? (
                <Link
                  to="/ops/runs"
                  search={opsRunsSearch({
                    job: 'matching',
                    request_id: journey.request_id,
                  })}
                  className="taste-frost-chip"
                >
                  Runs for request →
                </Link>
              ) : null}
            </div>
          </div>
        ) : null}
      </OpsPageChrome>
    </RequireRole>
  )
}
