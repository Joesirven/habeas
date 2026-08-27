/**
 * Variant F — Review-first work queue. DEV lab only (`/dev/pipeline-live?v=f`).
 * Counts only — no PII. Verticals differ by label and position, never hue.
 */
import { Link } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import {
  LIVE_VERTICALS,
  PIPELINE_LIVE_FIXTURE,
  formatCount,
  formatPercent,
} from './fixture'
import { CatalogOnlySection, LabFrame, VerticalName } from './chrome'

function NeedsReviewChip({ count }: { count: number }) {
  return (
    <span className="inline-flex items-center rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[0.65rem] font-medium uppercase tracking-wide text-amber-800">
      Needs review · {formatCount(count)}
    </span>
  )
}

export function VariantFReviewQueue() {
  // Work-queue order: most open review first; stable by catalog order.
  const rows = LIVE_VERTICALS.map((vertical, index) => ({ vertical, index })).sort((a, b) => {
    if (b.vertical.stages.review.open !== a.vertical.stages.review.open) {
      return b.vertical.stages.review.open - a.vertical.stages.review.open
    }
    return a.index - b.index
  })

  const openTotal = LIVE_VERTICALS.reduce((sum, row) => sum + row.stages.review.open, 0)
  const resolvedTotal = LIVE_VERTICALS.reduce((sum, row) => sum + row.stages.review.success, 0)

  return (
    <LabFrame title="F · Review-first work queue">
      <div className="space-y-3">
        <section className="flex flex-wrap items-center gap-3 rounded-md border border-line px-3 py-2.5">
          <div>
            <p className="text-lg font-semibold tabular-nums leading-tight text-ink">
              {formatCount(openTotal)}
            </p>
            <p className="text-[11px] text-mute">
              items need review · {formatCount(resolvedTotal)} resolved
            </p>
          </div>
          {openTotal > 0 ? <NeedsReviewChip count={openTotal} /> : null}
          <Link
            to="/requests/needs-attention"
            search={{ bulk: PIPELINE_LIVE_FIXTURE.processId }}
            className="taste-btn ml-auto inline-flex px-2 py-0.5 text-[0.6rem]"
          >
            Matching results
            {openTotal > 0 ? ` · ${formatCount(openTotal)}` : ''}
          </Link>
        </section>

        <ul className="space-y-1">
          {rows.map(({ vertical }) => {
            const review = vertical.stages.review
            const hasWork = review.open > 0
            return (
              <li
                key={vertical.id}
                className={cn(
                  'flex flex-wrap items-center gap-2 rounded-md border border-line px-2.5 py-2',
                  !hasWork && 'bg-canvas/50',
                )}
              >
                <span
                  className={cn(
                    'w-14 shrink-0 text-sm font-semibold tabular-nums',
                    hasWork ? 'text-amber-800' : 'text-mute',
                  )}
                >
                  {formatCount(review.open)}
                </span>
                <VerticalName vertical={vertical} />
                {hasWork ? <NeedsReviewChip count={review.open} /> : null}
                {review.failed > 0 ? (
                  <Badge variant="fail">Failed {formatCount(review.failed)}</Badge>
                ) : null}
                <span className="text-[11px] tabular-nums text-mute">
                  Matching {formatPercent(vertical.stages.matching)} · resolved{' '}
                  {formatCount(review.success)}
                </span>
                <Link
                  to="/requests/needs-attention"
                  search={{ bulk: PIPELINE_LIVE_FIXTURE.processId, vertical: vertical.id }}
                  className="taste-link ml-auto text-[11px]"
                >
                  Matching results
                </Link>
              </li>
            )
          })}
        </ul>

        <p className="text-[11px] leading-relaxed text-mute">
          The card answers “where is my work,” not “what did workers do” — open review heroes
          the row, matching percent is demoted to context.
        </p>

        <CatalogOnlySection />
      </div>
    </LabFrame>
  )
}
