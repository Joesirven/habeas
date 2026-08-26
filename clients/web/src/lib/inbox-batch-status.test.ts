// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { ConnectorReminder, NeedsAttentionItem } from './api'
import {
  buildInboxBatchStatusCrossGroups,
  buildInboxGroupingStacks,
  bulkProcessCollapsedCounts,
  bulkProcessCollapsedPercent,
  bulkProcessCollapsedStatus,
  bulkProcessCollapsedTitle,
  bulkProcessSourceLabel,
  groupInboxByBatchStatusStep,
  groupInboxConnectorNotifications,
  groupInboxItemsByBatchStatus,
  groupInboxItemsByDateSource,
  groupInboxItemsBySystem,
  inboxBatchId,
  inboxBatchStatusKey,
  inboxBatchStatusLabel,
  inboxBatchStatusStackSubtitle,
  inboxBatchStep,
  inboxBatchLabel,
  inboxDateSourceKey,
  inboxDateSourceLabel,
  inboxDateSourceParts,
  inboxIntakeSourceLabel,
  inboxItemConnectorBlock,
  inboxItemStepKey,
  inboxItemSystemId,
  inboxPendingWorkBatchKey,
  inboxPendingWorkUnitCount,
  inboxStandaloneResultKey,
  inboxWorkStatusKey,
  stackRequestIds,
} from './inbox-batch-status'

/** Midday UTC so local calendar day stays Aug 21 across US timezones. */
const AUG_21 = '2026-08-21T16:00:00.000Z'
const AUG_22 = '2026-08-22T16:00:00.000Z'

function matchingItem(
  overrides: Partial<NeedsAttentionItem> = {},
): NeedsAttentionItem {
  return {
    request_id: '11111111-1111-1111-1111-111111111111',
    reason: 'matching.review',
    kind: 'matching',
    current_stage: 'review',
    intake_source: 'drop',
    received_at: AUG_21,
    requested_at: AUG_21,
    match_type: 'single_match',
    match_count: 1,
    ...overrides,
  }
}

function localDateParts(iso: string): { key: string; label: string } {
  const date = new Date(iso)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return {
    key: `${year}-${month}-${day}`,
    label: date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
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

describe('inboxBatchStep', () => {
  test('fulfillment stage wins over matching fields', () => {
    expect(
      inboxBatchStep(
        matchingItem({
          current_stage: 'fulfillment',
          reason: 'fulfillment.owner',
        }),
      ),
    ).toBe('fulfillment')
    expect(inboxBatchStep(matchingItem())).toBe('matching')
  })
})

describe('groupInboxByBatchStatusStep', () => {
  test('same batch with different match status yields two stacks', () => {
    const groups = groupInboxByBatchStatusStep([
      matchingItem({
        request_id: 'a',
        match_type: 'single_match',
        bulk_process_id: 42,
      }),
      matchingItem({
        request_id: 'b',
        match_type: 'multi_match',
        match_count: 2,
        bulk_process_id: 42,
      }),
    ])
    expect(groups).toHaveLength(2)
    expect(groups.map((group) => group.key)).toEqual([
      { batchId: 'p:42', matchStatus: 'single_match', step: 'matching' },
      { batchId: 'p:42', matchStatus: 'multi_match', step: 'matching' },
    ])
    expect(groups[0]?.compositeKey).toBe('p:42::single_match::matching')
    expect(groups[1]?.compositeKey).toBe('p:42::multi_match::matching')
  })

  test('same batch and status but matching vs fulfillment yields two stacks', () => {
    const groups = groupInboxByBatchStatusStep([
      matchingItem({
        request_id: 'a',
        match_type: 'single_match',
        bulk_process_id: 7,
        current_stage: 'review',
        reason: 'matching.review',
        kind: 'matching',
      }),
      matchingItem({
        request_id: 'b',
        match_type: 'single_match',
        bulk_process_id: 7,
        current_stage: 'fulfillment',
        reason: 'fulfillment.owner',
        kind: 'matching',
      }),
    ])
    expect(groups).toHaveLength(2)
    expect(groups.map((group) => group.key)).toEqual([
      { batchId: 'p:7', matchStatus: 'single_match', step: 'matching' },
      { batchId: 'p:7', matchStatus: 'single_match', step: 'fulfillment' },
    ])
    expect(inboxBatchId(groups[0]!.items[0]!)).toBe('p:7')
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

describe('stackRequestIds', () => {
  const first = '11111111-1111-4111-8111-111111111111'
  const second = '22222222-2222-4222-8222-222222222222'

  test('returns all member UUIDs, never the stack composite key', () => {
    expect(
      stackRequestIds([
        matchingItem({ request_id: first }),
        matchingItem({ request_id: second }),
        matchingItem({ request_id: 'p:42::single_match::matching' }),
      ]),
    ).toEqual([first, second])
  })

  test('drops batch keys, sentinels, and duplicates', () => {
    expect(
      stackRequestIds([
        matchingItem({ request_id: first }),
        matchingItem({ request_id: 'p:42' }),
        matchingItem({ request_id: first }),
        matchingItem({ request_id: 'undefined' }),
      ]),
    ).toEqual([first])
  })

  test('empty stack yields no ids', () => {
    expect(stackRequestIds([])).toEqual([])
  })
})

describe('inboxDateSourceKey / inboxDateSourceLabel', () => {
  test('maps intake sources to human names on the local calendar day', () => {
    const { key: dateKey, label: dateLabel } = localDateParts(AUG_21)
    expect(inboxIntakeSourceLabel('drop')).toBe('CA DROP')
    expect(inboxIntakeSourceLabel('webform')).toBe('Gravity Forms')
    expect(inboxIntakeSourceLabel('csv')).toBe('Authorized Agent')
    expect(inboxIntakeSourceLabel('manual')).toBe('Manual')

    expect(inboxDateSourceKey(matchingItem({ intake_source: 'drop' }))).toBe(
      `${dateKey}::drop`,
    )
    expect(inboxDateSourceLabel(matchingItem({ intake_source: 'drop' }))).toBe(
      `${dateLabel} · CA DROP`,
    )
    expect(inboxDateSourceLabel(matchingItem({ intake_source: 'webform' }))).toBe(
      `${dateLabel} · Gravity Forms`,
    )
    expect(inboxDateSourceLabel(matchingItem({ intake_source: 'csv' }))).toBe(
      `${dateLabel} · Authorized Agent`,
    )
    expect(inboxDateSourceLabel(matchingItem({ intake_source: 'manual' }))).toBe(
      `${dateLabel} · Manual`,
    )
    expect(inboxBatchLabel(matchingItem({ intake_source: 'drop' }))).toBe(
      inboxDateSourceLabel(matchingItem({ intake_source: 'drop' })),
    )
  })

  test('falls back to received_at when requested_at is missing', () => {
    const { key: dateKey, label: dateLabel } = localDateParts(AUG_22)
    const item = matchingItem({
      requested_at: null,
      received_at: AUG_22,
      intake_source: 'drop',
    })
    expect(inboxDateSourceKey(item)).toBe(`${dateKey}::drop`)
    expect(inboxDateSourceLabel(item)).toBe(`${dateLabel} · CA DROP`)
  })

  test('default parts are date+source, never #42 or batch', () => {
    const parts = inboxDateSourceParts(
      matchingItem({ bulk_process_id: 42, source_csv_filename: 'batch.csv' }),
    )
    expect(parts.label).toBe(inboxDateSourceLabel(matchingItem()))
    expect(parts.label).not.toMatch(/#42/)
    expect(parts.label.toLowerCase()).not.toBe('batch')
    expect(parts.key).not.toBe(inboxBatchId(matchingItem({ bulk_process_id: 42 })))
  })
})

describe('groupInboxItemsByDateSource', () => {
  test('keeps phone and email on the same date+source stack', () => {
    const groups = groupInboxItemsByDateSource([
      matchingItem({
        request_id: 'aaaa',
        match_type: 'single_match',
        matched_via: 'email',
        bulk_process_id: 1,
      }),
      matchingItem({
        request_id: 'bbbb',
        match_type: 'multi_match',
        match_count: 2,
        matched_via: 'phone',
        bulk_process_id: 2,
      }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]?.key).toBe(inboxDateSourceKey(matchingItem()))
    expect(groups[0]?.label).toBe(inboxDateSourceLabel(matchingItem()))
    expect(groups[0]?.items).toHaveLength(2)
  })

  test('splits only when the local date or intake source differs', () => {
    const groups = groupInboxItemsByDateSource([
      matchingItem({ request_id: 'a', intake_source: 'drop', requested_at: AUG_21 }),
      matchingItem({ request_id: 'b', intake_source: 'webform', requested_at: AUG_21 }),
      matchingItem({ request_id: 'c', intake_source: 'drop', requested_at: AUG_22 }),
    ])
    expect(groups).toHaveLength(3)
    expect(groups.map((group) => group.label)).toEqual([
      inboxDateSourceLabel(matchingItem({ intake_source: 'drop', requested_at: AUG_21 })),
      inboxDateSourceLabel(
        matchingItem({ intake_source: 'webform', requested_at: AUG_21 }),
      ),
      inboxDateSourceLabel(matchingItem({ intake_source: 'drop', requested_at: AUG_22 })),
    ])
  })
})

describe('groupInboxItemsBySystem', () => {
  test('groups by system then system_id, not work type or match type', () => {
    const groups = groupInboxItemsBySystem([
      matchingItem({
        request_id: 'a',
        system: 'mailchimp',
        system_label: 'Mailchimp',
        match_type: 'single_match',
        kind: 'matching',
      }),
      matchingItem({
        request_id: 'b',
        system_id: 'mailchimp',
        match_type: 'not_found',
        kind: 'notice',
      }),
      matchingItem({
        request_id: 'c',
        system: 'lever',
        system_label: 'Lever',
      }),
    ])
    expect(inboxItemSystemId({ system: 'lever', system_id: 'ignored' })).toBe('lever')
    expect(inboxItemSystemId({ system_id: 'salesforce' })).toBe('salesforce')
    expect(groups).toHaveLength(2)
    const mailchimp = groups.find((group) => group.key === 'mailchimp')
    const lever = groups.find((group) => group.key === 'lever')
    expect(mailchimp?.items).toHaveLength(2)
    expect(mailchimp?.label).toBe('Mailchimp')
    expect(lever?.label).toBe('Lever')
    expect(mailchimp?.label).not.toBe(inboxIntakeSourceLabel('drop'))
    expect(lever?.label).not.toBe(inboxIntakeSourceLabel('drop'))
  })

  test('test vertical system stacks use System A / System B, not CA DROP', () => {
    const groups = groupInboxItemsBySystem([
      matchingItem({
        vertical: 'test',
        system: 'cassandra',
        system_label: 'CA DROP',
      }),
      matchingItem({
        request_id: '22222222-2222-4222-8222-222222222222',
        vertical: 'test',
        system: 'hr_alumni',
        system_label: 'Alumni Google Sheet',
      }),
    ])
    expect(groups.map((group) => group.label)).toEqual(['System A', 'System B'])
    expect(groups.map((group) => group.label)).not.toContain('CA DROP')
  })
})

describe('inboxItemStepKey', () => {
  test('maps current_stage onto ingest, matching, fulfillment, or notice', () => {
    expect(inboxItemStepKey(matchingItem({ current_stage: 'received' }))).toBe('ingest')
    expect(inboxItemStepKey(matchingItem({ current_stage: 'download' }))).toBe('ingest')
    expect(inboxItemStepKey(matchingItem({ current_stage: 'review' }))).toBe('matching')
    expect(inboxItemStepKey(matchingItem({ current_stage: 'matching' }))).toBe('matching')
    expect(inboxItemStepKey(matchingItem({ current_stage: 'fulfill' }))).toBe('fulfillment')
    expect(inboxItemStepKey(matchingItem({ current_stage: 'fulfillment' }))).toBe(
      'fulfillment',
    )
    expect(inboxItemStepKey(matchingItem({ current_stage: 'notice' }))).toBe('notice')
    expect(inboxItemStepKey(matchingItem({ current_stage: 'delivery' }))).toBe('notice')
    expect(inboxItemStepKey(matchingItem({ current_stage: '' }))).toBe('ingest')
  })
})

describe('buildInboxGroupingStacks', () => {
  test('defaults to date+source stacks', () => {
    const groups = buildInboxGroupingStacks([
      matchingItem({ request_id: 'a', bulk_process_id: 42, match_type: 'single_match' }),
      matchingItem({
        request_id: 'b',
        bulk_process_id: 99,
        match_type: 'not_found',
        matched_via: 'phone',
      }),
    ])
    expect(groups).toHaveLength(1)
    expect(groups[0]?.label).toBe(inboxDateSourceLabel(matchingItem()))
    expect(groups[0]?.label).not.toMatch(/#\d+|batch thread|batch stack/i)
  })

  test('optional system stacks ignore match type', () => {
    const groups = buildInboxGroupingStacks(
      [
        matchingItem({ request_id: 'a', system: 'mailchimp', match_type: 'single_match' }),
        matchingItem({ request_id: 'b', system: 'mailchimp', match_type: 'multi_match' }),
      ],
      { bySystem: true },
    )
    expect(groups).toHaveLength(1)
    expect(groups[0]?.key).toBe('mailchimp')
  })

  test('optional status stacks stay available without becoming row identity', () => {
    const groups = buildInboxGroupingStacks(
      [
        matchingItem({ request_id: 'a', match_type: 'single_match' }),
        matchingItem({ request_id: 'b', match_type: 'multi_match' }),
      ],
      { byStatus: true },
    )
    expect(groups.map((group) => group.key)).toEqual(['single_match', 'multi_match'])
    expect(groups[0]?.label).toBe('Single match')
  })

  test('Batch + Status is SQL GROUP BY — 2 batches × 4 statuses = 8 stacks', () => {
    const statuses = [
      'single_match',
      'multi_match',
      'not_found',
      'unknown',
    ] as const
    const items = [7, 9].flatMap((processId) =>
      statuses.map((matchType, index) =>
        matchingItem({
          request_id: `${processId}-${index}`,
          bulk_process_id: processId,
          match_type: matchType,
          requested_at: processId === 7 ? AUG_21 : AUG_22,
          received_at: processId === 7 ? AUG_21 : AUG_22,
        }),
      ),
    )
    const groups = buildInboxGroupingStacks(items, {
      byDateSource: true,
      byStatus: true,
    })
    expect(groups).toHaveLength(8)
    const keys = new Set(groups.map((group) => group.key))
    expect(keys.size).toBe(8)
    expect(groups.every((group) => group.items.length === 1)).toBe(true)
    expect(groups.some((group) => /CA DROP/.test(group.label))).toBe(true)
    expect(groups.some((group) => /Single match/.test(group.label))).toBe(true)
  })

  test('Batch + System + Status is one stack per unique combination', () => {
    const groups = buildInboxGroupingStacks(
      [
        matchingItem({
          request_id: 'a',
          bulk_process_id: 1,
          system: 'mailchimp',
          system_label: 'Mailchimp',
          match_type: 'single_match',
        }),
        matchingItem({
          request_id: 'b',
          bulk_process_id: 1,
          system: 'mailchimp',
          system_label: 'Mailchimp',
          match_type: 'not_found',
        }),
        matchingItem({
          request_id: 'c',
          bulk_process_id: 1,
          system: 'lever',
          system_label: 'Lever',
          match_type: 'single_match',
        }),
      ],
      { byDateSource: true, bySystem: true, byStatus: true },
    )
    expect(groups).toHaveLength(3)
    expect(groups.map((group) => group.items.length)).toEqual([1, 1, 1])
  })

  test('Status grouping uses Needs connection when a wizard reminder matches', () => {
    const groups = buildInboxGroupingStacks(
      [
        matchingItem({
          request_id: 'a',
          system: 'mailchimp',
          system_label: 'Mailchimp',
          vertical: 'communications',
          match_type: 'single_match',
        }),
        matchingItem({
          request_id: 'b',
          system: 'lever',
          system_label: 'Lever',
          vertical: 'people_hr',
          match_type: 'single_match',
        }),
      ],
      {
        byStatus: true,
        reminders: [
          {
            code: 'wizard_incomplete',
            system: 'mailchimp',
            vertical_id: 'communications',
            severity: 'overdue',
          },
        ],
      },
    )
    expect(groups.map((group) => group.key)).toEqual([
      'needs_connection',
      'single_match',
    ])
    expect(groups[0]?.label).toBe('Needs connection')
  })
})

describe('inboxPendingWorkUnitCount', () => {
  test('one dated DROP batch is one work unit when status is the same', () => {
    expect(
      inboxPendingWorkUnitCount([
        matchingItem({
          request_id: '11111111-1111-4111-8111-111111111111',
          matched_via: 'email',
          bulk_process_id: 7,
        }),
        matchingItem({
          request_id: '22222222-2222-4222-8222-222222222222',
          matched_via: 'phone',
          bulk_process_id: 7,
        }),
      ]),
    ).toBe(1)
  })

  test('2 batches × 4 statuses = 8 work units, not 2 batches and not 8 people', () => {
    const statuses = [
      'single_match',
      'multi_match',
      'not_found',
      'unknown',
    ] as const
    const items = [7, 9].flatMap((processId) =>
      statuses.flatMap((matchType, index) => [
        matchingItem({
          request_id: `${processId}-a-${index}`,
          bulk_process_id: processId,
          match_type: matchType,
        }),
        matchingItem({
          request_id: `${processId}-b-${index}`,
          bulk_process_id: processId,
          match_type: matchType,
          matched_via: 'phone',
        }),
      ]),
    )
    expect(items).toHaveLength(16)
    expect(inboxPendingWorkUnitCount(items)).toBe(8)
  })

  test('same batch with four dispositions is four units', () => {
    expect(
      inboxPendingWorkUnitCount([
        matchingItem({
          request_id: 'a',
          bulk_process_id: 7,
          match_type: 'single_match',
        }),
        matchingItem({
          request_id: 'b',
          bulk_process_id: 7,
          match_type: 'multi_match',
        }),
        matchingItem({
          request_id: 'c',
          bulk_process_id: 7,
          match_type: 'not_found',
        }),
        matchingItem({
          request_id: 'd',
          bulk_process_id: 7,
          response_status: 3,
        }),
      ]),
    ).toBe(4)
  })

  test('distinct batches plus unbatched results', () => {
    const batched = matchingItem({
      request_id: '11111111-1111-4111-8111-111111111111',
      bulk_process_id: 9,
    })
    const standaloneA = matchingItem({
      request_id: '22222222-2222-4222-8222-222222222222',
      intake_source: 'webform',
      requested_at: null,
      received_at: null,
      bulk_process_id: null,
      source_csv_filename: null,
      vertical: 'test',
      system: 'cassandra',
    })
    const standaloneB = matchingItem({
      request_id: '22222222-2222-4222-8222-222222222222',
      intake_source: 'webform',
      requested_at: null,
      received_at: null,
      bulk_process_id: null,
      source_csv_filename: null,
      vertical: 'test',
      system: 'hr_alumni',
    })
    expect(inboxPendingWorkBatchKey(batched)).toBe('p:9')
    expect(inboxPendingWorkBatchKey(standaloneA)).toBeNull()
    expect(inboxStandaloneResultKey(standaloneA)).toBe(
      '22222222-2222-4222-8222-222222222222::cassandra',
    )
    expect(inboxStandaloneResultKey(standaloneB)).toBe(
      '22222222-2222-4222-8222-222222222222::hr_alumni',
    )
    expect(inboxPendingWorkUnitCount([batched, standaloneA, standaloneB])).toBe(3)
  })

  test('needs connection in one batch is a separate unit from matching disposition', () => {
    const connected = matchingItem({
      request_id: '11111111-1111-4111-8111-111111111111',
      bulk_process_id: 7,
      vertical: 'communications',
      system: 'mailchimp',
      system_label: 'Mailchimp',
      match_type: 'single_match',
    })
    const blocked = matchingItem({
      request_id: '22222222-2222-4222-8222-222222222222',
      bulk_process_id: 7,
      vertical: 'people_hr',
      system: 'hr_alumni',
      system_label: 'Alumni Google Sheet',
      match_type: 'single_match',
    })
    const reminders = [
      {
        code: 'wizard_incomplete',
        system: 'hr_alumni',
        vertical_id: 'people_hr',
        severity: 'overdue',
      },
    ]
    expect(inboxWorkStatusKey(connected, { reminders })).toBe('single_match')
    expect(inboxWorkStatusKey(blocked, { reminders })).toBe('needs_connection')
    expect(inboxPendingWorkUnitCount([connected, blocked], { reminders })).toBe(2)
  })

  test('date+source groups items without process id into one batch', () => {
    expect(
      inboxPendingWorkUnitCount([
        matchingItem({
          request_id: '11111111-1111-4111-8111-111111111111',
          bulk_process_id: null,
        }),
        matchingItem({
          request_id: '22222222-2222-4222-8222-222222222222',
          bulk_process_id: null,
        }),
      ]),
    ).toBe(1)
  })
})

describe('inboxItemConnectorBlock', () => {
  test('maps stale upload reminder to Needs refresh', () => {
    const item = matchingItem({
      vertical: 'communications',
      system: 'mailchimp',
      system_label: 'Mailchimp',
    })
    expect(
      inboxItemConnectorBlock(item, {
        reminders: [
          {
            code: 'upload_stale',
            system: 'mailchimp',
            vertical_id: 'communications',
            severity: 'overdue',
          },
        ],
      }),
    ).toEqual({ kind: 'needs_refresh', label: 'Needs refresh' })
  })

  test('maps wizard incomplete and stubs to Needs connection', () => {
    const item = matchingItem({
      vertical: 'people_hr',
      system: 'hr_alumni',
      system_label: 'Alumni Google Sheet',
    })
    expect(
      inboxItemConnectorBlock(item, {
        reminders: [
          {
            code: 'wizard_incomplete',
            system: 'hr_alumni',
            vertical_id: 'people_hr',
            severity: 'overdue',
          },
        ],
      }),
    ).toEqual({ kind: 'needs_connection', label: 'Needs connection' })
    expect(
      inboxItemConnectorBlock(item, {
        matchingDetail: { result_kind: 'sheet_stub' },
      }),
    ).toEqual({ kind: 'needs_connection', label: 'Needs connection' })
    expect(
      inboxItemConnectorBlock(item, {
        matchingDetail: { result_kind: 'saas_stub' },
      }),
    ).toEqual({ kind: 'needs_connection', label: 'Needs connection' })
  })

  test('work status prefers Needs refresh over match type', () => {
    const item = matchingItem({
      vertical: 'communications',
      system: 'mailchimp',
      system_label: 'Mailchimp',
      match_type: 'single_match',
    })
    expect(
      inboxWorkStatusKey(item, {
        reminders: [
          {
            code: 'upload_stale',
            system: 'mailchimp',
            vertical_id: 'communications',
            severity: 'overdue',
          },
        ],
      }),
    ).toBe('needs_refresh')
    expect(inboxWorkStatusKey(item)).toBe('single_match')
  })

  test('never treats CA DROP source as a connectable system', () => {
    expect(
      inboxItemConnectorBlock(
        matchingItem({
          vertical: 'data',
          system: 'cassandra',
          system_label: 'CA DROP',
        }),
        { matchingDetail: { result_kind: 'sheet_stub' } },
      ),
    ).toBeNull()
  })

  test('test vertical still gates System A without showing cassandra', () => {
    const block = inboxItemConnectorBlock(
      matchingItem({
        vertical: 'test',
        system: 'cassandra',
        system_label: 'CA DROP',
      }),
      {
        reminders: [
          {
            code: 'wizard_incomplete',
            system: 'cassandra',
            vertical_id: 'test',
            severity: 'overdue',
          },
        ],
      },
    )
    expect(block).toEqual({ kind: 'needs_connection', label: 'Needs connection' })
    expect(JSON.stringify(block)).not.toMatch(/cassandra/i)
  })
})

describe('collapsed bulk-process row (lite snapshot)', () => {
  test('bulkProcessSourceLabel maps drop to CA DROP — a source, not a system', () => {
    expect(bulkProcessSourceLabel('drop')).toBe('CA DROP')
    expect(bulkProcessSourceLabel('drop')).toBe(inboxIntakeSourceLabel('drop'))
    expect(bulkProcessSourceLabel('drop')).not.toBe('cassandra')
    expect(bulkProcessSourceLabel('drop')).not.toBe('drop')
  })

  test('title with process_at + intake_source drop includes a date and CA DROP', () => {
    const { label: dateLabel } = localDateParts(AUG_21)
    const title = bulkProcessCollapsedTitle({
      process_at: AUG_21,
      intake_source: 'drop',
    })
    expect(title).toContain(dateLabel)
    expect(title).toContain('CA DROP')
    expect(title).not.toBe('')
    expect(title).not.toBe('—')
  })

  test('title with only label uses the label and is never empty', () => {
    const title = bulkProcessCollapsedTitle({ label: 'Nightly intake' })
    expect(title).toBe('Nightly intake')
    expect(title).not.toBe('')
    expect(title.trim().length).toBeGreaterThan(0)
  })

  test('title with nothing useful is an em dash, not an empty string', () => {
    expect(bulkProcessCollapsedTitle({})).toBe('—')
    expect(
      bulkProcessCollapsedTitle({
        process_at: null,
        intake_source: '',
        label: '',
      }),
    ).toBe('—')
    expect(bulkProcessCollapsedTitle({})).not.toBe('')
  })

  test('counts include request_rows and req; missing request_rows is null', () => {
    const counts = bulkProcessCollapsedCounts({ request_rows: 12 })
    expect(counts).toContain('12')
    expect(counts).toMatch(/req/i)
    expect(bulkProcessCollapsedCounts({})).toBeNull()
    expect(bulkProcessCollapsedCounts({ request_rows: undefined })).toBeNull()
  })

  test('status prefers overall.status, then download_status, else em dash', () => {
    expect(
      bulkProcessCollapsedStatus({
        overall: { status: 'needs_attention', percent: 10, current_stage: 'review' },
      }),
    ).toBe('needs attention')
    expect(bulkProcessCollapsedStatus({ download_status: 'in_flight' })).toMatch(
      /in[_\s]flight/,
    )
    expect(bulkProcessCollapsedStatus({})).toBe('—')
    expect(
      bulkProcessCollapsedStatus({
        overall: { status: '', percent: 0, current_stage: 'download' },
        download_status: '',
      }),
    ).toBe('—')
  })

  test('percent comes from overall.percent; missing is null', () => {
    const percent = bulkProcessCollapsedPercent({
      overall: { percent: 47, current_stage: 'matching', status: 'in_progress' },
    })
    expect(percent).not.toBeNull()
    expect(String(percent)).toMatch(/47/)
    expect(bulkProcessCollapsedPercent({})).toBeNull()
    expect(bulkProcessCollapsedPercent({ overall: undefined })).toBeNull()
  })

  test('CA DROP is the source label for intake drop only — never a connection name', () => {
    expect(bulkProcessSourceLabel('drop')).toBe('CA DROP')
    expect(bulkProcessSourceLabel('webform')).not.toBe('CA DROP')
    expect(bulkProcessSourceLabel('csv')).not.toBe('CA DROP')
    expect(bulkProcessSourceLabel('manual')).not.toBe('CA DROP')
    expect(bulkProcessSourceLabel('mailchimp')).not.toBe('CA DROP')
    expect(bulkProcessSourceLabel('cassandra')).not.toBe('CA DROP')
    expect(bulkProcessSourceLabel('axios_hq')).not.toBe('CA DROP')
    const titled = bulkProcessCollapsedTitle({
      process_at: AUG_21,
      intake_source: 'drop',
      label: 'Auth0',
    })
    expect(titled).toContain('CA DROP')
    expect(bulkProcessSourceLabel('drop')).toBe(inboxIntakeSourceLabel('drop'))
  })
})
