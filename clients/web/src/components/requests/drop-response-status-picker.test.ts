// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import { DROP_RESPONSE_STATUS_OPTIONS } from '../../lib/api'

import {
  OWNER_RESPONSE_STATUS_OPTIONS,
  dropResponseStatusPickerChrome,
  matchingDispositionCopy,
  matchingNotLiveCalloutCopy,
  ownerDropStatusLabel,
} from './RequestTriageDialog'

describe('DropResponseStatusPicker chrome (AE29)', () => {
  test('owner persona labels are Confirm match (3), Multi-person (4), Not a match (5)', () => {
    const chrome = dropResponseStatusPickerChrome('data_owner')
    expect(OWNER_RESPONSE_STATUS_OPTIONS).toEqual([
      { code: 3, label: 'Confirm match' },
      { code: 4, label: 'Multi-person' },
      { code: 5, label: 'Not a match' },
    ])
    expect(chrome.options).toEqual(OWNER_RESPONSE_STATUS_OPTIONS)
    expect(chrome.options.map((option) => [option.code, option.label])).toEqual([
      [3, 'Confirm match'],
      [4, 'Multi-person'],
      [5, 'Not a match'],
    ])
    expect(chrome.showCodes).toBe(false)
  })

  test('owner legend is not “CA DROP status result”', () => {
    const chrome = dropResponseStatusPickerChrome('data_owner')
    expect(chrome.legend).not.toBe('CA DROP status result')
    expect(chrome.legend).not.toMatch(/CA DROP/i)
    expect(chrome.helperText).toBeNull()
    expect(chrome.helperText ?? '').not.toMatch(/CA DROP/i)
    expect(chrome.helperText ?? '').not.toMatch(/Promote-to-raw/)
  })

  test('legal persona still uses Deleted / Opted out / Not found with codes', () => {
    const chrome = dropResponseStatusPickerChrome('legal')
    expect(chrome.options).toEqual(DROP_RESPONSE_STATUS_OPTIONS)
    expect(chrome.options).toEqual([
      { code: 3, label: 'Deleted' },
      { code: 4, label: 'Opted out' },
      { code: 5, label: 'Not found' },
    ])
    expect(chrome.showCodes).toBe(true)
    expect(chrome.legend).toBe('CA DROP status result')
    expect(chrome.helperText).toContain('3 Deleted')
    expect(chrome.helperText).toContain('4 Opted out')
    expect(chrome.helperText).toContain('5 Not found')
    expect(chrome.helperText).toContain('Promote-to-raw')
  })

  test('ops persona matches legal code+label chrome', () => {
    const ops = dropResponseStatusPickerChrome('ops')
    const legal = dropResponseStatusPickerChrome('legal')
    expect(ops).toEqual(legal)
    expect(ops.showCodes).toBe(true)
    expect(ops.options.map((option) => `${option.code} ${option.label}`)).toEqual([
      '3 Deleted',
      '4 Opted out',
      '5 Not found',
    ])
  })

  test('owner overlay/panel copy has no Deleted / Opted out / Not found', () => {
    const copy = matchingDispositionCopy('data_owner')
    expect(ownerDropStatusLabel(3)).toBe('Confirm match')
    expect(ownerDropStatusLabel(4)).toBe('Multi-person')
    expect(ownerDropStatusLabel(5)).toBe('Not a match')
    expect(copy.blurb).not.toMatch(/CA DROP|Deleted|Opted out|Not found/)
    expect(copy.confirmDescription('abc12345')).toMatch(/Confirm the match result/)
    expect(copy.confirmDescription('abc12345')).not.toMatch(/CA DROP/)
    expect(copy.confirmLabel).toBe('Confirm')
    expect(matchingDispositionCopy('legal').confirmLabel).toBe('Fulfill')
  })
})

describe('matching not-live callout (owner language)', () => {
  test('sheet stub keeps confirm/decline without catalog-only or CA DROP people', () => {
    const copy = matchingNotLiveCalloutCopy({
      result_kind: 'sheet_stub',
      system_label: 'People / HR',
    })
    expect(copy.title).toBe('Sheet matching not live')
    expect(copy.reason).toBe(
      'People / HR has no match result. Confirm or decline this inbox item.',
    )
    expect(copy.reason).toMatch(/Confirm or decline/)
    expect(copy.reason).not.toMatch(/catalog-only/i)
    expect(copy.reason).not.toMatch(/CA DROP/i)
    expect(copy.reason).not.toMatch(/not this system/i)
    expect(copy.reason).not.toMatch(/matching is not live/i)
  })

  test('saas stub keeps confirm/decline without invented matching claims', () => {
    const copy = matchingNotLiveCalloutCopy({
      result_kind: 'saas_stub',
      system: 'cassandra',
      system_label: 'Cassandra',
    })
    expect(copy.title).toBe('System matching not live')
    expect(copy.reason).toBe(
      'Cassandra has no match result. Confirm or decline this inbox item.',
    )
    expect(copy.reason).toMatch(/Confirm or decline/)
    expect(copy.reason).not.toMatch(/catalog-only/i)
    expect(copy.reason).not.toMatch(/CA DROP/i)
    expect(copy.reason).not.toMatch(/without CA DROP people/i)
  })

  test('prefers API not_live_reason when present', () => {
    const copy = matchingNotLiveCalloutCopy({
      result_kind: 'sheet_stub',
      system_label: 'People / HR',
      not_live_reason: 'Upload is stale.',
    })
    expect(copy.reason).toBe('Upload is stale.')
  })
})
