import { useParams } from '@tanstack/react-router'

import { RouteShell } from '@/lib/auth'

export function RequestDetailPage() {
  const { requestId } = useParams({ from: '/requests/$requestId' })

  return (
    <RouteShell
      eyebrow="Request"
      title={requestId}
      description="Overview, journey lineage, and request-scoped matching — Dagster-style stage rail without PII."
    />
  )
}
