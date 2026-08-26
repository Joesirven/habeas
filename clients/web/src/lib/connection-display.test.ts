// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  catalogDisplaySystemId,
  connectionSystemDisplayLabel,
  connectRedeemSystemLabel,
  isRetractedConnectionSystem,
} from './api'
import {
  connectionAllowsUploadFallback,
  connectionDisplayStatusLabel,
  connectionDisplayStatusVariant,
  connectionInviteAllowed,
  isCreatableConnectionSystem,
  isLiveAndUploadSystem,
  isUploadOnlySystem,
  leverTriageCopy,
  matchingConnectorGateBannerCopy,
  matchingConnectorGateChip,
  matchingGateFromAttemptAudit,
  matchingGateFromAttempts,
  matchingGateFromConnection,
  matchingGateFromReminder,
  isMatchingGateBlockedDisplayStatus,
  ownerAssignedVerticalSummary,
  ownerConnectorActionRequiredCount,
  ownerHomeItemTitle,
  ownerHomeQueueRows,
  overlayCalloutShowsOwnerCta,
  ownerConnectorsSearch,
  resolveMatchingConnectorGate,
  resolveOverlayConnectorCallout,
  resolveConnectionChipStatus,
  OVERLAY_LIVE_DOWN_COPY,
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
    expect(connectionInviteAllowed({ system: 'axios_hq' })).toBe(false)
    expect(connectionInviteAllowed({ system: 'axios_headquarters' })).toBe(false)
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
    expect(
      connectionInviteAllowed({
        system: 'lever',
        inviteAllowed: true,
        credentialFieldCount: 1,
      }),
    ).toBe(true)
    expect(
      connectionInviteAllowed({
        system: 'paylocity',
        inviteAllowed: true,
        credentialFieldCount: 1,
      }),
    ).toBe(true)
  })

  test('create picker hides retired google_sheets, infra cassandra, retracted axios_headquarters', () => {
    expect(
      isCreatableConnectionSystem({ system_id: 'google_sheets', invite_allowed: false }),
    ).toBe(false)
    expect(
      isCreatableConnectionSystem({ system_id: 'cassandra', invite_allowed: false }),
    ).toBe(false)
    expect(
      isCreatableConnectionSystem({ system_id: 'cassandra', invite_allowed: true }),
    ).toBe(false)
    expect(
      isCreatableConnectionSystem({ system_id: 'bizdev_contacts', invite_allowed: true }),
    ).toBe(true)
    expect(
      isCreatableConnectionSystem({ system_id: 'axios_hq', invite_allowed: false }),
    ).toBe(true)
    expect(
      isCreatableConnectionSystem({
        system_id: 'axios_headquarters',
        invite_allowed: false,
      }),
    ).toBe(false)
    expect(
      isCreatableConnectionSystem({
        system_id: 'axios_headquarters',
        invite_allowed: true,
      }),
    ).toBe(false)
    expect(
      isCreatableConnectionSystem({ system_id: 'lever', invite_allowed: true }),
    ).toBe(true)
    expect(
      isCreatableConnectionSystem({ system_id: 'paylocity', invite_allowed: true }),
    ).toBe(true)
    expect(isUploadOnlySystem('bizdev_contacts')).toBe(true)
    expect(isUploadOnlySystem('axios_hq')).toBe(true)
    expect(isUploadOnlySystem('axios_headquarters')).toBe(true)
    expect(isUploadOnlySystem('mailchimp')).toBe(false)
    expect(isUploadOnlySystem('lever')).toBe(false)
    expect(isUploadOnlySystem('paylocity')).toBe(false)
  })

  test('Wave M live+upload fallback for Lever / Paylocity; Axios HQ upload-only', () => {
    expect(isLiveAndUploadSystem('lever')).toBe(true)
    expect(isLiveAndUploadSystem('paylocity')).toBe(true)
    expect(isLiveAndUploadSystem('axios_hq')).toBe(false)
    expect(isLiveAndUploadSystem('cassandra')).toBe(false)
    expect(connectionAllowsUploadFallback('lever')).toBe(true)
    expect(connectionAllowsUploadFallback('paylocity')).toBe(true)
    expect(connectionAllowsUploadFallback('axios_hq')).toBe(true)
    expect(connectionAllowsUploadFallback('axios_headquarters')).toBe(true)
    expect(connectionAllowsUploadFallback('cassandra')).toBe(false)
    expect(connectionAllowsUploadFallback(null)).toBe(false)
  })

  test('catalog display id is axios_hq; retracted slug aliases for display only', () => {
    expect(catalogDisplaySystemId('axios_hq')).toBe('axios_hq')
    expect(catalogDisplaySystemId('axios_headquarters')).toBe('axios_hq')
    expect(isRetractedConnectionSystem('axios_headquarters')).toBe(true)
    expect(isRetractedConnectionSystem('axios_hq')).toBe(false)
    expect(connectionSystemDisplayLabel('axios_hq')).toBe('Axios HQ')
    expect(connectionSystemDisplayLabel('axios_headquarters')).toBe('Axios HQ')
    expect(
      connectRedeemSystemLabel({
        system: 'axios_hq',
        display_name: 'ignored',
      }),
    ).toBe('Axios HQ')
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

  test('matching gate banner labels Axios HQ for catalog and retracted slugs', () => {
    const catalog = matchingConnectorGateBannerCopy({
      blocked: true,
      displayStatus: 'needs_refresh',
      gateCode: 'upload_stale',
      system: 'axios_hq',
      source: 'reminder',
    })
    expect(catalog.description).toContain('Axios HQ')
    expect(catalog.description.toLowerCase()).not.toContain('axios_headquarters')
    const retracted = matchingConnectorGateBannerCopy({
      blocked: true,
      displayStatus: 'needs_refresh',
      gateCode: 'upload_stale',
      system: 'axios_headquarters',
      source: 'reminder',
    })
    expect(retracted.description).toContain('Axios HQ')
    expect(retracted.description).not.toContain('axios headquarters')
  })

  test('matchingConnectorGateChip never labels Connected when blocked (KD18)', () => {
    const blockedStatuses = ['needs_refresh', 'action_required', 'needs_setup'] as const
    for (const displayStatus of blockedStatuses) {
      expect(isMatchingGateBlockedDisplayStatus(displayStatus)).toBe(true)
      const chip = matchingConnectorGateChip({
        blocked: true,
        displayStatus,
        gateCode: 'upload_stale',
        system: 'auth0',
        source: 'attempt',
      })
      expect(chip.label).not.toBe('Connected')
      expect(chip.label.toLowerCase()).not.toContain('connected')
    }
    expect(isMatchingGateBlockedDisplayStatus('connected')).toBe(false)

    const fromConnection = matchingGateFromConnection({
      system: 'auth0',
      status: 'connected',
      display_status: 'needs_refresh',
      gate_allowed: false,
      gate_code: 'upload_stale',
    })
    expect(fromConnection?.blocked).toBe(true)
    expect(matchingConnectorGateChip(fromConnection!).label).toBe('Needs refresh')
    expect(matchingConnectorGateChip(fromConnection!).label).not.toBe('Connected')

    const fromRotation = matchingGateFromConnection({
      system: 'lever',
      status: 'connected',
      display_status: 'action_required',
      gate_allowed: false,
      gate_code: 'rotation_overdue',
    })
    expect(matchingConnectorGateChip(fromRotation!).label).toBe('Action required')
    expect(matchingConnectorGateChip(fromRotation!).label).not.toBe('Connected')

    const fromWizard = matchingGateFromReminder({
      code: 'wizard_incomplete',
      system: 'auth0',
      vertical_id: 'auth0',
      severity: 'overdue',
    })
    expect(matchingConnectorGateChip(fromWizard!).label).toBe('Action required')
    expect(matchingConnectorGateChip(fromWizard!).label).not.toBe('Connected')
  })
})

describe('ownerConnectorActionRequiredCount (R62)', () => {
  test('returns null when /me is missing — no fake number', () => {
    expect(ownerConnectorActionRequiredCount(null)).toBeNull()
    expect(ownerConnectorActionRequiredCount(undefined)).toBeNull()
  })

  test('counts overdue and hard-gate reminders plus wizard flag', () => {
    expect(
      ownerConnectorActionRequiredCount({
        connector_reminders: [
          {
            code: 'rotation_overdue',
            system: 'mailchimp',
            vertical_id: 'communications',
            severity: 'overdue',
          },
          {
            code: 'upload_approaching',
            system: 'paylocity',
            vertical_id: 'people_hr',
            severity: 'approaching',
          },
        ],
        needs_connector_setup: true,
      }),
    ).toBe(2)
  })

  test('does not double-count wizard_incomplete when setup is also flagged', () => {
    expect(
      ownerConnectorActionRequiredCount({
        connector_reminders: [
          {
            code: 'wizard_incomplete',
            system: 'mailchimp',
            vertical_id: 'communications',
            severity: 'overdue',
          },
        ],
        needs_connector_setup: true,
      }),
    ).toBe(1)
  })
})

describe('overlay connector callout (U19 / AE32)', () => {
  test('data_owner stale upload → Needs refresh + Connectors CTA', () => {
    const callout = resolveOverlayConnectorCallout({
      role: 'data_owner',
      assignedVerticals: ['communications'],
      reminders: [
        {
          code: 'upload_stale',
          system: 'mailchimp',
          vertical_id: 'communications',
          severity: 'overdue',
        },
      ],
    })
    expect(callout?.title).toBe('Needs refresh')
    expect(callout?.title).not.toBe('Connected')
    expect(callout?.showCta).toBe(true)
    expect(callout?.verticalId).toBe('communications')
    expect(callout?.description).toBe(OVERLAY_LIVE_DOWN_COPY)
    expect(callout?.description.toLowerCase()).not.toContain('invite')
    expect(ownerConnectorsSearch(callout?.verticalId)).toEqual({
      vertical: 'communications',
    })
  })

  test('data_owner Live rotation overdue → Action required + CTA', () => {
    const callout = resolveOverlayConnectorCallout({
      role: 'data_owner',
      assignedVerticals: ['people_hr'],
      reminders: [
        {
          code: 'rotation_overdue',
          system: 'lever',
          vertical_id: 'people_hr',
          severity: 'overdue',
        },
      ],
    })
    expect(callout?.title).toBe('Action required')
    expect(callout?.showCta).toBe(true)
    expect(callout?.verticalId).toBe('people_hr')
  })

  test('Data vertical is view-only — no upload CTA', () => {
    const callout = resolveOverlayConnectorCallout({
      role: 'data_owner',
      assignedVerticals: ['data'],
      reminders: [
        {
          code: 'wizard_incomplete',
          system: 'cassandra',
          vertical_id: 'data',
          severity: 'overdue',
        },
      ],
    })
    expect(callout?.title).toBe('Action required')
    expect(callout?.showCta).toBe(false)
    expect(overlayCalloutShowsOwnerCta('data_owner', 'data')).toBe(false)
  })

  test('legal/admin see informational callout without Connectors CTA', () => {
    const callout = resolveOverlayConnectorCallout({
      role: 'legal',
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
            display_status: 'action_required',
            system: 'mailchimp',
            vertical_id: 'communications',
          },
        },
      ],
    })
    expect(callout?.title).toBe('Action required')
    expect(callout?.showCta).toBe(false)
    expect(overlayCalloutShowsOwnerCta('legal', 'communications')).toBe(false)
    expect(overlayCalloutShowsOwnerCta('admin', 'communications')).toBe(false)
  })

  test('super_admin simulating data_owner gets CTA', () => {
    expect(overlayCalloutShowsOwnerCta('data_owner', 'communications')).toBe(true)
  })

  test('Live test / not permissioned error codes → Action required', () => {
    const callout = resolveOverlayConnectorCallout({
      role: 'data_owner',
      assignedVerticals: ['people_hr'],
      attempts: [
        {
          id: 1,
          attempt_number: 1,
          status: 'submit_error',
          attempted_at: null,
          completed_at: null,
          error_code: 'lever_forbidden',
          audit_payload: { vertical_id: 'people_hr', system: 'lever' },
        },
      ],
    })
    expect(callout?.title).toBe('Action required')
    expect(callout?.showCta).toBe(true)
    expect(callout?.verticalId).toBe('people_hr')
  })

  test('approaching reminder alone does not show callout', () => {
    expect(
      resolveOverlayConnectorCallout({
        role: 'data_owner',
        assignedVerticals: ['communications'],
        reminders: [
          {
            code: 'upload_approaching',
            system: 'mailchimp',
            vertical_id: 'communications',
            severity: 'approaching',
          },
        ],
      }),
    ).toBeNull()
  })

  test('data_owner assigned to SaaS does not get Data-cluster callout', () => {
    expect(
      resolveOverlayConnectorCallout({
        role: 'data_owner',
        assignedVerticals: ['communications'],
        attempts: [
          {
            id: 1,
            attempt_number: 1,
            status: 'gate_blocked',
            attempted_at: null,
            completed_at: null,
            error_code: 'gate_blocked',
            audit_payload: {
              event: 'gate_blocked',
              system: 'cassandra',
              vertical_id: 'data',
            },
          },
        ],
      }),
    ).toBeNull()
  })

  test('ownerConnectorsSearch omits vertical when unknown', () => {
    expect(ownerConnectorsSearch(null)).toEqual({})
    expect(ownerConnectorsSearch('  ')).toEqual({})
  })

  test('cassandra catalog id has no owner Connectors CTA', () => {
    expect(overlayCalloutShowsOwnerCta('data_owner', 'cassandra')).toBe(false)
    expect(overlayCalloutShowsOwnerCta('data_owner', 'data')).toBe(false)
  })
})

describe('owner Home helpers (R62)', () => {
  test('prefers catalog labels over raw vertical ids', () => {
    expect(
      ownerAssignedVerticalSummary(
        [{ vertical_id: 'communications', display_label: 'Communications' }],
        ['communications', 'data'],
      ),
    ).toBe('Communications')
    expect(ownerAssignedVerticalSummary(undefined, ['people_hr'])).toBe('people hr')
    expect(ownerAssignedVerticalSummary([], [])).toBe('No vertical assigned')
  })

  test('queue titles use owner match language and newest first', () => {
    expect(ownerHomeItemTitle({ match_type: 'single_match' }, 'matching')).toBe(
      'Confirm match',
    )
    expect(ownerHomeItemTitle({ match_type: 'not_found' }, 'matching')).toBe('Not a match')
    expect(ownerHomeItemTitle({ match_type: 'single_match' }, 'fulfillment')).toBe(
      'Fulfillment',
    )
    const rows = ownerHomeQueueRows({
      matching: [
        {
          request_id: 'older-match',
          reason: 'matching.review',
          current_stage: 'review',
          intake_source: 'drop',
          received_at: '2026-08-01T00:00:00Z',
          requested_at: '2026-08-01T00:00:00Z',
          match_type: 'multi_match',
          vertical: 'communications',
          vertical_label: 'Communications',
        },
      ],
      fulfillment: [
        {
          request_id: 'newer-fulfill',
          reason: 'fulfillment.owner',
          current_stage: 'fulfillment',
          intake_source: 'drop',
          received_at: '2026-08-10T00:00:00Z',
          requested_at: '2026-08-10T00:00:00Z',
          vertical: 'people_hr',
          vertical_label: 'People / HR',
        },
      ],
      limit: 8,
    })
    expect(rows.map((row) => row.requestId)).toEqual(['newer-fulfill', 'older-match'])
    expect(rows[0]?.title).toBe('Fulfillment')
    expect(rows[0]?.verticalLabel).toBe('People / HR')
    expect(rows[1]?.title).toBe('Multi-person')
    expect(rows[1]?.vertical).toBe('communications')
    expect(rows[1]?.verticalLabel).toBe('Communications')
  })
})
