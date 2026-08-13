// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  connectionDisplayStatusLabel,
  connectionDisplayStatusVariant,
  connectionInviteAllowed,
  isCreatableConnectionSystem,
  isUploadOnlySystem,
  leverTriageCopy,
  resolveConnectionChipStatus,
} from './connection-display'

describe('connection-display (AE8 / KD18)', () => {
  test('labels gated display statuses', () => {
    expect(connectionDisplayStatusLabel('needs_refresh')).toBe('Needs refresh')
    expect(connectionDisplayStatusLabel('action_required')).toBe('Action required')
    expect(connectionDisplayStatusLabel('needs_setup')).toBe('Needs setup')
    expect(connectionDisplayStatusLabel('connected')).toBe('Connected')
    expect(connectionDisplayStatusLabel('view_only')).toBe('View only')
  })

  test('never maps needs_refresh / action_required to Connected', () => {
    expect(connectionDisplayStatusLabel('needs_refresh')).not.toBe('Connected')
    expect(connectionDisplayStatusLabel('action_required')).not.toBe('Connected')
  })

  test('prefers display_status over raw status for chips', () => {
    expect(
      resolveConnectionChipStatus({
        status: 'connected',
        display_status: 'needs_refresh',
      }),
    ).toBe('needs_refresh')
    expect(
      resolveConnectionChipStatus({
        status: 'connected',
        display_status: 'action_required',
      }),
    ).toBe('action_required')
    expect(
      resolveConnectionChipStatus({
        status: 'connected',
        display_status: null,
      }),
    ).toBe('connected')
    expect(
      connectionDisplayStatusLabel(
        resolveConnectionChipStatus({
          status: 'connected',
          display_status: 'needs_refresh',
        }),
      ),
    ).toBe('Needs refresh')
  })

  test('variants emphasize gated attention states', () => {
    expect(connectionDisplayStatusVariant('connected')).toBe('ok')
    expect(connectionDisplayStatusVariant('needs_refresh')).toBe('fail')
    expect(connectionDisplayStatusVariant('action_required')).toBe('fail')
    expect(connectionDisplayStatusVariant('needs_setup')).toBe('wait')
    expect(connectionDisplayStatusVariant('view_only')).toBe('default')
  })

  test('invite rules for cassandra / upload-only / empty credentials', () => {
    expect(connectionInviteAllowed({ system: 'cassandra' })).toBe(false)
    expect(connectionInviteAllowed({ system: 'bizdev_contacts' })).toBe(false)
    expect(connectionInviteAllowed({ system: 'hr_alumni' })).toBe(false)
    expect(
      connectionInviteAllowed({ system: 'mailchimp', credentialFieldCount: 0 }),
    ).toBe(false)
    expect(
      connectionInviteAllowed({
        system: 'mailchimp',
        inviteAllowed: true,
        credentialFieldCount: 1,
      }),
    ).toBe(true)
    expect(
      connectionInviteAllowed({ system: 'google_sheets', inviteAllowed: false }),
    ).toBe(false)
  })

  test('create picker hides retired google_sheets', () => {
    expect(
      isCreatableConnectionSystem({ system_id: 'google_sheets', invite_allowed: false }),
    ).toBe(false)
    expect(
      isCreatableConnectionSystem({ system_id: 'cassandra', invite_allowed: false }),
    ).toBe(true)
    expect(
      isCreatableConnectionSystem({ system_id: 'bizdev_contacts', invite_allowed: true }),
    ).toBe(true)
    expect(isUploadOnlySystem('bizdev_contacts')).toBe(true)
    expect(isUploadOnlySystem('mailchimp')).toBe(false)
  })

  test('Lever triage copy for ops', () => {
    expect(leverTriageCopy('lever_unauthorized')).toContain('unauthorized')
    expect(leverTriageCopy('lever_forbidden')).toContain('forbidden')
    expect(leverTriageCopy('auth_failed')).toBeNull()
  })
})
