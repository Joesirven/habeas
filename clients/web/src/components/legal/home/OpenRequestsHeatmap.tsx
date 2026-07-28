import { useMemo, useState } from 'react'
import { Link } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

type HeatmapProps = {
  cells: LegalPortfolio['heatmap_cells']
  onCellClick?: (source: string, requestType: string) => void
}

type HeatmapTab = 'type_by_source' | 'state_map' | 'source_only' | 'type_only'

function cellKey(source: string, type: string): string {
  return `${source}:${type}`
}

function heatColor(count: number, max: number): string {
  if (count <= 0) return 'bg-canvas'
  const ratio = count / max
  if (ratio > 0.75) return 'bg-habeas-navy text-white'
  if (ratio > 0.5) return 'bg-habeas-navy/75 text-white'
  if (ratio > 0.25) return 'bg-habeas-light/40 text-ink'
  return 'bg-habeas-light/20 text-ink'
}

function TypeBySourceGrid({
  cells,
  showPercent,
  onCellClick,
}: {
  cells: LegalPortfolio['heatmap_cells']
  showPercent: boolean
  onCellClick?: (source: string, requestType: string) => void
}) {
  const sources = [...new Set(cells.map((c) => c.intake_source))].sort()
  const types = [...new Set(cells.map((c) => c.request_type))].sort()
  const lookup = new Map(cells.map((c) => [cellKey(c.intake_source, c.request_type), c.count]))
  const grandTotal = cells.reduce((sum, c) => sum + c.count, 0) || 1
  const max = Math.max(1, ...cells.map((c) => c.count))

  if (sources.length === 0 || types.length === 0) {
    return <p className="text-xs text-mute">No open requests in this window.</p>
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-paper p-1.5 text-left font-medium text-mute">Source</th>
            {types.map((type) => (
              <th key={type} className="p-1.5 text-center font-medium text-mute">
                {type}
              </th>
            ))}
            <th className="p-1.5 text-center font-medium text-mute">Total</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((source) => {
            const rowTotal = types.reduce((sum, type) => sum + (lookup.get(cellKey(source, type)) ?? 0), 0)
            return (
              <tr key={source} className="border-t border-line/50">
                <td className="sticky left-0 bg-paper p-1.5 font-medium text-ink-soft">{source}</td>
                {types.map((type) => {
                  const count = lookup.get(cellKey(source, type)) ?? 0
                  const display = showPercent
                    ? `${Math.round((count / grandTotal) * 100)}%`
                    : String(count)
                  return (
                    <td key={type} className="p-0.5">
                      <Link
                        to="/requests"
                        search={{
                          source: source as 'drop',
                          request_type: type,
                        }}
                        className={cn(
                          'flex min-h-[1.75rem] items-center justify-center rounded px-1 tabular-nums hover:ring-1 hover:ring-habeas-mid focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
                          heatColor(count, max),
                        )}
                        onClick={(event) => {
                          if (onCellClick) {
                            event.preventDefault()
                            onCellClick(source, type)
                          }
                        }}
                      >
                        {display}
                      </Link>
                    </td>
                  )
                })}
                <td className="p-1.5 text-center tabular-nums font-medium text-ink">{rowTotal}</td>
              </tr>
            )
          })}
          <tr className="border-t border-line bg-canvas/60 font-medium">
            <td className="sticky left-0 bg-canvas/60 p-1.5 text-mute">Total</td>
            {types.map((type) => {
              const colTotal = sources.reduce(
                (sum, source) => sum + (lookup.get(cellKey(source, type)) ?? 0),
                0,
              )
              return (
                <td key={type} className="p-1.5 text-center tabular-nums text-ink">
                  {showPercent ? `${Math.round((colTotal / grandTotal) * 100)}%` : colTotal}
                </td>
              )
            })}
            <td className="p-1.5 text-center tabular-nums text-ink">{grandTotal}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function AggregatedBars({
  rows,
  showPercent,
  linkSearch,
}: {
  rows: Array<{ label: string; count: number }>
  showPercent: boolean
  linkSearch: (label: string) => Record<string, string>
}) {
  const total = rows.reduce((sum, row) => sum + row.count, 0) || 1
  const max = Math.max(1, ...rows.map((row) => row.count))

  if (rows.length === 0) {
    return <p className="text-xs text-mute">No open requests in this window.</p>
  }

  return (
    <ul className="space-y-1.5 text-xs">
      {rows.map((row) => {
        const width = (row.count / max) * 100
        const display = showPercent
          ? `${Math.round((row.count / total) * 100)}%`
          : String(row.count)
        return (
          <li key={row.label}>
            <div className="mb-0.5 flex items-center justify-between gap-2">
              <span className="truncate text-ink-soft">{row.label}</span>
              <Link
                to="/requests"
                search={linkSearch(row.label)}
                className="shrink-0 tabular-nums text-habeas-navy hover:underline"
              >
                {display}
              </Link>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-line/40">
              <div
                className="h-full rounded-full bg-habeas-navy/80"
                style={{ width: `${width}%` }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export function OpenRequestsHeatmap({ cells, onCellClick }: HeatmapProps) {
  const [showPercent, setShowPercent] = useState(false)
  const [tab, setTab] = useState<HeatmapTab>('type_by_source')

  const bySource = useMemo(() => {
    const map = new Map<string, number>()
    for (const cell of cells) {
      map.set(cell.intake_source, (map.get(cell.intake_source) ?? 0) + cell.count)
    }
    return [...map.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count)
  }, [cells])

  const byType = useMemo(() => {
    const map = new Map<string, number>()
    for (const cell of cells) {
      map.set(cell.request_type, (map.get(cell.request_type) ?? 0) + cell.count)
    }
    return [...map.entries()]
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count)
  }, [cells])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Tabs value={tab} onValueChange={(value) => setTab(value as HeatmapTab)}>
          <TabsList aria-label="Heatmap view">
            <TabsTrigger value="type_by_source">Type by source</TabsTrigger>
            <TabsTrigger value="state_map">State map</TabsTrigger>
            <TabsTrigger value="source_only">Source only</TabsTrigger>
            <TabsTrigger value="type_only">Type only</TabsTrigger>
          </TabsList>
        </Tabs>
        <button
          type="button"
          className={cn(
            'rounded border px-2 py-0.5 text-[0.65rem] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid',
            showPercent
              ? 'border-habeas-navy bg-habeas-navy text-white'
              : 'border-line text-ink-soft hover:bg-canvas',
          )}
          aria-pressed={showPercent}
          onClick={() => setShowPercent((prev) => !prev)}
        >
          {showPercent ? 'Counts' : '%'}
        </button>
      </div>

      {tab === 'type_by_source' ? (
        <TypeBySourceGrid cells={cells} showPercent={showPercent} onCellClick={onCellClick} />
      ) : null}

      {tab === 'state_map' ? (
        <p className="text-xs text-mute">
          State breakdown is not available in this portfolio window yet. Use type by source or open
          All requests with a state filter.
        </p>
      ) : null}

      {tab === 'source_only' ? (
        <AggregatedBars
          rows={bySource}
          showPercent={showPercent}
          linkSearch={(label) => ({ source: label as 'drop' })}
        />
      ) : null}

      {tab === 'type_only' ? (
        <AggregatedBars
          rows={byType}
          showPercent={showPercent}
          linkSearch={(label) => ({ request_type: label })}
        />
      ) : null}
    </div>
  )
}
