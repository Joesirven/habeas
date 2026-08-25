import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  addVerticalAssignment,
  listConnectionOwnerCandidates,
  listVerticalAssignments,
  listVerticalBindings,
  listVerticalCatalog,
  removeVerticalAssignment,
  type VerticalAssignment,
  type VerticalBinding,
  type VerticalCatalogEntry,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

const VERTICALS_QUERY_KEY = ['admin-api', 'ops', 'verticals'] as const
const ASSIGNMENTS_QUERY_KEY = ['admin-api', 'ops', 'vertical-assignments'] as const

function formatApproach(approach: string): string {
  return approach.replaceAll('_', ' ')
}

function VerticalBindingsTable({ bindings }: { bindings: VerticalBinding[] }) {
  if (bindings.length === 0) {
    return <p className="text-xs text-ink-soft">No system bindings for this vertical.</p>
  }
  return (
    <table className="taste-table">
      <thead>
        <tr>
          <th>System</th>
          <th>Approaches</th>
          <th>Active</th>
        </tr>
      </thead>
      <tbody>
        {bindings.map((binding) => (
          <tr key={`${binding.vertical_id}:${binding.system}`}>
            <td className="font-mono text-xs">{binding.system}</td>
            <td className="text-xs text-ink-soft">
              {binding.allowed_approaches.length === 0
                ? '—'
                : binding.allowed_approaches.map(formatApproach).join(' · ')}
            </td>
            <td>
              <Badge variant={binding.active === false ? 'wait' : 'ok'}>
                {binding.active === false ? 'Inactive' : 'Active'}
              </Badge>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export function VerticalCatalogPanel() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [assignEmail, setAssignEmail] = useState('')

  const catalogQuery = useQuery({
    queryKey: VERTICALS_QUERY_KEY,
    queryFn: listVerticalCatalog,
    placeholderData: (previous) => previous,
  })

  const assignmentsQuery = useQuery({
    queryKey: ASSIGNMENTS_QUERY_KEY,
    queryFn: listVerticalAssignments,
    placeholderData: (previous) => previous,
  })

  const ownersQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'connection-owner-candidates'],
    queryFn: async () => {
      const payload = await listConnectionOwnerCandidates()
      return payload.owners
    },
  })

  const verticals = catalogQuery.data ?? []
  const selected =
    verticals.find((entry) => entry.id === selectedId) ?? verticals[0] ?? null

  const bindingsQuery = useQuery({
    queryKey: [...VERTICALS_QUERY_KEY, 'bindings', selected?.id],
    queryFn: () => listVerticalBindings(selected!.id),
    enabled: selected != null,
    placeholderData: (previous) => previous,
  })

  const assignments = assignmentsQuery.data ?? []
  const selectedAssignments = useMemo(
    () =>
      assignments.filter(
        (row) => row.vertical_id === selected?.id && row.active !== false,
      ),
    [assignments, selected?.id],
  )

  const addMutation = useMutation({
    mutationFn: (body: { email: string; vertical_id: string }) => addVerticalAssignment(body),
    onSuccess: (row) => {
      void queryClient.invalidateQueries({ queryKey: ASSIGNMENTS_QUERY_KEY })
      setAssignEmail('')
      actionToast.success({
        title: 'Owner assigned',
        description: `${row.email} → ${row.vertical_id}`,
      })
    },
    onError: (err) => {
      actionToast.error({
        title: 'Could not assign owner',
        description: actionToast.safeErrorMessage(err, 'Could not add vertical assignment.'),
        action: {
          label: 'Retry',
          onClick: () => {
            if (!selected || !assignEmail.trim()) return
            addMutation.mutate({
              email: assignEmail.trim(),
              vertical_id: selected.id,
            })
          },
        },
      })
    },
  })

  const removeMutation = useMutation({
    mutationFn: (row: VerticalAssignment) =>
      removeVerticalAssignment(row.vertical_id, row.email),
    onSuccess: (_void, row) => {
      void queryClient.invalidateQueries({ queryKey: ASSIGNMENTS_QUERY_KEY })
      actionToast.success({
        title: 'Assignment removed',
        description: `${row.email} removed from ${row.vertical_id}`,
      })
    },
    onError: (err, row) => {
      actionToast.error({
        title: 'Could not remove assignment',
        description: actionToast.safeErrorMessage(err, 'Could not remove vertical assignment.'),
        action: {
          label: 'Retry',
          onClick: () => removeMutation.mutate(row),
        },
      })
    },
  })

  function renderCatalogBody(entries: VerticalCatalogEntry[]) {
    if (catalogQuery.isPending && !catalogQuery.data) {
      return <SkeletonLines lines={5} />
    }
    if (catalogQuery.isError && !catalogQuery.data) {
      return (
        <div className="space-y-2">
          <p className="text-sm text-red-700" role="alert">
            {actionToast.safeErrorMessage(catalogQuery.error, 'Could not load vertical catalog.')}
          </p>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              void catalogQuery.refetch()
            }}
          >
            Retry
          </Button>
        </div>
      )
    }
    if (entries.length === 0) {
      return <p className="text-sm text-ink-soft">No verticals in catalog.</p>
    }
    return (
      <div className="flex flex-wrap gap-1.5">
        {entries.map((entry) => {
          const active = selected?.id === entry.id
          return (
            <button
              key={entry.id}
              type="button"
              className={
                active
                  ? 'rounded border border-habeas-navy/30 bg-white px-2.5 py-1 text-xs font-medium text-ink shadow-sm'
                  : 'rounded border border-line bg-canvas px-2.5 py-1 text-xs text-ink-soft hover:bg-white'
              }
              onClick={() => setSelectedId(entry.id)}
            >
              {entry.display_label}
              {entry.view_only ? ' · view only' : ''}
            </button>
          )
        })}
      </div>
    )
  }

  const busy = addMutation.isPending || removeMutation.isPending

  return (
    <div className="space-y-4">
      <div className="taste-panel space-y-3 p-4 sm:p-5">
        <div>
          <p className="text-xs font-medium text-ink">KD20 vertical catalog</p>
          <p className="mt-1 text-xs text-ink-soft">
            Department verticals, system bindings, and owner assignments. Data is view-only —
            no owner invite or upload wizard.
          </p>
        </div>
        {renderCatalogBody(verticals)}
      </div>

      {selected ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="taste-panel space-y-3 overflow-x-auto p-4 sm:p-5">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-medium text-ink">{selected.display_label}</h3>
              {selected.view_only ? <Badge variant="default">View only</Badge> : null}
            </div>
            {selected.view_only ? (
              <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                Data vertical is already connected via Infrastructure. No owner invite, Upload, or
                credential wizard — Cassandra remains INF handoff.
              </div>
            ) : null}
            {bindingsQuery.isPending && !bindingsQuery.data ? (
              <SkeletonLines lines={3} />
            ) : bindingsQuery.isError && !bindingsQuery.data ? (
              <p className="text-xs text-red-700" role="alert">
                {actionToast.safeErrorMessage(
                  bindingsQuery.error,
                  'Could not load system bindings.',
                )}
              </p>
            ) : (
              <VerticalBindingsTable bindings={bindingsQuery.data ?? []} />
            )}
          </div>

          <div className="taste-panel space-y-3 p-4 sm:p-5">
            <h3 className="text-sm font-medium text-ink">Owner assignments</h3>
            {selected.view_only ? (
              <p className="text-xs text-ink-soft">
                Assignments are optional for visibility; owners do not get a Data connector wizard.
              </p>
            ) : null}

            {assignmentsQuery.isPending && !assignmentsQuery.data ? (
              <SkeletonLines lines={3} />
            ) : assignmentsQuery.isError && !assignmentsQuery.data ? (
              <div className="space-y-2">
                <p className="text-xs text-red-700" role="alert">
                  {actionToast.safeErrorMessage(
                    assignmentsQuery.error,
                    'Could not load assignments.',
                  )}
                </p>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    void assignmentsQuery.refetch()
                  }}
                >
                  Retry
                </Button>
              </div>
            ) : selectedAssignments.length === 0 ? (
              <p className="text-xs text-ink-soft">No active assignments for this vertical.</p>
            ) : (
              <table className="taste-table">
                <thead>
                  <tr>
                    <th>Email</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {selectedAssignments.map((row) => (
                    <tr key={`${row.vertical_id}:${row.email}`}>
                      <td className="font-mono text-xs">{row.email}</td>
                      <td className="text-right">
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={busy}
                          onClick={() => removeMutation.mutate(row)}
                        >
                          Remove
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <form
              className="flex flex-wrap items-end gap-2 border-t border-line pt-3"
              onSubmit={(event) => {
                event.preventDefault()
                const email = assignEmail.trim()
                if (!email || !selected) return
                addMutation.mutate({ email, vertical_id: selected.id })
              }}
            >
              <label className="flex min-w-[14rem] flex-1 flex-col gap-1">
                <span className="text-xs text-ink-soft">Assign owner email</span>
                {ownersQuery.data && ownersQuery.data.length > 0 ? (
                  <select
                    className={`${fieldClass} text-xs`}
                    value={assignEmail}
                    onChange={(event) => setAssignEmail(event.target.value)}
                    disabled={busy}
                  >
                    <option value="">Select allowlisted owner…</option>
                    {ownersQuery.data.map((owner) => (
                      <option key={owner.email} value={owner.email}>
                        {owner.email}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="email"
                    className={`${fieldClass} text-xs`}
                    value={assignEmail}
                    onChange={(event) => setAssignEmail(event.target.value)}
                    placeholder="owner@example.com"
                    disabled={busy}
                    autoComplete="off"
                  />
                )}
              </label>
              <Button type="submit" size="sm" disabled={busy || !assignEmail.trim()}>
                {addMutation.isPending ? 'Adding…' : 'Add assignment'}
              </Button>
            </form>
          </div>
        </div>
      ) : null}
    </div>
  )
}
