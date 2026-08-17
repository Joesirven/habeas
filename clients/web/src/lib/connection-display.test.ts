// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  connectionDisplayStatusLabel,
  connectionDisplayStatusVariant,
  connectionInviteAllowed,
  isCreatableConnectionSystem,
  isUploadOnlySystem,
  leverTriageCopy,
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  matchingGateFromAttemptAudit,
  matchingGateFromAttempts,
  matchingGateFromConnection,
  matchingGateFromReminder,
  resolveMatchingConnectorGate,
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

  test('matching gate from attempt audit — needs_refresh not Connected (R52)', () => {
    const gate = matchingGateFromAttemptAudit(
      {
        event: 'gate_blocked',
        gate_code: 'upload_stale',
        display_status: 'needs_refresh',
        system: 'mailchimp',
      },
      { error_code: 'gate_blocked', status: 'submit_error' },
    )
    expect(gate?.displayStatus).toBe('needs_refresh')
    expect(matchingConnectorGateChip(gate!).label).toBe('Needs refresh')
    expect(matchingConnectorGateChip(gate!).label).not.toBe('Connected')
  })

  test('matching gate from attempts prefers latest attempt_number', () => {
    const gate = matchingGateFromAttempts([
      {
        id: 1,
        attempt_number: 1,
        status: 'success',
        attempted_at: null,
        completed_at: null,
        error_code: null,
        audit_payload: { matched: true, match_count: 1 },
      },
      {
        id: 2,
        attempt_number: 2,
        status: 'submit_error',
        attempted_at: null,
        completed_at: null,
        error_code: 'gate_blocked',
        audit_payload: {
          event: 'gate_blocked',
          display_status: 'action_required',
          gate_code: 'rotation_overdue',
          system: 'lever',
        },
      },
    ])
    expect(gate?.displayStatus).toBe('action_required')
    expect(gate?.system).toBe('lever')
  })

  test('matching gate from connection when gate_allowed is false', () => {
    const gate = matchingGateFromConnection({
      system: 'paylocity',
      status: 'connected',
      display_status: 'needs_refresh',
      gate_allowed: false,
      gate_code: 'upload_stale',
    })
    expect(gate?.displayStatus).toBe('needs_refresh')
    expect(matchingConnectorGateChip(gate!).label).toBe('Needs refresh')
  })

  test('resolveMatchingConnectorGate prefers attempt over connection/reminder', () => {
    const gate = resolveMatchingConnectorGate({
      attempts: [
        {
          id: 1,
          attempt_number: 1,
          status: 'submit_error',
          attempted_at: null,
          completed_at: null,
          error_code: 'gate_blocked',
          audit_payload: {
            event: 'gate_blocked',
            display_status: 'needs_refresh',
            system: 'auth0',
          },
        },
      ],
      connections: [
        {
          id: 'c1',
          system: 'mailchimp',
          display_name: 'Mailchimp',
          status: 'connected',
          display_status: 'action_required',
          gate_allowed: false,
          gate_code: 'rotation_overdue',
          owner_email: null,
          secret_resource_name: null,
          last_tested_at: null,
          last_test_ok: true,
          last_test_detail: null,
          created_by: 'ops',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          metadata: {},
        },
      ],
      reminders: [
        {
          code: 'wizard_incomplete',
          system: 'lever',
          vertical_id: 'communications',
          severity: 'overdue',
        },
      ],
    })
    expect(gate?.source).toBe('attempt')
    expect(gate?.displayStatus).toBe('needs_refresh')
  })

  test('reminder hard-gate codes map to KD18 labels', () => {
    const stale = matchingGateFromReminder({
      code: 'upload_stale',
      system: 'mailchimp',
      vertical_id: 'communications',
      severity: 'overdue',
    })
    expect(matchingConnectorGateChip(stale!).label).toBe('Needs refresh')
    const wizard = matchingGateFromReminder({
      code: 'wizard_incomplete',
      system: 'lever',
      vertical_id: 'hr',
      severity: 'approaching',
    })
    expect(matchingConnectorGateChip(wizard!).label).toBe('Action required')
    expect(
      matchingGateFromReminder({
        code: 'upload_approaching',
        system: 'mailchimp',
        vertical_id: 'communications',
        severity: 'approaching',
      }),
    ).toBeNull()
  })

  test('matching gate banner copy is honest about test vs matching', () => {
    const copy = matchingConnectorGateBannerCopy({
      blocked: true,
      displayStatus: 'needs_refresh',
      gateCode: 'upload_stale',
      system: 'mailchimp',
      source: 'attempt',
    })
    expect(copy.title).toContain('Needs refresh')
    expect(copy.description).toContain('stale')
  })
})
