// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import {
  InboxViewSettingsPopover,
  INBOX_VIEW_SETTING_HINTS,
  inboxViewSettingsInterior,
  type InboxViewSettingsPatch,
} from './InboxViewSettingsPopover'

const baseProps = {
  groupByBatch: true,
  groupBySystem: false,
  groupByStatus: false,
  matchFilter: 'all',
  dueFilter: 'all',
  systemFilter: undefined,
  sourceFilter: undefined,
  stepFilter: undefined,
  systemOptions: [{ id: 'lever', label: 'Lever' }],
  sourceOptions: [{ id: 'drop', label: 'DROP' }],
  stepOptions: [{ id: 'matching', label: 'Matching' }],
  matchOptions: [{ id: 'single_match', label: 'Single match', count: 2 }],
  dueOptions: [{ id: 'overdue', label: 'Overdue', count: 1 }],
  showSystem: true,
  onChange: (_patch: InboxViewSettingsPatch) => undefined,
}

function renderPopover(overrides: Record<string, unknown> = {}) {
  return renderToStaticMarkup(
    createElement(InboxViewSettingsPopover, { ...baseProps, ...overrides }),
  )
}

describe('InboxViewSettingsPopover', () => {
  test('labels are Group by, Result, Due, Filters — Batch not Date + source', () => {
    const html = renderPopover()
    expect(html).toContain('Group by')
    expect(html).toContain('Batch')
    expect(html).toContain('Result')
    expect(html).toContain('Due')
    expect(html).toContain('Filters')
    expect(inboxViewSettingsInterior(baseProps).groupByOptions.map((row) => row.label)).toEqual(
      ['Batch', 'System', 'Status'],
    )
    expect(renderPopover({ groupByStatus: true })).toContain('Status')
    expect(html).not.toContain('Date + source')
    expect(html).not.toContain('>Type<')
    expect(html).not.toContain('>Group<')
    expect(html).not.toContain('Vertical')
  })

  test('System bar trigger is gone when System/Source/Step are folded into Filters', () => {
    const html = renderPopover({ groupBySystem: false })
    expect(html).toContain('data-settings-trigger="Filters"')
    expect(html).toContain('data-settings-trigger="Group by"')
    expect(html).toContain('data-settings-trigger="Result"')
    expect(html).toContain('data-settings-trigger="Due"')
    expect(html).not.toContain('data-settings-trigger="System"')
    expect(html).not.toContain('data-settings-trigger="Source"')
    expect(html).not.toContain('data-settings-trigger="Step"')
  })

  test('title hover hints are on every trigger and every named option', () => {
    const html = renderPopover()
    expect(html).toContain(`title="${INBOX_VIEW_SETTING_HINTS.groupBy}"`)
    expect(html).toContain(`title="${INBOX_VIEW_SETTING_HINTS.result}"`)
    expect(html).toContain(`title="${INBOX_VIEW_SETTING_HINTS.due}"`)
    expect(html).toContain(`title="${INBOX_VIEW_SETTING_HINTS.filters}"`)

    const { groupByOptions, filterSections } = inboxViewSettingsInterior(baseProps)
    expect(groupByOptions.find((row) => row.label === 'Batch')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.groupByBatch,
    )
    expect(groupByOptions.find((row) => row.label === 'System')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.groupBySystem,
    )
    expect(groupByOptions.find((row) => row.label === 'Status')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.groupByStatus,
    )
    expect(filterSections.find((row) => row.key === 'system')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.system,
    )
    expect(filterSections.find((row) => row.key === 'source')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.source,
    )
    expect(filterSections.find((row) => row.key === 'step')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.step,
    )
    expect(filterSections.find((row) => row.key === 'system')?.allTitle).toBe(
      INBOX_VIEW_SETTING_HINTS.systemAll,
    )
    expect(filterSections.find((row) => row.key === 'source')?.allTitle).toBe(
      INBOX_VIEW_SETTING_HINTS.sourceAll,
    )
    expect(filterSections.find((row) => row.key === 'step')?.allTitle).toBe(
      INBOX_VIEW_SETTING_HINTS.stepAll,
    )
  })

  test('popover interiors expose Batch title, hide System when showSystem=false, and label Source + Step', () => {
    const shown = inboxViewSettingsInterior(baseProps)
    expect(shown.groupByOptions.find((row) => row.label === 'Batch')?.title).toBe(
      INBOX_VIEW_SETTING_HINTS.groupByBatch,
    )
    expect(shown.filterSections.map((row) => row.label)).toEqual(['System', 'Source', 'Step'])

    const hidden = inboxViewSettingsInterior({ ...baseProps, showSystem: false })
    expect(hidden.groupByOptions.map((row) => row.label)).toEqual(['Batch', 'Status'])
    expect(hidden.groupByOptions.some((row) => row.label === 'System')).toBe(false)
    expect(hidden.filterSections.some((row) => row.key === 'system')).toBe(false)
    expect(hidden.filterSections.map((row) => row.label)).toEqual(['Source', 'Step'])
  })

  test('showSystem=false hides System group-by and System filter', () => {
    const hidden = renderPopover({
      showSystem: false,
      groupBySystem: true,
      systemFilter: 'lever',
    })
    expect(hidden).toContain('data-show-system="false"')
    expect(hidden).toContain('Batch')
    expect(hidden).not.toContain('>System<')
    expect(hidden).not.toContain('data-settings-trigger="System"')
    expect(hidden).toContain(`title="${INBOX_VIEW_SETTING_HINTS.filtersWithoutSystem}"`)
    expect(hidden).not.toContain(`title="${INBOX_VIEW_SETTING_HINTS.filters}"`)
    expect(hidden).not.toContain('Lever')

    const shown = renderPopover({
      showSystem: true,
      groupBySystem: true,
      systemFilter: 'lever',
    })
    expect(shown).toContain('data-show-system="true"')
    expect(shown).toContain('System')
    expect(shown).toContain('Lever')
    expect(shown).toContain(`title="${INBOX_VIEW_SETTING_HINTS.filters}"`)
  })

  test('All and toggle-off emit explicit undefined for system, source, and step', () => {
    const patches: InboxViewSettingsPatch[] = []
    const onChange = (patch: InboxViewSettingsPatch) => {
      patches.push(patch)
    }
    const selected = {
      ...baseProps,
      systemFilter: 'lever',
      sourceFilter: 'drop',
      stepFilter: 'matching',
      onChange,
    }
    createElement(InboxViewSettingsPopover, selected)
    const { groupByOptions, filterSections } = inboxViewSettingsInterior(selected)

    const system = filterSections.find((row) => row.key === 'system')
    const source = filterSections.find((row) => row.key === 'source')
    const step = filterSections.find((row) => row.key === 'step')
    expect(system && source && step).toBeTruthy()

    system.onSelect(undefined)
    expect(patches.at(-1)).toEqual({ system: undefined })
    expect('system' in patches.at(-1)).toBe(true)
    expect(patches.at(-1).system).toBeUndefined()

    system.onSelect(system.value === 'lever' ? undefined : 'lever')
    expect(patches.at(-1)).toEqual({ system: undefined })
    expect('system' in patches.at(-1)).toBe(true)

    source.onSelect(undefined)
    expect(patches.at(-1)).toEqual({ source: undefined })
    expect('source' in patches.at(-1)).toBe(true)
    expect(patches.at(-1).source).toBeUndefined()

    source.onSelect(source.value === 'drop' ? undefined : 'drop')
    expect(patches.at(-1)).toEqual({ source: undefined })
    expect('source' in patches.at(-1)).toBe(true)

    step.onSelect(undefined)
    expect(patches.at(-1)).toEqual({ step: undefined })
    expect('step' in patches.at(-1)).toBe(true)
    expect(patches.at(-1).step).toBeUndefined()

    step.onSelect(step.value === 'matching' ? undefined : 'matching')
    expect(patches.at(-1)).toEqual({ step: undefined })
    expect('step' in patches.at(-1)).toBe(true)

    groupByOptions.find((row) => row.label === 'Batch')?.onClick()
    expect(patches.at(-1)).toEqual({ groupByBatch: false })
    groupByOptions.find((row) => row.label === 'System')?.onClick()
    expect(patches.at(-1)).toEqual({ groupBySystem: true })
    groupByOptions.find((row) => row.label === 'Status')?.onClick()
    expect(patches.at(-1)).toEqual({ groupByStatus: true })
  })
})
