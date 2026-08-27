import { cn } from '@/lib/utils'

export interface SegmentedStageBarProps {
  /** Finished (success) count — emerald, leading segment. */
  finished: number
  /** Claimed by a worker right now — habeas-light, carries the shimmer. */
  inFlight: number
  /** Waiting to be worked — muted middle segment. */
  queued: number
  /** Failed count — red, trailing segment. */
  failed?: number
  /** Explicit denominator; defaults to the sum of the four segments. */
  total?: number
  /**
   * White-sheen pulse overlay on the in-flight segment. Defaults to
   * `inFlight > 0`. Pass `false` for static fixtures / reconciliation paints.
   */
  running?: boolean
  className?: string
}

function clampCount(value: number | undefined): number {
  if (value == null || !Number.isFinite(value) || value <= 0) return 0
  return value
}

/**
 * Plan A2 — one bar split finished / in-flight / queued (/ failed) so the
 * expanded card shows live drain, not just a single done-percent fill.
 * Flat segment fills only. The in-flight segment carries a white-sheen
 * `animate-pulse` overlay — the page's pulse language (StatusLight ping,
 * confirm-dialog pulse) applied to the segment, not a gradient fill.
 */
export function SegmentedStageBar({
  finished,
  inFlight,
  queued,
  failed = 0,
  total,
  running,
  className,
}: SegmentedStageBarProps) {
  const safeFinished = clampCount(finished)
  const safeInFlight = clampCount(inFlight)
  const safeQueued = clampCount(queued)
  const safeFailed = clampCount(failed)
  const denominator =
    total != null && Number.isFinite(total) && total > 0
      ? total
      : safeFinished + safeInFlight + safeQueued + safeFailed

  const segments: { key: string; count: number; className: string }[] = [
    { key: 'finished', count: safeFinished, className: 'bg-emerald-600' },
    { key: 'in-flight', count: safeInFlight, className: 'bg-habeas-light' },
    { key: 'queued', count: safeQueued, className: 'bg-line-strong' },
    { key: 'failed', count: safeFailed, className: 'bg-red-600' },
  ]

  const showShimmer = (running ?? safeInFlight > 0) && safeInFlight > 0
  const label =
    denominator > 0
      ? `Finished ${safeFinished} · in flight ${safeInFlight} · queued ${safeQueued} · failed ${safeFailed} of ${denominator}`
      : 'No work in this stage yet'

  return (
    <div
      className={cn(
        'relative h-1.5 overflow-hidden rounded-full bg-line/60',
        className,
      )}
      role="img"
      aria-label={label}
      title={label}
    >
      {denominator > 0 ? (
        <div className="flex h-full w-full">
          {segments.map((segment) => {
            if (segment.count <= 0) return null
            const width = (segment.count / denominator) * 100
            if (segment.key === 'in-flight') {
              return (
                <div
                  key={segment.key}
                  className={cn(
                    'relative h-full shrink-0 overflow-hidden transition-[width]',
                    segment.className,
                  )}
                  style={{ width: `${width}%` }}
                >
                  {showShimmer ? (
                    <div className="pointer-events-none absolute inset-0 animate-pulse bg-gradient-to-r from-transparent via-white/50 to-transparent" />
                  ) : null}
                </div>
              )
            }
            return (
              <div
                key={segment.key}
                className={cn(
                  'h-full shrink-0 transition-[width]',
                  segment.className,
                )}
                style={{ width: `${width}%` }}
              />
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
