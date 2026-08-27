import { Badge } from '@/components/ui/badge'

import { MATCH_QUALITY_PARAMETERS, formatCount, formatRate } from './fixture'
import { DenseRateTable, LabFrame } from './chrome'

export function VariantBAlertRail() {
  const email = MATCH_QUALITY_PARAMETERS[0]
  return (
    <LabFrame title="B · Alert rail">
      <div
        className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-900"
        role="alert"
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="fail">P0</Badge>
          <p className="font-medium">Email match rate is 0%</p>
        </div>
        <p className="mt-1 leading-relaxed">
          {formatCount(email.requests)} CA DROP delete requests · exact{' '}
          {formatRate(email.exact, email.requests)} · any-hit{' '}
          {formatRate(email.anyHit, email.requests)}. Treat as a breach until{' '}
          <span className="font-mono">email_hash</span> CA coverage is non-zero.
        </p>
      </div>
      <DenseRateTable />
    </LabFrame>
  )
}
