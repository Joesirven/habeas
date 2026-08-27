import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { actionToast } from '@/lib/action-toast'
import {
  getWorkerSchedules,
  patchWorkerSchedule,
  type WorkerSchedule,
  type WorkerScheduleKind,
} from '@/lib/api'
import {
  formatMonthDaysInput,
  formatScheduleCadence,
  parseMonthDaysInput,
} from '@/lib/worker-fleet'

type Draft = {
  enabled: boolean
  cadence: WorkerScheduleKind
  interval: number
  month_days: string
  time_utc: string
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function cadenceHint(draft: Draft): string {
  if (draft.cadence === 'month_days') {
    const days = parseMonthDaysInput(draft.month_days)
    const label = days.length
      ? formatScheduleCadence(
          `on_${days
            .map((day) => {
              const suffix =
                day % 100 >= 11 && day % 100 <= 13
                  ? 'th'
                  : day % 10 === 1
                    ? 'st'
                    : day % 10 === 2
                      ? 'nd'
                      : day % 10 === 3
                        ? 'rd'
                        : 'th'
              return `${day}${suffix}`
            })
            .join('_and_')}`,
        )
      : 'Days of the month'
    return `${label} · ${draft.time_utc || '—'} UTC`
  }
  if (draft.cadence === 'interval_days') {
    return `Every ${draft.interval || '—'} days · daily tick ${draft.time_utc || '—'} UTC`
  }
  return `Every ${draft.interval || '—'} min`
}

function draftFromRow(row: WorkerSchedule): Draft {
  return {
    enabled: row.enabled,
    cadence: row.schedule_kind,
    interval:
      row.schedule_kind === 'interval_minutes'
        ? (row.interval_minutes ?? 5)
        : (row.interval_days ?? 15),
    month_days: formatMonthDaysInput(row.month_days ?? [1, 15]),
    time_utc: row.time_utc ?? '14:00',
  }
}

export function ScheduleConfigPanel() {
  const queryClient = useQueryClient()
  const [drafts, setDrafts] = useState<Record<string, Draft>>({})

  const schedulesQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'worker-schedules'],
    queryFn: getWorkerSchedules,
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const saveMutation = useMutation({
    mutationFn: patchWorkerSchedule,
    onSuccess: async (payload) => {
      actionToast.success({
        title: 'Schedule saved',
        description: `${payload.schedule.job_key} (${payload.mode}${
          payload.schedule.scheduler_reachable ? '' : ', local defaults'
        })`,
      })
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'worker-schedules'],
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Could not save schedule',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => saveMutation.mutate(variables),
        },
      })
    },
  })

  const schedules = schedulesQuery.data?.schedules ?? []

  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
      <div>
        <Micro>Run schedules</Micro>
        <p className="mt-2 max-w-2xl text-sm text-ink-soft">
          Live from Cloud Scheduler when enabled on admin-api. Next is the next
          Scheduler fire — not a skip-gate. CA DROP download uses calendar days
          (1st and 15th) or a daily tick plus an interval-days eligibility gate.
          Super admin only.
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
                <th>Schedule</th>
                <th>Time UTC</th>
                <th>Next</th>
                <th>Last success</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {schedules.map((row) => {
                const draft = drafts[row.job_key] ?? draftFromRow(row)
                const calendarJob = row.schedule_kind !== 'interval_minutes'
                return (
                  <tr key={row.job_key}>
                    <td>
                      <p className="text-sm text-ink">{row.label}</p>
                      <p className="font-mono text-[0.65rem] text-mute">{row.job_key}</p>
                    </td>
                    <td className="text-xs text-ink-soft">{cadenceHint(draft)}</td>
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
                      {calendarJob ? (
                        <div className="flex flex-col gap-1.5">
                          <select
                            className="rounded-md border border-line bg-paper px-2 py-1 text-xs"
                            value={draft.cadence}
                            onChange={(event) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [row.job_key]: {
                                  ...draft,
                                  cadence: event.target.value as WorkerScheduleKind,
                                },
                              }))
                            }
                            aria-label={`Cadence for ${row.label}`}
                          >
                            <option value="month_days">Days of the month</option>
                            <option value="interval_days">Every N days</option>
                          </select>
                          {draft.cadence === 'month_days' ? (
                            <input
                              type="text"
                              inputMode="numeric"
                              className="w-28 rounded-md border border-line bg-paper px-2 py-1 font-mono text-sm"
                              value={draft.month_days}
                              onChange={(event) =>
                                setDrafts((prev) => ({
                                  ...prev,
                                  [row.job_key]: {
                                    ...draft,
                                    month_days: event.target.value,
                                  },
                                }))
                              }
                              aria-label={`Days of month for ${row.label}`}
                              placeholder="1, 15"
                            />
                          ) : (
                            <label className="flex items-center gap-1">
                              <input
                                type="number"
                                min={1}
                                max={90}
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
                                aria-label={`Interval days for ${row.label}`}
                              />
                              <span className="text-[0.65rem] text-mute">days</span>
                            </label>
                          )}
                        </div>
                      ) : (
                        <label className="flex items-center gap-1">
                          <input
                            type="number"
                            min={1}
                            max={59}
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
                            aria-label={`Interval minutes for ${row.label}`}
                          />
                          <span className="text-[0.65rem] text-mute">min</span>
                        </label>
                      )}
                    </td>
                    <td>
                      {calendarJob ? (
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
                          aria-label={`Time UTC for ${row.label}`}
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
                          if (draft.cadence === 'month_days') {
                            const monthDays = parseMonthDaysInput(draft.month_days)
                            if (monthDays.length === 0) {
                              actionToast.error({
                                title: 'Could not save schedule',
                                description: 'Enter at least one calendar day (1–31).',
                              })
                              return
                            }
                            saveMutation.mutate({
                              job_key: row.job_key,
                              enabled: draft.enabled,
                              month_days: monthDays,
                              time_utc: draft.time_utc,
                            })
                            return
                          }
                          if (draft.cadence === 'interval_days') {
                            saveMutation.mutate({
                              job_key: row.job_key,
                              enabled: draft.enabled,
                              interval_days: draft.interval,
                              time_utc: draft.time_utc,
                            })
                            return
                          }
                          saveMutation.mutate({
                            job_key: row.job_key,
                            enabled: draft.enabled,
                            interval_minutes: draft.interval,
                          })
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
    </div>
  )
}
