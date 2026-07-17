import { RouteShell } from '@/lib/auth'

export function RequestsSlasPage() {
  return (
    <RouteShell
      eyebrow="Requests"
      title="SLAs"
      description="Stale and waiting filters only in v1 — breach clocks and SLA monitor wiring are deferred."
      note="Shell submenu — filter presets for stale / waiting-on-review requests ship with journey APIs."
    />
  )
}
