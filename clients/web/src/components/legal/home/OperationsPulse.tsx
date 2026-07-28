import { useState } from 'react'
import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { cn } from '@/lib/utils'

export type OperationsPulseChip = 'assigned' | 'team' | 'at_risk' | 'overdue' | 'median_age'

type OperationsPulseProps = {
  pulse: LegalPortfolio['operations_pulse'] | undefined
  onChipClick?: (chip: Exclude<OperationsPulseChip, 'median_age'>) => void
  embedded?: boolean
}

function formatMedianAge(hours: number): string {
  if (hours < 24) return `${Math.round(hours)}h`
  const days = hours / 24
  return days < 10 ? `${days.toFixed(1)}d` : `${Math.round(days)}d`
}

const CHIP_DRILL: Record<
  Exclude<OperationsPulseChip, 'median_age'>,
  { label: string; description: string; to: string; search?: Record<string, string> }
> = {
  assigned: {
    label: 'Open — you',
    description: 'Assigned to you across all stages — oldest first.',
    to: '/requests/needs-attention',
    search: { filter: 'assigned_to_me' },
  },
  team: {
    label: 'Open — team',
    description: 'Team-wide open requests across the portfolio.',
    to: '/requests',
    search: { attention: 'needs' },
  },
  at_risk: {
    label: 'SLA at risk',
    description: 'Deadline inside the SLA warning window — needs triage this week.',
    to: '/requests',
    search: { attention: 'needs' },
  },
  overdue: {
    label: 'Overdue',
    description: 'Open requests past their calculated or overridden due date.',
    to: '/requests',
    search: { attention: 'needs' },
  },
}

type PulseChipConfig = {
  id: OperationsPulseChip
  label: string
  value: string
  expandable: boolean
  tone?: 'warning' | 'danger'
}

export function OperationsPulse({ pulse, onChipClick, embedded = false }: OperationsPulseProps) {
  const [expanded, setExpanded] = useState<OperationsPulseChip | null>(null)

  if (!pulse) return null

  const chips: PulseChipConfig[] = [
    {
      id: 'assigned',
      label: 'Open — you',
      value: pulse.open_assigned_to_you.toLocaleString(),
      expandable: true,
    },
    {
      id: 'team',
      label: 'Open — team',
      value: pulse.open_team_wide.toLocaleString(),
      expandable: true,
    },
    {
      id: 'at_risk',
      label: 'SLA at risk',
      value: pulse.sla_at_risk.toLocaleString(),
      expandable: true,
      tone: pulse.sla_at_risk > 0 ? 'warning' : undefined,
    },
    {
      id: 'overdue',
      label: 'Overdue',
      value: pulse.overdue.toLocaleString(),
      expandable: true,
      tone: pulse.overdue > 0 ? 'danger' : undefined,
    },
    {
      id: 'median_age',
      label: 'Median age',
      value: formatMedianAge(pulse.median_age_hours),
      expandable: true,
    },
  ]

  function toggleChip(chip: PulseChipConfig) {
    if (!chip.expandable) return
    const next = expanded === chip.id ? null : chip.id
    setExpanded(next)
    if (next && next !== 'median_age') {
      onChipClick?.(next)
    }
  }

  return (
    <div className={cn(!embedded && 'rounded-lg border border-line px-3.5 py-2.5')}>
      <div
        className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5"
        role="group"
        aria-label="Operations pulse"
      >
        {chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            className={cn(
              'rounded-md px-1.5 py-1 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
              expanded === chip.id ? 'bg-panel' : 'hover:bg-panel/60',
            )}
            aria-expanded={chip.expandable ? expanded === chip.id : undefined}
            onClick={() => toggleChip(chip)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                toggleChip(chip)
              }
            }}
          >
            <p
              className={cn(
                'font-display text-xl font-medium tabular-nums leading-tight',
                chip.tone === 'warning' && 'text-amber-700',
                chip.tone === 'danger' && 'text-red-700',
                !chip.tone && 'text-ink',
              )}
            >
              {chip.value}
            </p>
            <p className="mt-0.5 text-[0.65rem] text-mute">{chip.label}</p>
          </button>
        ))}
      </div>

      {expanded ? (
        <div className="mt-3 border-t border-line/70 pt-3 text-xs text-ink-soft">
          {expanded === 'median_age' ? (
            <>
              <p className="font-medium text-ink">Median age</p>
              <p className="mt-1">
                Age distribution of open requests (received → now). Median:{' '}
                {formatMedianAge(pulse.median_age_hours)}.
              </p>
            </>
          ) : (
            <>
              <p className="font-medium text-ink">{CHIP_DRILL[expanded].label}</p>
              <p className="mt-1">{CHIP_DRILL[expanded].description}</p>
              <Link
                to={CHIP_DRILL[expanded].to}
                search={CHIP_DRILL[expanded].search}
                className="mt-2 inline-block text-habeas-navy hover:underline"
              >
                View in queue →
              </Link>
            </>
          )}
          <p className="mt-2 text-[0.65rem] text-mute">Click the metric again to collapse</p>
        </div>
      ) : null}
    </div>
  )
}
