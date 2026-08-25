import { Link } from '@tanstack/react-router'

const LABS = [
  { to: '/dev/sheets-oauth', label: 'Sheets OAuth lab' },
  { to: '/dev/sheets-cadence-lab', label: 'Sheets cadence lab' },
  { to: '/dev/pending-settings', label: 'Pending settings lab' },
] as const

export function DevLabsIndexPage() {
  return (
    <section className="mx-auto max-w-lg space-y-4 p-6">
      <header>
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
          Temporary
        </p>
        <h1 className="mt-1 text-lg font-semibold text-slate-900">Dev labs</h1>
        <p className="mt-1 text-sm text-slate-600">Not in primary nav. Tear down after pick.</p>
      </header>
      <ul className="space-y-2 text-sm">
        {LABS.map((lab) => (
          <li key={lab.to}>
            <Link className="underline underline-offset-2" to={lab.to}>
              {lab.label}
            </Link>
            <span className="ml-2 font-mono text-xs text-slate-500">{lab.to}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
