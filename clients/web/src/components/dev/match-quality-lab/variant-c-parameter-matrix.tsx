import { Badge } from '@/components/ui/badge'

import {
  MATCH_QUALITY_PARAMETERS,
  formatCount,
  formatRate,
  parameterZeroHit,
  rateTone,
} from './fixture'
import { LabFrame } from './chrome'

function zeroTone(zero: number, requests: number): 'fail' | 'ok' | 'wait' {
  if (requests <= 0 || zero === requests) return 'fail'
  if (zero === 0) return 'ok'
  return 'wait'
}

function MatrixBadge({
  hits,
  requests,
  label,
  invert,
}: {
  hits: number
  requests: number
  label: string
  invert?: boolean
}) {
  const tone = invert ? zeroTone(hits, requests) : rateTone(hits, requests)
  return (
    <Badge variant={tone} className="normal-case tracking-normal">
      {label} · {formatRate(hits, requests)}
    </Badge>
  )
}

export function VariantCParameterMatrix() {
  return (
    <LabFrame title="C · Parameter matrix">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-line">
              <th className="h-8 px-2 text-left text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Parameter
              </th>
              <th className="h-8 px-2 text-left text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Exact
              </th>
              <th className="h-8 px-2 text-left text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Any-hit
              </th>
              <th className="h-8 px-2 text-left text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                Zero
              </th>
            </tr>
          </thead>
          <tbody>
            {MATCH_QUALITY_PARAMETERS.map((row) => {
              const zero = parameterZeroHit(row)
              return (
                <tr key={row.id} className="border-b border-line last:border-0">
                  <td className="p-2 font-medium text-ink">
                    {row.label}
                    <span className="ml-2 font-normal tabular-nums text-mute">
                      {formatCount(row.requests)}
                    </span>
                  </td>
                  <td className="p-2">
                    <MatrixBadge hits={row.exact} requests={row.requests} label="Exact" />
                  </td>
                  <td className="p-2">
                    <MatrixBadge hits={row.anyHit} requests={row.requests} label="Any-hit" />
                  </td>
                  <td className="p-2">
                    <MatrixBadge hits={zero} requests={row.requests} label="Zero" invert />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </LabFrame>
  )
}
