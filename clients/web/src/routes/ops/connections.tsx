import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { ConnectionCreateDialog } from '@/components/ops/ConnectionCreateDialog'
import { ConnectionInvitePanel } from '@/components/ops/ConnectionInvitePanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  connectTestTriageSummary,
  listConnections,
  type ConnectionRecord,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import { cn } from '@/lib/utils'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

type ConnectionStatus = ConnectionRecord['status']
type StatusFilter = 'all' | 'failed' | 'connected' | 'open'

const STATUS_FILTERS: Array<{ value: StatusFilter; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'failed', label: 'Failed' },
  { value: 'open', label: 'Pending / invited' },
  { value: 'connected', label: 'Connected' },
]

function connectionStatusVariant(
  status: ConnectionStatus,
): 'ok' | 'fail' | 'run' | 'wait' | 'default' {
  switch (status) {
    case 'connected':
      return 'ok'
    case 'failed':
    case 'revoked':
      return 'fail'
    case 'invited':
      return 'run'
    case 'pending':
    case 'infra_pending':
      return 'wait'
    default:
      return 'default'
  }
}

function formatSystemLabel(system: string): string {
  return system.replaceAll('_', ' ')
}

function connectionDetailTitle(connection: ConnectionRecord): string {
  if (connection.system === 'cassandra') {
    return `${connection.display_name} · Infrastructure`
  }
  return `${connection.display_name} · Invite`
}

function matchesStatusFilter(connection: ConnectionRecord, filter: StatusFilter): boolean {
  if (filter === 'all') return true
  if (filter === 'failed') {
    return connection.status === 'failed' || connection.last_test_ok === false
  }
  if (filter === 'connected') return connection.status === 'connected'
  return (
    connection.status === 'pending' ||
    connection.status === 'invited' ||
    connection.status === 'infra_pending'
  )
}

function formatLastTest(connection: ConnectionRecord): string {
  if (!connection.last_tested_at) return '—'
  const when = new Date(connection.last_tested_at).toLocaleString()
  if (connection.last_test_ok === true) return `${when} · ok`
  if (connection.last_test_ok === false) {
    return `${when} · ${connectTestTriageSummary(connection.last_test_detail, connection.metadata)}`
  }
  return when
}

function triageSort(a: ConnectionRecord, b: ConnectionRecord): number {
  const aFailed = a.status === 'failed' || a.last_test_ok === false ? 0 : 1
  const bFailed = b.status === 'failed' || b.last_test_ok === false ? 0 : 1
  if (aFailed !== bFailed) return aFailed - bFailed
  return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
}

function ConnectionsBody() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<ConnectionRecord | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')

  const connectionsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'connections'],
    queryFn: async () => {
      const payload = await listConnections()
      return payload.connections
    },
    refetchInterval: 30_000,
    placeholderData: (previous) => previous,
  })

  const connections = connectionsQuery.data ?? []
  const failedCount = useMemo(
    () =>
      connections.filter(
        (row) => row.status === 'failed' || row.last_test_ok === false,
      ).length,
    [connections],
  )
  const visible = useMemo(
    () =>
      connections
        .filter((row) => matchesStatusFilter(row, statusFilter))
        .slice()
        .sort(triageSort),
    [connections, statusFilter],
  )

  function onCreated(_connection: ConnectionRecord) {
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'connections'] })
  }

  return (
    <section className="taste-ops-page space-y-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Micro>Ops · Connections</Micro>
          <h2 className="mt-1 font-display text-xl font-medium tracking-tight text-ink">
            Connections
          </h2>
          <p className="mt-1 max-w-xl text-xs text-ink-soft">
            Secure owner onboarding — invite links and connection tests; credentials never appear
            here. Failed tests keep allowlisted error codes for triage.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ops/workers/settings" className="taste-btn text-xs">
            ← Worker settings
          </Link>
          <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
            New connection
          </Button>
        </div>
      </header>

      {failedCount > 0 ? (
        <div
          className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900"
          role="status"
        >
          <p>
            {failedCount} connection{failedCount === 1 ? '' : 's'} need triage — open a row for the
            last test error code and retest after the owner corrects credentials.
          </p>
          {statusFilter !== 'failed' ? (
            <Button type="button" size="sm" variant="outline" onClick={() => setStatusFilter('failed')}>
              Show failed
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap gap-1.5">
        {STATUS_FILTERS.map((item) => {
          const active = statusFilter === item.value
          return (
            <button
              key={item.value}
              type="button"
              className={cn(
                'rounded-md border px-2.5 py-1 text-xs transition-colors',
                active
                  ? 'border-ink bg-ink text-paper'
                  : 'border-line bg-paper text-ink-soft hover:border-ink/40 hover:text-ink',
              )}
              aria-pressed={active}
              onClick={() => setStatusFilter(item.value)}
            >
              {item.label}
              {item.value === 'failed' && failedCount > 0 ? ` (${failedCount})` : null}
            </button>
          )
        })}
      </div>

      <div className="taste-panel overflow-x-auto p-4 sm:p-5">
        {connectionsQuery.isPending && !connectionsQuery.data ? (
          <SkeletonLines lines={6} />
        ) : connectionsQuery.isError && !connectionsQuery.data ? (
          <div className="space-y-2">
            <p className="text-sm text-red-700" role="alert">
              {actionToast.safeErrorMessage(
                connectionsQuery.error,
                'Could not load connections.',
              )}
            </p>
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => {
                void connectionsQuery.refetch().then((result) => {
                  if (result.isError) {
                    actionToast.error({
                      title: 'Could not load connections',
                      description: actionToast.safeErrorMessage(
                        result.error,
                        'Could not load connections.',
                      ),
                      action: {
                        label: 'Retry',
                        onClick: () => {
                          void connectionsQuery.refetch()
                        },
                      },
                    })
                  }
                })
              }}
            >
              Retry
            </Button>
          </div>
        ) : connections.length === 0 ? (
          <p className="text-sm text-ink-soft">
            No connections yet. Create one to send an owner invite.
          </p>
        ) : visible.length === 0 ? (
          <p className="text-sm text-ink-soft">No connections match this filter.</p>
        ) : (
          <table className="taste-table">
            <thead>
              <tr>
                <th>System</th>
                <th>Name</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Last test / error</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((connection) => {
                const needsTriage =
                  connection.status === 'failed' || connection.last_test_ok === false
                return (
                  <tr
                    key={connection.id}
                    className={cn(
                      'cursor-pointer hover:bg-canvas/80',
                      needsTriage && 'bg-red-50/70',
                    )}
                    onClick={() => setSelected(connection)}
                  >
                    <td className="font-mono text-xs">{formatSystemLabel(connection.system)}</td>
                    <td>{connection.display_name}</td>
                    <td className="text-ink-soft">{connection.owner_email ?? '—'}</td>
                    <td>
                      <Badge variant={connectionStatusVariant(connection.status)}>
                        {connection.status.replaceAll('_', ' ')}
                      </Badge>
                    </td>
                    <td
                      className={cn(
                        'max-w-md text-xs',
                        needsTriage ? 'text-red-800' : 'text-ink-soft',
                      )}
                    >
                      {formatLastTest(connection)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>

      <ConnectionCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={onCreated}
      />

      <Dialog open={selected != null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {selected ? connectionDetailTitle(selected) : 'Connection'}
            </DialogTitle>
          </DialogHeader>
          {selected ? (
            <ConnectionInvitePanel
              connectionId={selected.id}
              system={selected.system}
              displayName={selected.display_name}
              ownerEmail={selected.owner_email ?? undefined}
              status={selected.status}
              lastTestOk={selected.last_test_ok}
              lastTestDetail={selected.last_test_detail}
              lastTestedAt={selected.last_tested_at}
              metadata={selected.metadata}
              onDone={() => setSelected(null)}
              onDeleted={() => {
                setSelected(null)
                void queryClient.invalidateQueries({
                  queryKey: ['admin-api', 'ops', 'connections'],
                })
              }}
              onUpdated={() => {
                void queryClient
                  .invalidateQueries({ queryKey: ['admin-api', 'ops', 'connections'] })
                  .then(async () => {
                    const refreshed = await queryClient.fetchQuery({
                      queryKey: ['admin-api', 'ops', 'connections'],
                      queryFn: async () => {
                        const payload = await listConnections()
                        return payload.connections
                      },
                    })
                    const next = refreshed.find((row) => row.id === selected.id)
                    if (next) setSelected(next)
                  })
              }}
            />
          ) : null}
        </DialogContent>
      </Dialog>
    </section>
  )
}

export function ConnectionsPage() {
  return (
    <RoleGate allow={isSuperAdmin}>
      <ConnectionsBody />
    </RoleGate>
  )
}
