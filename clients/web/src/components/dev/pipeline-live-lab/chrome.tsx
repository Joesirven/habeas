import type { ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

import {
  CATALOG_ONLY_VERTICALS,
  PIPELINE_LIVE_FIXTURE,
  PIPELINE_LIVE_STAGES,
  aggregateStage,
  formatCount,
  microBarTone,
  stagePercent,
  stageVisual,
  type PipelineLiveStageId,
  type VerticalFixtureRow,
} from './fixture'

export function LabFrame({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <article className="rounded-md border border-line bg-white">
      <header className="border-b border-line px-4 py-3">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Fixture · {PIPELINE_LIVE_FIXTURE.snapshotDate} · counts only
        </p>
        <h2 className="mt-1 text-sm font-semibold text-ink">{title}</h2>
        <p className="mt-0.5 text-[11px] text-mute">
          Batch {PIPELINE_LIVE_FIXTURE.batchLabel} · process {PIPELINE_LIVE_FIXTURE.processId} ·{' '}
          {formatCount(PIPELINE_LIVE_FIXTURE.totalRequests)} requests
        </p>
      </header>
      <div className="p-4">{children}</div>
    </article>
  )
}

export type StatusLightTone = 'emerald' | 'sky' | 'amber' | 'red' | 'mute' | 'navy'

export function StatusLight({
  tone = 'mute',
  pulse = false,
  title,
}: {
  tone?: StatusLightTone
  pulse?: boolean
  title?: string
}) {
  const fill =
    tone === 'emerald'
      ? 'bg-emerald-500'
      : tone === 'sky'
        ? 'bg-sky-500'
        : tone === 'amber'
          ? 'bg-amber-500'
          : tone === 'red'
            ? 'bg-red-500'
            : tone === 'navy'
              ? 'bg-habeas-navy'
              : 'bg-mute/70'
  return (
    <span
      className="relative inline-flex h-1.5 w-1.5 shrink-0"
      title={title}
      aria-hidden={title ? undefined : true}
    >
      {pulse ? (
        <span
          className={`absolute inline-flex h-full w-full animate-ping rounded-full ${fill} opacity-60`}
        />
      ) : null}
      <span className={`relative inline-flex h-1.5 w-1.5 rounded-full ${fill}`} />
    </span>
  )
}

export function MicroBar({
  percent,
  tone = 'navy',
  shimmer = false,
  className,
}: {
  percent: number
  tone?: 'navy' | 'emerald' | 'red' | 'amber'
  shimmer?: boolean
  className?: string
}) {
  const clamped = Math.max(0, Math.min(100, percent))
  const fill =
    tone === 'emerald'
      ? 'bg-emerald-600'
      : tone === 'red'
        ? 'bg-red-600'
        : tone === 'amber'
          ? 'bg-amber-500'
          : 'bg-habeas-navy'
  return (
    <div
      className={cn('relative h-1 overflow-hidden rounded-full bg-line/60', className)}
      role="progressbar"
      aria-valuenow={clamped}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div
        className={cn('h-full rounded-full transition-[width]', fill)}
        style={{ width: `${clamped}%` }}
      />
      {shimmer ? (
        <div className="pointer-events-none absolute inset-0 animate-pulse bg-gradient-to-r from-transparent via-white/50 to-transparent" />
      ) : null}
    </div>
  )
}

export function StageSwitcher({
  stage,
  onSelect,
}: {
  stage: PipelineLiveStageId
  onSelect: (next: PipelineLiveStageId) => void
}) {
  return (
    <div className="flex flex-wrap gap-1" role="tablist" aria-label="Pipeline stage">
      {PIPELINE_LIVE_STAGES.map((tab) => {
        const counts = aggregateStage(tab.id)
        const selected = tab.id === stage
        const visual = stageVisual(counts)
        const percent = stagePercent(counts)
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onSelect(tab.id)}
            className={cn(
              'flex min-w-[8rem] flex-1 flex-col justify-center rounded-md px-2.5 py-2 text-left transition-colors',
              selected
                ? 'bg-habeas-navy/8 ring-1 ring-inset ring-habeas-navy/25'
                : 'hover:bg-panel/50',
            )}
          >
            <div className="flex min-w-0 items-center gap-1.5">
              <StatusLight tone={visual.light} pulse={visual.pulse} title={visual.state} />
              <span
                className={cn(
                  'truncate text-[0.65rem] font-semibold leading-none tracking-wide',
                  selected ? 'text-habeas-navy' : 'text-ink-soft',
                )}
              >
                {tab.label}
              </span>
              <span className="ml-auto shrink-0 text-xs font-medium tabular-nums leading-none text-ink">
                {counts.total > 0 ? `${percent}%` : '—'}
              </span>
            </div>
            <MicroBar
              className="mt-1.5"
              percent={percent}
              tone={microBarTone(visual)}
              shimmer={counts.inFlight > 0}
            />
          </button>
        )
      })}
    </div>
  )
}

export function VerticalName({ vertical }: { vertical: VerticalFixtureRow }) {
  return (
    <div className="min-w-0">
      <p className="truncate text-xs font-medium text-ink">{vertical.label}</p>
      <p className="truncate text-[11px] text-mute">{vertical.systems.join(' · ')}</p>
    </div>
  )
}

export function FailedCount({ count }: { count: number }) {
  if (count <= 0) return <span className="tabular-nums text-mute">0</span>
  return <span className="tabular-nums font-medium text-red-800">{formatCount(count)}</span>
}

export function CatalogOnlySection() {
  return (
    <section className="rounded-md border border-dashed border-line bg-canvas p-3 opacity-70">
      <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-mute">
        Catalog-only — matching is not live
      </p>
      <ul className="grid gap-2 sm:grid-cols-2">
        {CATALOG_ONLY_VERTICALS.map((row) => (
          <li
            key={row.id}
            className="flex items-center justify-between gap-2 rounded-md border border-line bg-white px-2.5 py-2"
          >
            <div>
              <p className="text-xs text-ink-soft">{row.label}</p>
              <p className="text-[11px] text-mute">{row.systems.join(' · ')}</p>
            </div>
            <Badge variant="wait">Catalog-only</Badge>
          </li>
        ))}
      </ul>
    </section>
  )
}
