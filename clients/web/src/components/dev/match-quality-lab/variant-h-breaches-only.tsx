import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

import {
  MATCH_QUALITY_FIXTURE,
  MATCH_QUALITY_PARAMETERS,
  formatCount,
  formatRate,
} from './fixture'
import { LabFrame, StatusBadge } from './chrome'

export function VariantHBreachesOnly() {
  const [showHealthy, setShowHealthy] = useState(false)
  const email = MATCH_QUALITY_PARAMETERS.find((row) => row.id === 'email')
  const healthy = MATCH_QUALITY_PARAMETERS.filter((row) => !row.breach)
  const emailCoverage = MATCH_QUALITY_FIXTURE.coverage.find((row) => row.mart === 'email_hash')

  return (
    <LabFrame title="H · Breaches-only ticker">
      <ol className="space-y-2">
        {email ? (
          <li className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="fail">Breach</Badge>
              <p className="font-medium">Email exact / any-hit 0%</p>
            </div>
            <p className="mt-1 tabular-nums">
              {formatCount(email.requests)} requests · exact {formatRate(email.exact, email.requests)}{' '}
              · any-hit {formatRate(email.anyHit, email.requests)}
            </p>
          </li>
        ) : null}
        {emailCoverage ? (
          <li className="rounded-md border border-red-200 px-3 py-2 text-xs">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="fail">Coverage gap</Badge>
              <p className="font-medium text-ink">
                <span className="font-mono">email_hash</span> CA unknown / likely 0
              </p>
            </div>
            <p className="mt-1 text-mute">{emailCoverage.note} · 0 states in serving mart</p>
          </li>
        ) : null}
      </ol>

      <div className="mt-3">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={() => setShowHealthy((open) => !open)}
        >
          {showHealthy ? 'Hide healthy rates' : 'Show healthy Phone / NDZ'}
        </Button>
      </div>

      {showHealthy ? (
        <ul className="mt-3 space-y-2">
          {healthy.map((row) => (
            <li
              key={row.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-line px-3 py-2"
            >
              <div>
                <p className="text-xs font-medium text-ink">{row.label}</p>
                <p className="text-[11px] tabular-nums text-mute">
                  Exact {formatRate(row.exact, row.requests)} · any-hit{' '}
                  {formatRate(row.anyHit, row.requests)} · {formatCount(row.requests)} requests
                </p>
              </div>
              <StatusBadge row={row} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-[11px] text-mute">
          Phone and NDZ rates are hidden. Open the toggle to compare healthy parameters.
        </p>
      )}
    </LabFrame>
  )
}
