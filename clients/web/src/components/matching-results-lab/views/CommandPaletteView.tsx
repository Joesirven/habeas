import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
} from 'react'

import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { cn } from '@/lib/utils'

import {
  ResultMatchMeta,
  applyNeedsPeople,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import {
  matchingLabItemKey,
  type MatchingResultsViewProps,
} from '../matching-results-lab-types'

type CommandGroup = 'Status' | 'People' | 'Apply'

type CommandRow = {
  kind: 'status' | 'person' | 'apply'
  id: string
  group: CommandGroup
  verb: string
  label: string
  current: boolean
  disabled?: boolean
}

/** Keyboard command list — set status, toggle person, or apply (cmdk-style, no dialog). */
export function CommandPaletteView({
  item,
  detail,
  contacts,
  loading,
  ownerLanguage,
  statusOptions,
  statusId,
  onStatusChange,
  selectedDwids,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
}: MatchingResultsViewProps) {
  const empty = resultViewEmpty(loading, Boolean(item))
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const itemKey = item ? matchingLabItemKey(item) : ''

  const statusLabel =
    statusOptions.find((option) => option.id === statusId)?.label ?? 'No status'
  const peopleLocked = statusId === '5'
  const applyBlocked =
    disabled || pending || statusId == null || applyNeedsPeople(statusId, selectedDwids)

  const commands = useMemo<CommandRow[]>(() => {
    const statusRows: CommandRow[] = statusOptions.map((option) => ({
      kind: 'status',
      id: option.id,
      group: 'Status',
      verb: 'Set status',
      label: option.label,
      current: option.id === statusId,
    }))
    const personRows: CommandRow[] = peopleLocked
      ? []
      : contacts.map((contact) => ({
          kind: 'person',
          id: contact.dwid,
          group: 'People',
          verb: 'Toggle person',
          label: formatMatchedContactLabel(contact),
          current: selectedDwids.includes(contact.dwid),
        }))
    const applyRow: CommandRow = {
      kind: 'apply',
      id: 'apply',
      group: 'Apply',
      verb: 'Apply',
      label:
        statusId == null
          ? 'Choose a status first'
          : peopleLocked
            ? `${statusLabel} · no people`
            : `${statusLabel} · ${selectedDwids.length} people`,
      current: false,
      disabled: applyBlocked,
    }
    return [...statusRows, ...personRows, applyRow]
  }, [
    applyBlocked,
    contacts,
    peopleLocked,
    selectedDwids,
    statusId,
    statusLabel,
    statusOptions,
  ])

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return commands
    return commands.filter((row) =>
      `${row.verb} ${row.label}`.toLowerCase().includes(needle),
    )
  }, [commands, query])

  const runCommand = useCallback(
    (row: CommandRow) => {
      if (disabled || pending || row.disabled) return
      if (row.kind === 'status') {
        onStatusChange(row.id)
        return
      }
      if (row.kind === 'person') {
        onSelectedDwidsChange(toggleDwid(selectedDwids, row.id))
        return
      }
      onApply()
    },
    [
      disabled,
      onApply,
      onSelectedDwidsChange,
      onStatusChange,
      pending,
      selectedDwids,
    ],
  )

  useEffect(() => {
    setQuery('')
    setActiveIndex(0)
  }, [itemKey])

  useEffect(() => {
    if (empty) return
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [empty, itemKey])

  useEffect(() => {
    setActiveIndex((current) => {
      if (rows.length === 0) return 0
      return Math.min(current, rows.length - 1)
    })
  }, [rows.length])

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(
      `[data-index="${activeIndex}"]`,
    )
    node?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  if (empty) return empty

  function onInputKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((current) => (rows.length ? (current + 1) % rows.length : 0))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((current) =>
        rows.length ? (current - 1 + rows.length) % rows.length : 0,
      )
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const row = rows[activeIndex]
      if (row) runCommand(row)
    }
  }

  const groups = (['Status', 'People', 'Apply'] as const).filter((group) =>
    rows.some((row) => row.group === group),
  )

  return (
    <div className="space-y-2">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      <p className="text-[0.65rem] text-ink-soft">
        {statusLabel}
        <span className="text-mute">
          {' '}
          · {peopleLocked ? 'people cleared' : `${selectedDwids.length} selected`}
        </span>
      </p>

      <div className="overflow-hidden rounded-md border border-line bg-paper">
        <div className="border-b border-line px-2.5 py-1.5">
          <input
            ref={inputRef}
            type="search"
            value={query}
            disabled={disabled || pending}
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={onInputKeyDown}
            placeholder="Type a command…"
            className="w-full bg-transparent text-xs text-ink outline-none placeholder:text-mute disabled:opacity-50"
            aria-label="Filter commands"
            autoComplete="off"
            spellCheck={false}
          />
          <p className="mt-0.5 text-[0.6rem] text-mute">
            ↑↓ navigate · ↵ run · set status · toggle person · apply
          </p>
        </div>

        <div
          ref={listRef}
          className="max-h-[min(18rem,45vh)] overflow-y-auto py-1"
          role="listbox"
          aria-label="Matching commands"
        >
          {rows.length === 0 ? (
            <p className="px-2.5 py-3 text-xs text-mute">No matching commands.</p>
          ) : (
            groups.map((group) => {
              const grouped = rows.filter((row) => row.group === group)
              return (
                <div key={group}>
                  <p className="px-2.5 pt-1.5 pb-0.5 text-[0.6rem] font-medium uppercase tracking-wide text-mute">
                    {group}
                  </p>
                  {grouped.map((row) => {
                    const index = rows.indexOf(row)
                    const active = index === activeIndex
                    return (
                      <button
                        key={`${row.kind}:${row.id}`}
                        type="button"
                        data-index={index}
                        role="option"
                        aria-selected={row.current}
                        disabled={disabled || pending || row.disabled}
                        className={cn(
                          'flex w-full items-center justify-between gap-3 px-2.5 py-1.5 text-left text-xs',
                          active ? 'bg-panel text-ink' : 'text-ink-soft hover:bg-panel/70',
                          row.current && 'font-medium text-habeas-navy',
                          (disabled || pending || row.disabled) && 'opacity-50',
                        )}
                        onMouseEnter={() => setActiveIndex(index)}
                        onClick={() => runCommand(row)}
                      >
                        <span className="min-w-0 truncate">
                          <span className="text-mute">{row.verb}</span>
                          {' · '}
                          {row.label}
                        </span>
                        {row.kind === 'apply' && pending ? (
                          <span className="shrink-0 text-[0.6rem] text-mute">working</span>
                        ) : row.current ? (
                          <span className="shrink-0 text-[0.6rem] text-mute">
                            {row.kind === 'person' ? 'on' : 'current'}
                          </span>
                        ) : null}
                      </button>
                    )
                  })}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
