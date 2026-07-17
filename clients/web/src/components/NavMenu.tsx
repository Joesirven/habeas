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

const PIPELINE_GROUP: NavGroup = {
  label: 'Pipeline',
  to: '/ops/drop-pipeline',
  search: { tab: 'home' },
  children: [
    { label: 'Download', to: '/ops/drop-pipeline', search: { tab: 'download' } },
    { label: 'Ingest', to: '/ops/drop-pipeline', search: { tab: 'ingest' } },
    { label: 'Matching', to: '/ops/drop-pipeline', search: { tab: 'matching' } },
    { label: 'Fulfillment', to: '/ops/drop-pipeline', search: { tab: 'fulfillment' } },
    { label: 'Configurations', to: '/ops/drop-pipeline', search: { tab: 'configurations' } },
  ],
}

const HEALTH_GROUP: NavGroup = {
  label: 'Health',
  to: '/ops/health',
  children: [
    { label: 'Escalations / retries', to: '/ops/health/escalations' },
    { label: 'Configuration', to: '/ops/health/configuration' },
  ],
}

function pathMatches(pathname: string, to: string) {
  return pathname === to || pathname.startsWith(`${to}/`)
}

function groupIsActive(pathname: string, group: NavGroup) {
  if (pathMatches(pathname, group.to)) return true
  return group.children.some((child) => pathMatches(pathname, child.to))
}

function NavDropdown({ group }: { group: NavGroup }) {
  const menuId = useId()
  const rootRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const active = groupIsActive(pathname, group)

  const close = useCallback(() => setOpen(false), [])

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
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
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
          className="absolute right-0 top-full z-30 mt-2 min-w-[11rem] rounded-lg border border-[var(--glass-border)] bg-paper-raised/95 py-1 shadow-sm backdrop-blur-md lg:left-0 lg:right-auto"
        >
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
      ) : null}
    </div>
  )
}

export function NavMenu() {
  return (
    <nav className="flex flex-wrap items-center justify-end gap-x-5 gap-y-2 text-[0.8125rem]">
      <Link to="/" className={navClass}>
        Dashboard
      </Link>
      <NavDropdown group={PIPELINE_GROUP} />
      <NavDropdown group={HEALTH_GROUP} />
      <Link to="/requests" className={navClass}>
        Requests
      </Link>
      <Link to="/approvals/matching-review" className={navClass}>
        Matching review
      </Link>
    </nav>
  )
}
