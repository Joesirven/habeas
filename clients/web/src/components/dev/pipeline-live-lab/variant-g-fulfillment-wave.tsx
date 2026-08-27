/**
 * Variant G — Fulfillment wave. DEV lab only (`/dev/pipeline-live?v=g`).
 * Counts only — no PII. Verticals differ by label and position, never hue.
 */
import { cn } from '@/lib/utils'

import {
  LIVE_VERTICALS,
  formatCount,
  formatPercent,
  microBarTone,
  stagePercent,
  stageVisual,
  type StageCounts,
} from './fixture'
import {
  CatalogOnlySection,
  LabFrame,
  MicroBar,
  StatusLight,
  VerticalName,
} from './chrome'

function fulfillmentTiles(counts: StageCounts) {
  return [
    { key: 'queued', label: 'Queued', value: counts.open, text: 'text-sky-950' },
    { key: 'in_flight', label: 'In flight', value: counts.inFlight, text: 'text-habeas-navy' },
    { key: 'failed', label: 'Failed', value: counts.failed, text: 'text-red-800' },
    { key: 'finished', label: 'Finished', value: counts.success, text: 'text-emerald-900' },
  ] as const
}

export function VariantGFulfillmentWave() {
  return (
    <LabFrame title="G · Fulfillment wave">
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2 lg:grid-cols-5">
          {LIVE_VERTICALS.map((vertical) => {
            const counts = vertical.stages.fulfillment
            const visual = stageVisual(counts)
            return (
              <section
                key={vertical.id}
                className="rounded-md border border-line p-2.5"
                aria-label={`${vertical.label} fulfillment`}
              >
                <header className="mb-2 flex items-center gap-1.5">
                  <StatusLight tone={visual.light} pulse={visual.pulse} title={visual.state} />
                  <div className="min-w-0 flex-1">
                    <VerticalName vertical={vertical} />
                  </div>
                  <span className="ml-auto shrink-0 text-[11px] tabular-nums text-mute">
                    {formatPercent(counts)}
                  </span>
                </header>
                <ul className="space-y-1">
                  {fulfillmentTiles(counts).map((tile) => (
                    <li
                      key={tile.key}
                      className={cn(
                        'flex items-center justify-between rounded-md border border-line px-2 py-1.5',
                        tile.key === 'failed' && tile.value > 0 && 'border-red-200 bg-red-50/70',
                      )}
                    >
                      <span className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
                        {tile.label}
                      </span>
                      <span className={cn('text-sm font-semibold tabular-nums', tile.text)}>
                        {formatCount(tile.value)}
                      </span>
                    </li>
                  ))}
                </ul>
                <MicroBar
                  className="mt-2"
                  percent={stagePercent(counts)}
                  tone={microBarTone(visual)}
                  shimmer={counts.inFlight > 0}
                />
              </section>
            )
          })}
        </div>

        <p className="text-[11px] leading-relaxed text-mute">
          One column per vertical — Queued · In flight · Failed · Finished stacked. The column
          with the tall Queued tile and empty Finished tile is the laggard, visible by shape
          before numbers.
        </p>

        <CatalogOnlySection />
      </div>
    </LabFrame>
  )
}
