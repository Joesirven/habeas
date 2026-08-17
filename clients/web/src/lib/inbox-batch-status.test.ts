// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { ConnectorReminder, NeedsAttentionItem } from './api'
import {
  buildInboxBatchStatusCrossGroups,
  groupInboxConnectorNotifications,
  groupInboxItemsByBatchStatus,
  inboxBatchStatusKey,
  inboxBatchStatusLabel,
  inboxBatchStatusStackSubtitle,
} from './inbox-batch-status'

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

describe('inboxBatchStatusKey', () => {
  test('maps match types to status buckets', () => {
    expect(inboxBatchStatusKey(matchingItem())).toBe('single_match')
    expect(
      inboxBatchStatusKey(matchingItem({ match_type: 'multi_match', match_count: 2 })),
    ).toBe('multi_match')
    expect(
      inboxBatchStatusKey(matchingItem({ match_type: 'not_found', match_count: 0 })),
    ).toBe('not_found')
  })

  test('prefers DROP response_status when set', () => {
    expect(
      inboxBatchStatusKey(
        matchingItem({ response_status: 4, match_type: 'single_match' }),
      ),
    ).toBe('drop_4')
    expect(
      inboxBatchStatusKey(
        matchingItem({ response_status: 5, match_type: 'multi_match' }),
      ),
    ).toBe('drop_5')
  })
})

describe('inboxBatchStatusLabel', () => {
  test('uses owner language for data-owner inbox', () => {
    expect(inboxBatchStatusLabel('not_found', true)).toBe('Not a match')
    expect(inboxBatchStatusLabel('drop_3', true)).toBe('Confirm match')
    expect(inboxBatchStatusLabel('drop_4', true)).toBe('Multi-person')
  })

  test('uses ops labels for DROP codes', () => {
    expect(inboxBatchStatusLabel('drop_3', false)).toBe('Deleted (3)')
    expect(inboxBatchStatusLabel('single_match', false)).toBe('Single match')
  })
})

describe('groupInboxItemsByBatchStatus', () => {
  test('groups and orders by status taxonomy', () => {
    const sections = groupInboxItemsByBatchStatus([
      matchingItem({ request_id: 'aaaa', match_type: 'not_found' }),
      matchingItem({ request_id: 'bbbb', match_type: 'single_match' }),
      matchingItem({ request_id: 'cccc', match_type: 'multi_match' }),
    ])
    expect(sections.map((section) => section.key)).toEqual([
      'single_match',
      'multi_match',
      'not_found',
    ])
    expect(sections[0]?.items).toHaveLength(1)
    expect(sections[0]?.label).toBe('Single match')
  })
})

describe('buildInboxBatchStatusCrossGroups', () => {
  test('cross-product splits one batch by status type', () => {
    const batchParts = () => ({ key: 'p:99', label: '#99' })
    const groups = buildInboxBatchStatusCrossGroups(
      [
        matchingItem({ request_id: 'a', match_type: 'single_match', bulk_process_id: 99 }),
        matchingItem({ request_id: 'b', match_type: 'multi_match', bulk_process_id: 99 }),
      ],
      batchParts,
    )
    expect(groups).toHaveLength(2)
    expect(groups[0]?.compositeKey).toBe('p:99::single_match')
    expect(groups[1]?.compositeKey).toBe('p:99::multi_match')
    expect(groups[0]?.statusLabel).toBe('Single match')
  })
})

describe('inboxBatchStatusStackSubtitle', () => {
  test('Exact 1:1 for homogeneous single-match stacks', () => {
    expect(
      inboxBatchStatusStackSubtitle([
        matchingItem({ match_type: 'single_match' }),
        matchingItem({ request_id: '2222', match_type: 'single_match' }),
      ]),
    ).toBe('Exact 1:1')
    expect(
      inboxBatchStatusStackSubtitle([
        matchingItem({ match_type: 'single_match' }),
        matchingItem({ request_id: '2222', match_type: 'multi_match' }),
      ]),
    ).toBeNull()
  })
})

describe('groupInboxConnectorNotifications', () => {
  test('groups reminders by code and attaches gate', () => {
    const reminders: ConnectorReminder[] = [
      {
        vertical_id: 'mailchimp',
        system: 'mailchimp',
        code: 'upload_stale',
        severity: 'overdue',
      },
      {
        vertical_id: 'salesforce',
        system: 'salesforce',
        code: 'wizard_incomplete',
        severity: 'approaching',
      },
    ]
    const groups = groupInboxConnectorNotifications({
      reminders,
      gate: {
        blocked: true,
        displayStatus: 'needs_refresh',
        gateCode: 'upload_stale',
        system: 'mailchimp',
        source: 'reminder',
      },
    })
    expect(groups.map((group) => group.key)).toEqual([
      'reminder:upload_stale',
      'reminder:wizard_incomplete',
    ])
    expect(groups[0]?.gate?.gateCode).toBe('upload_stale')
    expect(groups[0]?.reminders).toHaveLength(1)
  })
})
