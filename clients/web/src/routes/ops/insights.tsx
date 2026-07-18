import { OpsPageChrome } from '@/lib/auth'

/** Thin Insights for all resolved roles — fleet view without console power paths. */
export function OpsInsightsPage() {
  return (
    <OpsPageChrome
      eyebrow="OPS · INSIGHTS"
      title="Insights"
      support="Thin read surface for operators. Deeper fleet analytics absorb Health labeling over time; Health routes remain for super_admin."
    >
      <div className="taste-panel p-5">
        <p className="taste-micro">Shell</p>
        <p className="mt-3 text-sm text-ink-soft">
          No insights aggregates yet. Matching backlog and worker tallies stay on Needs me and (for
          super_admin) Health until U8.
        </p>
      </div>
    </OpsPageChrome>
  )
}
