import { Badge } from '@/components/ui/badge'
import {
  canAccessOpsSurfaces,
  isLegalAdminPersona,
  useAuth,
} from '@/lib/auth'
import { getLegalNeedsAttention, getNeedsAttention, getOwnerFulfillmentNeedsAttention } from '@/lib/api'

import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'

const navClass =
  'text-mute transition-colors hover:text-ink [&.active]:text-ink [&.active]:underline [&.active]:decoration-ink/25 [&.active]:underline-offset-4'

type NavChild = {
  label: string
  to: string
  search?: Record<string, string>
}

type NavGroup = {
  label: string
  to: string
  search?: Record<string, string>
  children: NavChild[]
}

/** Super-admin DROP ops — Pipeline umbrella; legal/admin keep Home · Requests · Inbox (KD2). */
const PIPELINE_GROUP: NavGroup = {
  label: 'Pipeline',
  to: '/ops/drop-pipeline',
  children: [
    { label: 'Workers', to: '/ops/workers' },
    { label: 'Settings', to: '/ops/workers/settings' },
    { label: 'Runs', to: '/ops/runs' },
    { label: 'Connections', to: '/ops/connections' },
  ],
}

function pathMatches(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`)
}

function groupIsActive(pathname: string, group: NavGroup) {
  if (pathMatches(pathname, group.to)) return true
  if (group.children.some((child) => pathMatches(pathname, child.to))) return true
  // Pipeline umbrella: light up for any /ops/* surface (settings, trends, jobs, …).
  if (group.label === 'Pipeline' && pathname.startsWith('/ops/')) return true
  return false
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

function NavDropdown({ group }: { group: NavGroup }) {
  const menuId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [open, setOpen] = useState(false)
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const active = groupIsActive(pathname, group)

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current != null) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }, [])

  const close = useCallback(() => {
    clearCloseTimer()
    setOpen(false)
  }, [clearCloseTimer])

  const openMenu = useCallback(() => {
    clearCloseTimer()
    setOpen(true)
  }, [clearCloseTimer])

  const scheduleClose = useCallback(() => {
    clearCloseTimer()
    closeTimerRef.current = setTimeout(() => setOpen(false), 120)
  }, [clearCloseTimer])

  useEffect(() => () => clearCloseTimer(), [clearCloseTimer])

  useEffect(() => {
    if (!open) return
    function onPointerDown(event: MouseEvent) {
      if (!rootRef.current?.contains(event.target as Node)) {
        close()
      }
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open, close])

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    }
  }

  return (
    <div
      ref={rootRef}
      className="relative shrink-0"
      onMouseEnter={openMenu}
      onMouseLeave={scheduleClose}
      onKeyDown={onKeyDown}
    >
      <div className="flex items-center gap-0.5">
        <Link
          to={group.to}
          search={group.search}
          activeOptions={{ exact: false, includeSearch: false }}
          className={`${navClass}${active ? ' active' : ''}`}
          onClick={() => close()}
        >
          {group.label}
        </Link>
        <button
          type="button"
          className="rounded px-1 py-0.5 text-mute hover:text-ink"
          aria-expanded={open}
          aria-controls={menuId}
          aria-haspopup="menu"
          aria-label={`${group.label} menu`}
          onClick={() => setOpen((value) => !value)}
        >
          ▾
        </button>
      </div>

      {open ? (
        <div
          id={menuId}
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 min-w-[12rem] max-w-[min(16rem,calc(100vw-1.5rem))]"
        >
          <div className="overflow-hidden rounded-md border border-line bg-white py-1 shadow-md">
            {group.children.map((child) => (
              <Link
                key={child.label}
                to={child.to}
                search={child.search}
                role="menuitem"
                className="block px-3 py-2 text-[0.8125rem] text-ink-soft transition-colors hover:bg-panel hover:text-ink"
                onClick={() => close()}
              >
                {child.label}
              </Link>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function NavMenu() {
  const { role, isLoading } = useAuth()
  const showOps = canAccessOpsSurfaces(role)
  const legalAdminNav = isLegalAdminPersona(role)
  const showOwnerConnectors =
    role === 'data_owner' ||
    role === 'data_user' ||
    role === 'admin' ||
    role === 'super_admin'
  const homeLabel = legalAdminNav || role === 'data_owner' || role === 'data_user' ? 'Home' : 'My work'

  const isLegalNav = legalAdminNav
  const isDataOwnerNav = role === 'data_owner' || role === 'data_user'
  const inboxQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      isLegalNav ? 'legal' : isDataOwnerNav ? 'data-owner' : 'ops',
      'nav',
    ],
    queryFn: async () => {
      if (isLegalNav) return getLegalNeedsAttention({ limit: 200 })
      if (isDataOwnerNav) {
        const [matching, fulfillment] = await Promise.all([
          getNeedsAttention({ limit: 200, kind: 'matching' }),
          getOwnerFulfillmentNeedsAttention({ limit: 200 }),
        ])
        const matchingTotal = matching.total ?? matching.items.length
        const fulfillmentTotal = fulfillment.total ?? fulfillment.items.length
        return {
          items: matching.items,
          kind: matching.kind,
          total: matchingTotal + fulfillmentTotal,
          limit: matching.limit,
          offset: matching.offset,
        }
      }
      return getNeedsAttention({ limit: 200, kind: 'all' })
    },
    refetchInterval: 30_000,
    staleTime: 15_000,
  })
  const inboxCount = inboxQuery.data?.total ?? inboxQuery.data?.items.length ?? null

  return (
    <nav
      className="flex flex-wrap items-center justify-end gap-x-5 gap-y-2 text-[0.8125rem]"
      aria-busy={isLoading}
    >
      {showOps ? <NavDropdown group={PIPELINE_GROUP} /> : <NavLink to="/" label={homeLabel} exact />}
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
      {showOwnerConnectors ? (
        <NavLink to="/owner/connectors" label="Connectors" exact />
      ) : null}
      <NavLink to="/docs" label="Docs" exact />
    </nav>
  )
}
