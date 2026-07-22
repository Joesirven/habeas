import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  getWorkerSchedules,
  patchWorkerSchedule,
  type WorkerSchedule,
} from '@/lib/api'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function cadenceHint(row: WorkerSchedule): string {
  if (row.schedule_kind === 'interval_days') {
    const days = row.interval_days ?? '—'
    const time = row.time_utc ?? '—'
    return `Every ${days} days · tick ${time} UTC`
  }
  return `Every ${row.interval_minutes ?? '—'} min`
}

export function ScheduleConfigPanel() {
  const queryClient = useQueryClient()
  const [drafts, setDrafts] = useState<
    Record<
      string,
      { enabled: boolean; interval: number; time_utc: string }
    >
  >({})
  const [message, setMessage] = useState<string | null>(null)

  const schedulesQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'worker-schedules'],
    queryFn: getWorkerSchedules,
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const saveMutation = useMutation({
    mutationFn: patchWorkerSchedule,
    onSuccess: async (payload) => {
      setMessage(
        `Saved ${payload.schedule.job_key} (${payload.mode}${
          payload.schedule.scheduler_reachable ? '' : ', local defaults'
        })`,
      )
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'worker-schedules'],
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    },
    onError: (error) => {
      setMessage(error instanceof Error ? error.message : String(error))
    },
  })

  const schedules = schedulesQuery.data?.schedules ?? []

  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
      <div>
        <Micro>Run schedules</Micro>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Live from Cloud Scheduler when enabled on admin-api. CA DROP download uses a daily
          tick plus an interval-days eligibility gate (default 15). Super admin only.
        </p>
      </div>

      {schedulesQuery.isPending && !schedulesQuery.data ? <SkeletonLines lines={5} /> : null}

      {schedulesQuery.isError && !schedulesQuery.data ? (
        <p className="text-sm text-red-700">Could not load worker schedules.</p>
      ) : null}

      {schedulesQuery.data ? (
        <div className="overflow-x-auto">
          <table className="taste-table">
            <thead>
              <tr>
                <th>Worker</th>
                <th>Cadence</th>
                <th>Enabled</th>
                <th>Interval</th>
                <th>Time UTC</th>
                <th>Next</th>
                <th>Last success</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {schedules.map((row) => {
                const draft = drafts[row.job_key] ?? {
                  enabled: row.enabled,
                  interval:
                    row.schedule_kind === 'interval_days'
                      ? (row.interval_days ?? 15)
                      : (row.interval_minutes ?? 5),
                  time_utc: row.time_utc ?? '14:00',
                }
                return (
                  <tr key={row.job_key}>
                    <td>
                      <p className="text-sm text-ink">{row.label}</p>
                      <p className="font-mono text-[0.65rem] text-mute">{row.job_key}</p>
                    </td>
                    <td className="text-xs text-ink-soft">{cadenceHint(row)}</td>
                    <td>
                      <input
                        type="checkbox"
                        checked={draft.enabled}
                        onChange={(event) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [row.job_key]: { ...draft, enabled: event.target.checked },
                          }))
                        }
                        aria-label={`Enable ${row.label}`}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        min={1}
                        max={row.schedule_kind === 'interval_days' ? 90 : 59}
                        className="w-20 rounded-md border border-line bg-paper px-2 py-1 font-mono text-sm"
                        value={draft.interval}
                        onChange={(event) =>
                          setDrafts((prev) => ({
                            ...prev,
                            [row.job_key]: {
                              ...draft,
                              interval: Number(event.target.value),
                            },
                          }))
                        }
                      />
                      <span className="ml-1 text-[0.65rem] text-mute">
                        {row.schedule_kind === 'interval_days' ? 'days' : 'min'}
                      </span>
                    </td>
                    <td>
                      {row.schedule_kind === 'interval_days' ? (
                        <input
                          type="text"
                          pattern="[0-2][0-9]:[0-5][0-9]"
                          className="w-24 rounded-md border border-line bg-paper px-2 py-1 font-mono text-sm"
                          value={draft.time_utc}
                          onChange={(event) =>
                            setDrafts((prev) => ({
                              ...prev,
                              [row.job_key]: { ...draft, time_utc: event.target.value },
                            }))
                          }
                        />
                      ) : (
                        <span className="text-mute">—</span>
                      )}
                    </td>
                    <td className="tabular-nums text-xs">
                      {row.next_run_at ? new Date(row.next_run_at).toLocaleString() : '—'}
                    </td>
                    <td className="tabular-nums text-xs">
                      {row.last_success_at
                        ? new Date(row.last_success_at).toLocaleString()
                        : '—'}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="taste-btn px-2.5 py-1 text-[0.65rem]"
                        disabled={saveMutation.isPending}
                        onClick={() => {
                          if (row.schedule_kind === 'interval_days') {
                            saveMutation.mutate({
                              job_key: row.job_key,
                              enabled: draft.enabled,
                              interval_days: draft.interval,
                              time_utc: draft.time_utc,
                            })
                          } else {
                            saveMutation.mutate({
                              job_key: row.job_key,
                              enabled: draft.enabled,
                              interval_minutes: draft.interval,
                            })
                          }
                        }}
                      >
                        Save
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : null}

      {message ? <p className="text-sm text-ink-soft">{message}</p> : null}
    </div>
  )
}
