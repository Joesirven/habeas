import type { ReactNode } from 'react'
import { Link } from '@tanstack/react-router'
import { cn } from '@/lib/utils'

/** Brainstorm probe — directional chrome only; not production journey logic. */

export const JOURNEY_CHROME_VARIANTS = [
  {
    id: 'four-nested',
    option: '2',
    name: 'Four-rail · nested substeps',
    blurb:
      'Detail only: same 4 high-level stages. Current stage expands inline (Matching a/b + coming-soon verticals).',
  },
  {
    id: 'four-panel',
    option: '2',
    name: 'Four-rail · substep panel',
    blurb:
      'Detail only: same 4 high-level stages. Substeps sit in a thin panel under the rail.',
  },
  {
    id: 'dual-dots',
    option: '3',
    name: 'Dual density · batch 4 / request 6',
    blurb:
      'Detail only: selected batch shows a thin 4-stage strip; individual request shows full KD29 6-stage rail.',
  },
  {
    id: 'dual-labels',
    option: '3',
    name: 'Dual density · batch 4 / request 6 + nest',
    blurb:
      'Detail only: selected batch shows abbreviated 4 labels; individual request shows KD29 6-stage rail with nested substeps.',
  },
] as const

export type JourneyChromeVariantId = (typeof JOURNEY_CHROME_VARIANTS)[number]['id']

const FOUR = [
  { key: 'ingest', label: 'Ingest', status: 'complete' as const },
  { key: 'matching', label: 'Matching', status: 'current' as const },
  { key: 'fulfillment', label: 'Fulfillment', status: 'next' as const },
  { key: 'notice', label: 'Notice', status: 'future' as const },
]

const SIX = [
  { key: 'receive', label: 'receive', status: 'complete' as const },
  { key: 'matching', label: 'matching', status: 'complete' as const },
  { key: 'data_owner_review', label: 'data owner review', status: 'current' as const },
  { key: 'legal_review', label: 'legal / pre-fulfillment', status: 'next' as const },
  { key: 'fulfillment', label: 'fulfillment', status: 'future' as const },
  { key: 'delivery_notice', label: 'delivery / DROP notice', status: 'future' as const },
]

type StageStatus = 'complete' | 'current' | 'next' | 'future' | 'soon'

function statusDot(status: StageStatus) {
  return cn(
    'size-2 shrink-0 rounded-full ring-1 ring-inset',
    status === 'complete' && 'bg-emerald-600 ring-emerald-700/30',
    status === 'current' && 'bg-amber-500 ring-amber-700/40',
    status === 'next' && 'bg-sky-400/80 ring-sky-700/30',
    (status === 'future' || status === 'soon') && 'bg-line ring-line',
  )
}

function statusText(status: StageStatus) {
  return cn(
    status === 'complete' && 'text-emerald-800',
    status === 'current' && 'font-medium text-amber-950',
    status === 'next' && 'text-sky-900',
    (status === 'future' || status === 'soon') && 'text-mute',
  )
}

function ProbeBanner({
  variantId,
  option,
  name,
}: {
  variantId: JourneyChromeVariantId
  option: string
  name: string
}) {
  return (
    <div className="rounded-[0.75rem] border border-dashed border-amber-300 bg-amber-50/80 px-3 py-2 text-xs text-amber-950">
      <p className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-amber-800/80">
        Brainstorm probe · Option {option} · {variantId}
      </p>
      <p className="mt-0.5 font-medium">{name}</p>
      <p className="mt-1 text-amber-900/80">
        Journey steps live only in the opened detail pane (selected batch and/or individual
        request) — not on Inbox list rows. Judge density and nesting, not final styling.
      </p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Link to="/dev/journey-chrome" className="underline underline-offset-2">
          All variants
        </Link>
        {JOURNEY_CHROME_VARIANTS.map((v) => (
          <Link
            key={v.id}
            to="/dev/journey-chrome/$variant"
            params={{ variant: v.id }}
            className={cn(
              'underline underline-offset-2',
              v.id === variantId ? 'font-medium text-ink no-underline' : 'text-amber-900/70',
            )}
          >
            {v.id}
          </Link>
        ))}
      </div>
    </div>
  )
}

function MockRow({
  title,
  meta,
  active,
}: {
  title: string
  meta: string
  active?: boolean
}) {
  return (
    <div
      className={cn(
        'border-b border-line px-3 py-2.5',
        active ? 'bg-sky-50/70' : 'bg-panel',
      )}
    >
      <p className="truncate text-sm font-medium text-ink">{title}</p>
      <p className="mt-0.5 truncate text-[0.7rem] text-mute">{meta}</p>
    </div>
  )
}

function FourRail({
  expanded,
  mode,
}: {
  expanded: boolean
  mode: 'nested' | 'panel'
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-stretch gap-1" role="list" aria-label="High-level journey">
        {FOUR.map((stage, i) => (
          <div key={stage.key} className="flex min-w-0 flex-1 items-center gap-1" role="listitem">
            <div
              className={cn(
                'min-w-0 flex-1 rounded-md border px-1.5 py-1.5 text-center',
                stage.status === 'current'
                  ? 'border-amber-300 bg-amber-50'
                  : stage.status === 'complete'
                    ? 'border-emerald-200/80 bg-emerald-50/50'
                    : 'border-line bg-canvas',
              )}
            >
              <div className="mx-auto mb-1 flex justify-center">
                <span className={statusDot(stage.status)} />
              </div>
              <p className={cn('truncate text-[0.6rem] leading-tight', statusText(stage.status))}>
                {stage.label}
              </p>
            </div>
            {i < FOUR.length - 1 ? (
              <span className="shrink-0 text-[0.6rem] text-mute" aria-hidden>
                →
              </span>
            ) : null}
          </div>
        ))}
      </div>

      {mode === 'nested' && expanded ? (
        <div className="rounded-md border border-amber-200 bg-amber-50/40 px-2.5 py-2">
          <p className="text-[0.65rem] font-medium text-amber-950">
            Matching · current substeps
          </p>
          <ul className="mt-1.5 space-y-1 text-[0.7rem]">
            <li className="flex items-center gap-2 text-emerald-800">
              <span className={statusDot('complete')} />
              a. Auto-match · Data vertical
            </li>
            <li className="flex items-center gap-2 text-amber-950">
              <span className={statusDot('current')} />
              b. Data owner status · recommended 4 Opted out
            </li>
            <li className="flex items-center gap-2 text-mute">
              <span className={statusDot('soon')} />
              Mailchimp · coming soon
            </li>
            <li className="flex items-center gap-2 text-mute">
              <span className={statusDot('soon')} />
              Lever · coming soon
            </li>
          </ul>
        </div>
      ) : null}

      {mode === 'panel' ? (
        <div className="grid gap-2 sm:grid-cols-[8rem_minmax(0,1fr)]">
          <div className="rounded-md border border-line bg-canvas px-2 py-1.5 text-[0.65rem] text-mute">
            Substeps for
            <br />
            <span className="font-medium text-ink">Matching</span>
          </div>
          <div className="rounded-md border border-line bg-panel px-2.5 py-2 text-[0.7rem]">
            <div className="flex flex-wrap gap-x-3 gap-y-1">
              <span className="text-emerald-800">a Auto-match ✓</span>
              <span className="font-medium text-amber-950">b DO status · now</span>
              <span className="text-mute">Mailchimp soon</span>
              <span className="text-mute">Lever soon</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function SixRail({ nested }: { nested: boolean }) {
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-1" role="list" aria-label="KD29 coarse journey">
        {SIX.map((stage, i) => (
          <div key={stage.key} className="flex items-center gap-1" role="listitem">
            <div
              className={cn(
                'rounded-md border px-2 py-1',
                stage.status === 'current' && 'border-amber-300 bg-amber-50',
                stage.status === 'complete' && 'border-emerald-200/80 bg-emerald-50/40',
                stage.status === 'next' && 'border-sky-200 bg-sky-50/50',
                stage.status === 'future' && 'border-line bg-canvas',
              )}
            >
              <p className={cn('text-[0.65rem] whitespace-nowrap', statusText(stage.status))}>
                {stage.label}
              </p>
            </div>
            {i < SIX.length - 1 ? (
              <span className="text-[0.6rem] text-mute" aria-hidden>
                →
              </span>
            ) : null}
          </div>
        ))}
      </div>
      {nested ? (
        <div className="rounded-md border border-line bg-panel px-2.5 py-2 text-[0.7rem]">
          <p className="font-medium text-ink">data owner review · substeps</p>
          <ul className="mt-1 space-y-1 text-mute">
            <li className="text-emerald-800">Auto-match complete · Data vertical</li>
            <li className="font-medium text-amber-950">Approve status · default 4 Opted out</li>
            <li>Assign to legal (optional)</li>
            <li className="opacity-60">Other verticals · coming soon</li>
          </ul>
          <p className="mt-2 text-[0.65rem] text-sky-900">Next: legal / pre-fulfillment</p>
        </div>
      ) : (
        <p className="text-[0.7rem] text-mute">
          Current: <span className="font-medium text-amber-950">data owner review</span>
          {' · '}
          Next: <span className="text-sky-900">legal / pre-fulfillment</span>
        </p>
      )}
    </div>
  )
}

function FourDots() {
  return (
    <div className="flex items-center gap-1.5" aria-label="Batch journey · 4 stages">
      {FOUR.map((stage) => (
        <span
          key={stage.key}
          className={statusDot(stage.status)}
          title={`${stage.label}: ${stage.status}`}
        />
      ))}
      <span className="ml-1 truncate text-[0.65rem] text-amber-950">Matching · batch</span>
    </div>
  )
}

function FourAbbrevLabels() {
  return (
    <div className="flex gap-1" aria-label="Batch journey · 4 stages">
      {FOUR.map((stage) => (
        <span
          key={stage.key}
          className={cn(
            'rounded border border-line bg-canvas px-1.5 py-0.5 text-[0.6rem]',
            statusText(stage.status),
          )}
          title={stage.label}
        >
          {stage.label}
        </span>
      ))}
    </div>
  )
}

function DetailPane({
  eyebrow,
  title,
  meta,
  chrome,
}: {
  eyebrow: string
  title: string
  meta: string
  chrome: ReactNode
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-canvas/40">
      <div className="shrink-0 border-b border-line px-3 py-3 md:px-4">
        <p className="taste-micro">{eyebrow}</p>
        <p className="mt-1 font-display text-lg text-ink">{title}</p>
        <p className="mt-0.5 text-xs text-mute">{meta}</p>
      </div>
      <div className="shrink-0 space-y-2 border-b border-line px-3 py-3 md:px-4">
        <p className="font-mono text-[0.6rem] uppercase tracking-[0.12em] text-mute">
          Journey · detail only
        </p>
        {chrome}
      </div>
      <div className="min-h-0 flex-1 px-3 py-3 md:px-4">
        <div className="rounded-md border border-line bg-panel px-3 py-2 text-[0.7rem] text-mute">
          Fulfillment · Details · Matching · Activity (existing Variation 1 chrome below the rail)
        </div>
      </div>
    </div>
  )
}

function MockSplit({
  list,
  detail,
}: {
  list: ReactNode
  detail: ReactNode
}) {
  return (
    <div className="overflow-hidden rounded-[1rem] border border-line bg-panel shadow-sm">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <p className="text-sm font-medium text-ink">Inbox</p>
        <p className="font-mono text-[0.65rem] uppercase tracking-[0.1em] text-mute">
          List has no journey strip
        </p>
      </div>
      <div className="grid min-h-[32rem] md:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
        <div className="border-b border-line md:border-b-0 md:border-r">{list}</div>
        {detail}
      </div>
    </div>
  )
}

function listRowsFor(variant: JourneyChromeVariantId) {
  if (variant === 'dual-dots' || variant === 'dual-labels') {
    return (
      <>
        <MockRow
          active
          title="Batch 2026-07-22 · 48 open"
          meta="CA DROP · selected batch"
        />
        <MockRow
          title="REQ-probe-1042 · multi-match"
          meta="CA DROP · individual request"
        />
        <MockRow
          title="REQ-probe-0988 · single match"
          meta="CA DROP · individual request"
        />
      </>
    )
  }
  return (
    <>
      <MockRow
        active
        title="Multi-match · recommended Opt-out"
        meta="CA DROP · Matching · REQ-probe-1042"
      />
      <MockRow
        title="Single match · recommended Delete"
        meta="CA DROP · Matching · REQ-probe-0988"
      />
      <MockRow
        title="No match · recommended Not found"
        meta="CA DROP · Matching · REQ-probe-0550"
      />
    </>
  )
}

export function JourneyChromeProbe({ variant }: { variant: JourneyChromeVariantId }) {
  const meta = JOURNEY_CHROME_VARIANTS.find((v) => v.id === variant)!

  const requestChrome =
    variant === 'four-nested' ? (
      <FourRail expanded mode="nested" />
    ) : variant === 'four-panel' ? (
      <FourRail expanded={false} mode="panel" />
    ) : variant === 'dual-dots' ? (
      <SixRail nested={false} />
    ) : (
      <SixRail nested />
    )

  const batchChrome = variant === 'dual-dots' ? <FourDots /> : <FourAbbrevLabels />

  return (
    <section className="space-y-4">
      <ProbeBanner variantId={variant} option={meta.option} name={meta.name} />

      {meta.option === '2' ? (
        <MockSplit
          list={listRowsFor(variant)}
          detail={
            <DetailPane
              eyebrow="Selected individual request · detail pane"
              title="REQ-probe-1042"
              meta="CA DROP · delete · batch 2026-07-22"
              chrome={requestChrome}
            />
          }
        />
      ) : (
        <div className="space-y-4">
          <MockSplit
            list={listRowsFor(variant)}
            detail={
              <DetailPane
                eyebrow="Selected batch · detail pane (thin 4)"
                title="Batch 2026-07-22"
                meta="CA DROP · 48 open · aggregate posture"
                chrome={batchChrome}
              />
            }
          />
          <div className="overflow-hidden rounded-[1rem] border border-line bg-panel shadow-sm">
            <div className="border-b border-line px-3 py-2">
              <p className="text-sm font-medium text-ink">
                Same selection path · individual request opened
              </p>
              <p className="text-[0.7rem] text-mute">
                Option 3 denser chrome: KD29 6-stage rail on the individual request detail only.
              </p>
            </div>
            <DetailPane
              eyebrow="Selected individual request · detail pane (full 6)"
              title="REQ-probe-1042"
              meta="CA DROP · delete · from batch 2026-07-22"
              chrome={requestChrome}
            />
          </div>
        </div>
      )}
    </section>
  )
}

export function JourneyChromeHub() {
  return (
    <section className="space-y-6">
      <div className="rounded-[0.75rem] border border-dashed border-amber-300 bg-amber-50/80 px-3 py-2 text-xs text-amber-950">
        Temporary brainstorm lab — journey chrome appears only in the opened detail view
        (selected batch and/or individual request), never on Inbox list rows. Option 2 = four
        high-level stages on detail; Option 3 = thinner 4 on batch detail, denser 6 on request
        detail.
      </div>
      <header>
        <p className="taste-micro">Dev · journey chrome probes</p>
        <h2 className="mt-2 font-display text-3xl font-medium tracking-tight text-ink">
          Journey chrome lab
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-ink-soft">
          Two variations for Option 2, two for Option 3. Open a route, compare density and nesting
          in the detail pane, then reply in chat with the variant id (or a mix).
        </p>
      </header>
      <div className="grid gap-3 sm:grid-cols-2">
        {JOURNEY_CHROME_VARIANTS.map((v) => (
          <Link
            key={v.id}
            to="/dev/journey-chrome/$variant"
            params={{ variant: v.id }}
            className="block rounded-[1rem] border border-line bg-panel px-4 py-3 transition hover:border-ink/30"
          >
            <p className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-mute">
              Option {v.option} · {v.id}
            </p>
            <p className="mt-1 font-medium text-ink">{v.name}</p>
            <p className="mt-1 text-xs text-ink-soft">{v.blurb}</p>
          </Link>
        ))}
      </div>
    </section>
  )
}
