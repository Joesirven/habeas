import { DenseRateTable, LabFrame } from './chrome'

export function VariantGRunningVsBatch() {
  return (
    <LabFrame title="G · Running vs batch">
      <p className="mb-3 rounded-md border border-line bg-canvas px-3 py-2 text-[11px] leading-relaxed text-ink-soft">
        Batch = this 2026-08-26 snapshot. Running = same rates for now — no separate
        rolling window is wired yet.
      </p>
      <DenseRateTable dualRunning />
    </LabFrame>
  )
}
