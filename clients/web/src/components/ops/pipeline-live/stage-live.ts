/**
 * Live stage-progress primitives for the DROP pipeline expanded card.
 * Counts only — never PII. Shared by the real Pipeline page (I7) and the
 * `/dev/pipeline-live` lab variants (I8/I9).
 */

/** Open work for one stage: `open` waiting, `in_flight` claimed by a worker. */
export interface StageLiveCounts {
  open: number
  in_flight: number
}

/**
 * Worker has drained a stage when nothing is open and nothing is in flight
 * (plan A4/A5). Drives the handoff left-border on the next stage.
 */
export function stageWorkerDone({ open, in_flight }: StageLiveCounts): boolean {
  return open === 0 && in_flight === 0
}

/**
 * Est/err label that names the selected stage (plan A6):
 * `formatStageEstLabel('Matching', 82, 1)` → `'Matching 82% · err 1%'`.
 * Unknown percent renders `—`; the err clause is omitted unless finite.
 */
export function formatStageEstLabel(
  stageName: string,
  percent: number | null | undefined,
  errPercent?: number | null,
): string {
  const pct =
    percent != null && Number.isFinite(percent)
      ? `${Math.round(percent)}%`
      : '—'
  const err =
    errPercent != null && Number.isFinite(errPercent)
      ? `err ${Math.round(errPercent)}%`
      : null
  return err ? `${stageName} ${pct} · ${err}` : `${stageName} ${pct}`
}
