// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { plugin } from 'bun'
import { describe, expect, mock, test } from 'bun:test'
import { join } from 'node:path'

plugin({
  name: 'at-alias',
  setup(build) {
    build.onResolve({ filter: /^@\// }, (args) => ({
      path: join(import.meta.dir, '..', args.path.slice(2)),
    }))
  },
})

const { canAccessLegalSurfaces, canAccessOwnerPalette, isVerticalOperatorRole } =
  await import('./auth')
const { PENDING_SETTING_INVITE_USERS, SIMULATE_ROLE_VALUES } = await import('./api')
const { paletteSearchPlaceholder, staticActions } = await import(
  '../components/CommandPalette'
)
const {
  nextPostAuthPrompt,
  shouldHintSettingsInvite,
  shouldShowConnectorWelcome,
  shouldShowPendingSettings,
} = await import('../components/AppShell')

describe('canAccessOwnerPalette', () => {
  test('true for data_owner, data_user, legal, admin, super_admin', () => {
    expect(canAccessOwnerPalette('data_owner')).toBe(true)
    expect(canAccessOwnerPalette('data_user')).toBe(true)
    expect(canAccessOwnerPalette('legal')).toBe(true)
    expect(canAccessOwnerPalette('admin')).toBe(true)
    expect(canAccessOwnerPalette('super_admin')).toBe(true)
  })

  test('false for undefined', () => {
    expect(canAccessOwnerPalette(undefined)).toBe(false)
  })
})

describe('isVerticalOperatorRole', () => {
  test('true for data_owner and data_user', () => {
    expect(isVerticalOperatorRole('data_owner')).toBe(true)
    expect(isVerticalOperatorRole('data_user')).toBe(true)
  })

  test('false for legal, admin, super_admin', () => {
    expect(isVerticalOperatorRole('legal')).toBe(false)
    expect(isVerticalOperatorRole('admin')).toBe(false)
    expect(isVerticalOperatorRole('super_admin')).toBe(false)
  })
})

describe('simulate-role palette', () => {
  test('includes data_user', () => {
    expect(SIMULATE_ROLE_VALUES).toContain('data_user')
    expect(SIMULATE_ROLE_VALUES).toContain('data_owner')
  })
})

describe('canAccessLegalSurfaces (People group gate)', () => {
  test('true for legal, admin, super_admin', () => {
    expect(canAccessLegalSurfaces('legal')).toBe(true)
    expect(canAccessLegalSurfaces('admin')).toBe(true)
    expect(canAccessLegalSurfaces('super_admin')).toBe(true)
  })

  test('false for data_owner and data_user', () => {
    expect(canAccessLegalSurfaces('data_owner')).toBe(false)
    expect(canAccessLegalSurfaces('data_user')).toBe(false)
  })
})

describe('owner command palette (R65 leftovers)', () => {
  const navigate = mock(() => undefined)

  test('placeholder omits people for owners', () => {
    expect(paletteSearchPlaceholder(false)).toBe('Search requests or actions…')
    expect(paletteSearchPlaceholder(true)).toBe(
      'Search requests, people, or actions…',
    )
  })

  test('owner actions skip Legal chips, pipeline Home, and People settings', () => {
    const items = staticActions(navigate, false, false, true, () => undefined)
    const ids = items.map((item) => item.id)
    const labels = items.map((item) => item.label)
    expect(ids).toEqual([
      'action-home',
      'action-requests',
      'action-inbox',
      'action-docs',
      'action-inbox-matching',
      'action-inbox-fulfillment',
      'action-inbox-tasks',
      'action-connectors',
    ])
    expect(labels).toContain('Go to Home')
    expect(labels).not.toContain('Inbox · Unassigned')
    expect(labels).not.toContain('Inbox · Notice')
    expect(labels).not.toContain('Inbox · Delivery')
    expect(labels).not.toContain('Inbox · Assignment to legal')
    expect(labels).not.toContain('Open Settings')

    const home = items.find((item) => item.id === 'action-home')
    home?.onSelect()
    expect(navigate).toHaveBeenCalledWith({ to: '/', search: { tab: 'pipeline' } })
    expect(navigate).not.toHaveBeenCalledWith(
      expect.objectContaining({ to: '/ops/drop-pipeline' }),
    )
  })
})

describe('pending-settings invite prompt', () => {
  const ownerEmail = 'owner@example.com'

  function ownerMe(overrides = {}) {
    return {
      email: ownerEmail,
      role: 'data_owner',
      real_role: 'data_owner',
      verticals: ['data'],
      pending_settings: [
        {
          id: PENDING_SETTING_INVITE_USERS,
          title: 'Invite data users',
          status: 'pending',
        },
      ],
      ...overrides,
    }
  }

  test('does not block login when data_owner has invite_data_users pending', () => {
    const me = ownerMe()
    expect(shouldShowPendingSettings(me)).toBe(false)
    expect(nextPostAuthPrompt(me)).toBeNull()
    expect(shouldHintSettingsInvite(me)).toBe(true)
  })

  test('hides hint when invite_data_users is skipped or done', () => {
    expect(
      shouldShowPendingSettings(
        ownerMe({
          pending_settings: [
            {
              id: PENDING_SETTING_INVITE_USERS,
              title: 'Invite data users',
              status: 'skipped',
            },
          ],
        }),
      ),
    ).toBe(false)
    expect(
      shouldHintSettingsInvite(
        ownerMe({
          pending_settings: [
            {
              id: PENDING_SETTING_INVITE_USERS,
              title: 'Invite data users',
              status: 'skipped',
            },
          ],
        }),
      ),
    ).toBe(false)
    expect(
      shouldHintSettingsInvite(
        ownerMe({
          pending_settings: [
            {
              id: PENDING_SETTING_INVITE_USERS,
              title: 'Invite data users',
              status: 'done',
            },
          ],
        }),
      ),
    ).toBe(false)
    expect(
      nextPostAuthPrompt(
        ownerMe({
          pending_settings: [
            {
              id: PENDING_SETTING_INVITE_USERS,
              title: 'Invite data users',
              status: 'done',
            },
          ],
        }),
      ),
    ).toBeNull()
  })

  test('hides for data_user even when invite_data_users is pending', () => {
    const me = ownerMe({
      email: 'teammate@example.com',
      role: 'data_user',
      real_role: 'data_user',
    })
    expect(shouldShowPendingSettings(me)).toBe(false)
    expect(shouldHintSettingsInvite(me)).toBe(false)
    expect(nextPostAuthPrompt(me)).toBeNull()
  })

  test('connector welcome still shows when setup is needed', () => {
    const me = ownerMe({ needs_connector_setup: true })
    expect(shouldShowConnectorWelcome(me)).toBe(true)
    expect(shouldShowPendingSettings(me)).toBe(false)
    expect(shouldHintSettingsInvite(me)).toBe(true)
    expect(nextPostAuthPrompt(me)).toBe('connector_welcome')
  })
})
