import { Badge } from '@/components/ui/badge'
import {
  canAccessOpsSurfaces,
  isLegalAdminPersona,
  useAuth,
} from '@/lib/auth'
import {
  getLegalNeedsAttention,
  getNeedsAttention,
  getOwnerFulfillmentNeedsAttention,
  getOwnerMatchingNeedsAttention,
} from '@/lib/api'

import { inboxPendingWorkUnitCount } from '@/lib/inbox-batch-status'

import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from 'react'

const navClass =
  'text-mute transition-colors hover:text-ink [&.active]:text-ink [&.active]:underline [&.active]:decoration-ink/25 [&.active]:underline-offset-4'

type NavChild = {
  label: string
  to: string
  search?: Record<string, string>
  /** Match pathname exactly — needed when `/requests` shares a prefix with Inbox / lab. */
  exact?: boolean
  count?: number | null
  /** Temporary lab — hover submenu only, not a product surface. */
  temp?: boolean
}

type NavGroup = {
  label: string
  to: string
  search?: Record<string, string>
  count?: number | null
  children: NavChild[]
}

/** Super-admin DROP ops — Pipeline umbrella; legal/admin keep Home · Requests ▾. */
const PIPELINE_GROUP: NavGroup = {
  label: 'Pipeline',
  to: '/ops/drop-pipeline',
  children: [
    { label: 'Workers', to: '/ops/workers' },
    { label: 'Settings', to: '/ops/workers/settings' },
    { label: 'Runs', to: '/ops/runs' },
    { label: 'Connections', to: '/ops/connections' },
    { label: 'DROP prod cutover', to: '/dev/drop-prod-cutover', temp: true },
  ],
}

function requestsGroup(opts: {
  legalAdmin: boolean
  showResultsLab: boolean
  inboxCount?: number | null
}): NavGroup {
  const children: NavChild[] = [
    {
      label: 'Inbox',
      to: '/requests/needs-attention',
      search: opts.legalAdmin ? { kind: 'triage' } : undefined,
      count: opts.inboxCount,
    },
    { label: 'All requests', to: '/requests', search: {}, exact: true },
    { label: 'Batches', to: '/requests', search: { view: 'batch' }, exact: true },
  ]
  if (opts.showResultsLab) {
    children.push({ label: 'Results lab', to: '/requests/matching-results-lab', temp: true })
  }
  return {
    label: 'Requests',
    to: '/requests',
    search: {},
    count: opts.inboxCount,
    children,
  }
}

function useInboxWorkUnitCount(): number | null {
  const { me } = useAuth()
  const query = useInboxNavQuery()
  return useMemo(() => {
    if (!query.data) return null
    return inboxPendingWorkUnitCount(query.data.items ?? [], {
      reminders: me?.connector_reminders,
    })
  }, [me?.connector_reminders, query.data])
}

function useInboxNavQuery() {
  const { role } = useAuth()
  const isLegalNav = isLegalAdminPersona(role)
  const isDataOwnerNav = role === 'data_owner' || role === 'data_user'
  return useQuery({
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
          getOwnerMatchingNeedsAttention({ limit: 200 }),
          getOwnerFulfillmentNeedsAttention({ limit: 200 }),
        ])
        const matchingTotal = matching.total ?? matching.items.length
        const fulfillmentTotal = fulfillment.total ?? fulfillment.items.length
        return {
          items: [...matching.items, ...fulfillment.items],
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
}

/** Title-row inbox entry. Count only — no matching/delivery/notice/comms letter codes. */
export function InboxEntryPill() {
  const { role } = useAuth()
  const legalAdmin = isLegalAdminPersona(role)
  const workUnitCount = useInboxWorkUnitCount()
  const total = workUnitCount ?? 0

  return (
    <Link
      to="/requests/needs-attention"
      search={legalAdmin ? { kind: 'triage' } : undefined}
      className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-line bg-paper px-2 py-0.5 text-[0.65rem] text-ink-soft transition-colors hover:border-habeas-navy/35 hover:text-ink"
      aria-label={total > 0 ? `Inbox, ${total} pending` : 'Inbox'}
    >
      <span className="font-medium text-ink">Inbox</span>
      {total > 0 ? (
        <Badge variant="notification" className="min-w-[1.1rem] justify-center px-1">
          {total > 99 ? '99+' : total}
        </Badge>
      ) : null}
    </Link>
  )
}

function settingsGroup(showOwnerConnectors: boolean, showDevLabs: boolean): NavGroup {
  const children: NavChild[] = []
  if (showOwnerConnectors) {
    children.push({ label: 'Connectors', to: '/owner/connectors' })
  }
  children.push({ label: 'Docs', to: '/docs' })
  if (showDevLabs) {
    children.push({ label: 'Sheets OAuth', to: '/dev/sheets-oauth', temp: true })
    children.push({ label: 'Sheets cadence', to: '/dev/sheets-cadence-lab', temp: true })
    children.push({ label: 'Pending settings', to: '/dev/pending-settings', temp: true })
    children.push({ label: 'All labs', to: '/dev', exact: true, temp: true })
  }
  return {
    label: 'Settings',
    to: showOwnerConnectors ? '/owner/connectors' : '/docs',
    children,
  }
}

function NavCount({ count }: { count?: number | null }) {
  if (count == null || count <= 0) return null
  return (
    <Badge variant="notification" aria-label={`${count} unread`}>
      {count > 99 ? '99+' : count}
    </Badge>
  )
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

function childIsActive(
  pathname: string,
  search: Record<string, unknown>,
  child: NavChild,
) {
  const pathOk = child.exact ? pathname === child.to : pathMatches(pathname, child.to)
  if (!pathOk) return false
  if (child.search && Object.keys(child.search).length > 0) {
    return Object.entries(child.search).every(([key, value]) => search[key] === value)
  }
  // Unfiltered `/requests` sibling — active only when not on the batch view.
  if (child.exact && child.to === '/requests') return search.view !== 'batch'
  return true
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
      <NavCount count={count} />
    </Link>
  )
}

function NavDropdown({ group }: { group: NavGroup }) {
  const menuId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const pendingFocusRef = useRef(false)
  const [open, setOpen] = useState(false)
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const locationSearch = useRouterState({
    select: (state) => state.location.search as Record<string, unknown>,
  })
  const active = groupIsActive(pathname, group)

  const clearCloseTimer = useCallback(() => {
    if (closeTimerRef.current != null) {
      clearTimeout(closeTimerRef.current)
      closeTimerRef.current = null
    }
  }, [])

  const close = useCallback(() => {
    clearCloseTimer()
    pendingFocusRef.current = false
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

  useEffect(() => {
    if (!open || !pendingFocusRef.current) return
    pendingFocusRef.current = false
    rootRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
  }, [open])

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      if (open) {
        rootRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus()
        return
      }
      pendingFocusRef.current = true
      openMenu()
    }
  }

  function onFocusOut(event: FocusEvent<HTMLDivElement>) {
    if (!rootRef.current?.contains(event.relatedTarget as Node)) {
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
      onBlur={onFocusOut}
    >
      <div className="flex items-center gap-0.5">
        <Link
          to={group.to}
          search={group.search}
          activeOptions={{ exact: false, includeSearch: false }}
          className={`inline-flex items-center gap-1.5 ${navClass}${active ? ' active' : ''}`}
          onClick={() => close()}
        >
          {group.label}
          <NavCount count={group.count} />
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
          className="absolute right-0 top-full z-50 mt-1 min-w-[14rem] max-w-[min(20rem,calc(100vw-1.5rem))]"
        >
          <div className="overflow-hidden rounded-md border border-line bg-white py-1 shadow-md">
            {group.children.map((child) => {
              const childActive = childIsActive(pathname, locationSearch, child)
              return (
                <Link
                  key={child.label}
                  to={child.to}
                  search={child.search}
                  activeOptions={{
                    exact: child.exact ?? false,
                    includeSearch: Boolean(child.search),
                  }}
                  role="menuitem"
                  className={`flex items-center justify-between gap-3 px-3 py-2 text-[0.8125rem] transition-colors hover:bg-panel hover:text-ink ${
                    childActive ? 'bg-panel text-ink' : 'text-ink-soft'
                  }`}
                  onClick={() => close()}
                >
                  <span className="flex min-w-0 items-baseline gap-1.5">
                    <span className="truncate">{child.label}</span>
                    {child.temp ? (
                      <span className="shrink-0 text-[0.65rem] uppercase tracking-wide text-mute">
                        temp
                      </span>
                    ) : null}
                  </span>
                  <NavCount count={child.count} />
                </Link>
              )
            })}
          </div>
        </div>
      ) : null}
    </div>
  )
}

export function NavMenu() {
  const { role, isLoading } = useAuth()
  const inboxCount = useInboxWorkUnitCount()
  const showOps = canAccessOpsSurfaces(role)
  const legalAdminNav = isLegalAdminPersona(role)
  const isOwnerPersona = role === 'data_owner' || role === 'data_user'
  const showOwnerConnectors =
    isOwnerPersona || role === 'admin' || role === 'super_admin'
  const showDevLabs = role === 'super_admin'
  const homeLabel = 'Home'

  return (
    <nav
      className="flex flex-wrap items-center justify-end gap-x-5 gap-y-2 text-[0.8125rem]"
      aria-busy={isLoading}
    >
      {showOps ? <NavDropdown group={PIPELINE_GROUP} /> : <NavLink to="/" label={homeLabel} exact />}
      <NavDropdown
        group={requestsGroup({
          legalAdmin: legalAdminNav,
          showResultsLab: showOps && !legalAdminNav && !isOwnerPersona,
          inboxCount,
        })}
      />
      <NavDropdown group={settingsGroup(showOwnerConnectors, showDevLabs)} />
    </nav>
  )
}
