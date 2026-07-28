import { useMemo, useState } from 'react'
import { Link, useNavigate } from '@tanstack/react-router'

import type { LegalPortfolio } from '@/lib/api'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

type HeatmapProps = {
  cells: NonNullable<LegalPortfolio['heatmap_cells']>
  onCellClick?: (source: string, requestType: string) => void
}

type HeatmapTab = 'type_by_source' | 'state_map' | 'source_only' | 'type_only'

type StateTile = { id: string; name: string; col: number; row: number }

const STATE_TILES: StateTile[] = [
  { id: 'AK', name: 'Alaska', col: 0, row: 0 },
  { id: 'ME', name: 'Maine', col: 11, row: 0 },
  { id: 'VT', name: 'Vermont', col: 10, row: 1 },
  { id: 'NH', name: 'New Hampshire', col: 11, row: 1 },
  { id: 'WA', name: 'Washington', col: 1, row: 2 },
  { id: 'ID', name: 'Idaho', col: 2, row: 2 },
  { id: 'MT', name: 'Montana', col: 3, row: 2 },
  { id: 'ND', name: 'North Dakota', col: 4, row: 2 },
  { id: 'MN', name: 'Minnesota', col: 5, row: 2 },
  { id: 'IL', name: 'Illinois', col: 6, row: 2 },
  { id: 'WI', name: 'Wisconsin', col: 7, row: 2 },
  { id: 'MI', name: 'Michigan', col: 8, row: 2 },
  { id: 'NY', name: 'New York', col: 9, row: 2 },
  { id: 'RI', name: 'Rhode Island', col: 10, row: 2 },
  { id: 'MA', name: 'Massachusetts', col: 11, row: 2 },
  { id: 'OR', name: 'Oregon', col: 1, row: 3 },
  { id: 'NV', name: 'Nevada', col: 2, row: 3 },
  { id: 'WY', name: 'Wyoming', col: 3, row: 3 },
  { id: 'SD', name: 'South Dakota', col: 4, row: 3 },
  { id: 'IA', name: 'Iowa', col: 5, row: 3 },
  { id: 'IN', name: 'Indiana', col: 6, row: 3 },
  { id: 'OH', name: 'Ohio', col: 7, row: 3 },
  { id: 'PA', name: 'Pennsylvania', col: 8, row: 3 },
  { id: 'NJ', name: 'New Jersey', col: 9, row: 3 },
  { id: 'CT', name: 'Connecticut', col: 10, row: 3 },
  { id: 'CA', name: 'California', col: 1, row: 4 },
  { id: 'UT', name: 'Utah', col: 2, row: 4 },
  { id: 'CO', name: 'Colorado', col: 3, row: 4 },
  { id: 'NE', name: 'Nebraska', col: 4, row: 4 },
  { id: 'MO', name: 'Missouri', col: 5, row: 4 },
  { id: 'KY', name: 'Kentucky', col: 6, row: 4 },
  { id: 'WV', name: 'West Virginia', col: 7, row: 4 },
  { id: 'VA', name: 'Virginia', col: 8, row: 4 },
  { id: 'MD', name: 'Maryland', col: 9, row: 4 },
  { id: 'DE', name: 'Delaware', col: 10, row: 4 },
  { id: 'AZ', name: 'Arizona', col: 2, row: 5 },
  { id: 'NM', name: 'New Mexico', col: 3, row: 5 },
  { id: 'KS', name: 'Kansas', col: 4, row: 5 },
  { id: 'AR', name: 'Arkansas', col: 5, row: 5 },
  { id: 'TN', name: 'Tennessee', col: 6, row: 5 },
  { id: 'NC', name: 'North Carolina', col: 7, row: 5 },
  { id: 'SC', name: 'South Carolina', col: 8, row: 5 },
  { id: 'DC', name: 'District of Columbia', col: 9, row: 5 },
  { id: 'OK', name: 'Oklahoma', col: 4, row: 6 },
  { id: 'LA', name: 'Louisiana', col: 5, row: 6 },
  { id: 'MS', name: 'Mississippi', col: 6, row: 6 },
  { id: 'AL', name: 'Alabama', col: 7, row: 6 },
  { id: 'GA', name: 'Georgia', col: 8, row: 6 },
  { id: 'HI', name: 'Hawaii', col: 0, row: 7 },
  { id: 'TX', name: 'Texas', col: 4, row: 7 },
  { id: 'FL', name: 'Florida', col: 8, row: 7 },
]

const MAP_COLS = 12
const MAP_ROWS = 8
const MAP_CELL = 26

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
  cells: NonNullable<LegalPortfolio['heatmap_cells']>
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

function StateTileMap({
  countsByState,
}: {
  countsByState: Map<string, number>
}) {
  const navigate = useNavigate()
  const counts = STATE_TILES.map((tile) => countsByState.get(tile.id) ?? 0)
  const maxCount = Math.max(1, ...counts)
  const total = counts.reduce((sum, count) => sum + count, 0)

  function openState(stateId: string) {
    void navigate({ to: '/requests', search: { state: stateId } })
  }

  return (
    <div className="space-y-2">
      <svg
        width="100%"
        viewBox={`0 0 ${MAP_COLS * MAP_CELL} ${MAP_ROWS * MAP_CELL}`}
        className="max-w-[19.5rem]"
        role="img"
        aria-label="Open requests by state"
      >
        {STATE_TILES.map((tile) => {
          const count = countsByState.get(tile.id) ?? 0
          const intensity =
            count > 0 ? 0.06 + (Math.log(1 + count) / Math.log(1 + maxCount)) * 0.86 : 0.06
          const dark = intensity > 0.5
          const cx = tile.col * MAP_CELL + MAP_CELL / 2
          const cy = tile.row * MAP_CELL + MAP_CELL / 2

          return (
            <g
              key={tile.id}
              className="cursor-pointer"
              role="link"
              tabIndex={0}
              aria-label={`${tile.name}: ${count.toLocaleString()} open`}
              onClick={() => openState(tile.id)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  openState(tile.id)
                }
              }}
            >
              <title>{`${tile.name}: ${count.toLocaleString()} open`}</title>
              <rect
                x={tile.col * MAP_CELL + 1}
                y={tile.row * MAP_CELL + 1}
                width={MAP_CELL - 2}
                height={MAP_CELL - 2}
                rx={3}
                className="fill-panel"
              />
              <rect
                x={tile.col * MAP_CELL + 1}
                y={tile.row * MAP_CELL + 1}
                width={MAP_CELL - 2}
                height={MAP_CELL - 2}
                rx={3}
                className="fill-habeas-navy"
                opacity={intensity}
              />
              <text
                x={cx}
                y={cy + 3}
                textAnchor="middle"
                fontSize={8}
                fontWeight={600}
                className={dark ? 'fill-white' : 'fill-ink-soft'}
              >
                {tile.id}
              </text>
            </g>
          )
        })}
      </svg>
      <p className="text-[0.65rem] text-mute">
        Open requests per state · tile shade ∝ log(count) ·{' '}
        {total > 0
          ? `${total.toLocaleString()} open across 50 states + DC`
          : 'No state attribution in this window yet — map still shows all jurisdictions'}{' '}
        · click a tile for state drill-down
      </p>
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

  const countsByState = useMemo(() => new Map<string, number>(), [])

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line/70">
        <Tabs value={tab} onValueChange={(value) => setTab(value as HeatmapTab)}>
          <TabsList
            aria-label="Heatmap view"
            className="h-auto gap-4 rounded-none border-0 bg-transparent p-0"
          >
            <TabsTrigger
              value="type_by_source"
              className="rounded-none border-0 border-b-2 border-transparent bg-transparent px-0 pb-1.5 shadow-none data-[state=active]:border-habeas-navy data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              Type by source
            </TabsTrigger>
            <TabsTrigger
              value="state_map"
              className="rounded-none border-0 border-b-2 border-transparent bg-transparent px-0 pb-1.5 shadow-none data-[state=active]:border-habeas-navy data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              State map
            </TabsTrigger>
            <TabsTrigger
              value="source_only"
              className="rounded-none border-0 border-b-2 border-transparent bg-transparent px-0 pb-1.5 shadow-none data-[state=active]:border-habeas-navy data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              Source only
            </TabsTrigger>
            <TabsTrigger
              value="type_only"
              className="rounded-none border-0 border-b-2 border-transparent bg-transparent px-0 pb-1.5 shadow-none data-[state=active]:border-habeas-navy data-[state=active]:bg-transparent data-[state=active]:shadow-none"
            >
              Type only
            </TabsTrigger>
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

      {tab === 'state_map' ? <StateTileMap countsByState={countsByState} /> : null}

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
