// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  mergeOwnerFulfillmentItems,
  ownerFulfillmentItemFromApproval,
  ownerFulfillmentItemFromRequest,
  type NeedsAttentionItem,
} from '../../lib/api'
import {
  DATA_OWNER_INBOX_KIND_TABS,
  dropStatusPill,
  isAutomaticFulfillmentVertical,
  isOwnerFulfillmentItem,
  matchTypeLabel,
  ownerMatchResultLabel,
  suggestedBulkFulfillStatus,
} from './needs-attention'

function matchingItem(
  overrides: Partial<NeedsAttentionItem> = {},
): NeedsAttentionItem {
  return {
    request_id: '11111111-1111-1111-1111-111111111111',
    reason: 'matching.review',
    kind: 'matching',
    current_stage: 'review',
    intake_source: 'drop',
    received_at: '2026-08-01T00:00:00Z',
    requested_at: '2026-08-01T00:00:00Z',
    match_type: 'single_match',
    match_count: 1,
    ...overrides,
  }
}

describe('DATA_OWNER_INBOX_KIND_TABS (R61)', () => {
  test('tabs are Matching · Fulfillment · Tasks', () => {
    expect(DATA_OWNER_INBOX_KIND_TABS.map((tab) => tab.value)).toEqual([
      'matching',
      'fulfillment',
      'pending_tasks',
    ])
    expect(DATA_OWNER_INBOX_KIND_TABS.map((tab) => tab.label)).toEqual([
      'Matching',
      'Fulfillment',
      'Tasks',
    ])
  })
})

describe('owner fulfillment row helpers (AE30)', () => {
  test('kicked-off fulfillment is owner work; matching.review is not', () => {
    expect(
      isOwnerFulfillmentItem(
        matchingItem({
          reason: 'fulfillment.kickoff',
          current_stage: 'fulfillment',
          kind: undefined,
          match_type: null,
        }),
      ),
    ).toBe(true)
    expect(isOwnerFulfillmentItem(matchingItem())).toBe(false)
  })

  test('Data / Cassandra are automatic; SaaS catalog ids are not', () => {
    expect(isAutomaticFulfillmentVertical('data')).toBe(true)
    expect(isAutomaticFulfillmentVertical('cassandra')).toBe(true)
    expect(isAutomaticFulfillmentVertical('communications')).toBe(false)
    expect(isAutomaticFulfillmentVertical('mailchimp')).toBe(false)
  })

  test('merge prefers request metadata when an approval also matched', () => {
    const fromApproval = ownerFulfillmentItemFromApproval({
      id: 9,
      request_id: 'aaaaaaa1-1111-1111-1111-111111111111',
      action_type: 'fulfillment.kickoff',
      status: 'approved',
    })
    const fromRequest = ownerFulfillmentItemFromRequest({
      id: 'aaaaaaa1-1111-1111-1111-111111111111',
      received_at: '2026-08-02T00:00:00Z',
      intake_source: 'webform',
      raw_record_id: null,
      requestor_state: 'CA',
    })
    const merged = mergeOwnerFulfillmentItems([fromRequest], [fromApproval])
    expect(merged).toHaveLength(1)
    expect(merged[0].intake_source).toBe('webform')
    expect(merged[0].requestor_state).toBe('CA')
    expect(merged[0].reason).toBe('fulfillment.owner')
    expect(merged[0].current_stage).toBe('fulfillment')
  })
})

describe('owner Inbox match language (KD34 leftovers)', () => {
  test('queue chips say Not a match, not Not found', () => {
    expect(matchTypeLabel('not_found', true)).toBe('Not a match')
    expect(matchTypeLabel('not_found', false)).toBe('Not found')
    expect(matchTypeLabel('single_match', true)).toBe('Confirm match')
    expect(matchTypeLabel('multi_match', true)).toBe('Multi-person')
  })

  test('owner pill does not lead with DROP status · Deleted (3)', () => {
    const pill = dropStatusPill(
      matchingItem({ recommended_response_status: 3 }),
      null,
      true,
    )
    expect(pill?.label).toBe('Match result · Confirm match')
    expect(pill?.label).not.toMatch(/DROP status/)
    expect(pill?.label).not.toMatch(/Deleted \(3\)/)
    expect(ownerMatchResultLabel(5)).toBe('Not a match')
    expect(dropStatusPill(matchingItem({ recommended_response_status: 3 }), null, false)?.label).toBe(
      'DROP status · Deleted (3)',
    )
  })

  test('bulk fulfill suggests 4 for multi, not always 3', () => {
    expect(
      suggestedBulkFulfillStatus([
        matchingItem({ match_type: 'multi_match', match_count: 3 }),
      ]),
    ).toBe(4)
    expect(
      suggestedBulkFulfillStatus([
        matchingItem({ match_type: 'single_match', match_count: 1 }),
        matchingItem({ match_type: 'multi_match', match_count: 2 }),
      ]),
    ).toBe(4)
    expect(
      suggestedBulkFulfillStatus([
        matchingItem({ match_type: 'not_found', match_count: 0 }),
      ]),
    ).toBe(5)
    expect(
      suggestedBulkFulfillStatus([
        matchingItem({ match_type: 'single_match', match_count: 1 }),
      ]),
    ).toBe(3)
  })
})
