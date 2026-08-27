import { cn } from '@/lib/utils'

export interface ChipMicroBarProps {
  /** 0–100; clamped. Null / non-finite renders an empty track. */
  percent: number | null | undefined
  /** Fill tone — navy default; emerald done, red failed, mute queued. */
  tone?: 'navy' | 'emerald' | 'red' | 'mute'
  className?: string
}

const TONE_FILL: Record<NonNullable<ChipMicroBarProps['tone']>, string> = {
  navy: 'bg-habeas-navy',
  emerald: 'bg-emerald-600',
  red: 'bg-red-600',
  mute: 'bg-line-strong',
}

/**
 * Plan A10 — 2px underline under compact stage chips; width is the stage
 * percent. Decorative: the chip above it already carries the label/counts,
 * so the bar is aria-hidden.
 */
export function ChipMicroBar({
  percent,
  tone = 'navy',
  className,
}: ChipMicroBarProps) {
  const clamped =
    percent != null && Number.isFinite(percent)
      ? Math.max(0, Math.min(100, percent))
      : 0
  return (
    <div
      className={cn(
        'h-0.5 w-full overflow-hidden rounded-full bg-line/60',
        className,
      )}
      aria-hidden="true"
    >
      <div
        className={cn('h-full rounded-full transition-[width]', TONE_FILL[tone])}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}
