import { RouteShell } from '@/lib/auth'

export function NeedsAttentionPage() {
  return (
    <RouteShell
      eyebrow="Requests"
      title="Needs attention"
      description="Human gates and blockers — pending matching review and other approval queues reshaped here."
    />
  )
}
