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
  buildVerticalWizardSteps,
  parseVerticalWizardStepId,
  cadenceDaysFromMetadata,
  cadenceOptionFromMetadata,
  cadenceOptionFromRefreshPolicy,
  HABEAS_PLATFORM_DISPLAY_NAME,
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WEEKLY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
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
  refreshCadenceFromCadenceOption,
  refreshPolicyFromCadenceOption,
  SYSTEM_COPY,
  verticalWizardStepIndex,
  visibleReminderBanners,
  wizardProgressPercent,
  suggestUploadColumnMapping,
  uploadMappingComplete,
  UPLOAD_SAMPLE_CSV,
  parseCsvHeaderRow,
  isOwnerConnectorsHiddenSystem,
  isOwnerConnectorsHiddenVertical,
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
      system: 'axios_hq',
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
    expect(items[0].id).toBe('communications:axios_hq:upload_stale')
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

  test('sheets_refresh_stale copy avoids volatile wording', () => {
    const items = buildReminderBannerItems([
      {
        code: 'sheets_refresh_stale',
        system: 'google_sheets',
        vertical_id: 'tech',
        severity: 'overdue',
      },
    ])
    expect(items[0].description.toLowerCase()).not.toContain('volatile')
    expect(items[0].description).toContain('12 hours')
    expect(items[0].description.toLowerCase()).toContain('login is not blocked')
  })

  test('filterRemindersForOwnerConnectorsPage drops wizard_incomplete', () => {
    const filtered = filterRemindersForOwnerConnectorsPage([
      {
        code: 'wizard_incomplete',
        system: 'axios_hq',
        vertical_id: 'communications',
        severity: 'overdue',
      },
      {
        code: 'upload_stale',
        system: 'axios_hq',
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

  test('verticalWizardStepIndex finds dynamic step ids', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'axios_hq', allowedApproaches: ['upload'] }],
    })
    expect(verticalWizardStepIndex(steps, 'axios_hq-howto-upload')).toBe(0)
    expect(verticalWizardStepIndex(steps, 'confirm')).toBe(steps.length - 1)
    expect(verticalWizardStepIndex(steps, 'missing')).toBe(-1)
  })
})

describe('vertical wizard steps', () => {
  test('axios_hq upload-only vertical ends with cadence and confirm', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'axios_hq', allowedApproaches: ['upload'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'axios_hq-howto-upload',
      'axios_hq-upload',
      'cadence',
      'confirm',
    ])
  })

  test('parses hr_alumni howto-upload as howto, not upload', () => {
    expect(parseVerticalWizardStepId('hr_alumni-howto-upload')).toEqual({
      kind: 'howto-upload',
      system: 'hr_alumni',
    })
    expect(parseVerticalWizardStepId('hr_alumni-upload')).toEqual({
      kind: 'upload',
      system: 'hr_alumni',
    })
  })

  test('paylocity live first then upload fallback', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'paylocity', allowedApproaches: ['upload', 'live'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'paylocity-howto-live',
      'paylocity-live-creds',
      'paylocity-howto-upload',
      'paylocity-upload',
      'cadence',
      'confirm',
    ])
  })

  test('people_hr bindings produce many steps before cadence', () => {
    const steps = buildVerticalWizardSteps({
      systems: [
        { system: 'paylocity', allowedApproaches: ['upload', 'live'] },
        { system: 'lever', allowedApproaches: ['live'] },
        { system: 'hr_alumni', allowedApproaches: ['upload'] },
      ],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'paylocity-howto-live',
      'paylocity-live-creds',
      'paylocity-howto-upload',
      'paylocity-upload',
      'lever-howto-live',
      'lever-live-creds',
      'hr_alumni-howto-upload',
      'hr_alumni-upload',
      'cadence',
      'confirm',
    ])
  })

  test('skips cassandra and empty-approach systems', () => {
    const steps = buildVerticalWizardSteps({
      systems: [
        { system: 'cassandra', allowedApproaches: [] },
        { system: 'bizdev_contacts', allowedApproaches: ['upload'] },
      ],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'bizdev_contacts-howto-upload',
      'bizdev_contacts-upload',
      'cadence',
      'confirm',
    ])
  })

  test('viewOnly vertical yields no steps', () => {
    expect(
      buildVerticalWizardSteps({
        viewOnly: true,
        systems: [{ system: 'axios_hq', allowedApproaches: ['upload'] }],
      }),
    ).toEqual([])
  })

  test('wizardProgressPercent is 0–100 across the step range', () => {
    expect(wizardProgressPercent(0, 4)).toBe(25)
    expect(wizardProgressPercent(3, 4)).toBe(100)
    expect(wizardProgressPercent(0, 0)).toBe(0)
    expect(wizardProgressPercent(-1, 5)).toBe(0)
  })
})

describe('cadence option mapping', () => {
  test('maps legacy refresh_policy to cadence option ids', () => {
    expect(cadenceOptionFromRefreshPolicy('static')).toBe(CADENCE_OPTION_RARELY)
    expect(cadenceOptionFromRefreshPolicy('volatile')).toBe(
      CADENCE_OPTION_WITH_NEW_BATCHES,
    )
    expect(cadenceOptionFromRefreshPolicy(null)).toBeNull()
  })

  test('maps cadence options back to refresh_policy when applicable', () => {
    expect(refreshPolicyFromCadenceOption(CADENCE_OPTION_RARELY)).toBe('static')
    expect(refreshPolicyFromCadenceOption(CADENCE_OPTION_WITH_NEW_BATCHES)).toBe(
      'volatile',
    )
    expect(refreshPolicyFromCadenceOption(CADENCE_OPTION_WEEKLY)).toBeNull()
  })

  test('cadenceOptionFromMetadata prefers refresh_cadence over refresh_policy', () => {
    expect(cadenceOptionFromMetadata({ refresh_cadence: 'rarely' })).toBe(
      CADENCE_OPTION_RARELY,
    )
    expect(
      cadenceOptionFromMetadata({
        refresh_cadence: 'with_new_batches',
        refresh_policy: 'static',
      }),
    ).toBe(CADENCE_OPTION_WITH_NEW_BATCHES)
  })

  test('cadenceOptionFromMetadata falls back to refresh_policy', () => {
    expect(cadenceOptionFromMetadata({ refresh_policy: 'volatile' })).toBe(
      CADENCE_OPTION_WITH_NEW_BATCHES,
    )
    expect(cadenceOptionFromMetadata({ refresh_policy: 'static' })).toBe(
      CADENCE_OPTION_RARELY,
    )
  })

  test('weekly refresh_cadence wins over volatile refresh_policy', () => {
    expect(
      cadenceOptionFromMetadata({
        refresh_cadence: 'weekly',
        refresh_policy: 'volatile',
      }),
    ).toBe(CADENCE_OPTION_WEEKLY)
  })

  test('refreshCadenceFromCadenceOption maps option ids to API strings', () => {
    expect(refreshCadenceFromCadenceOption(CADENCE_OPTION_RARELY)).toBe('rarely')
    expect(refreshCadenceFromCadenceOption(CADENCE_OPTION_WITH_NEW_BATCHES)).toBe(
      'with_new_batches',
    )
    expect(refreshCadenceFromCadenceOption(CADENCE_OPTION_WEEKLY)).toBe('weekly')
    expect(refreshCadenceFromCadenceOption(null)).toBeNull()
  })
})

describe('SYSTEM_COPY', () => {
  test('axios_hq upload how-to copy is CSV-only', () => {
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).toContain('axios hq')
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).not.toContain('mailchimp')
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).toContain('csv')
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
    expect(MODE_DEFINITION_CARDS[0].definition.toLowerCase()).toContain('map')
    expect(MODE_DEFINITION_CARDS[1].definition.toLowerCase()).toContain('credentials')
    expect(MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE.toLowerCase()).toContain(
      'does not start matching',
    )
  })

  test('modeStepIntroCopy names the system', () => {
    expect(modeStepIntroCopy('Axios HQ')).toContain('Axios HQ')
    expect(modeStepIntroCopy('Axios HQ')).toContain(
      HABEAS_PLATFORM_DISPLAY_NAME,
    )
  })

  test('isModeAllowed mirrors allowsUpload / allowsLive', () => {
    expect(isModeAllowed('upload', ['live', 'upload'])).toBe(true)
    expect(isModeAllowed('live', ['upload'])).toBe(false)
    expect(isModeAllowed('live', ['live'])).toBe(true)
  })

  test('paylocity cards include per-system hints when both modes allowed', () => {
    const cards = buildModeStepCards({
      systemId: 'paylocity',
      displayName: 'Paylocity',
      allowedApproaches: ['live', 'upload'],
    })
    expect(cards).toHaveLength(2)
    expect(cards.every((card) => card.allowed)).toBe(true)
    expect(cards.find((card) => card.mode === 'upload')?.hint).toContain('map')
    expect(cards.find((card) => card.mode === 'live')?.hint?.toLowerCase()).toContain('sftp')
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

describe('owner connectors hide cassandra', () => {
  test('hides cassandra system and data vertical', () => {
    expect(isOwnerConnectorsHiddenSystem('cassandra')).toBe(true)
    expect(isOwnerConnectorsHiddenSystem('hr_alumni')).toBe(false)
    expect(isOwnerConnectorsHiddenVertical('data')).toBe(true)
    expect(isOwnerConnectorsHiddenVertical('people_hr')).toBe(false)
  })
})

describe('upload column mapping', () => {
  test('success and autobind samples suggest a complete map', () => {
    const successHeaders = parseCsvHeaderRow(UPLOAD_SAMPLE_CSV.success.body)
    expect(suggestUploadColumnMapping(successHeaders)).toEqual({
      first_name: 'first_name',
      last_name: 'last_name',
      email: 'email',
    })
    const autoHeaders = parseCsvHeaderRow(UPLOAD_SAMPLE_CSV.autobind.body)
    expect(suggestUploadColumnMapping(autoHeaders)).toEqual({
      first_name: 'First Name',
      last_name: 'Last Name',
      email: 'Email Address',
    })
    expect(uploadMappingComplete(suggestUploadColumnMapping(autoHeaders))).toBe(true)
  })

  test('remap sample is incomplete until the owner binds columns', () => {
    const headers = parseCsvHeaderRow(UPLOAD_SAMPLE_CSV.remap.body)
    expect(headers).toEqual(['Given', 'Family', 'Work Email', 'Department'])
    const suggested = suggestUploadColumnMapping(headers)
    expect(uploadMappingComplete(suggested)).toBe(false)
    expect(
      uploadMappingComplete({
        first_name: 'Given',
        last_name: 'Family',
        email: 'Work Email',
      }),
    ).toBe(true)
  })

  test('email-only or phone-only samples auto-bind a complete identifier map', () => {
    expect(
      uploadMappingComplete(
        suggestUploadColumnMapping(parseCsvHeaderRow(UPLOAD_SAMPLE_CSV.success_email_only.body)),
      ),
    ).toBe(true)
    expect(
      uploadMappingComplete(
        suggestUploadColumnMapping(parseCsvHeaderRow(UPLOAD_SAMPLE_CSV.success_phone_only.body)),
      ),
    ).toBe(true)
  })

  test('failure with no identifier columns cannot auto-bind', () => {
    const headers = parseCsvHeaderRow(UPLOAD_SAMPLE_CSV.failure_no_identifier.body)
    expect(uploadMappingComplete(suggestUploadColumnMapping(headers))).toBe(false)
  })
})
