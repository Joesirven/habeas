// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { ConnectorReminder } from './api'
import {
  MULTI_PII_DELIMITER_OPTIONS,
  activeModeFromMetadata,
  allowsLive,
  allowsOauth,
  allowsUpload,
  buildModeStepCards,
  buildReminderBannerItems,
  buildVerticalWizardSteps,
  parseVerticalWizardStepId,
  cadenceDaysFromMetadata,
  cadenceOptionFromMetadata,
  cadenceOptionFromRefreshPolicy,
  HABEAS_PLATFORM_DISPLAY_NAME,
  CADENCE_OPTION_IDS,
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WEEKLY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
  cadenceOptionIdsForSystems,
  SHEETS_CADENCE_OPTION_IDS,
  SHEETS_CONNECT_METHODS,
  SHEETS_OWNER_SYSTEM_IDS,
  isSheetsOwnerSystem,
  shouldIncludeSheetsMappingClean,
  disallowedModeReason,
  delimiterOptionFromKey,
  delimiterValueFromKey,
  displayStatusChip,
  filterRemindersForOwnerConnectorsPage,
  isModeAllowed,
  ownerUploadAllowed,
  liveConnectReady,
  MANUAL_UPLOAD_LABEL,
  connectionMethodLabel,
  MODE_DEFINITION_CARDS,
  MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE,
  MODE_UPLOAD_DEFINITION_CARD,
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
  parseCsvDocument,
  serializeCsvDocument,
  isOwnerConnectorsHiddenSystem,
  isOwnerConnectorsHiddenVertical,
  isOwnerWizardHiddenSystem,
  ownerConnectorsVerticalIds,
  ownerSeesAllCatalogVerticals,
  filterOwnerWizardConnectors,
  ownerConnectorDisplayName,
  catalogOwnerSystemId,
  isAxiosHqOwnerSystem,
  systemWizardCopy,
  findOwnerConnector,
  sameOwnerConnectorSystem,
  LIVE_CONNECT_FAILURE_HINT,
  LIVE_CONNECT_FAILURE_RETRY_ONLY_HINT,
  LIVE_CONNECT_RETRY_LABEL,
  LIVE_CONNECT_SETUP_UPLOAD_LABEL,
  LIVE_CONNECT_SUCCESS_CONTINUE_HINT,
  LIVE_CONNECT_SUCCESS_MAPPING_HINT,
  LIVE_PING_NOT_EXTRACT_HINT,
  LIVE_PING_NOT_EXTRACT_SYSTEMS,
  liveConnectFailureActions,
  liveConnectOffersUploadFallback,
  liveConnectSuccessFollowOn,
  liveMappingFollowOnStepId,
  livePingIsNotMatchingExtract,
  liveUploadFallbackStepId,
  nextWizardStepAfterSuccessfulLive,
  mappingFollowOnCopy,
  shouldIncludeLiveMappingFollowOn,
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

  test('blocked / gated chips never say Connected', () => {
    for (const status of ['needs_refresh', 'action_required', 'needs_setup', 'connected']) {
      const chip = displayStatusChip(status, { gateAllowed: false })
      expect(chip.label).not.toBe('Connected')
      expect(chip.label.toLowerCase()).not.toContain('connected')
    }
    expect(displayStatusChip('needs_setup', { gateAllowed: false }).label).toBe(
      'Needs setup',
    )
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

describe('ownerUploadAllowed', () => {
  test('Auth0 local fallback is false; API boolean wins', () => {
    expect(ownerUploadAllowed('auth0')).toBe(false)
    expect(ownerUploadAllowed('auth0', false)).toBe(false)
    expect(ownerUploadAllowed('auth0', true)).toBe(true)
  })

  test('advertised systems stay true without an API value', () => {
    expect(ownerUploadAllowed('paylocity')).toBe(true)
    expect(ownerUploadAllowed('lever')).toBe(true)
    expect(ownerUploadAllowed('axios_hq')).toBe(true)
    expect(ownerUploadAllowed('axios_headquarters')).toBe(true)
    expect(ownerUploadAllowed('hr_alumni')).toBe(true)
    expect(ownerUploadAllowed('bizdev_contacts')).toBe(true)
  })

  test('unadvertised catalog slugs stay false without an API value', () => {
    expect(ownerUploadAllowed('cassandra')).toBe(false)
    expect(ownerUploadAllowed('google_sheets')).toBe(false)
    expect(ownerUploadAllowed('alumni_google_sheet')).toBe(false)
    expect(ownerUploadAllowed('contact_us_google_sheet')).toBe(false)
    expect(ownerUploadAllowed('mailchimp')).toBe(false)
  })
})

describe('mode and cadence helpers', () => {
  test('allowsUpload / allowsLive / allowsOauth', () => {
    expect(allowsUpload(['live', 'upload'])).toBe(true)
    expect(allowsUpload(['live'])).toBe(false)
    expect(allowsLive(['live'])).toBe(true)
    expect(allowsLive([])).toBe(false)
    expect(allowsOauth(['oauth', 'upload'])).toBe(true)
    expect(allowsOauth(['upload'])).toBe(false)
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

  test('communications worker slug axios_headquarters still builds upload steps', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'axios_headquarters', allowedApproaches: ['upload'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'axios_headquarters-howto-upload',
      'axios_headquarters-upload',
      'cadence',
      'confirm',
    ])
  })

  test('parses hr_alumni howto-upload as howto-upload, not upload', () => {
    expect(parseVerticalWizardStepId('hr_alumni-howto-upload')).toEqual({
      kind: 'howto-upload',
      system: 'hr_alumni',
    })
    expect(parseVerticalWizardStepId('hr_alumni-upload')).toEqual({
      kind: 'upload',
      system: 'hr_alumni',
    })
  })

  test('parses sheets howto / connect / mapping-clean without colliding suffixes', () => {
    expect(parseVerticalWizardStepId('hr_alumni-howto')).toEqual({
      kind: 'howto',
      system: 'hr_alumni',
    })
    expect(parseVerticalWizardStepId('hr_alumni-connect')).toEqual({
      kind: 'connect',
      system: 'hr_alumni',
    })
    expect(parseVerticalWizardStepId('bizdev_contacts-mapping-clean')).toEqual({
      kind: 'mapping-clean',
      system: 'bizdev_contacts',
    })
    expect(parseVerticalWizardStepId('hr_alumni-mapping')).toEqual({
      kind: 'mapping',
      system: 'hr_alumni',
    })
    expect(parseVerticalWizardStepId('hr_alumni-clean')).toEqual({
      kind: 'clean',
      system: 'hr_alumni',
    })
    expect(parseVerticalWizardStepId('hr_alumni-oauth')).toEqual({
      kind: 'oauth',
      system: 'hr_alumni',
    })
  })

  test('paylocity live first then mapping then upload fallback', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'paylocity', allowedApproaches: ['upload', 'live'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'paylocity-howto-live',
      'paylocity-live-creds',
      'paylocity-mapping',
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
      'paylocity-mapping',
      'paylocity-howto-upload',
      'paylocity-upload',
      'lever-howto-live',
      'lever-live-creds',
      'hr_alumni-howto',
      'hr_alumni-connect',
      'hr_alumni-mapping-clean',
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
      'bizdev_contacts-howto',
      'bizdev_contacts-connect',
      'bizdev_contacts-mapping-clean',
      'cadence',
      'confirm',
    ])
  })

  test('hr_alumni / bizdev_contacts use howto → connect → mapping-clean', () => {
    expect(SHEETS_OWNER_SYSTEM_IDS).toEqual(['hr_alumni', 'bizdev_contacts'])
    expect(SHEETS_CONNECT_METHODS).toEqual(['oauth', 'upload'])
    expect(isSheetsOwnerSystem('HR_Alumni')).toBe(true)
    expect(isSheetsOwnerSystem('axios_hq')).toBe(false)

    const alumni = buildVerticalWizardSteps({
      systems: [{ system: 'hr_alumni', allowedApproaches: ['upload'] }],
    })
    expect(alumni.map((step) => step.id)).toEqual([
      'hr_alumni-howto',
      'hr_alumni-connect',
      'hr_alumni-mapping-clean',
      'cadence',
      'confirm',
    ])

    const contacts = buildVerticalWizardSteps({
      systems: [{ system: 'bizdev_contacts', allowedApproaches: [] }],
    })
    expect(contacts.map((step) => step.id)).toEqual([
      'bizdev_contacts-howto',
      'bizdev_contacts-connect',
      'bizdev_contacts-mapping-clean',
      'cadence',
      'confirm',
    ])
  })

  test('omits sheets mapping-clean when the caller says it is not needed', () => {
    const steps = buildVerticalWizardSteps({
      systems: [
        {
          system: 'hr_alumni',
          allowedApproaches: ['oauth', 'upload'],
          needsMappingClean: false,
        },
      ],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'hr_alumni-howto',
      'hr_alumni-connect',
      'cadence',
      'confirm',
    ])
  })

  test('shouldIncludeSheetsMappingClean is true until map is complete and rows are clean', () => {
    expect(shouldIncludeSheetsMappingClean()).toBe(true)
    expect(shouldIncludeSheetsMappingClean({ mappingComplete: false })).toBe(true)
    expect(
      shouldIncludeSheetsMappingClean({
        mapping: { email: 'email' },
        rejectedRowCount: 2,
      }),
    ).toBe(true)
    expect(
      shouldIncludeSheetsMappingClean({
        mapping: { email: 'email' },
        rejectedRowCount: 0,
      }),
    ).toBe(false)
    expect(
      shouldIncludeSheetsMappingClean({
        mappingComplete: true,
        rejectedRowCount: 0,
      }),
    ).toBe(false)
  })

  test('lever live-only has no mapping follow-on until upload is allowed', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'lever', allowedApproaches: ['live'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'lever-howto-live',
      'lever-live-creds',
      'cadence',
      'confirm',
    ])
    expect(shouldIncludeLiveMappingFollowOn({
      system: 'lever',
      allowedApproaches: ['live'],
    })).toBe(false)
  })

  test('lever live+upload inserts mapping after live-creds', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'lever', allowedApproaches: ['live', 'upload'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'lever-howto-live',
      'lever-live-creds',
      'lever-mapping',
      'lever-howto-upload',
      'lever-upload',
      'cadence',
      'confirm',
    ])
    expect(parseVerticalWizardStepId('lever-mapping')).toEqual({
      kind: 'mapping',
      system: 'lever',
    })
  })

  test('auth0 live extract has no mapping or upload steps after live-creds', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'auth0', allowedApproaches: ['live', 'upload'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'auth0-howto-live',
      'auth0-live-creds',
      'cadence',
      'confirm',
    ])
    expect(steps.map((step) => step.id)).not.toContain('auth0-howto-upload')
    expect(steps.map((step) => step.id)).not.toContain('auth0-upload')
  })

  test('omits live mapping follow-on when the caller says mapping is complete', () => {
    const steps = buildVerticalWizardSteps({
      systems: [
        {
          system: 'paylocity',
          allowedApproaches: ['live', 'upload'],
          needsMappingClean: false,
        },
      ],
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

describe('live connect mapping follow-on (Wave M)', () => {
  test('live ping is not extract for Lever and Paylocity only', () => {
    expect(LIVE_PING_NOT_EXTRACT_SYSTEMS).toEqual(['lever', 'paylocity'])
    expect(livePingIsNotMatchingExtract('lever')).toBe(true)
    expect(livePingIsNotMatchingExtract('Paylocity')).toBe(true)
    expect(livePingIsNotMatchingExtract('auth0')).toBe(false)
    expect(livePingIsNotMatchingExtract('axios_hq')).toBe(false)
    expect(livePingIsNotMatchingExtract('cassandra')).toBe(false)
  })

  test('step ids are mapping after live and howto-upload for fallback', () => {
    expect(liveMappingFollowOnStepId('Paylocity')).toBe('paylocity-mapping')
    expect(liveUploadFallbackStepId('LEVER')).toBe('lever-howto-upload')
  })

  test('shouldIncludeLiveMappingFollowOn requires live ping-not-extract plus upload', () => {
    expect(
      shouldIncludeLiveMappingFollowOn({
        system: 'paylocity',
        allowedApproaches: ['live', 'upload'],
      }),
    ).toBe(true)
    expect(
      shouldIncludeLiveMappingFollowOn({
        system: 'lever',
        allowedApproaches: ['live', 'upload'],
        mappingComplete: true,
        rejectedRowCount: 0,
      }),
    ).toBe(false)
    expect(
      shouldIncludeLiveMappingFollowOn({
        system: 'auth0',
        allowedApproaches: ['live', 'upload'],
      }),
    ).toBe(false)
    expect(
      shouldIncludeLiveMappingFollowOn({
        system: 'axios_hq',
        allowedApproaches: ['upload'],
      }),
    ).toBe(false)
    expect(
      shouldIncludeLiveMappingFollowOn({
        system: 'cassandra',
        allowedApproaches: ['live', 'upload'],
      }),
    ).toBe(false)
  })

  test('live fail offers Retry connection and Set up manual upload when upload is allowed', () => {
    const paylocity = liveConnectFailureActions({
      system: 'paylocity',
      allowedApproaches: ['live', 'upload'],
    })
    expect(paylocity.retryLabel).toBe(LIVE_CONNECT_RETRY_LABEL)
    expect(paylocity.setupManualUpload).toEqual({
      label: LIVE_CONNECT_SETUP_UPLOAD_LABEL,
      stepId: 'paylocity-howto-upload',
    })
    expect(paylocity.hint).toBe(LIVE_CONNECT_FAILURE_HINT)
    expect(paylocity.hint.toLowerCase()).toContain('retry')
    expect(paylocity.hint.toLowerCase()).toContain('manual upload')
    expect(paylocity.hint.toLowerCase()).toContain('email or phone')
    expect(paylocity.hint.toLowerCase()).not.toContain(
      'first name, last name, and email',
    )
    expect(paylocity.hint.toLowerCase()).not.toContain('coming soon')

    const leverLiveOnly = liveConnectFailureActions({
      system: 'lever',
      allowedApproaches: ['live'],
    })
    expect(leverLiveOnly.retryLabel).toBe(LIVE_CONNECT_RETRY_LABEL)
    expect(leverLiveOnly.setupManualUpload).toBeNull()
    expect(leverLiveOnly.hint).toBe(LIVE_CONNECT_FAILURE_RETRY_ONLY_HINT)
    expect(leverLiveOnly.hint.toLowerCase()).toContain('retry')
    expect(leverLiveOnly.hint.toLowerCase()).not.toContain('manual upload')
    expect(liveConnectOffersUploadFallback(['live'], 'lever')).toBe(false)
    expect(liveConnectOffersUploadFallback(['upload'], 'cassandra')).toBe(false)
  })

  test('Auth0 live fail is retry-only even when approaches include upload', () => {
    const auth0 = liveConnectFailureActions({
      system: 'auth0',
      allowedApproaches: ['live', 'upload'],
    })
    expect(auth0.retryLabel).toBe(LIVE_CONNECT_RETRY_LABEL)
    expect(auth0.setupManualUpload).toBeNull()
    expect(auth0.hint).toBe(LIVE_CONNECT_FAILURE_RETRY_ONLY_HINT)
    expect(auth0.hint.toLowerCase()).toContain('retry')
    expect(auth0.hint.toLowerCase()).not.toContain('manual upload')
    expect(auth0.hint.toLowerCase()).not.toContain('csv')
    expect(liveConnectOffersUploadFallback(['live', 'upload'], 'auth0')).toBe(false)
  })

  test('live success next step is mapping when upload is allowed', () => {
    const paylocity = liveConnectSuccessFollowOn({
      system: 'paylocity',
      allowedApproaches: ['live', 'upload'],
    })
    expect(paylocity.nextKind).toBe('mapping')
    expect(paylocity.nextStepId).toBe('paylocity-mapping')
    expect(paylocity.hint).toBe(LIVE_PING_NOT_EXTRACT_HINT)
    expect(paylocity.setupManualUpload?.label).toBe(LIVE_CONNECT_SETUP_UPLOAD_LABEL)
    expect(paylocity.setupManualUpload?.stepId).toBe('paylocity-howto-upload')

    const leverMapped = liveConnectSuccessFollowOn({
      system: 'lever',
      allowedApproaches: ['live', 'upload'],
      mappingComplete: true,
      rejectedRowCount: 0,
    })
    expect(leverMapped.nextKind).toBe('howto-upload')
    expect(leverMapped.nextStepId).toBe('lever-howto-upload')

    const auth0 = liveConnectSuccessFollowOn({
      system: 'auth0',
      allowedApproaches: ['live', 'upload'],
    })
    expect(auth0.nextKind).toBe('continue')
    expect(auth0.nextStepId).toBeNull()
    expect(auth0.setupManualUpload).toBeNull()
    expect(auth0.hint).toBe(LIVE_CONNECT_SUCCESS_CONTINUE_HINT)
    expect(auth0.hint.toLowerCase()).not.toContain('upload')
    expect(auth0.hint.toLowerCase()).toContain('cadence')

    const leverPingOnly = liveConnectSuccessFollowOn({
      system: 'lever',
      allowedApproaches: ['live'],
    })
    expect(leverPingOnly.nextKind).toBe('continue')
    expect(leverPingOnly.nextStepId).toBeNull()
    expect(leverPingOnly.hint).toBe(LIVE_PING_NOT_EXTRACT_HINT)
    expect(leverPingOnly.setupManualUpload).toBeNull()
  })

  test('Auth0 live success lands on cadence with no upload steps in the list', () => {
    const steps = buildVerticalWizardSteps({
      systems: [{ system: 'auth0', allowedApproaches: ['live', 'upload'] }],
    })
    expect(steps.map((step) => step.id)).toEqual([
      'auth0-howto-live',
      'auth0-live-creds',
      'cadence',
      'confirm',
    ])
    expect(steps.map((step) => step.id)).not.toContain('auth0-howto-upload')
    expect(steps.map((step) => step.id)).not.toContain('auth0-upload')
    expect(nextWizardStepAfterSuccessfulLive(steps, 'auth0')).toBe('cadence')
    expect(nextWizardStepAfterSuccessfulLive(steps, 'Auth0')).toBe('cadence')
    expect(nextWizardStepAfterSuccessfulLive(steps, 'lever')).toBeNull()
  })

  test('Auth0 Live success skips only Auth0 upload when another system follows', () => {
    const steps = buildVerticalWizardSteps({
      systems: [
        { system: 'auth0', allowedApproaches: ['live', 'upload'] },
        { system: 'axios_hq', allowedApproaches: ['upload'] },
      ],
    })
    expect(nextWizardStepAfterSuccessfulLive(steps, 'auth0')).toBe(
      'axios_hq-howto-upload',
    )
  })

  test('mapping follow-on copy uses identifier fields only', () => {
    const copy = mappingFollowOnCopy('Paylocity')
    expect(copy.title).toContain('Paylocity')
    expect(copy.intro.toLowerCase()).toContain('identifier')
    expect(copy.intro.toLowerCase()).toContain('headers differ')
    expect(copy.intro.toLowerCase()).toContain('email or phone')
    expect(copy.intro.toLowerCase()).not.toContain(
      'first name, last name, and email',
    )
    expect(LIVE_CONNECT_SUCCESS_MAPPING_HINT.toLowerCase()).toContain(
      'email or phone',
    )
    expect(LIVE_CONNECT_SUCCESS_MAPPING_HINT.toLowerCase()).not.toContain(
      'first name, last name, and email',
    )
    expect(LIVE_PING_NOT_EXTRACT_HINT.toLowerCase()).toContain('email or phone')
    expect(LIVE_PING_NOT_EXTRACT_HINT.toLowerCase()).not.toContain(
      'first name, last name, and email',
    )
    expect(copy.intro.toLowerCase()).not.toContain('opportunity')
    expect(copy.intro.toLowerCase()).not.toContain('department')
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

  test('sheets cadence options are rarely and with_new_batches only', () => {
    expect(SHEETS_CADENCE_OPTION_IDS).toEqual([
      CADENCE_OPTION_RARELY,
      CADENCE_OPTION_WITH_NEW_BATCHES,
    ])
    expect(cadenceOptionIdsForSystems(['hr_alumni'])).toEqual(
      SHEETS_CADENCE_OPTION_IDS,
    )
    expect(cadenceOptionIdsForSystems(['bizdev_contacts', 'hr_alumni'])).toEqual(
      SHEETS_CADENCE_OPTION_IDS,
    )
    expect(cadenceOptionIdsForSystems(['hr_alumni'])).not.toContain(
      CADENCE_OPTION_WEEKLY,
    )
    expect(cadenceOptionIdsForSystems(['axios_hq'])).toEqual(
      CADENCE_OPTION_IDS,
    )
    expect(cadenceOptionIdsForSystems(['paylocity', 'hr_alumni'])).toEqual(
      CADENCE_OPTION_IDS,
    )
  })
})

describe('SYSTEM_COPY', () => {
  test('axios_hq upload how-to copy is CSV-only and every-batch', () => {
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).toContain('axios hq')
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).not.toContain('mailchimp')
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).toContain('csv')
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).toContain('every batch')
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).not.toContain(
      'coming soon',
    )
    expect(SYSTEM_COPY.axios_hq.uploadHowto?.toLowerCase()).not.toContain('api')
    expect(systemWizardCopy('axios_headquarters')?.uploadHowto).toBe(
      SYSTEM_COPY.axios_hq.uploadHowto,
    )
    expect(modeStepSystemHint('axios_headquarters', 'upload')?.toLowerCase()).toContain(
      'every batch',
    )
  })

  test('catalog owner system id aliases Axios HQ worker slug', () => {
    expect(catalogOwnerSystemId('axios_headquarters')).toBe('axios_hq')
    expect(catalogOwnerSystemId('Axios_HQ')).toBe('axios_hq')
    expect(isAxiosHqOwnerSystem('axios_headquarters')).toBe(true)
    expect(isAxiosHqOwnerSystem('axios_hq')).toBe(true)
    expect(isAxiosHqOwnerSystem('lever')).toBe(false)
    expect(sameOwnerConnectorSystem('axios_hq', 'axios_headquarters')).toBe(true)
    expect(
      findOwnerConnector(
        [
          {
            system: 'axios_headquarters',
            display_name: 'Axios HQ',
            allowed_approaches: ['upload'],
            connection_id: null,
            status: null,
            last_test_ok: null,
            metadata: {},
            display_status: 'needs_setup',
            gate_code: '',
            gate_allowed: false,
          },
        ],
        'axios_hq',
      )?.system,
    ).toBe('axios_headquarters')
  })

  test('lever upload how-to maps identifiers without requiring first last email', () => {
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).toContain('csv')
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).toContain('identifier')
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).toContain('headers differ')
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).toContain('email or phone')
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).not.toContain(
      'first name, last name, and email',
    )
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).not.toContain('opportunities')
    expect(SYSTEM_COPY.lever.uploadHowto?.toLowerCase()).not.toContain('/v1/')
    expect(SYSTEM_COPY.lever.liveHowto?.toLowerCase()).toContain('retry')
    expect(SYSTEM_COPY.lever.liveHowto?.toLowerCase()).toContain('manual upload')
  })

  test('paylocity how-to keeps SFTP honesty and live-fail upload', () => {
    expect(SYSTEM_COPY.paylocity.liveHowto?.toLowerCase()).toContain('sftp')
    expect(SYSTEM_COPY.paylocity.liveHowto?.toLowerCase()).toContain('not an api')
    expect(SYSTEM_COPY.paylocity.liveHowto?.toLowerCase()).toContain('manual upload')
    expect(SYSTEM_COPY.paylocity.uploadHowto?.toLowerCase()).toContain('fail')
    expect(SYSTEM_COPY.paylocity.uploadHowto?.toLowerCase()).toContain('map')
  })

  test('sheets howto covers oauth or upload and does not mention service-account share', () => {
    for (const system of SHEETS_OWNER_SYSTEM_IDS) {
      const copy = SYSTEM_COPY[system]
      expect(copy.howto?.toLowerCase()).toContain('google')
      expect(copy.howto?.toLowerCase()).toContain('upload')
      expect(copy.oauthHowto?.toLowerCase()).toContain('oauth')
      expect(copy.oauthHowto?.toLowerCase()).not.toContain('service account')
      expect(copy.uploadHowto?.toLowerCase()).toContain('csv')
    }
  })
})

const REQUIRED_TRIO_PHRASE =
  /first name,\s*last name,?\s+and email|map columns to first name/i

function alwaysVisibleIdentifierCopy(): Array<{ label: string; text: string }> {
  const surfaces: Array<{ label: string; text: string }> = [
    {
      label: 'MODE_UPLOAD_DEFINITION_CARD',
      text: MODE_UPLOAD_DEFINITION_CARD.definition,
    },
    {
      label: 'DISALLOWED_MODE_REASONS.paylocity.live',
      text: disallowedModeReason('paylocity', 'live', {
        displayName: 'Paylocity',
        allowedApproaches: ['upload'],
      }),
    },
  ]
  for (const [system, copy] of Object.entries(SYSTEM_COPY)) {
    for (const [field, text] of Object.entries(copy)) {
      if (text) surfaces.push({ label: `SYSTEM_COPY.${system}.${field}`, text })
    }
  }
  for (const system of [
    'paylocity',
    'auth0',
    'hr_alumni',
    'bizdev_contacts',
    'lever',
    'axios_hq',
  ]) {
    const hint = modeStepSystemHint(system, 'upload')
    if (hint) {
      surfaces.push({ label: `MODE_SYSTEM_HINTS.${system}.upload`, text: hint })
    }
  }
  return surfaces
}

describe('identifier mapping copy (no required trio)', () => {
  test('always-visible upload copy does not require first+last+email', () => {
    const surfaces = alwaysVisibleIdentifierCopy()
    expect(surfaces.length).toBeGreaterThan(10)
    for (const { label, text } of surfaces) {
      expect(REQUIRED_TRIO_PHRASE.test(text), `${label}: ${text}`).toBe(false)
    }
  })

  test('upload definition and system how-tos say email or phone is enough', () => {
    expect(MODE_UPLOAD_DEFINITION_CARD.definition.toLowerCase()).toContain(
      'email or phone',
    )
    expect(MODE_UPLOAD_DEFINITION_CARD.definition.toLowerCase()).toContain(
      'headers differ',
    )
    for (const system of [
      'axios_hq',
      'hr_alumni',
      'bizdev_contacts',
      'alumni_google_sheet',
      'contact_us_google_sheet',
      'paylocity',
      'auth0',
      'lever',
    ]) {
      const howto = SYSTEM_COPY[system].uploadHowto
      expect(howto, system).toBeDefined()
      expect(howto?.toLowerCase(), system).toContain('email or phone')
      expect(howto?.toLowerCase(), system).not.toMatch(REQUIRED_TRIO_PHRASE)
    }
    expect(modeStepSystemHint('paylocity', 'upload')?.toLowerCase()).toContain(
      'email or phone',
    )
    expect(modeStepSystemHint('auth0', 'upload')?.toLowerCase()).toContain(
      'email or phone',
    )
    expect(modeStepSystemHint('hr_alumni', 'upload')?.toLowerCase()).toContain(
      'email or phone',
    )
    expect(
      modeStepSystemHint('bizdev_contacts', 'upload')?.toLowerCase(),
    ).toContain('email or phone')
    expect(modeStepSystemHint('axios_hq', 'upload')?.toLowerCase()).toContain(
      'email or phone',
    )
    expect(modeStepSystemHint('axios_headquarters', 'upload')?.toLowerCase()).toContain(
      'email or phone',
    )
    expect(
      disallowedModeReason('paylocity', 'live', {
        allowedApproaches: ['upload'],
      }).toLowerCase(),
    ).toContain('email or phone')
  })
})

describe('mode step explainer (KD25)', () => {
  test('definition cards use plain language and Habeas Platform name', () => {
    expect(MODE_DEFINITION_CARDS).toHaveLength(2)
    expect(MODE_DEFINITION_CARDS[0].title).toBe('Manual upload')
    expect(MODE_DEFINITION_CARDS[0].title).toBe(MANUAL_UPLOAD_LABEL)
    expect(MODE_DEFINITION_CARDS[1].title).not.toBe('Live')
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

  test('isModeAllowed follows approaches except Auth0 upload is not advertised', () => {
    expect(isModeAllowed('upload', ['live', 'upload'])).toBe(true)
    expect(isModeAllowed('live', ['upload'])).toBe(false)
    expect(isModeAllowed('live', ['live'])).toBe(true)
    expect(isModeAllowed('live', ['oauth'])).toBe(true)
    expect(isModeAllowed('live', ['upload'], 'hr_alumni')).toBe(true)
    expect(isModeAllowed('upload', ['oauth'], 'bizdev_contacts')).toBe(true)
    expect(isModeAllowed('upload', ['live', 'upload'], 'auth0')).toBe(false)
    expect(isModeAllowed('live', ['live', 'upload'], 'auth0')).toBe(true)
  })

  test('Auth0 Mode step is Management API only — no Manual upload card', () => {
    const cards = buildModeStepCards({
      systemId: 'auth0',
      displayName: 'Auth0',
      allowedApproaches: ['live', 'upload'],
    })
    expect(cards).toHaveLength(1)
    expect(cards[0].mode).toBe('live')
    expect(cards[0].title).toBe('Management API')
    expect(cards[0].title).not.toBe('Live')
    expect(cards.find((card) => card.mode === 'upload')).toBeUndefined()
    expect(cards.every((card) => card.title !== 'Manual upload')).toBe(true)
    expect(cards.every((card) => card.title !== 'Live')).toBe(true)
  })

  test('paylocity cards include per-system hints when both modes allowed', () => {
    const cards = buildModeStepCards({
      systemId: 'paylocity',
      displayName: 'Paylocity',
      allowedApproaches: ['live', 'upload'],
    })
    expect(cards).toHaveLength(2)
    expect(cards.every((card) => card.allowed)).toBe(true)
    expect(cards.find((card) => card.mode === 'upload')?.title).toBe('Manual upload')
    expect(cards.find((card) => card.mode === 'live')?.title).toBe('SFTP')
    expect(cards.find((card) => card.mode === 'upload')?.hint).toContain('map')
    expect(cards.find((card) => card.mode === 'live')?.hint?.toLowerCase()).toContain('sftp')
    expect(cards.every((card) => card.disabledReason === null)).toBe(true)
    expect(cards.every((card) => card.title !== 'Live')).toBe(true)
  })

  test('upload-only Axios HQ omits the live method card', () => {
    const cards = buildModeStepCards({
      systemId: 'axios_hq',
      displayName: 'Axios HQ',
      allowedApproaches: ['upload'],
    })
    expect(cards).toHaveLength(1)
    expect(cards[0].mode).toBe('upload')
    expect(cards[0].title).toBe('Manual upload')
    expect(cards[0].allowed).toBe(true)
    expect(cards.find((card) => card.mode === 'live')).toBeUndefined()
    expect(cards[0].definition.toLowerCase()).not.toContain('coming soon')
    const headquarters = buildModeStepCards({
      systemId: 'axios_headquarters',
      displayName: 'Axios HQ',
      allowedApproaches: ['upload'],
    })
    expect(headquarters).toHaveLength(1)
    expect(headquarters[0].mode).toBe('upload')
    expect(headquarters[0].title).toBe('Manual upload')
    expect(
      disallowedModeReason('axios_hq', 'live', {
        displayName: 'Axios HQ',
        allowedApproaches: ['upload'],
      }),
    ).toBe('Direct connection is not available for Axios HQ.')
    expect(
      disallowedModeReason('axios_hq', 'live', {
        displayName: 'Axios HQ',
        allowedApproaches: ['upload'],
      }).toLowerCase(),
    ).not.toContain('live is not available')
  })

  test('sheets systems allow oauth (live) or upload', () => {
    const cards = buildModeStepCards({
      systemId: 'bizdev_contacts',
      displayName: 'BizDev Contacts',
      allowedApproaches: ['upload'],
    })
    expect(cards.every((card) => card.allowed)).toBe(true)
    expect(cards.every((card) => card.disabledReason === null)).toBe(true)
    expect(cards.find((card) => card.mode === 'live')?.title).toBe('Google OAuth')
    expect(cards.find((card) => card.mode === 'upload')?.title).toBe('Manual upload')
    expect(cards.find((card) => card.mode === 'live')?.hint?.toLowerCase()).toContain(
      'oauth',
    )
    expect(disallowedModeReason('hr_alumni', 'live')).toBe('')
  })

  test('lever allows Upload when catalog includes it', () => {
    const cards = buildModeStepCards({
      systemId: 'lever',
      displayName: 'Lever',
      allowedApproaches: ['live', 'upload'],
    })
    expect(cards.find((card) => card.mode === 'upload')?.allowed).toBe(true)
    expect(cards.find((card) => card.mode === 'upload')?.title).toBe('Manual upload')
    expect(cards.find((card) => card.mode === 'live')?.title).toBe('Lever API')
    expect(cards.find((card) => card.mode === 'upload')?.disabledReason).toBeNull()
    expect(cards.find((card) => card.mode === 'upload')?.hint?.toLowerCase()).toContain(
      'map',
    )
    expect(modeStepSystemHint('lever', 'live')).toContain('Users read/list')
  })

  test('lever greys Upload only when catalog omits it', () => {
    const reason = disallowedModeReason('lever', 'upload', {
      displayName: 'Lever',
      allowedApproaches: ['live'],
    })
    expect(reason).toBe('Manual upload is not available for Lever.')
    expect(reason.toLowerCase()).toContain('not available')
    expect(reason.toLowerCase()).not.toContain('only supports live')
    expect(reason.toLowerCase()).not.toContain('live is not available')
    const cards = buildModeStepCards({
      systemId: 'lever',
      displayName: 'Lever',
      allowedApproaches: ['live'],
    })
    expect(cards.find((card) => card.mode === 'upload')?.disabledReason).toBe(reason)
    expect(cards.find((card) => card.mode === 'upload')?.title).toBe('Manual upload')
    expect(cards.find((card) => card.mode === 'live')?.title).toBe('Lever API')
    expect(modeStepSystemHint('lever', 'live')).toContain('Users read/list')
  })

  test('live card titles use the real method; upload is always Manual upload', () => {
    const cases: Array<{
      systemId: string
      displayName: string
      allowedApproaches: readonly string[]
      liveTitle: string
    }> = [
      {
        systemId: 'paylocity',
        displayName: 'Paylocity',
        allowedApproaches: ['live', 'upload'],
        liveTitle: 'SFTP',
      },
      {
        systemId: 'auth0',
        displayName: 'Auth0',
        allowedApproaches: ['live', 'upload'],
        liveTitle: 'Management API',
      },
      {
        systemId: 'lever',
        displayName: 'Lever',
        allowedApproaches: ['live', 'upload'],
        liveTitle: 'Lever API',
      },
      {
        systemId: 'hr_alumni',
        displayName: 'HR Alumni',
        allowedApproaches: ['oauth', 'upload'],
        liveTitle: 'Google OAuth',
      },
      {
        systemId: 'bizdev_contacts',
        displayName: 'BizDev Contacts',
        allowedApproaches: ['oauth', 'upload'],
        liveTitle: 'Google OAuth',
      },
      {
        systemId: 'google_sheets',
        displayName: 'Google Sheets',
        allowedApproaches: ['oauth', 'upload'],
        liveTitle: 'Google Sheets',
      },
      {
        systemId: 'alumni_google_sheet',
        displayName: 'Alumni Google Sheet',
        allowedApproaches: ['live', 'upload'],
        liveTitle: 'Google Sheets',
      },
      {
        systemId: 'contact_us_google_sheet',
        displayName: 'Contact Us Google Sheet',
        allowedApproaches: ['live', 'upload'],
        liveTitle: 'Google Sheets',
      },
    ]
    for (const { systemId, displayName, allowedApproaches, liveTitle } of cases) {
      const cards = buildModeStepCards({
        systemId,
        displayName,
        allowedApproaches,
      })
      if (ownerUploadAllowed(systemId)) {
        expect(cards.find((card) => card.mode === 'upload')?.title, systemId).toBe(
          'Manual upload',
        )
      } else {
        expect(cards.find((card) => card.mode === 'upload'), systemId).toBeUndefined()
      }
      expect(cards.find((card) => card.mode === 'live')?.title, systemId).toBe(liveTitle)
      expect(cards.every((card) => card.title !== 'Live'), systemId).toBe(true)
    }
    expect(connectionMethodLabel('paylocity')).toBe('SFTP')
    expect(connectionMethodLabel('auth0')).toBe('Management API')
    expect(connectionMethodLabel('lever')).toBe('Lever API')
    expect(connectionMethodLabel('hr_alumni')).toBe('Google OAuth')
    expect(connectionMethodLabel('bizdev_contacts')).toBe('Google OAuth')
    expect(connectionMethodLabel('google_sheets')).toBe('Google Sheets')
    expect(connectionMethodLabel('axios_hq')).toBeNull()
    expect(connectionMethodLabel('axios_headquarters')).toBeNull()
  })

  test('paylocity SFTP copy promises SFTP, not API', () => {
    const cards = buildModeStepCards({
      systemId: 'paylocity',
      displayName: 'Paylocity',
      allowedApproaches: ['upload'],
    })
    const live = cards.find((card) => card.mode === 'live')
    expect(live?.title).toBe('SFTP')
    expect(live?.title).not.toBe('Live')
    expect(live?.definition.toLowerCase()).toContain('sftp')
    expect(live?.definition.toLowerCase()).toContain('not an api connection')
    expect(live?.definition.toLowerCase()).toContain('upload today')
    expect(live?.definition.toLowerCase()).not.toContain('coming soon')
    expect(live?.disabledReason?.toLowerCase()).toContain('sftp')
    expect(live?.disabledReason?.toLowerCase()).toContain('upload')
    expect(live?.disabledReason?.toLowerCase()).not.toContain('yet')
    expect(live?.disabledReason?.toLowerCase()).not.toContain('coming soon')
    expect(live?.disabledReason?.toLowerCase()).not.toContain('api')
    const liveAllowed = buildModeStepCards({
      systemId: 'paylocity',
      displayName: 'Paylocity',
      allowedApproaches: ['live', 'upload'],
    }).find((card) => card.mode === 'live')
    expect(liveAllowed?.title).toBe('SFTP')
    expect(liveAllowed?.definition.toLowerCase()).toContain('sftp')
    expect(liveAllowed?.definition.toLowerCase()).toContain('manual upload')
    expect(liveAllowed?.definition.toLowerCase()).not.toContain('use upload today')
    expect(liveAllowed?.definition.toLowerCase()).not.toContain('only supports')
    expect(liveAllowed?.definition.toLowerCase()).not.toContain('coming soon')
    expect(liveAllowed?.hint?.toLowerCase()).toContain('sftp')
    expect(liveAllowed?.hint?.toLowerCase()).toContain('not an api')
    expect(liveAllowed?.hint?.toLowerCase()).toContain('manual upload')
    expect(liveAllowed?.hint?.toLowerCase()).not.toContain('coming soon')
  })
})

describe('owner connectors super_admin verticals', () => {
  test('View-as super_admin sees every catalog chip, not only tech', () => {
    expect(ownerSeesAllCatalogVerticals('super_admin', 'super_admin')).toBe(true)
    expect(ownerSeesAllCatalogVerticals('data_owner', 'super_admin')).toBe(true)
    expect(ownerSeesAllCatalogVerticals('data_owner', 'data_owner')).toBe(false)
    expect(
      ownerConnectorsVerticalIds({
        role: 'super_admin',
        realRole: 'super_admin',
        meVerticals: ['tech'],
        catalogVerticalIds: ['communications', 'people_hr', 'tech', 'data', 'test'],
      }),
    ).toEqual(['communications', 'people_hr', 'tech', 'test'])
  })

  test('00023 fallback uses /me catalog when owner index is missing', () => {
    expect(
      ownerConnectorsVerticalIds({
        role: 'super_admin',
        meVerticals: ['communications', 'people_hr', 'tech', 'test'],
      }),
    ).toEqual(['communications', 'people_hr', 'tech', 'test'])
  })

  test('data_owner stays on assigned verticals', () => {
    expect(
      ownerConnectorsVerticalIds({
        role: 'data_owner',
        meVerticals: ['tech'],
        catalogVerticalIds: ['tech'],
      }),
    ).toEqual(['tech'])
  })
})

describe('owner connectors hide cassandra', () => {
  test('hides cassandra system and data vertical', () => {
    expect(isOwnerConnectorsHiddenSystem('cassandra')).toBe(true)
    expect(isOwnerConnectorsHiddenSystem('hr_alumni')).toBe(false)
    expect(isOwnerConnectorsHiddenVertical('data')).toBe(true)
    expect(isOwnerConnectorsHiddenVertical('people_hr')).toBe(false)
  })

  test('isOwnerWizardHiddenSystem matches the infra slug only', () => {
    expect(isOwnerWizardHiddenSystem('cassandra')).toBe(true)
    expect(isOwnerWizardHiddenSystem('Cassandra')).toBe(true)
    expect(isOwnerWizardHiddenSystem('hr_alumni')).toBe(false)
  })

  test('filterOwnerWizardConnectors removes cassandra cards', () => {
    const visible = filterOwnerWizardConnectors([
      {
        system: 'cassandra',
        display_name: 'Cassandra',
        allowed_approaches: [],
        connection_id: null,
        status: null,
        last_test_ok: null,
        metadata: {},
        display_status: 'view_only',
        gate_code: '',
        gate_allowed: true,
      },
      {
        system: 'hr_alumni',
        display_name: 'HR Alumni List',
        allowed_approaches: ['upload'],
        connection_id: null,
        status: null,
        last_test_ok: null,
        metadata: {},
        display_status: 'needs_setup',
        gate_code: '',
        gate_allowed: false,
      },
    ])
    expect(visible.map((row) => row.system)).toEqual(['hr_alumni'])
  })

  test('ownerConnectorDisplayName uses System A / System B in test vertical', () => {
    expect(ownerConnectorDisplayName('test', 'cassandra', 'Cassandra')).toBe('System A')
    expect(ownerConnectorDisplayName('test', 'hr_alumni', 'HR Alumni List')).toBe(
      'System B',
    )
    expect(ownerConnectorDisplayName('communications', 'axios_hq', 'Axios HQ')).toBe(
      'Axios HQ',
    )
    expect(ownerConnectorDisplayName('communications', 'axios_headquarters')).toBe(
      'Axios HQ',
    )
    expect(
      ownerConnectorDisplayName('communications', 'axios_headquarters', 'Axios HQ'),
    ).toBe('Axios HQ')
    expect(
      ownerConnectorDisplayName('communications', 'axios_headquarters', 'axios headquarters'),
    ).toBe('Axios HQ')
    expect(ownerConnectorDisplayName('data', 'cassandra', 'Cassandra')).not.toMatch(
      /cassandra/i,
    )
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

  test('parse and serialize round-trip mixed corrupt sample', () => {
    const doc = parseCsvDocument(UPLOAD_SAMPLE_CSV.mixed_good_and_corrupt.body)
    expect(doc.headers).toEqual(['email', 'phone', 'first_name'])
    expect(doc.rows).toHaveLength(3)
    expect(doc.rows[1][0]).toBe('not-an-email')
    expect(parseCsvDocument(serializeCsvDocument(doc)).rows).toEqual(doc.rows)
  })
})
