import { useQuery } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { OPEN_LEGAL_SETTINGS_EVENT } from '@/components/LegalSettingsSheet'
import {
  getLegalOperators,
  listRequests,
  type LegalOperator,
  type RequestRecord,
} from '@/lib/api'
import { canAccessLegalSurfaces, useMe } from '@/lib/auth'
import type { LegalInboxFilter } from '@/router'

const SOURCE_LABELS: Record<string, string> = {
  drop: 'CA DROP',
  webform: 'Gravity Forms',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

type PaletteGroup = 'requests' | 'people' | 'actions'

type PaletteItem = {
  id: string
  group: PaletteGroup
  label: string
  sublabel?: string
  onSelect: () => void
}

function requestPaletteLabel(request: RequestRecord): string {
  if (request.intake_source === 'drop') {
    const shortId = request.id.length > 8 ? `${request.id.slice(0, 8)}…` : request.id
    return `${shortId} · ${SOURCE_LABELS.drop}`
  }
  return request.display_label?.trim() || request.id
}

function operatorSublabel(operator: LegalOperator): string {
  if (operator.kind === 'legal_team') return 'Legal team'
  if (operator.kind === 'data_owner') return 'Data team'
  if (operator.kind === 'assignee') return 'Assignee'
  return operator.kind
}

function staticActions(
  navigate: ReturnType<typeof useNavigate>,
  showPeople: boolean,
  showSuperAdminOps: boolean,
  onClose: () => void,
): PaletteItem[] {
  const finish = (fn: () => void) => () => {
    fn()
    onClose()
  }

  const inbox = (filter?: LegalInboxFilter) => {
    navigate({
      to: '/requests/needs-attention',
      search: filter ? { filter } : {},
    })
  }

  const items: PaletteItem[] = [
    {
      id: 'action-home',
      group: 'actions',
      label: 'Go to Home',
      onSelect: finish(() => navigate({ to: '/', search: { tab: 'pipeline' } })),
    },
    {
      id: 'action-requests',
      group: 'actions',
      label: 'Go to All requests',
      onSelect: finish(() => navigate({ to: '/requests' })),
    },
    {
      id: 'action-inbox',
      group: 'actions',
      label: 'Go to Inbox',
      onSelect: finish(() => inbox()),
    },
    {
      id: 'action-docs',
      group: 'actions',
      label: 'Go to Docs',
      onSelect: finish(() => navigate({ to: '/docs' })),
    },
    {
      id: 'action-workers',
      group: 'actions',
      label: 'Go to Workers',
      onSelect: finish(() => navigate({ to: '/ops/workers' })),
    },
    {
      id: 'action-runs',
      group: 'actions',
      label: 'Go to Runs',
      onSelect: finish(() => navigate({ to: '/ops/runs' })),
    },
    ...(showSuperAdminOps
      ? [
          {
            id: 'action-connections',
            group: 'actions' as const,
            label: 'Go to Connections',
            onSelect: finish(() => navigate({ to: '/ops/connections' })),
          },
        ]
      : []),

    {
      id: 'action-inbox-unassigned',
      group: 'actions',
      label: 'Inbox · Unassigned',
      onSelect: finish(() => inbox('unassigned')),
    },
    {
      id: 'action-inbox-assignment',
      group: 'actions',
      label: 'Inbox · Assignment to legal',
      onSelect: finish(() => inbox('assignment_to_legal')),
    },
    {
      id: 'action-inbox-fulfillment',
      group: 'actions',
      label: 'Inbox · Fulfillment',
      onSelect: finish(() => inbox('fulfillment')),
    },
    {
      id: 'action-inbox-notice',
      group: 'actions',
      label: 'Inbox · Notice',
      onSelect: finish(() => inbox('notice')),
    },
    {
      id: 'action-inbox-delivery',
      group: 'actions',
      label: 'Inbox · Delivery',
      onSelect: finish(() => inbox('delivery')),
    },
    {
      id: 'action-inbox-holds',
      group: 'actions',
      label: 'Inbox · Pre-matching holds',
      onSelect: finish(() => inbox('pre_matching_holds')),
    },
    {
      id: 'action-inbox-me',
      group: 'actions',
      label: 'Inbox · Assigned to me',
      onSelect: finish(() => inbox('assigned_to_me')),
    },
    {
      id: 'action-upload',
      group: 'actions',
      label: 'Upload request',
      onSelect: finish(() => navigate({ to: '/requests/new' })),
    },
    {
      id: 'action-settings',
      group: 'actions',
      label: 'Open Settings',
      onSelect: finish(() => {
        document.dispatchEvent(new CustomEvent(OPEN_LEGAL_SETTINGS_EVENT))
      }),
    },
  ]

  if (!showPeople) {
    return items.filter((item) => item.id !== 'action-settings')
  }

  return items
}

type CommandPaletteProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const navigate = useNavigate()
  const { role, me, isSuperAdmin } = useMe()
  const showPeople = canAccessLegalSurfaces(role)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const trimmedQuery = query.trim()
  const requestSearchEnabled = trimmedQuery.length >= 2

  const requestsQuery = useQuery({
    queryKey: ['admin-api', 'palette', 'requests', trimmedQuery],
    queryFn: () => listRequests({ q: trimmedQuery, limit: 8 }),
    enabled: open && requestSearchEnabled,
    staleTime: 10_000,
  })

  const operatorsQuery = useQuery({
    queryKey: ['admin-api', 'palette', 'operators'],
    queryFn: getLegalOperators,
    enabled: open && showPeople,
    staleTime: 60_000,
  })

  const close = useCallback(() => {
    onOpenChange(false)
    setQuery('')
    setActiveIndex(0)
  }, [onOpenChange])

  const items = useMemo(() => {
    const result: PaletteItem[] = []
    const needle = trimmedQuery.toLowerCase()

    if (requestSearchEnabled && requestsQuery.data) {
      for (const request of requestsQuery.data.items) {
        result.push({
          id: `request-${request.id}`,
          group: 'requests',
          label: requestPaletteLabel(request),
          sublabel: SOURCE_LABELS[request.intake_source] ?? request.intake_source,
          onSelect: () => {
            navigate({
              to: '/requests/$requestId',
              params: { requestId: request.id },
            })
            close()
          },
        })
      }
    }

    if (showPeople && operatorsQuery.data) {
      const filteredOperators = needle
        ? operatorsQuery.data.filter((operator) =>
            operator.email.toLowerCase().includes(needle),
          )
        : operatorsQuery.data.slice(0, 8)

      for (const operator of filteredOperators) {
        result.push({
          id: `person-${operator.email}`,
          group: 'people',
          label: operator.email,
          sublabel: operatorSublabel(operator),
          onSelect: () => {
            if (me?.email && operator.email.toLowerCase() === me.email.toLowerCase()) {
              navigate({
                to: '/requests/needs-attention',
                search: { filter: 'assigned_to_me' },
              })
            } else if (operator.kind === 'legal_team') {
              navigate({
                to: '/requests/needs-attention',
                search: { filter: 'assignment_to_legal' },
              })
            } else {
              navigate({ to: '/requests/needs-attention' })
            }
            close()
          },
        })
      }
    }

    const actions = staticActions(navigate, showPeople, isSuperAdmin, close).filter((item) => {
      if (!needle) return true
      return item.label.toLowerCase().includes(needle)
    })
    result.push(...actions)

    return result
  }, [
    close,
    me?.email,
    navigate,
    operatorsQuery.data,
    requestSearchEnabled,
    requestsQuery.data,
    showPeople,
    isSuperAdmin,
    trimmedQuery,
  ])

  useEffect(() => {
    if (!open) return
    setActiveIndex(0)
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [open])

  useEffect(() => {
    setActiveIndex((current) => {
      if (items.length === 0) return 0
      return Math.min(current, items.length - 1)
    })
  }, [items.length])

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  function selectItem(index: number) {
    const item = items[index]
    if (!item) return
    item.onSelect()
  }

  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((current) => (items.length ? (current + 1) % items.length : 0))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((current) =>
        items.length ? (current - 1 + items.length) % items.length : 0,
      )
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      selectItem(activeIndex)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    }
  }

  const grouped = {
    requests: items.filter((item) => item.group === 'requests'),
    people: items.filter((item) => item.group === 'people'),
    actions: items.filter((item) => item.group === 'actions'),
  }

  let runningIndex = -1

  function renderGroup(title: string, groupItems: PaletteItem[]) {
    if (groupItems.length === 0) return null
    return (
      <div key={title} className="py-1">
        <p className="px-3 py-1 text-[0.65rem] font-medium uppercase tracking-[0.08em] text-mute">
          {title}
        </p>
        <ul>
          {groupItems.map((item) => {
            runningIndex += 1
            const index = runningIndex
            const active = index === activeIndex
            return (
              <li key={item.id}>
                <button
                  type="button"
                  data-index={index}
                  className={`flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm ${
                    active ? 'bg-panel text-ink' : 'text-ink-soft hover:bg-panel/70'
                  }`}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => selectItem(index)}
                >
                  <span className="truncate">{item.label}</span>
                  {item.sublabel ? (
                    <span className="shrink-0 text-xs text-mute">{item.sublabel}</span>
                  ) : null}
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="max-w-xl gap-0 overflow-hidden p-0"
        onOpenAutoFocus={(event) => event.preventDefault()}
      >
        <DialogHeader className="border-b border-line px-4 py-3">
          <DialogTitle className="sr-only">Command palette</DialogTitle>
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={onInputKeyDown}
            placeholder="Search requests, people, or actions…"
            className="w-full bg-transparent text-sm text-ink outline-none placeholder:text-mute"
            aria-label="Command palette search"
            autoComplete="off"
            spellCheck={false}
          />
          <p className="text-[0.65rem] text-mute">
            {!requestSearchEnabled && trimmedQuery.length > 0
              ? 'Requests need at least 2 characters.'
              : 'Type to search — arrow keys navigate, Enter selects, Esc closes.'}
          </p>
        </DialogHeader>
        <div ref={listRef} className="max-h-[min(24rem,50vh)] overflow-y-auto py-1">
          {requestsQuery.isFetching && requestSearchEnabled ? (
            <p className="px-3 py-2 text-xs text-mute">Searching requests…</p>
          ) : null}
          {!requestSearchEnabled && trimmedQuery.length > 0 ? (
            <p className="px-3 py-2 text-xs text-mute">Keep typing to search requests.</p>
          ) : null}
          {items.length === 0 ? (
            <p className="px-3 py-4 text-sm text-mute">No results.</p>
          ) : (
            <>
              {renderGroup('Requests', grouped.requests)}
              {showPeople ? renderGroup('People', grouped.people) : null}
              {renderGroup('Actions', grouped.actions)}
            </>
          )}
        </div>
        <div className="border-t border-line px-4 py-2 text-[0.65rem] text-mute">
          <span className="rounded border border-line px-1.5 py-0.5">↑↓</span> navigate{' '}
          <span className="rounded border border-line px-1.5 py-0.5">↵</span> select{' '}
          <span className="rounded border border-line px-1.5 py-0.5">esc</span> close
        </div>
      </DialogContent>
    </Dialog>
  )
}

export function useCommandPaletteShortcut(onOpen: () => void) {
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        onOpen()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onOpen])
}