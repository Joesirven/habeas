import { Badge } from '@/components/ui/badge'

import {
  MATCH_QUALITY_FIXTURE,
  MATCH_QUALITY_PARAMETERS,
  formatCount,
  formatRate,
} from './fixture'
import { LabFrame, StatusBadge } from './chrome'

export function VariantECoverageVsMatch() {
  return (
    <LabFrame title="E · Coverage vs match">
      <div className="grid gap-3 md:grid-cols-2">
        <section className="rounded-md border border-line p-3">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-mute">
            Hash-index coverage
          </p>
          <ul className="space-y-2">
            {MATCH_QUALITY_FIXTURE.coverage.map((row) => (
              <li
                key={row.mart}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line bg-canvas px-2.5 py-2"
              >
                <div>
                  <p className="font-mono text-xs text-ink">{row.mart}</p>
                  <p className="text-[11px] text-mute">{row.note}</p>
                </div>
                <Badge variant={row.gap ? 'fail' : 'ok'}>
                  {row.states === 0 ? '0 states' : `${row.states} states`}
                </Badge>
              </li>
            ))}
          </ul>
        </section>
        <section className="rounded-md border border-line p-3">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-mute">
            Match rates
          </p>
          <ul className="space-y-2">
            {MATCH_QUALITY_PARAMETERS.map((row) => (
              <li
                key={row.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line px-2.5 py-2"
              >
                <div>
                  <p className="text-xs font-medium text-ink">{row.label}</p>
                  <p className="text-[11px] tabular-nums text-mute">
                    Exact {formatRate(row.exact, row.requests)} · any-hit{' '}
                    {formatRate(row.anyHit, row.requests)} · {formatCount(row.requests)}{' '}
                    requests
                  </p>
                </div>
                <StatusBadge row={row} />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </LabFrame>
  )
}
