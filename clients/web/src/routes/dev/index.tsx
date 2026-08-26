import { Link } from '@tanstack/react-router'

const LABS = [
  { to: '/dev/sheets-oauth', label: 'Sheets OAuth lab' },
  { to: '/dev/sheets-cadence-lab', label: 'Sheets cadence lab' },
  { to: '/dev/pending-settings', label: 'Pending settings lab' },
  { to: '/dev/drop-prod-cutover', label: 'DROP prod cutover lab' },
  {
    to: '/dev/token-resource-server',
    label: 'Token resource server (Architecture B)',
  },
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
      <p className="text-xs text-slate-500">
        <span className="font-mono">/dev/token-resource-server</span> is URL-only (not in
        primary nav). It describes the intended B path (GIS + direct admin-api + IAP on
        admin-web only). Current prod web is not on B — revision 00023 is nginx /api,
        not GIS. The comms meeting used snapshot API + web 00023, not B.
      </p>
    </section>
  )
}
