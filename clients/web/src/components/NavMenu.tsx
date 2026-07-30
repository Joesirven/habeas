import { Badge } from '@/components/ui/badge'
import {
  canAccessOpsSurfaces,
  isLegalAdminPersona,
  useAuth,
} from '@/lib/auth'
import { getLegalNeedsAttention, getNeedsAttention } from '@/lib/api'

import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'

const navClass =
  'text-mute transition-colors hover:text-ink [&.active]:text-ink [&.active]:underline [&.active]:decoration-ink/25 [&.active]:underline-offset-4'

function pathMatches(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`)
}

function NavLink({
  to,
  label,
  exact = false,
  count,
  search,
}: {
  to: string
  label: string
  exact?: boolean
  count?: number | null
  search?: Record<string, string | number | undefined>
}) {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  // TanStack Link also adds `.active` for prefix matches unless exact is set —
  // without activeOptions, `/requests` stays selected on `/requests/needs-attention`.
  const active = exact ? pathname === to : pathMatches(pathname, to)
  return (
    <Link
      to={to}
      search={search}
      activeOptions={{ exact, includeSearch: false }}
      className={`inline-flex items-center gap-1.5 ${navClass}${active ? ' active' : ''}`}
    >
      {label}
      {count != null && count > 0 ? (
        <Badge variant="notification" aria-label={`${count} unread`}>
          {count > 99 ? '99+' : count}
        </Badge>
      ) : null}
    </Link>
  )
}

export function NavMenu() {
  const { role, isLoading } = useAuth()
  const legalAdminNav = isLegalAdminPersona(role)
  const homeLabel = canAccessOpsSurfaces(role)
    ? 'Dashboard'
    : legalAdminNav
      ? 'Home'
      : 'My work'

  const isLegalNav = legalAdminNav
  const inboxQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      isLegalNav ? 'legal' : 'ops',
      'nav',
    ],
    queryFn: () =>
      isLegalNav
        ? getLegalNeedsAttention(200)
        : getNeedsAttention({ limit: 200, kind: 'all' }),
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
  const inboxCount = inboxQuery.data?.items.length ?? null

  return (
    <nav
      className="flex flex-wrap items-center justify-end gap-x-5 gap-y-2 text-[0.8125rem]"
      aria-busy={isLoading}
    >
      <NavLink to="/" label={homeLabel} exact />
      <NavLink
        to="/requests"
        label={legalAdminNav ? 'All requests' : 'Requests'}
        exact
      />
      <NavLink
        to="/requests/needs-attention"
        label="Inbox"
        count={inboxCount}
        search={isLegalNav ? { kind: 'triage' } : undefined}
      />
      <NavLink to="/docs" label="Docs" exact />
    </nav>
  )
}
