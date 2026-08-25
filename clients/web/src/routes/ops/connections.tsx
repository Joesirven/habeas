import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { ConnectionCreateDialog } from '@/components/ops/ConnectionCreateDialog'
import { ConnectionInvitePanel } from '@/components/ops/ConnectionInvitePanel'
import { VerticalCatalogPanel } from '@/components/ops/VerticalCatalogPanel'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { listConnections, type ConnectionRecord } from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, isSuperAdmin } from '@/lib/auth'
import {
  connectionDisplayStatusLabel,
  connectionDisplayStatusVariant,
  resolveConnectionChipStatus,
} from '@/lib/connection-display'

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function formatSystemLabel(system: string): string {
  return system.replaceAll('_', ' ')
}

function connectionDetailTitle(connection: ConnectionRecord): string {
  if (connection.system === 'cassandra') {
    return `${connection.display_name} · Infrastructure`
  }
  return connection.display_name
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

function ConnectionsTable({
  connections,
  loading,
  error,
  onRetry,
  onSelect,
}: {
  connections: ConnectionRecord[]
  loading: boolean
  error: unknown
  onRetry: () => void
  onSelect: (connection: ConnectionRecord) => void
}) {
  if (loading) {
    return <SkeletonLines lines={6} />
  }
  if (error) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-red-700" role="alert">
          {actionToast.safeErrorMessage(error, 'Could not load connections.')}
        </p>
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
      </div>
    )
  }
  if (connections.length === 0) {
    return (
      <p className="text-sm text-ink-soft">
        No connections yet. Create one, then assign verticals on the Verticals tab.
      </p>
    )
  }
  return (
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
        {connections.map((connection) => {
          const chip = resolveConnectionChipStatus(connection)
          return (
            <tr
              key={connection.id}
              className="cursor-pointer hover:bg-canvas/80"
              onClick={() => onSelect(connection)}
            >
              <td className="font-mono text-xs">{formatSystemLabel(connection.system)}</td>
              <td>{connection.display_name}</td>
              <td className="text-ink-soft">{connection.owner_email ?? '—'}</td>
              <td>
                <Badge variant={connectionDisplayStatusVariant(chip)}>
                  {connectionDisplayStatusLabel(chip)}
                </Badge>
              </td>
              <td className="text-xs text-ink-soft">{formatLastTest(connection)}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

function ConnectionsBody() {
  const queryClient = useQueryClient()
  const [createOpen, setCreateOpen] = useState(false)
  const [selected, setSelected] = useState<ConnectionRecord | null>(null)
  const [tab, setTab] = useState('connections')

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
            Connection registry, gated status, and vertical catalog assignments — credentials never
            appear here. Owners complete setup from Connectors after vertical assignment.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Link to="/ops/workers/settings" className="taste-btn text-xs">
            ← Worker settings
          </Link>
          {tab === 'connections' ? (
            <Button type="button" size="sm" onClick={() => setCreateOpen(true)}>
              New connection
            </Button>
          ) : null}
        </div>
      </header>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList aria-label="Connections views">
          <TabsTrigger value="connections">Connections</TabsTrigger>
          <TabsTrigger value="verticals">Verticals</TabsTrigger>
        </TabsList>

        <TabsContent value="connections">
          <div className="taste-panel overflow-x-auto p-4 sm:p-5">
            <ConnectionsTable
              connections={connections}
              loading={connectionsQuery.isPending && !connectionsQuery.data}
              error={
                connectionsQuery.isError && !connectionsQuery.data
                  ? connectionsQuery.error
                  : null
              }
              onRetry={() => {
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
              onSelect={setSelected}
            />
          </div>
        </TabsContent>

        <TabsContent value="verticals">
          <VerticalCatalogPanel />
        </TabsContent>
      </Tabs>

      <ConnectionCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={onCreated}
      />

      <Dialog open={selected != null} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="max-w-lg">
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
              displayStatus={selected.display_status}
              gateCode={selected.gate_code}
              gateAllowed={selected.gate_allowed}
              metadata={selected.metadata}
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
