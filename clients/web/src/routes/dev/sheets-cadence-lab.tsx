/**
 * Temporary lab — three Sheets owner-wizard cadence UI variations.
 * Port 5174 only; not primary nav. Tear down after pick.
 */
import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

type Policy = 'static' | 'volatile' | null

const STEPS = ['Connect Google', 'Spreadsheet', 'Refresh policy', 'Confirm'] as const

function LabChrome({
  title,
  blurb,
  children,
}: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <article className="flex min-h-[28rem] flex-col rounded-md border border-slate-200 bg-white">
      <header className="border-b border-slate-200 px-4 py-3">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-slate-500">
          Variation
        </p>
        <h2 className="mt-1 text-sm font-semibold text-slate-900">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-slate-600">{blurb}</p>
      </header>
      <div className="flex flex-1 flex-col gap-3 p-4">{children}</div>
    </article>
  )
}

function StepDots({ active }: { active: number }) {
  return (
    <ol className="flex flex-wrap gap-1.5">
      {STEPS.map((label, index) => (
        <li
          key={label}
          className={cn(
            'rounded border px-2 py-0.5 text-[0.65rem]',
            index === active
              ? 'border-habeas-navy bg-habeas-navy text-white'
              : index < active
                ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                : 'border-slate-200 bg-slate-50 text-slate-500',
          )}
        >
          {index + 1}. {label}
        </li>
      ))}
    </ol>
  )
}

/** A — Two consequence cards */
function VariationA() {
  const [policy, setPolicy] = useState<Policy>(null)
  return (
    <LabChrome
      title="A · Consequence cards"
      blurb="Pick Static vs Volatile as equal cards; consequences stay on the card."
    >
      <StepDots active={2} />
      <p className="text-xs text-slate-600">
        How often does this sheet’s data change? Matching for this vertical waits until
        a refresh when the policy requires it (minimum 12 hours between required
        refreshes).
      </p>
      <div className="grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => setPolicy('static')}
          className={cn(
            'rounded-md border p-3 text-left transition-colors',
            policy === 'static'
              ? 'border-habeas-navy bg-slate-50 ring-1 ring-habeas-navy'
              : 'border-slate-200 hover:border-slate-300',
          )}
        >
          <p className="text-sm font-medium text-slate-900">Static</p>
          <p className="mt-1 text-xs text-slate-600">
            Rarely or never changes. Connect and build the hash index once.
          </p>
          <Badge variant="ok" className="mt-2">
            Matching stays ready
          </Badge>
        </button>
        <button
          type="button"
          onClick={() => setPolicy('volatile')}
          className={cn(
            'rounded-md border p-3 text-left transition-colors',
            policy === 'volatile'
              ? 'border-habeas-navy bg-slate-50 ring-1 ring-habeas-navy'
              : 'border-slate-200 hover:border-slate-300',
          )}
        >
          <p className="text-sm font-medium text-slate-900">Volatile</p>
          <p className="mt-1 text-xs text-slate-600">
            Can change (including daily). New intake batches may require a refresh
            before matching — not more often than every 12 hours.
          </p>
          <Badge variant="wait" className="mt-2">
            May block matching
          </Badge>
        </button>
      </div>
      <div className="mt-auto flex justify-between pt-2">
        <Button type="button" size="sm" variant="ghost">
          Back
        </Button>
        <Button type="button" size="sm" disabled={!policy}>
          Continue
        </Button>
      </div>
    </LabChrome>
  )
}

/** B — Compact radios + dynamic callout */
function VariationB() {
  const [policy, setPolicy] = useState<Policy>('volatile')
  return (
    <LabChrome
      title="B · Radios + callout"
      blurb="Dense list; one callout updates with the selected policy."
    >
      <StepDots active={2} />
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-slate-900">Refresh policy</legend>
        {(
          [
            {
              id: 'static' as const,
              label: 'Static — sheet rarely changes',
              detail: 'One successful refresh unlocks matching until you reconnect.',
            },
            {
              id: 'volatile' as const,
              label: 'Volatile — sheet can change',
              detail:
                'After a new intake batch, refresh if the last one was ≥12 hours ago.',
            },
          ] as const
        ).map((opt) => (
          <label
            key={opt.id}
            className={cn(
              'flex cursor-pointer gap-2 rounded-md border px-3 py-2',
              policy === opt.id ? 'border-habeas-navy bg-slate-50' : 'border-slate-200',
            )}
          >
            <input
              type="radio"
              name="policy-b"
              className="mt-0.5"
              checked={policy === opt.id}
              onChange={() => setPolicy(opt.id)}
            />
            <span>
              <span className="block text-xs font-medium text-slate-900">{opt.label}</span>
              <span className="mt-0.5 block text-[0.7rem] text-slate-600">{opt.detail}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div
        className={cn(
          'rounded-md border px-3 py-2 text-xs',
          policy === 'volatile'
            ? 'border-amber-200 bg-amber-50 text-amber-950'
            : 'border-emerald-200 bg-emerald-50 text-emerald-950',
        )}
      >
        {policy === 'volatile'
          ? 'You will see Needs refresh when a new batch arrives and your last refresh is older than 12 hours. Login is never blocked.'
          : 'Matching will not wait on batch intake for this sheet after the first successful hash build.'}
      </div>
      <div className="mt-auto flex justify-between pt-2">
        <Button type="button" size="sm" variant="ghost">
          Back
        </Button>
        <Button type="button" size="sm">
          Continue
        </Button>
      </div>
    </LabChrome>
  )
}

/** C — Segmented control + checklist confirm preview */
function VariationC() {
  const [policy, setPolicy] = useState<Policy>('static')
  return (
    <LabChrome
      title="C · Segment + checklist"
      blurb="Segmented control; checklist previews what Confirm will require."
    >
      <StepDots active={2} />
      <div className="inline-flex rounded-md border border-slate-200 p-0.5">
        {(['static', 'volatile'] as const).map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => setPolicy(id)}
            className={cn(
              'rounded px-3 py-1.5 text-xs font-medium capitalize',
              policy === id
                ? 'bg-habeas-navy text-white'
                : 'text-slate-600 hover:bg-slate-50',
            )}
          >
            {id}
          </button>
        ))}
      </div>
      <ul className="space-y-1.5 text-xs text-slate-700">
        <li className="flex gap-2">
          <span className="text-emerald-600">✓</span> Google connected (refresh token stored)
        </li>
        <li className="flex gap-2">
          <span className="text-emerald-600">✓</span> Spreadsheet URL tested
        </li>
        <li className="flex gap-2">
          <span className={policy ? 'text-emerald-600' : 'text-slate-400'}>
            {policy ? '✓' : '○'}
          </span>
          Policy: {policy ?? '—'}
          {policy === 'volatile' ? ' · 12h minimum between required refreshes' : ''}
        </li>
        <li className="flex gap-2 text-slate-500">
          <span>○</span>
          {policy === 'static'
            ? 'First hash index build (once)'
            : 'Refresh → hash → mart when matching is gated'}
        </li>
      </ul>
      <div className="mt-auto flex justify-between pt-2">
        <Button type="button" size="sm" variant="ghost">
          Back
        </Button>
        <Button type="button" size="sm">
          Continue
        </Button>
      </div>
    </LabChrome>
  )
}

export function SheetsCadenceLabPage() {
  return (
    <section className="mx-auto max-w-6xl space-y-4">
      <header className="space-y-1">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
          Dev lab · port 5175 · pick one
        </p>
        <h1 className="text-xl font-semibold text-slate-900">
          Sheets wizard — refresh policy
        </h1>
        <p className="max-w-2xl text-sm text-slate-600">
          Shipping <strong>A · Consequence cards</strong>. B and C are leftover samples.
        </p>
      </header>
      <div className="grid gap-4 lg:grid-cols-3">
        <VariationA />
        <VariationB />
        <VariationC />
      </div>
    </section>
  )
}
