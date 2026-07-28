import { useState } from 'react'
import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { cn } from '@/lib/utils'

export type OperationsPulseChip = 'assigned' | 'team' | 'at_risk' | 'overdue' | 'median_age'

type OperationsPulseProps = {
  pulse: LegalPortfolio['operations_pulse']
  onChipClick?: (chip: Exclude<OperationsPulseChip, 'median_age'>) => void
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
    label: 'Assigned to you',
    description: 'Open requests currently assigned to your operator identity.',
    to: '/requests/needs-attention',
    search: { filter: 'assigned_to_me' },
  },
  team: {
    label: 'Open team-wide',
    description: 'All open legal and admin work across the portfolio.',
    to: '/requests',
    search: { attention: 'needs' },
  },
  at_risk: {
    label: 'SLA at risk',
    description: 'Requests approaching their due date within the SLA warning window.',
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

export function OperationsPulse({ pulse, onChipClick }: OperationsPulseProps) {
  const [expanded, setExpanded] = useState<OperationsPulseChip | null>(null)

  const chips: Array<{
    id: OperationsPulseChip
    label: string
    value: string
    expandable: boolean
  }> = [
    {
      id: 'assigned',
      label: 'Assigned to you',
      value: String(pulse.open_assigned_to_you),
      expandable: true,
    },
    {
      id: 'team',
      label: 'Open team-wide',
      value: String(pulse.open_team_wide),
      expandable: true,
    },
    {
      id: 'at_risk',
      label: 'SLA at risk',
      value: String(pulse.sla_at_risk),
      expandable: true,
    },
    {
      id: 'overdue',
      label: 'Overdue',
      value: String(pulse.overdue),
      expandable: true,
    },
    {
      id: 'median_age',
      label: 'Median age',
      value: formatMedianAge(pulse.median_age_hours),
      expandable: false,
    },
  ]

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2" role="group" aria-label="Operations pulse">
        {chips.map((chip) => (
          <button
            key={chip.id}
            type="button"
            className={cn(
              'taste-frost-chip tabular-nums text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
              expanded === chip.id && chip.expandable && 'border-habeas-navy/40 bg-white',
            )}
            aria-expanded={chip.expandable ? expanded === chip.id : undefined}
            onClick={() => {
              if (!chip.expandable) return
              const next = expanded === chip.id ? null : chip.id
              setExpanded(next)
              if (next && next !== 'median_age') {
                onChipClick?.(next)
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                if (!chip.expandable) return
                const next = expanded === chip.id ? null : chip.id
                setExpanded(next)
                if (next && next !== 'median_age') {
                  onChipClick?.(next)
                }
              }
            }}
          >
            {chip.label}: {chip.value}
          </button>
        ))}
      </div>

      {expanded && expanded !== 'median_age' ? (
        <div className="rounded-md border border-line bg-white px-3 py-2 text-xs text-ink-soft">
          <p className="font-medium text-ink">{CHIP_DRILL[expanded].label}</p>
          <p className="mt-1">{CHIP_DRILL[expanded].description}</p>
          <Link
            to={CHIP_DRILL[expanded].to}
            search={CHIP_DRILL[expanded].search}
            className="mt-2 inline-block text-habeas-navy hover:underline"
          >
            View in queue →
          </Link>
        </div>
      ) : null}
    </div>
  )
}
