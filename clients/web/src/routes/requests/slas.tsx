import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'
import { getLegalSlaSettings, patchLegalSlaSettings } from '@/lib/api'
import { canAccessLegalSurfaces, canMutateLegalSettings, RouteShell, useMe } from '@/lib/auth'

const SLA_FIELDS = [
  ['data_owner_review_days', 'Data owner review (days)'],
  ['legal_pre_fulfillment_days', 'Legal / pre-fulfillment (days)'],
  ['fulfillment_days', 'Fulfillment (days)'],
  ['lifecycle_days', 'Overall lifecycle (days)'],
] as const

function DeadlinesSlasForm() {
  const { role } = useMe()
  const canWrite = canMutateLegalSettings(role)
  const queryClient = useQueryClient()

  const slaQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'settings', 'sla'],
    queryFn: getLegalSlaSettings,
  })

  const slaMutation = useMutation({
    mutationFn: patchLegalSlaSettings,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'legal', 'settings', 'sla'] })
    },
  })

  if (slaQuery.isPending) {
    return <p className="text-sm text-mute">Loading deadline settings…</p>
  }

  if (!slaQuery.data) {
    return <p className="text-sm text-mute">Deadline settings unavailable.</p>
  }

  return (
    <div className="space-y-4">
      {!canWrite ? (
        <p className="flex items-center gap-2 text-xs text-mute">
          <span aria-hidden="true">🔒</span>
          Read-only — admin role required to save changes.
        </p>
      ) : null}
      <p className="text-sm text-ink-soft">
        Global stage and lifecycle SLA durations. Per-request due dates are calculated from
        received datetime and stage entry; admins may override individual deadlines from request
        detail.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {SLA_FIELDS.map(([key, label]) => (
          <label key={key} className="block text-xs text-ink-soft">
            {label}
            <input
              type="number"
              min={1}
              className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm"
              defaultValue={slaQuery.data[key]}
              disabled={!canWrite}
              onBlur={(event) => {
                if (!canWrite) return
                const value = Number.parseInt(event.target.value, 10)
                if (!Number.isFinite(value)) return
                slaMutation.mutate({ [key]: value })
              }}
            />
          </label>
        ))}
      </div>
      {slaQuery.data.updated_at ? (
        <p className="text-xs text-mute">
          Last updated {new Date(slaQuery.data.updated_at).toLocaleString()}
        </p>
      ) : null}
    </div>
  )
}

export function RequestsSlasPage() {
  const { role } = useMe()
  const legalSurface = canAccessLegalSurfaces(role)

  if (legalSurface) {
    return (
      <section className="space-y-6">
        <header>
          <p className="taste-micro">Legal</p>
          <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">
            Deadlines & SLAs
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Configure global breach clocks for data owner review, legal pre-fulfillment, fulfillment,
            and overall request lifecycle.
          </p>
        </header>
        <div className="taste-panel-soft space-y-3 p-6 sm:p-7">
          <DeadlinesSlasForm />
          <Button asChild size="sm" variant="outline">
            <Link to="/requests/needs-attention" search={{ filter: 'fulfillment' }}>
              Open Inbox · Fulfillment
            </Link>
          </Button>
        </div>
      </section>
    )
  }

  return (
    <RouteShell
      eyebrow="Requests"
      title="Deadlines & SLAs"
      description="Global stage and lifecycle SLA durations for legal and admin operators."
      note="Shell submenu — deadline risk on Home and inbox badges use calculated per-request due dates."
    />
  )
}
