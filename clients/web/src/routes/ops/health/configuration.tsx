import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { actionToast } from '@/lib/action-toast'
import { getRetryConfig, patchRetryConfig } from '@/lib/api'
import { RoleGate, isSuperAdmin } from '@/lib/auth'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

export function RetryConfigPanel() {
  const queryClient = useQueryClient()
  const [drafts, setDrafts] = useState<Record<string, number>>({})

  const configQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'retry-config'],
    queryFn: getRetryConfig,
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const saveMutation = useMutation({
    mutationFn: patchRetryConfig,
    onSuccess: async (payload) => {
      actionToast.success({
        title: 'Retry config saved',
        description: `${payload.table_name} → ${payload.max_attempts} (reaper next cycle)`,
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'retry-config'] })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Could not save retry config',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => saveMutation.mutate(variables),
        },
      })
    },
  })

  const tables = configQuery.data?.tables ?? []
  const floor = configQuery.data?.floor ?? 4

  return (
    <div className="taste-panel-soft flex flex-col gap-5 p-6 sm:p-7">
        <div>
          <Micro>Retry attempts</Micro>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Matching must stay ≥ {floor}. Values persist in{' '}
            <code className="rounded border border-line bg-paper-raised px-1.5 py-0.5 font-mono text-xs">
              ops_retry_config
            </code>
            .
          </p>
        </div>

        {configQuery.isPending && !configQuery.data ? <SkeletonLines lines={4} /> : null}

        {configQuery.isError && !configQuery.data ? (
          <p className="text-sm text-red-700">Could not load retry configuration.</p>
        ) : null}

        {configQuery.data ? (
          <div className="overflow-x-auto">
            <table className="taste-table">
              <thead>
                <tr>
                  <th>Attempt table</th>
                  <th>Current</th>
                  <th>Default</th>
                  <th>Set</th>
                </tr>
              </thead>
              <tbody>
                {tables.map((row) => {
                  const value = drafts[row.table_name] ?? row.max_attempts
                  return (
                    <tr key={row.table_name}>
                      <td className="font-mono text-xs">{row.table_name}</td>
                      <td className="tabular-nums">
                        {row.max_attempts}
                        {row.overridden ? (
                          <span className="ml-2 text-xs text-mute">override</span>
                        ) : null}
                      </td>
                      <td className="tabular-nums text-ink-soft">{row.default_max_attempts}</td>
                      <td>
                        <div className="flex flex-wrap items-center gap-2">
                          <input
                            type="number"
                            min={floor}
                            max={20}
                            className="w-20 rounded-md border border-line bg-paper px-2 py-1 font-mono text-sm"
                            value={value}
                            onChange={(event) =>
                              setDrafts((prev) => ({
                                ...prev,
                                [row.table_name]: Number(event.target.value),
                              }))
                            }
                          />
                          <button
                            type="button"
                            className="taste-btn px-2.5 py-1 text-[0.65rem]"
                            disabled={saveMutation.isPending || value < floor}
                            onClick={() =>
                              saveMutation.mutate({
                                table_name: row.table_name,
                                max_attempts: value,
                              })
                            }
                          >
                            Save
                          </button>
                        </div>
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

export function HealthConfigurationPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <HealthConfigurationBody />
    </RoleGate>
  )
}

function HealthConfigurationBody() {
  const configQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'retry-config'],
    queryFn: getRetryConfig,
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const floor = configQuery.data?.floor ?? 4

  return (
    <section className="space-y-12">
      <header className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr] lg:items-end">
        <div>
          <Micro>Health</Micro>
          <h2 className="mt-3 max-w-md font-display text-[2.75rem] font-medium leading-[1.05] tracking-tight text-ink sm:text-[3.25rem]">
            Configuration
          </h2>
          <p className="mt-3 text-sm text-ink-soft">
            <Link
              to="/ops/connections"
              className="text-habeas-mid underline decoration-habeas-mid/30 underline-offset-2"
            >
              Connections
            </Link>
          </p>
        </div>
        <p className="max-w-sm border-l border-line pl-5 text-sm leading-relaxed text-ink-soft">
          Per-worker retry attempts via admin-api. Floor is {floor}. Reaper applies overrides on
          the next cycle.
        </p>
      </header>

      <RetryConfigPanel />

      <p className="text-sm text-ink-soft">
        <Link to="/ops/health" className="underline decoration-ink/25 underline-offset-4">
          ← Health landing
        </Link>
      </p>
    </section>
  )
}
