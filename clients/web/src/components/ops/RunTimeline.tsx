import type { RunTimelineStep } from '@/lib/api'

function stepStatusClass(status: RunTimelineStep['status']): string {
  switch (status) {
    case 'completed':
      return 'bg-habeas-mid'
    case 'failed':
      return 'bg-red-700/70'
    case 'running':
      return 'bg-habeas-light animate-pulse ring-2 ring-habeas-mid/40'
    case 'waiting':
      return 'border-2 border-habeas-mid bg-paper'
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
      return 'text-habeas-navy font-semibold'
    case 'waiting':
      return 'text-habeas-mid'
    default:
      return 'text-ink-soft'
  }
}

function connectorClass(prevStatus: RunTimelineStep['status'] | null): string {
  if (prevStatus === 'failed') return 'bg-red-300/80'
  if (prevStatus === 'completed') return 'bg-habeas-mid/50'
  return 'bg-line'
}

function formatTimestamp(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

type RunTimelineProps = {
  steps: RunTimelineStep[]
  emptyMessage?: string
  orientation?: 'vertical' | 'horizontal'
}

function VerticalRunTimeline({
  steps,
  emptyMessage,
}: {
  steps: RunTimelineStep[]
  emptyMessage: string
}) {
  if (steps.length === 0) {
    return <p className="text-sm text-ink-soft">{emptyMessage}</p>
  }

  return (
    <ol className="relative space-y-0" aria-label="Run timeline">
      {steps.map((step, index) => {
        const isLast = index === steps.length - 1
        return (
          <li key={`${step.key}-${index}`} className="relative flex gap-3 pb-5 last:pb-0">
            {!isLast ? (
              <span
                className="absolute left-[6px] top-3.5 h-[calc(100%-0.25rem)] w-px bg-line"
                aria-hidden="true"
              />
            ) : null}
            <span
              className={`relative z-10 mt-1 h-3 w-3 shrink-0 rounded-full ${stepStatusClass(step.status)}`}
              aria-hidden="true"
            />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className={`text-xs font-medium ${stepLabelClass(step.status)}`}>{step.label}</p>
                <time className="taste-micro tabular-nums normal-case tracking-normal">
                  {formatTimestamp(step.timestamp)}
                </time>
              </div>
              {step.detail ? (
                <p className="mt-0.5 text-[0.65rem] text-ink-soft">{step.detail}</p>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

function HorizontalRunTimeline({
  steps,
  emptyMessage,
}: {
  steps: RunTimelineStep[]
  emptyMessage: string
}) {
  if (steps.length === 0) {
    return <p className="text-sm text-ink-soft">{emptyMessage}</p>
  }

  return (
    <ol className="flex w-full items-start" aria-label="Run timeline">
      {steps.map((step, index) => {
        const prevStatus = index > 0 ? steps[index - 1]!.status : null
        const isLast = index === steps.length - 1
        return (
          <li
            key={`${step.key}-${index}`}
            className={`flex min-w-0 flex-1 flex-col items-center ${step.status === 'running' ? 'relative z-10' : ''}`}
          >
            <div className="flex w-full items-center">
              {index > 0 ? (
                <span
                  className={`h-0.5 min-w-2 flex-1 ${connectorClass(prevStatus)}`}
                  aria-hidden="true"
                />
              ) : (
                <span className="flex-1" aria-hidden="true" />
              )}
              <span
                className={`mx-1 h-3.5 w-3.5 shrink-0 rounded-full ${stepStatusClass(step.status)}`}
                aria-hidden="true"
                title={step.label}
              />
              {!isLast ? (
                <span
                  className={`h-0.5 min-w-2 flex-1 ${connectorClass(step.status)}`}
                  aria-hidden="true"
                />
              ) : (
                <span className="flex-1" aria-hidden="true" />
              )}
            </div>
            <div className="mt-2 w-full px-1 text-center">
              <p className={`text-[0.65rem] font-medium leading-tight ${stepLabelClass(step.status)}`}>
                {step.label}
              </p>
              <time className="mt-0.5 block text-[0.55rem] tabular-nums text-mute">
                {formatTimestamp(step.timestamp)}
              </time>
              {step.status === 'failed' && step.detail ? (
                <p className="mt-0.5 text-[0.6rem] leading-tight text-red-700">{step.detail}</p>
              ) : step.status === 'running' ? (
                <p className="mt-0.5 text-[0.6rem] text-habeas-mid">In progress</p>
              ) : step.status === 'waiting' ? (
                <p className="mt-0.5 text-[0.6rem] text-habeas-mid">Waiting</p>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

export function RunTimeline({
  steps,
  emptyMessage = 'No timeline steps recorded.',
  orientation = 'vertical',
}: RunTimelineProps) {
  if (orientation === 'horizontal') {
    return <HorizontalRunTimeline steps={steps} emptyMessage={emptyMessage} />
  }
  return <VerticalRunTimeline steps={steps} emptyMessage={emptyMessage} />
}
