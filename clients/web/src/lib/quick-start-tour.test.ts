// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { ConnectorReminder, OwnerConnectorSystem } from './api'
import {
  clearOwnerQuickStartTourState,
  connectorHasPassingConnectionTest,
  isOwnerQuickStartTourEligible,
  ownerQuickStartTourStepsForRole,
  ownerTourStorageKey,
  readTourPersistence,
  shouldDeferTourForOnboardingChrome,
  shouldOfferOwnerQuickStartTour,
  wizardCompletedAt,
  writeTourPersistence,
} from './quick-start-tour'

function connector(
  overrides: Partial<OwnerConnectorSystem> = {},
): OwnerConnectorSystem {
  return {
    system: 'axios_hq',
    display_name: 'Axios HQ',
    allowed_approaches: ['upload'],
    connection_id: 'conn-1',
    status: 'connected',
    last_test_ok: true,
    metadata: { wizard_completed_at: '2026-08-13T12:00:00+00:00' },
    display_status: 'connected',
    gate_code: 'ok',
    gate_allowed: true,
    ...overrides,
  }
}

describe('ownerTourStorageKey', () => {
  test('uses habeas-cli.tour.v1.owner.{userId}', () => {
    expect(ownerTourStorageKey('owner@example.com')).toBe(
      'habeas-cli.tour.v1.owner.owner@example.com',
    )
  })
})

describe('wizardCompletedAt + connectorHasPassingConnectionTest', () => {
  test('reads wizard_completed_at from metadata', () => {
    expect(wizardCompletedAt({ wizard_completed_at: '2026-08-01T00:00:00Z' })).toBe(
      '2026-08-01T00:00:00Z',
    )
    expect(wizardCompletedAt({})).toBeNull()
  })

  test('needs_setup never passes connection test gate', () => {
    expect(
      connectorHasPassingConnectionTest(
        connector({ display_status: 'needs_setup', last_test_ok: true }),
      ),
    ).toBe(false)
  })

  test('upload_ok via last_successful_upload_at', () => {
    expect(
      connectorHasPassingConnectionTest(
        connector({
          last_test_ok: null,
          metadata: {
            wizard_completed_at: '2026-08-01T00:00:00Z',
            last_successful_upload_at: '2026-08-02T00:00:00Z',
          },
        }),
      ),
    ).toBe(true)
  })
})

describe('isOwnerQuickStartTourEligible (KD32)', () => {
  test('false for non-owner-nav roles', () => {
    expect(
      isOwnerQuickStartTourEligible({
        role: 'legal',
        verticals: ['communications'],
        connectorReminders: [],
        connectors: [connector()],
      }),
    ).toBe(false)
  })

  test('false while any connector needs_setup', () => {
    expect(
      isOwnerQuickStartTourEligible({
        role: 'data_owner',
        verticals: ['communications'],
        connectorReminders: [],
        connectors: [
          connector(),
          connector({ system: 'lever', display_status: 'needs_setup', last_test_ok: null }),
        ],
      }),
    ).toBe(false)
  })

  test('false while wizard_incomplete reminder present', () => {
    const reminders: ConnectorReminder[] = [
      {
        code: 'wizard_incomplete',
        system: 'axios_hq',
        vertical_id: 'communications',
        severity: 'approaching',
      },
    ]
    expect(
      isOwnerQuickStartTourEligible({
        role: 'data_owner',
        verticals: ['communications'],
        connectorReminders: reminders,
        connectors: [connector()],
      }),
    ).toBe(false)
  })

  test('false without wizard completion + passing test', () => {
    expect(
      isOwnerQuickStartTourEligible({
        role: 'data_owner',
        verticals: ['communications'],
        connectorReminders: [],
        connectors: [
          connector({
            metadata: {},
            last_test_ok: true,
          }),
        ],
      }),
    ).toBe(false)

    expect(
      isOwnerQuickStartTourEligible({
        role: 'data_owner',
        verticals: ['communications'],
        connectorReminders: [],
        connectors: [
          connector({
            metadata: { wizard_completed_at: '2026-08-01T00:00:00Z' },
            last_test_ok: false,
            status: 'pending',
          }),
        ],
      }),
    ).toBe(false)
  })

  test('true when wizard complete and connection test passed', () => {
    expect(
      isOwnerQuickStartTourEligible({
        role: 'data_owner',
        verticals: ['communications'],
        connectorReminders: [],
        connectors: [connector()],
      }),
    ).toBe(true)
  })
})

describe('ownerQuickStartTourStepsForRole (F9, OQ18)', () => {
  test('data_owner gets full owner chain', () => {
    const steps = ownerQuickStartTourStepsForRole('data_owner')
    expect(steps.map((step) => step.id)).toEqual([
      'connectors',
      'my-work',
      'requests',
      'matching-inbox',
      'docs',
    ])
  })

  test('super_admin gets Connectors + ops Connections only', () => {
    const steps = ownerQuickStartTourStepsForRole('super_admin')
    expect(steps.map((step) => step.id)).toEqual(['connectors', 'ops-connections'])
  })

  test('legal persona skips Connectors', () => {
    const steps = ownerQuickStartTourStepsForRole('legal')
    expect(steps.map((step) => step.id)).toEqual([
      'my-work',
      'requests',
      'matching-inbox',
      'docs',
    ])
  })
})

describe('shouldDeferTourForOnboardingChrome', () => {
  test('defers while post-auth splash would play', () => {
    expect(
      shouldDeferTourForOnboardingChrome({
        me: { email: 'owner@example.com', needs_connector_setup: false },
        postAuthSplashWouldPlay: true,
      }),
    ).toBe(true)
  })

  test('defers while connector welcome is active', () => {
    expect(
      shouldDeferTourForOnboardingChrome({
        me: { email: 'owner@example.com', needs_connector_setup: true },
        postAuthSplashWouldPlay: false,
      }),
    ).toBe(true)
  })

  test('does not defer after welcome dismissed', () => {
    expect(
      shouldDeferTourForOnboardingChrome({
        me: { email: 'owner@example.com', needs_connector_setup: true },
        postAuthSplashWouldPlay: false,
        connectorWelcomeDismissed: true,
      }),
    ).toBe(false)
  })
})

describe('shouldOfferOwnerQuickStartTour (KD33)', () => {
  test('re-offers when eligible and persistence unset', () => {
    expect(
      shouldOfferOwnerQuickStartTour({
        eligible: true,
        persistence: null,
        sessionDismissed: false,
      }),
    ).toBe(true)
  })

  test('does not offer after completed or skipped', () => {
    expect(
      shouldOfferOwnerQuickStartTour({
        eligible: true,
        persistence: 'completed',
        sessionDismissed: false,
      }),
    ).toBe(false)
    expect(
      shouldOfferOwnerQuickStartTour({
        eligible: true,
        persistence: 'skipped',
        sessionDismissed: false,
      }),
    ).toBe(false)
  })

  test('mid-chain session dismiss waits until next login', () => {
    expect(
      shouldOfferOwnerQuickStartTour({
        eligible: true,
        persistence: null,
        sessionDismissed: true,
      }),
    ).toBe(false)
  })

  test('defers during splash/welcome or connect invite path', () => {
    expect(
      shouldOfferOwnerQuickStartTour({
        eligible: true,
        persistence: null,
        sessionDismissed: false,
        deferForOnboardingChrome: true,
      }),
    ).toBe(false)
    expect(
      shouldOfferOwnerQuickStartTour({
        eligible: true,
        persistence: null,
        sessionDismissed: false,
        onConnectInvitePath: true,
      }),
    ).toBe(false)
  })
})

describe('tour persistence helpers', () => {
  test('write/read/clear localStorage state', () => {
    const storage = new Map<string, string>()
    const fakeStorage = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    }

    writeTourPersistence('owner@example.com', 'skipped', fakeStorage as Storage)
    expect(readTourPersistence('owner@example.com', fakeStorage)).toBe('skipped')

    clearOwnerQuickStartTourState('owner@example.com', fakeStorage as Storage)
    expect(readTourPersistence('owner@example.com', fakeStorage)).toBeNull()
  })
})
