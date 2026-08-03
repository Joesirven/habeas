import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

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
import { listConnections, type ConnectionRecord } from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, isSuperAdmin } from '@/lib/auth'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

type ConnectionStatus = ConnectionRecord['status']

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

function formatLastTest(connection: ConnectionRecord): string {
  if (!connection.last_tested_at) return '—'
  const when = new Date(connection.last_tested_at).toLocaleString()
  if (connection.last_test_ok === true) return `${when} · ok`
  if (connection.last_test_ok === false) {
    const detail = connection.last_test_detail?.trim()
    return detail ? `${when} · fail (${detail})` : `${when} · fail`
  }
  return when
}

function ConnectionsBody() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<ConnectionRecord | null>(null)

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
            here.
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
        ) : (
          <table className="taste-table">
            <thead>
              <tr>
                <th>System</th>
                <th>Name</th>
                <th>Owner</th>
                <th>Status</th>
                <th>Last test</th>
              </tr>
            </thead>
            <tbody>
              {connections.map((connection) => (
                <tr
                  key={connection.id}
                  className="cursor-pointer hover:bg-canvas/80"
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
                  <td className="text-xs text-ink-soft">{formatLastTest(connection)}</td>
                </tr>
              ))}
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
