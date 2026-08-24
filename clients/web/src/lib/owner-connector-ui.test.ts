// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { ConnectorReminder } from './api'
import {
  MULTI_PII_DELIMITER_OPTIONS,
  activeModeFromMetadata,
  allowsLive,
  allowsUpload,
  buildModeStepCards,
  buildReminderBannerItems,
  cadenceDaysFromMetadata,
  HABEAS_PLATFORM_DISPLAY_NAME,
  disallowedModeReason,
  delimiterOptionFromKey,
  delimiterValueFromKey,
  displayStatusChip,
  filterRemindersForOwnerConnectorsPage,
  isModeAllowed,
  liveConnectReady,
  MODE_DEFINITION_CARDS,
  MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE,
  modeStepIntroCopy,
  modeStepSystemHint,
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

  test('wizard_incomplete uses curated copy and soft severity', () => {
    const items = buildReminderBannerItems([
      {
        code: 'wizard_incomplete',
        system: 'lever',
        vertical_id: 'people_hr',
        severity: 'overdue',
      },
    ])
    expect(items[0].title.toLowerCase()).toContain('incomplete')
    expect(items[0].severity).toBe('approaching')
  })

  test('filterRemindersForOwnerConnectorsPage drops wizard_incomplete', () => {
    const filtered = filterRemindersForOwnerConnectorsPage([
      {
        code: 'wizard_incomplete',
        system: 'mailchimp',
        vertical_id: 'communications',
        severity: 'overdue',
      },
      {
        code: 'upload_stale',
        system: 'mailchimp',
        vertical_id: 'communications',
        severity: 'overdue',
      },
    ])
    expect(filtered).toHaveLength(1)
    expect(filtered[0].code).toBe('upload_stale')
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

  test('liveConnectReady requires redeem evidence or successful test', () => {
    expect(liveConnectReady({ status: 'pending', metadata: {} })).toBe(false)
    expect(
      liveConnectReady({
        status: 'invited',
        metadata: { credentials_rotated_at: '2026-08-12T00:00:00Z' },
      }),
    ).toBe(true)
    expect(liveConnectReady({ status: 'connected', metadata: {} })).toBe(true)
    expect(
      liveConnectReady({ status: 'pending', last_test_ok: true, metadata: {} }),
    ).toBe(true)
  })

  test('ownerWizardStepIndex', () => {
    expect(ownerWizardStepIndex('mode')).toBe(0)
    expect(ownerWizardStepIndex('confirm')).toBe(3)
  })
})

describe('mode step explainer (KD25)', () => {
  test('definition cards use plain language and Habeas Platform name', () => {
    expect(MODE_DEFINITION_CARDS).toHaveLength(2)
    expect(MODE_DEFINITION_CARDS[0].title).toBe('Upload')
    expect(MODE_DEFINITION_CARDS[1].title).toBe('Live')
    expect(MODE_DEFINITION_CARDS[0].definition).toContain(
      HABEAS_PLATFORM_DISPLAY_NAME,
    )
    expect(MODE_DEFINITION_CARDS[0].definition.toLowerCase()).toContain('schedule')
    expect(MODE_DEFINITION_CARDS[1].definition.toLowerCase()).toContain('credentials')
    expect(MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE.toLowerCase()).toContain(
      'does not start matching',
    )
  })

  test('modeStepIntroCopy names the system', () => {
    expect(modeStepIntroCopy('Mailchimp')).toContain('Mailchimp')
    expect(modeStepIntroCopy('Mailchimp')).toContain(
      HABEAS_PLATFORM_DISPLAY_NAME,
    )
  })

  test('isModeAllowed mirrors allowsUpload / allowsLive', () => {
    expect(isModeAllowed('upload', ['live', 'upload'])).toBe(true)
    expect(isModeAllowed('live', ['upload'])).toBe(false)
    expect(isModeAllowed('live', ['live'])).toBe(true)
  })

  test('mailchimp cards include per-system hints when both modes allowed', () => {
    const cards = buildModeStepCards({
      systemId: 'mailchimp',
      displayName: 'Mailchimp',
      allowedApproaches: ['live', 'upload'],
    })
    expect(cards).toHaveLength(2)
    expect(cards.every((card) => card.allowed)).toBe(true)
    expect(cards.find((card) => card.mode === 'upload')?.hint).toContain('template')
    expect(cards.find((card) => card.mode === 'live')?.hint).toContain('API key')
    expect(cards.every((card) => card.disabledReason === null)).toBe(true)
  })

  test('upload-only system greys Live with curated reason', () => {
    const cards = buildModeStepCards({
      systemId: 'bizdev_contacts',
      displayName: 'BizDev Contacts',
      allowedApproaches: ['upload'],
    })
    const live = cards.find((card) => card.mode === 'live')
    expect(live?.allowed).toBe(false)
    expect(live?.hint).toBeNull()
    expect(live?.disabledReason?.toLowerCase()).toContain('upload only')
    expect(cards.find((card) => card.mode === 'upload')?.allowed).toBe(true)
  })

  test('lever greys Upload with live-only reason', () => {
    const reason = disallowedModeReason('lever', 'upload')
    expect(reason.toLowerCase()).toContain('live')
    const cards = buildModeStepCards({
      systemId: 'lever',
      displayName: 'Lever',
      allowedApproaches: ['live'],
    })
    expect(cards.find((card) => card.mode === 'upload')?.disabledReason).toBe(reason)
    expect(modeStepSystemHint('lever', 'live')).toContain('Users read/list')
  })

  test('paylocity Live copy promises SFTP later, not API', () => {
    const cards = buildModeStepCards({
      systemId: 'paylocity',
      displayName: 'Paylocity',
      allowedApproaches: ['upload'],
    })
    const live = cards.find((card) => card.mode === 'live')
    expect(live?.definition.toLowerCase()).toContain('sftp')
    expect(live?.definition.toLowerCase()).toContain('not an api connection')
    expect(live?.disabledReason?.toLowerCase()).toContain('sftp')
    const liveAllowed = buildModeStepCards({
      systemId: 'paylocity',
      displayName: 'Paylocity',
      allowedApproaches: ['live', 'upload'],
    }).find((card) => card.mode === 'live')
    expect(liveAllowed?.definition.toLowerCase()).toContain('sftp')
    expect(liveAllowed?.hint?.toLowerCase()).toContain('sftp')
    expect(liveAllowed?.hint?.toLowerCase()).toContain('not an api')
  })
})
