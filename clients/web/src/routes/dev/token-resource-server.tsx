// @ts-nocheck — /dev paths are omitted from the product router Register.
/**
 * Temporary lab — Architecture B as intended (GIS + direct API + IAP on web only).
 * Prod web is not on B: admin-web-prod 00023 (100%) is nginx /api, not GIS.
 * Not in primary nav. Tear down after the post-meeting pick.
 */
import { Link } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const B_HOPS = [
  'IAP stays on admin-web as the human SSO front door (page access only). IAP is off on admin-api.',
  'When VITE_ADMIN_API_URL is an http(s) origin, the SPA loads Google Identity Services (VITE_GOOGLE_CLIENT_ID or VITE_GIS_CLIENT_ID — never a hardcoded client id) and holds a user Google ID token in memory.',
  'JSON fetch goes to that admin-api origin with Authorization: Bearer. nginx is not the REST session.',
  'GET /me maps this token to a role. Empty VITE_ADMIN_API_URL skips GIS and keeps same-origin /api.',
  'EventSource stays on same-origin /api/live/events. Native EventSource cannot set Authorization.',
] as const

const MEETING_HOPS = [
  'The comms meeting needed a loading pipeline console, not a new token path.',
  'admin-api grew GET /ops/drop/console/snapshot so first paint is one payload (ids/counts).',
  'admin-web-prod revision 00023 (100% traffic) is current prod: nginx /api, IAP cookie — not GIS.',
  'Revision 00024 is the B bake at 0% traffic. Do not treat 00023 as GIS or a B bake.',
] as const

const HOP_ROWS = [
  {
    hop: 'Human SSO',
    current: 'IAP on admin-web only. IAP is off on admin-api.',
    emptyVite: 'IAP on admin-web (page + /api proxy)',
  },
  {
    hop: 'Browser credential',
    current:
      'GIS user ID token in memory when a direct admin-api origin is baked. Same-origin /api skips GIS.',
    emptyVite: 'IAP cookie only. GIS is not prompted.',
  },
  {
    hop: 'API session',
    current: 'Browser Bearer on admin-api. nginx is not the REST session.',
    emptyVite: 'nginx mints a service-account Bearer and forwards X-Goog-*',
  },
  {
    hop: 'GET /me',
    current: 'Map this token to a role',
    emptyVite: 'IAP + nginx + sibling Cloud Run + allowlist',
  },
  {
    hop: 'Server-Sent Events',
    current: 'Same-origin EventSource to /api/live/events (no headers)',
    emptyVite: 'Same-origin EventSource to /api/live/events (no headers)',
  },
  {
    hop: 'CLI',
    current: 'ADC Bearer (or ADC + email header) — unchanged',
    emptyVite: 'Unchanged',
  },
] as const

export function TokenResourceServerLabPage() {
  return (
    <section className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="space-y-1">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Temporary · not in primary nav
        </p>
        <h1 className="text-xl font-semibold text-ink">Token resource server</h1>
        <p className="max-w-3xl text-sm text-ink-soft">
          Architecture B as intended in this tree: Google Identity Services, direct
          admin-api, Identity-Aware Proxy on admin-web only. Current prod web is not
          on B — revision 00023 (100% traffic) is nginx /api, not GIS. The 26 Aug 2026
          comms meeting used the snapshot API on that 00023 path.{' '}
          <Link className="text-habeas-navy underline-offset-2 hover:underline" to="/dev">
            All labs
          </Link>
          .
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="default">Intended B · GIS + direct API</Badge>
        <Badge variant="wait">IAP · admin-web only</Badge>
        <Badge variant="wait">Prod 00023 · not GIS</Badge>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <article className="rounded-md border border-line bg-white">
          <header className="border-b border-line px-4 py-3">
            <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
              Architecture B
            </p>
            <h2 className="mt-1 text-sm font-semibold text-ink">Intended path</h2>
          </header>
          <ol className="space-y-2 px-4 py-3 text-xs leading-relaxed text-ink-soft">
            {B_HOPS.map((hop, index) => (
              <li key={hop} className="flex gap-2">
                <span className="font-mono text-mute">{index + 1}.</span>
                <span>{hop}</span>
              </li>
            ))}
          </ol>
        </article>
        <article className="rounded-md border border-line bg-white">
          <header className="border-b border-line px-4 py-3">
            <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
              Meeting
            </p>
            <h2 className="mt-1 text-sm font-semibold text-ink">Snapshot API + 00023</h2>
          </header>
          <ol className="space-y-2 px-4 py-3 text-xs leading-relaxed text-ink-soft">
            {MEETING_HOPS.map((hop, index) => (
              <li key={hop} className="flex gap-2">
                <span className="font-mono text-mute">{index + 1}.</span>
                <span>{hop}</span>
              </li>
            ))}
          </ol>
        </article>
      </div>

      <article className="rounded-md border border-line bg-white">
        <header className="border-b border-line px-4 py-3">
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
            Hop by hop
          </p>
          <h2 className="mt-1 text-sm font-semibold text-ink">B vs empty VITE</h2>
        </header>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Hop</TableHead>
              <TableHead>Intended B</TableHead>
              <TableHead>Empty VITE (prod 00023)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {HOP_ROWS.map((row) => (
              <TableRow key={row.hop}>
                <TableCell className="font-medium text-ink">{row.hop}</TableCell>
                <TableCell className="text-ink-soft">{row.current}</TableCell>
                <TableCell className="text-mute">{row.emptyVite}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </article>

      <div className="grid gap-3 lg:grid-cols-2">
        <article className="rounded-md border border-line bg-white px-4 py-3">
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
            GIS mint is gated
          </p>
          <p className="mt-2 text-xs leading-relaxed text-ink-soft">
            Direct admin-api (<span className="font-mono">VITE_ADMIN_API_URL</span> set) loads
            Google Identity Services at runtime and stores the user ID token in memory only.
            Same-origin <span className="font-mono">/api</span> skips GIS so local and empty-URL
            images stay on the nginx/Vite proxy. Do not invent or hardcode a client id.
          </p>
        </article>
        <article className="rounded-md border border-line bg-white px-4 py-3">
          <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
            Server-Sent Events stay same-origin
          </p>
          <p className="mt-2 text-xs leading-relaxed text-ink-soft">
            Live updates stay on admin-api <span className="font-mono">GET /live/events</span>.
            The browser uses native <span className="font-mono">EventSource</span>, which cannot
            set Authorization. Keep the same-origin{' '}
            <span className="font-mono">/api/live/events</span> proxy even when JSON goes
            cross-origin. Do not move the event bus onto nginx.
          </p>
        </article>
      </div>

      <article className="rounded-md border border-line bg-canvas px-4 py-3">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Meeting vs B
        </p>
        <p className="mt-2 text-xs leading-relaxed text-ink-soft">
          26 Aug 2026 — Communications onboarding needed a loading console. That cutover was{' '}
          <span className="font-mono">GET /ops/drop/console/snapshot</span> plus web revision
          00023 (still 100% of prod; nginx /api, not GIS). Architecture B is intended in
          this tree and is not what prod serves. Do not claim prod already uses Google
          Identity Services. This lab is URL-only — not in primary nav.
        </p>
      </article>
    </section>
  )
}
