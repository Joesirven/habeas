import { useEffect, useMemo, useRef, useState } from 'react'

import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

import {
  ResultApplyBar,
  ResultMatchMeta,
  resultViewEmpty,
  toggleDwid,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

type ComboboxRow = { id: string; label: string }

function SearchCombobox({
  ariaLabel,
  triggerLabel,
  placeholder,
  options,
  selectedIds,
  multi,
  disabled,
  onPick,
}: {
  ariaLabel: string
  triggerLabel: string
  placeholder: string
  options: ComboboxRow[]
  selectedIds: string[]
  multi: boolean
  disabled?: boolean
  onPick: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [activeIndex, setActiveIndex] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return options
    return options.filter((row) => row.label.toLowerCase().includes(needle))
  }, [options, query])

  function close() {
    setOpen(false)
    setQuery('')
    setActiveIndex(0)
  }

  useEffect(() => {
    if (!open) return
    setActiveIndex(0)
    const frame = window.requestAnimationFrame(() => inputRef.current?.focus())
    return () => window.cancelAnimationFrame(frame)
  }, [open])

  useEffect(() => {
    setActiveIndex((current) => {
      if (filtered.length === 0) return 0
      return Math.min(current, filtered.length - 1)
    })
  }, [filtered.length])

  useEffect(() => {
    const node = listRef.current?.querySelector<HTMLElement>(`[data-index="${activeIndex}"]`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex])

  function pick(id: string) {
    onPick(id)
    if (!multi) close()
  }

  function onInputKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((current) => (filtered.length ? (current + 1) % filtered.length : 0))
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((current) =>
        filtered.length ? (current - 1 + filtered.length) % filtered.length : 0,
      )
      return
    }
    if (event.key === 'Enter') {
      event.preventDefault()
      const row = filtered[activeIndex]
      if (row) pick(row.id)
      return
    }
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    }
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (!next) close()
        else setOpen(true)
      }}
    >
      <PopoverTrigger asChild>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={ariaLabel}
          className="h-7 w-full max-w-sm justify-between gap-2 px-2 text-[0.65rem] font-normal"
        >
          <span className="truncate text-ink">{triggerLabel}</span>
          <span className="shrink-0 text-mute" aria-hidden>
            ▼
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-0" align="start">
        <div className="border-b border-line px-2 py-1.5">
          <input
            ref={inputRef}
            type="search"
            value={query}
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={onInputKeyDown}
            placeholder={placeholder}
            className="w-full bg-transparent text-xs text-ink outline-none placeholder:text-mute"
            aria-label={placeholder}
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <div
          ref={listRef}
          className="max-h-56 overflow-y-auto py-1"
          role="listbox"
          aria-label={ariaLabel}
        >
          {filtered.length === 0 ? (
            <p className="px-2 py-3 text-xs text-mute">No matches.</p>
          ) : (
            filtered.map((row, index) => {
              const selected = selectedIds.includes(row.id)
              return (
                <button
                  key={row.id}
                  type="button"
                  data-index={index}
                  role="option"
                  aria-selected={selected}
                  className={cn(
                    'flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs',
                    index === activeIndex ? 'bg-panel text-ink' : 'text-ink-soft hover:bg-panel/70',
                    selected && 'font-medium text-habeas-navy',
                  )}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => pick(row.id)}
                >
                  <span className="truncate">{row.label}</span>
                  {selected ? (
                    <span className="shrink-0 text-[0.6rem] text-mute">
                      {multi ? 'on' : 'current'}
                    </span>
                  ) : null}
                </button>
              )
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  )
}

/** Search-first typeahead for person, then status (Command/Combobox). */
export function ComboboxView({
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
  if (empty) return empty

  const peopleLocked = statusId === '5'
  const personRows = contacts.map((contact) => ({
    id: contact.dwid,
    label: formatMatchedContactLabel(contact),
  }))
  const selectedPerson = contacts.find((contact) => selectedDwids.includes(contact.dwid))
  const personTrigger =
    selectedDwids.length === 0
      ? 'Search people…'
      : selectedDwids.length === 1 && selectedPerson
        ? formatMatchedContactLabel(selectedPerson)
        : `${selectedDwids.length} people selected`
  const statusTrigger =
    statusOptions.find((option) => option.id === statusId)?.label ?? 'Search status…'

  return (
    <div className="space-y-3">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      <ol className="space-y-2">
        <li className="space-y-1">
          <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
            1 · Person
          </p>
          {peopleLocked ? (
            <p className="text-xs text-mute">Not found clears selected people.</p>
          ) : contacts.length === 0 ? (
            <p className="text-xs text-mute">No matched people.</p>
          ) : (
            <SearchCombobox
              ariaLabel="Search matched people"
              triggerLabel={personTrigger}
              placeholder="Type to filter people…"
              options={personRows}
              selectedIds={selectedDwids}
              multi
              disabled={disabled || pending}
              onPick={(dwid) => onSelectedDwidsChange(toggleDwid(selectedDwids, dwid))}
            />
          )}
        </li>
        <li className="space-y-1">
          <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
            2 · Status
          </p>
          <SearchCombobox
            ariaLabel="Search match status"
            triggerLabel={statusTrigger}
            placeholder="Type to filter status…"
            options={statusOptions.map((option) => ({ id: option.id, label: option.label }))}
            selectedIds={statusId ? [statusId] : []}
            multi={false}
            disabled={disabled || pending}
            onPick={onStatusChange}
          />
        </li>
      </ol>
      <ResultApplyBar
        pending={pending}
        disabled={disabled || statusId == null}
        statusId={statusId}
        selectedDwids={selectedDwids}
        onApply={onApply}
      />
    </div>
  )
}
