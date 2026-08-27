// @ts-nocheck — /dev paths are omitted from the product router Register.
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
  {
    to: '/dev/owner-map-fallback',
    label: 'Owner map / live-fail fallback',
  },
  {
    to: '/dev/owner-map-alternatives',
    label: 'Owner map alternatives (8 variants)',
  },
  {
    to: '/dev/match-quality',
    label: 'Match quality (8 variants)',
  },
] as const

const OWNER_WIZARD_LINKS = [
  {
    vertical: 'people_hr',
    label: 'People/HR wizard (Lever / Paylocity)',
    note: 'Live fail → Retry connection or Set up manual upload, then map columns. Live ping is not candidate matching.',
  },
  {
    vertical: 'communications',
    label: 'Communications wizard (Axios HQ)',
    note: 'Upload-every-batch. Map identifier columns if headers differ — email or phone is enough.',
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
        primary nav). Architecture B is the intended authorized identity: GIS user JWT
        → admin-api as resource server, IAP on admin-web only. Master yaml was reverted
        in 2094211; ARCH-B is re-shipping the bake. Bake is not live traffic until that
        cutover — do not treat nginx /api as the standing prod JSON path.
      </p>
      <p className="text-xs text-slate-500">
        <span className="font-mono">/dev/owner-map-fallback</span> still redirects to the
        owner wizard. Use{' '}
        <span className="font-mono">/dev/owner-map-alternatives</span> for the eight-variant
        switcher (default A). Cassandra has no mapping or hash; it is an infra card on{' '}
        <Link className="underline underline-offset-2" to="/ops/connections">
          /ops/connections
        </Link>
        .
      </p>
      <ul className="space-y-3 text-sm">
        {OWNER_WIZARD_LINKS.map((lab) => (
          <li key={lab.vertical}>
            <Link
              className="underline underline-offset-2"
              to="/owner/connectors"
              search={{ vertical: lab.vertical }}
            >
              {lab.label}
            </Link>
            <span className="ml-2 font-mono text-xs text-slate-500">
              /owner/connectors?vertical={lab.vertical}
            </span>
            <p className="mt-0.5 text-xs text-slate-500">{lab.note}</p>
          </li>
        ))}
      </ul>
    </section>
  )
}
