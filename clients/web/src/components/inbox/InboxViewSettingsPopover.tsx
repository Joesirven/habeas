import { forwardRef, type ComponentPropsWithoutRef } from 'react'

import { Button } from '@/components/ui/button'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { cn } from '@/lib/utils'

export type InboxViewSettingsPatch = {
  groupByBatch?: boolean
  groupBySystem?: boolean
  groupByStatus?: boolean
  matchFilter?: string
  dueFilter?: string
  system?: string | undefined
  source?: string | undefined
  step?: string | undefined
}

export type InboxViewSettingsOption = {
  id: string
  label: string
  count?: number
}

export type InboxViewSettingsPopoverProps = {
  groupByBatch: boolean
  groupBySystem: boolean
  groupByStatus: boolean
  matchFilter: string
  dueFilter: string
  systemFilter?: string
  sourceFilter?: string
  stepFilter?: string
  systemOptions: readonly InboxViewSettingsOption[]
  sourceOptions: readonly InboxViewSettingsOption[]
  stepOptions: readonly InboxViewSettingsOption[]
  matchOptions: readonly InboxViewSettingsOption[]
  dueOptions: readonly InboxViewSettingsOption[]
  showSystem: boolean
  onChange: (patch: InboxViewSettingsPatch) => void
  className?: string
}

/** Hover titles on every trigger and option. System = connection; Source = intake. */
export const INBOX_VIEW_SETTING_HINTS = {
  groupBy: 'Choose how inbox rows are grouped',
  groupByBatch: 'Group by intake batch (date + source)',
  groupBySystem: 'Group by data system / connection — owner reviews matching per system',
  groupByStatus: 'Group by matching status (disposition, needs connection / refresh, or confirmed)',
  result: 'Filter by matching result',
  resultAll: 'Show all matching results',
  due: 'Filter by due date',
  dueAll: 'Show all due dates',
  filters: 'Filter by system (connection), source (intake), and step',
  filtersWithoutSystem: 'Filter by source (intake) and step',
  system: 'Filter by data system / connection. Test vertical uses System A / System B.',
  systemAll: 'Show all data systems',
  source: 'Filter by intake source (CA DROP vs other). Not a connection.',
  sourceAll: 'Show all sources',
  step: 'Filter by journey step',
  stepAll: 'Show all journey steps',
} as const

export type InboxViewGroupByOption = {
  label: string
  title: string
  active: boolean
  onClick: () => void
}

export type InboxViewFilterSectionModel = {
  key: 'system' | 'source' | 'step'
  label: string
  title: string
  allTitle: string
  value: string | undefined
  options: readonly InboxViewSettingsOption[]
  onSelect: (next: string | undefined) => void
}

/** Option lists and titles the popovers render. Tests read this instead of closed Radix portals. */
export function inboxViewSettingsInterior(props: InboxViewSettingsPopoverProps): {
  groupByOptions: InboxViewGroupByOption[]
  filterSections: InboxViewFilterSectionModel[]
} {
  const groupByOptions: InboxViewGroupByOption[] = [
    {
      label: 'Batch',
      title: INBOX_VIEW_SETTING_HINTS.groupByBatch,
      active: props.groupByBatch,
      onClick: () => props.onChange({ groupByBatch: !props.groupByBatch }),
    },
  ]
  if (props.showSystem) {
    groupByOptions.push({
      label: 'System',
      title: INBOX_VIEW_SETTING_HINTS.groupBySystem,
      active: props.groupBySystem,
      onClick: () => props.onChange({ groupBySystem: !props.groupBySystem }),
    })
  }
  groupByOptions.push({
    label: 'Status',
    title: INBOX_VIEW_SETTING_HINTS.groupByStatus,
    active: props.groupByStatus,
    onClick: () => props.onChange({ groupByStatus: !props.groupByStatus }),
  })

  const filterSections: InboxViewFilterSectionModel[] = []
  if (props.showSystem) {
    filterSections.push({
      key: 'system',
      label: 'System',
      title: INBOX_VIEW_SETTING_HINTS.system,
      allTitle: INBOX_VIEW_SETTING_HINTS.systemAll,
      value: props.systemFilter,
      options: props.systemOptions,
      onSelect: (next) => props.onChange({ system: next }),
    })
  }
  filterSections.push(
    {
      key: 'source',
      label: 'Source',
      title: INBOX_VIEW_SETTING_HINTS.source,
      allTitle: INBOX_VIEW_SETTING_HINTS.sourceAll,
      value: props.sourceFilter,
      options: props.sourceOptions,
      onSelect: (next) => props.onChange({ source: next }),
    },
    {
      key: 'step',
      label: 'Step',
      title: INBOX_VIEW_SETTING_HINTS.step,
      allTitle: INBOX_VIEW_SETTING_HINTS.stepAll,
      value: props.stepFilter,
      options: props.stepOptions,
      onSelect: (next) => props.onChange({ step: next }),
    },
  )
  return { groupByOptions, filterSections }
}

const SettingsTrigger = forwardRef<
  HTMLButtonElement,
  {
    label: string
    summary: string
    title: string
  } & Omit<ComponentPropsWithoutRef<typeof Button>, 'title' | 'children'>
>(function SettingsTrigger({ label, summary, title, className, ...props }, ref) {
  return (
    <Button
      ref={ref}
      type="button"
      variant="outline"
      size="sm"
      title={title}
      data-settings-trigger={label}
      className={cn('h-7 max-w-[11rem] gap-1 px-2 text-[0.65rem]', className)}
      {...props}
    >
      <span className="text-mute">{label}</span>
      <span className="truncate font-medium text-ink">{summary}</span>
    </Button>
  )
})

function OptionButton({
  active,
  label,
  title,
  count,
  onClick,
}: {
  active: boolean
  label: string
  title: string
  count?: number
  onClick: () => void
}) {
  return (
    <button
      type="button"
      title={title}
      className={cn(
        'flex w-full items-center justify-between rounded-md px-2 py-1 text-left text-[0.7rem]',
        active ? 'bg-habeas-navy/10 font-medium text-habeas-navy' : 'hover:bg-panel/70',
      )}
      aria-pressed={active}
      onClick={onClick}
    >
      <span>{label}</span>
      {count != null ? <span className="tabular-nums text-mute">{count}</span> : null}
    </button>
  )
}

function optionSummary(
  value: string | undefined,
  options: readonly InboxViewSettingsOption[],
): string | null {
  if (value == null || value === '') return null
  return options.find((row) => row.id === value)?.label ?? value
}

function FilterSection({
  label,
  title,
  allTitle,
  value,
  options,
  onSelect,
}: {
  label: string
  title: string
  allTitle: string
  value: string | undefined
  options: readonly InboxViewSettingsOption[]
  onSelect: (next: string | undefined) => void
}) {
  const allActive = value == null || value === ''
  return (
    <div className="space-y-1">
      <p
        className="px-1 text-[0.6rem] font-medium uppercase tracking-wide text-mute"
        title={title}
      >
        {label}
      </p>
      <OptionButton
        active={allActive}
        label="All"
        title={allTitle}
        onClick={() => onSelect(undefined)}
      />
      {options.map((row) => (
        <OptionButton
          key={row.id}
          active={value === row.id}
          label={row.label}
          title={`${title}: ${row.label}`}
          count={row.count}
          onClick={() => onSelect(value === row.id ? undefined : row.id)}
        />
      ))}
    </div>
  )
}

/** Compact Group by / Result / Due plus folded System · Source · Step filters. No Vertical.
 *  Group-by option is Status (disposition), not the Result match-type filter. */
export function InboxViewSettingsPopover({
  groupByBatch,
  groupBySystem,
  groupByStatus,
  matchFilter,
  dueFilter,
  systemFilter,
  sourceFilter,
  stepFilter,
  systemOptions,
  sourceOptions,
  stepOptions,
  matchOptions,
  dueOptions,
  showSystem,
  onChange,
  className,
}: InboxViewSettingsPopoverProps) {
  const groupSummary = [
    groupByBatch ? 'Batch' : null,
    showSystem && groupBySystem ? 'System' : null,
    groupByStatus ? 'Status' : null,
  ]
    .filter(Boolean)
    .join(', ')

  const matchSummary =
    matchFilter === 'all'
      ? 'All'
      : (matchOptions.find((row) => row.id === matchFilter)?.label ?? matchFilter)
  const dueSummary =
    dueFilter === 'all'
      ? 'All'
      : (dueOptions.find((row) => row.id === dueFilter)?.label ?? dueFilter)

  const filterParts = [
    showSystem ? optionSummary(systemFilter, systemOptions) : null,
    optionSummary(sourceFilter, sourceOptions),
    optionSummary(stepFilter, stepOptions),
  ].filter(Boolean)
  const filtersSummary = filterParts.join(', ') || 'All'
  const filtersTitle = showSystem
    ? INBOX_VIEW_SETTING_HINTS.filters
    : INBOX_VIEW_SETTING_HINTS.filtersWithoutSystem
  const { groupByOptions, filterSections } = inboxViewSettingsInterior({
    groupByBatch,
    groupBySystem,
    groupByStatus,
    matchFilter,
    dueFilter,
    systemFilter,
    sourceFilter,
    stepFilter,
    systemOptions,
    sourceOptions,
    stepOptions,
    matchOptions,
    dueOptions,
    showSystem,
    onChange,
  })

  return (
    <div
      className={cn('flex shrink-0 flex-wrap items-center gap-1', className)}
      role="group"
      aria-label="Inbox view settings"
      data-show-system={showSystem ? 'true' : 'false'}
    >
      <Popover>
        <PopoverTrigger asChild>
          <SettingsTrigger
            label="Group by"
            summary={groupSummary || 'Off'}
            title={INBOX_VIEW_SETTING_HINTS.groupBy}
          />
        </PopoverTrigger>
        <PopoverContent className="w-56 space-y-1" align="start">
          <p className="px-1 pb-1 text-[0.6rem] font-medium uppercase tracking-wide text-mute">
            Group by
          </p>
          {groupByOptions.map((option) => (
            <OptionButton
              key={option.label}
              active={option.active}
              label={option.label}
              title={option.title}
              onClick={option.onClick}
            />
          ))}
        </PopoverContent>
      </Popover>

      <Popover>
        <PopoverTrigger asChild>
          <SettingsTrigger
            label="Result"
            summary={matchSummary}
            title={INBOX_VIEW_SETTING_HINTS.result}
          />
        </PopoverTrigger>
        <PopoverContent className="w-56 space-y-1" align="start">
          <OptionButton
            active={matchFilter === 'all'}
            label="All"
            title={INBOX_VIEW_SETTING_HINTS.resultAll}
            onClick={() => onChange({ matchFilter: 'all' })}
          />
          {matchOptions.map((row) => (
            <OptionButton
              key={row.id}
              active={matchFilter === row.id}
              label={row.label}
              title={`${INBOX_VIEW_SETTING_HINTS.result}: ${row.label}`}
              count={row.count}
              onClick={() =>
                onChange({ matchFilter: matchFilter === row.id ? 'all' : row.id })
              }
            />
          ))}
        </PopoverContent>
      </Popover>

      {dueOptions.length > 0 ? (
        <Popover>
          <PopoverTrigger asChild>
            <SettingsTrigger
              label="Due"
              summary={dueSummary}
              title={INBOX_VIEW_SETTING_HINTS.due}
            />
          </PopoverTrigger>
          <PopoverContent className="w-52 space-y-1" align="start">
            <OptionButton
              active={dueFilter === 'all'}
              label="All"
              title={INBOX_VIEW_SETTING_HINTS.dueAll}
              onClick={() => onChange({ dueFilter: 'all' })}
            />
            {dueOptions.map((row) => (
              <OptionButton
                key={row.id}
                active={dueFilter === row.id}
                label={row.label}
                title={`${INBOX_VIEW_SETTING_HINTS.due}: ${row.label}`}
                count={row.count}
                onClick={() =>
                  onChange({ dueFilter: dueFilter === row.id ? 'all' : row.id })
                }
              />
            ))}
          </PopoverContent>
        </Popover>
      ) : null}

      <Popover>
        <PopoverTrigger asChild>
          <SettingsTrigger
            label="Filters"
            summary={filtersSummary}
            title={filtersTitle}
          />
        </PopoverTrigger>
        <PopoverContent className="w-56 space-y-2.5" align="start">
          {filterSections.map((section) => (
            <FilterSection
              key={section.key}
              label={section.label}
              title={section.title}
              allTitle={section.allTitle}
              value={section.value}
              options={section.options}
              onSelect={section.onSelect}
            />
          ))}
        </PopoverContent>
      </Popover>
    </div>
  )
}
