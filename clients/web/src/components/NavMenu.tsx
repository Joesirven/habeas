import { Badge } from '@/components/ui/badge'
import { LegalSettingsSheet } from '@/components/LegalSettingsSheet'
import {
  canAccessLegalSurfaces,
  canAccessOpsSurfaces,
  isLegalAdminPersona,
  useAuth,
} from '@/lib/auth'
import { getLegalNeedsAttention, getNeedsAttention } from '@/lib/api'

import { useQuery } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'

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

const WORKERS_GROUP: NavGroup = {
  label: 'Workers',
  to: '/ops/workers',
  children: [
    { label: 'Overview', to: '/ops/workers' },
    { label: 'Trends', to: '/ops/workers/trends' },
    { label: 'Runs', to: '/ops/runs' },
    { label: 'Settings', to: '/ops/workers/settings' },
  ],
}

function pathMatches(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`)
}

function groupIsActive(pathname: string, group: NavGroup) {
  if (pathMatches(pathname, group.to)) return true
  return group.children.some((child) => pathMatches(pathname, child.to))
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
  const active = exact ? pathname === to : pathMatches(pathname, to)
  return (
    <Link
      to={to}
      search={search}
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
      className="relative"
      onMouseEnter={openMenu}
      onMouseLeave={scheduleClose}
      onKeyDown={onKeyDown}
    >
      <div className="flex items-center gap-1">
        <Link
          to={group.to}
          search={group.search}
          className={`${navClass}${active ? ' active' : ''}`}
          onClick={() => close()}
        >
          {group.label}
        </Link>
        <button
          type="button"
          className="rounded px-1 py-0.5 text-mute hover:text-ink lg:hidden"
          aria-expanded={open}
          aria-controls={menuId}
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
          className="absolute right-0 top-full z-30 min-w-[11rem] pt-2 lg:left-0 lg:right-auto"
        >
          <div className="rounded-lg border border-[var(--glass-border)] bg-paper-raised/95 py-1 shadow-sm backdrop-blur-md">
            {group.children.map((child) => (
              <Link
                key={child.label}
                to={child.to}
                search={child.search}
                role="menuitem"
                className="block px-3 py-2 text-[0.8125rem] text-ink-soft transition-colors hover:bg-paper hover:text-ink"
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
  const { role, isLoading, isError } = useAuth()
  const showWorkers = canAccessOpsSurfaces(role) || isError
  const showLegalExtras = canAccessLegalSurfaces(role)
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
      {legalAdminNav ? <LegalSettingsSheet /> : null}
      {showLegalExtras && !legalAdminNav ? (
        <>
          <NavLink to="/requests/slas" label="SLAs" />
          <NavLink to="/requests/conditions" label="Conditions" />
          <NavLink to="/requests/new" label="Upload" />
        </>
      ) : null}
      {showWorkers ? <NavDropdown group={WORKERS_GROUP} /> : null}
    </nav>
  )
}
