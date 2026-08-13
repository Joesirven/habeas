// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { ConnectorReminder } from './api'
import {
  MULTI_PII_DELIMITER_OPTIONS,
  activeModeFromMetadata,
  allowsLive,
  allowsUpload,
  buildReminderBannerItems,
    cadenceDaysFromMetadata,
  delimiterOptionFromKey,
  delimiterValueFromKey,
  displayStatusChip,
  liveConnectReady,
  ownerWizardStepIndex,
  visibleReminderBanners,
} from './owner-connector-ui'

describe('MULTI_PII_DELIMITER_OPTIONS (AE10 UI)', () => {
  test('presents None / ; / | / ,', () => {
    expect(MULTI_PII_DELIMITER_OPTIONS.map((o) => o.value)).toEqual([
      null,
      ';',
      '|',
      ',',
    ])
    expect(MULTI_PII_DELIMITER_OPTIONS[0].label).toContain('None')
    expect(MULTI_PII_DELIMITER_OPTIONS.map((o) => o.key)).toEqual([
      'none',
      ';',
      '|',
      ',',
    ])
  })

  test('delimiterValueFromKey maps none to null', () => {
    expect(delimiterValueFromKey('none')).toBeNull()
    expect(delimiterValueFromKey(';')).toBe(';')
    expect(delimiterValueFromKey('|')).toBe('|')
    expect(delimiterValueFromKey(',')).toBe(',')
    expect(delimiterOptionFromKey('unknown').key).toBe('none')
  })
})

describe('displayStatusChip (KD18)', () => {
  test('maps gated statuses to Needs refresh / Action required / Needs setup', () => {
    expect(displayStatusChip('needs_refresh').label).toBe('Needs refresh')
    expect(displayStatusChip('needs_refresh').variant).toBe('fail')
    expect(displayStatusChip('action_required').label).toBe('Action required')
    expect(displayStatusChip('needs_setup').label).toBe('Needs setup')
    expect(displayStatusChip('view_only').label).toBe('View only')
  })

  test('never shows Connected when gate fails', () => {
    const chip = displayStatusChip('connected', { gateAllowed: false })
    expect(chip.label).not.toBe('Connected')
    expect(chip.label).toBe('Needs refresh')
  })

  test('shows Connected only when gate allows', () => {
    expect(displayStatusChip('connected', { gateAllowed: true }).label).toBe(
      'Connected',
    )
    expect(displayStatusChip('connected').label).toBe('Connected')
  })

  test('gateAllowed false with action_required keeps Action required', () => {
    expect(
      displayStatusChip('action_required', { gateAllowed: false }).label,
    ).toBe('Action required')
  })
})

describe('reminder banners (R10 soft)', () => {
  const sample: ConnectorReminder[] = [
    {
      code: 'upload_stale',
      system: 'mailchimp',
      vertical_id: 'communications',
      severity: 'overdue',
    },
    {
      code: 'rotation_approaching',
      system: 'lever',
      vertical_id: 'people_hr',
      severity: 'approaching',
    },
  ]

  test('builds non-blocking banner items from reminders', () => {
    const items = buildReminderBannerItems(sample)
    expect(items).toHaveLength(2)
    expect(items[0].id).toBe('communications:mailchimp:upload_stale')
    expect(items[0].severity).toBe('overdue')
    expect(items[0].title.toLowerCase()).toContain('overdue')
    expect(items[1].severity).toBe('approaching')
  })

  test('empty / null reminders yield no banners', () => {
    expect(buildReminderBannerItems(null)).toEqual([])
    expect(buildReminderBannerItems([])).toEqual([])
  })

  test('local dismiss hides banners without blocking', () => {
    const items = buildReminderBannerItems(sample)
    const visible = visibleReminderBanners(items, [items[0].id])
    expect(visible).toHaveLength(1)
    expect(visible[0].system).toBe('lever')
  })

  test('unknown code still produces soft copy', () => {
    const items = buildReminderBannerItems([
      {
        code: 'custom_code',
        system: 'paylocity',
        vertical_id: 'people_hr',
        severity: 'approaching',
      },
    ])
    expect(items[0].title.toLowerCase()).toContain('approaching')
    expect(items[0].description.toLowerCase()).toContain('does not block')
  })

  test('wizard_incomplete uses curated copy', () => {
    const items = buildReminderBannerItems([
      {
        code: 'wizard_incomplete',
        system: 'lever',
        vertical_id: 'people_hr',
        severity: 'overdue',
      },
    ])
    expect(items[0].title.toLowerCase()).toContain('incomplete')
  })
})

describe('mode and cadence helpers', () => {
  test('allowsUpload / allowsLive', () => {
    expect(allowsUpload(['live', 'upload'])).toBe(true)
    expect(allowsUpload(['live'])).toBe(false)
    expect(allowsLive(['live'])).toBe(true)
    expect(allowsLive([])).toBe(false)
  })

  test('cadenceDaysFromMetadata defaults and override', () => {
    expect(cadenceDaysFromMetadata({})).toBe(30)
    expect(cadenceDaysFromMetadata({ cadence_days: 14 })).toBe(14)
    expect(
      cadenceDaysFromMetadata({ cadence_days: 14, cadence_days_override: 7 }),
    ).toBe(7)
  })

  test('activeModeFromMetadata', () => {
    expect(activeModeFromMetadata({ active_mode: 'upload' })).toBe('upload')
    expect(activeModeFromMetadata({ active_mode: 'live' })).toBe('live')
    expect(activeModeFromMetadata({})).toBeNull()
  })

  test('liveConnectReady requires redeem evidence', () => {
    expect(liveConnectReady({ status: 'pending', metadata: {} })).toBe(false)
    expect(
      liveConnectReady({
        status: 'invited',
        metadata: { credentials_rotated_at: '2026-08-12T00:00:00Z' },
      }),
    ).toBe(true)
    expect(liveConnectReady({ status: 'connected', metadata: {} })).toBe(true)
  })

  test('ownerWizardStepIndex', () => {
    expect(ownerWizardStepIndex('mode')).toBe(0)
    expect(ownerWizardStepIndex('confirm')).toBe(3)
  })
})
