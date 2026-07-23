import { Link } from '@tanstack/react-router'

import { Button } from '@/components/ui/button'
import { canAccessLegalSurfaces, RouteShell, useMe } from '@/lib/auth'

export function RequestsSlasPage() {
  const { role } = useMe()
  const legalSurface = canAccessLegalSurfaces(role)

  if (legalSurface) {
    return (
      <section className="space-y-6">
        <header>
          <p className="taste-micro">Legal</p>
          <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">
            SLAs
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Breach clocks and waiting-on-review presets ship with journey monitors. Until
            then, clear Triage and Escalations from Inbox on the case due labels.
          </p>
        </header>
        <div className="taste-panel-soft space-y-3 p-6 sm:p-7">
          <p className="text-sm text-ink-soft">
            Inbox rows show overdue / due soon from the matching-review SLA window. Dedicated
            Legal SLA filters are deferred.
          </p>
          <Button asChild size="sm">
            <Link to="/requests/needs-attention" search={{ kind: 'triage' }}>
              Open Inbox · Triage
            </Link>
          </Button>
        </div>
      </section>
    )
  }

  return (
    <RouteShell
      eyebrow="Requests"
      title="SLAs"
      description="Stale and waiting filters only in v1 — breach clocks and SLA monitor wiring are deferred."
      note="Shell submenu — filter presets for stale / waiting-on-review requests ship with journey APIs."
    />
  )
}
