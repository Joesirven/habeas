import { formatCount, funnelTotals } from './fixture'
import { LabFrame } from './chrome'

const STAGES = [
  { key: 'requests', label: 'Requests', color: 'bg-habeas-navy' },
  { key: 'anyHit', label: 'Any-hit', color: 'bg-habeas-mid' },
  { key: 'exact', label: 'Exact', color: 'bg-habeas-light' },
  { key: 'people', label: 'Habeas people', color: 'bg-[#1E4191]/60' },
] as const

export function VariantDFunnel() {
  const totals = funnelTotals()
  const max = totals.requests
  return (
    <LabFrame title="D · Funnel">
      <ol className="space-y-2">
        {STAGES.map((stage) => {
          const value = totals[stage.key]
          const width = Math.max(8, Math.round((value / max) * 100))
          return (
            <li key={stage.key}>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="text-xs font-medium text-ink">{stage.label}</span>
                <span className="font-mono text-[11px] tabular-nums text-mute">
                  {formatCount(value)}
                </span>
              </div>
              <div className="h-6 overflow-hidden rounded-md bg-canvas">
                <div
                  className={`h-full ${stage.color}`}
                  style={{ width: `${width}%` }}
                  aria-hidden
                />
              </div>
            </li>
          )
        })}
      </ol>
      <p className="mt-3 text-[11px] leading-relaxed text-mute">
        Any-hit and exact are sums across Email, NDZ, and Phone. Habeas people is distinct
        exact matches ({formatCount(totals.people)}), not a sum of parameter exacts.
      </p>
    </LabFrame>
  )
}
