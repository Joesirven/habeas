import { Badge } from '@/components/ui/badge'

import {
  MATCH_QUALITY_FIXTURE,
  MATCH_QUALITY_PARAMETERS,
  formatCount,
  formatRate,
} from './fixture'
import { LabFrame, StatusBadge } from './chrome'

export function VariantFVerticalSplit() {
  return (
    <LabFrame title="F · Vertical split">
      <div className="space-y-3">
        <section className="rounded-md border border-habeas-navy/30 p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium text-ink">Data · DROP hash</p>
            <Badge variant="run">Live</Badge>
          </div>
          <ul className="grid gap-2 sm:grid-cols-3">
            {MATCH_QUALITY_PARAMETERS.map((row) => (
              <li key={row.id} className="rounded-md border border-line px-2.5 py-2">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-ink">{row.label}</p>
                  <StatusBadge row={row} />
                </div>
                <p className="mt-1 text-[11px] tabular-nums text-mute">
                  {formatCount(row.requests)} · exact {formatRate(row.exact, row.requests)} ·
                  any-hit {formatRate(row.anyHit, row.requests)}
                </p>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-md border border-line p-3">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <p className="text-xs font-medium text-ink">Auth0</p>
            <Badge variant="run">Live</Badge>
            <Badge variant="fail">0 hits</Badge>
          </div>
          <p className="mb-2 text-[11px] text-mute">
            Four matching snapshots. Email hash is empty, so every snapshot is 0 hits.
          </p>
          <ul className="grid gap-1 sm:grid-cols-4">
            {MATCH_QUALITY_FIXTURE.auth0Snapshots.map((snap) => (
              <li
                key={snap.id}
                className="rounded-md border border-line bg-canvas px-2 py-1.5 text-[11px]"
              >
                <p className="font-medium text-ink">{snap.label}</p>
                <p className="tabular-nums text-mute">{snap.hits} hits</p>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-md border border-dashed border-line bg-canvas p-3 opacity-70">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-mute">
            Catalog-only — matching is not live
          </p>
          <ul className="grid gap-2 sm:grid-cols-2">
            {MATCH_QUALITY_FIXTURE.catalogOnly.map((row) => (
              <li
                key={row.id}
                className="flex items-center justify-between gap-2 rounded-md border border-line bg-white px-2.5 py-2"
              >
                <div>
                  <p className="text-xs text-ink-soft">{row.label}</p>
                  <p className="text-[11px] text-mute">{row.vertical}</p>
                </div>
                <Badge variant="wait">Catalog-only</Badge>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </LabFrame>
  )
}
