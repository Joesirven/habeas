import { cn } from '@/lib/utils'

export type HomeWindow = '7' | '30' | '90' | 'ytd' | 'all'

type DateToolbarProps = {
  value: HomeWindow
  onChange: (next: HomeWindow) => void
}

const WINDOWS: { value: HomeWindow; label: string }[] = [
  { value: '7', label: '7d' },
  { value: '30', label: '30d' },
  { value: '90', label: '90d' },
  { value: 'ytd', label: 'YTD' },
  { value: 'all', label: 'All' },
]

function activateWindow(onChange: (next: HomeWindow) => void, next: HomeWindow) {
  onChange(next)
}

export function DateToolbar({ value, onChange }: DateToolbarProps) {
  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-paper px-3 py-2"
      role="toolbar"
      aria-label="Analytics date range"
    >
      <span className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
        Analytics window
      </span>
      <div className="flex flex-wrap items-center gap-1.5">
        {WINDOWS.map((window) => (
          <button
            key={window.value}
            type="button"
            className={cn(
              'rounded px-2.5 py-1 text-xs font-medium tabular-nums transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
              value === window.value
                ? 'bg-habeas-navy text-white'
                : 'text-ink-soft hover:bg-canvas hover:text-ink',
            )}
            aria-pressed={value === window.value}
            onClick={() => activateWindow(onChange, window.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                activateWindow(onChange, window.value)
              }
            }}
          >
            {window.label}
          </button>
        ))}
        {value !== '30' ? (
          <button
            type="button"
            className="ml-1 text-xs text-habeas-navy hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid"
            onClick={() => activateWindow(onChange, '30')}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                activateWindow(onChange, '30')
              }
            }}
          >
            Reset to 30d
          </button>
        ) : null}
      </div>
    </div>
  )
}
