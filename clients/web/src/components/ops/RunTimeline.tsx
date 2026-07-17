import type { RunTimelineStep } from '@/lib/api'

function stepStatusClass(status: RunTimelineStep['status']): string {
  switch (status) {
    case 'completed':
      return 'bg-habeas-mid'
    case 'failed':
      return 'bg-red-700/70'
    case 'running':
      return 'bg-habeas-light animate-pulse'
    case 'skipped':
      return 'bg-line-strong'
    default:
      return 'border border-line-strong bg-paper'
  }
}

function stepLabelClass(status: RunTimelineStep['status']): string {
  switch (status) {
    case 'completed':
      return 'text-ink'
    case 'failed':
      return 'text-red-800'
    case 'running':
      return 'text-habeas-navy'
    default:
      return 'text-ink-soft'
  }
}

function formatTimestamp(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

type RunTimelineProps = {
  steps: RunTimelineStep[]
  emptyMessage?: string
}

export function RunTimeline({ steps, emptyMessage = 'No timeline steps recorded.' }: RunTimelineProps) {
  if (steps.length === 0) {
    return <p className="text-sm text-ink-soft">{emptyMessage}</p>
  }

  return (
    <ol className="relative space-y-0" aria-label="Run timeline">
      {steps.map((step, index) => {
        const isLast = index === steps.length - 1
        return (
          <li key={`${step.key}-${index}`} className="relative flex gap-4 pb-6 last:pb-0">
            {!isLast ? (
              <span
                className="absolute left-[7px] top-4 h-[calc(100%-0.5rem)] w-px bg-line"
                aria-hidden="true"
              />
            ) : null}
            <span
              className={`relative z-10 mt-1.5 h-3.5 w-3.5 shrink-0 rounded-full ${stepStatusClass(step.status)}`}
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className={`text-sm font-medium ${stepLabelClass(step.status)}`}>{step.label}</p>
                <time className="taste-micro tabular-nums normal-case tracking-normal">
                  {formatTimestamp(step.timestamp)}
                </time>
              </div>
              {step.detail ? (
                <p className="mt-1 text-xs text-ink-soft">{step.detail}</p>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
