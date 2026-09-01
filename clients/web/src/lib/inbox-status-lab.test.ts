// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { afterEach, describe, expect, spyOn, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

import { MatchingResultsMethodToolbar } from '../components/inbox-status-lab/StatusLabToolbar'
import {
  MATCHING_RESULT_LAB_METHODS,
  MATCHING_RESULT_LAB_METHOD_STORAGE_KEY,
  readMatchingResultLabMethod,
  readStatusLabMethod,
  STATUS_LAB_METHODS,
  STATUS_LAB_METHOD_STORAGE_KEY,
} from '../components/inbox-status-lab/status-selector-types'
import * as api from './api'
import {
  allRequestIdsSelected,
  applyInboxStatuses,
  buildApplySelectionPayload,
  coalesceInboxReviewItems,
  expandInboxReviewBySystem,
  inboxSystemFilterOptions,
  groupSelectedRequestIds,
  inboxItemChannels,
  inboxItemSourceFilterKey,
  isInboxIdentifierSurface,
  inboxReviewItemKey,
  inboxReviewItemSystemLabel,
  inboxReviewItemVerticalLabel,
  inboxStatusLabApplyStatus,
  isInboxReviewItemKey,
  requirePromoteDwidsForStatus,
  listSelectedRequestIds,
  matchingReviewBulkPromoteToast,
  matchingReviewPostFields,
  matchingReviewPromoteToast,
  requestIdsFromSelectedReviewItems,
  selectedReviewTargets,
  selectedStackMemberIds,
  selectionToolbarVisible,
  someRequestIdsSelected,
  toggleSelectedRequestGroup,
  toggleSelectedRequestId,
} from './inbox-status-lab'
import { filterRequestUuids, isRequestUuid } from './utils'

const SAMPLE_UUID = '11111111-1111-4111-8111-111111111111'
const SECOND_UUID = '22222222-2222-4222-8222-222222222222'
const THIRD_UUID = '33333333-3333-4333-8333-333333333333'
const STACK_KEY = 'p:42::single_match::matching'

describe('isRequestUuid', () => {
  test('accepts canonical UUIDs', () => {
    expect(isRequestUuid(SAMPLE_UUID)).toBe(true)
  })

  test('rejects batch keys and sentinel strings', () => {
    expect(isRequestUuid('p:42')).toBe(false)
    expect(isRequestUuid('p:42::single_match')).toBe(false)
    expect(isRequestUuid('p:42::single_match::matching')).toBe(false)
    expect(isRequestUuid(`${SAMPLE_UUID}::communications::cassandra`)).toBe(false)
    expect(isRequestUuid('undefined')).toBe(false)
    expect(isRequestUuid('')).toBe(false)
    expect(isRequestUuid('thread:batch:42')).toBe(false)
  })
})

describe('filterRequestUuids', () => {
  test('drops non-UUID ids and dedupes', () => {
    expect(
      filterRequestUuids([
        SAMPLE_UUID,
        'p:42',
        'p:42::single_match::matching',
        `${SAMPLE_UUID}::communications::cassandra`,
        SAMPLE_UUID,
        '22222222-2222-4222-8222-222222222222',
      ]),
    ).toEqual([SAMPLE_UUID, '22222222-2222-4222-8222-222222222222'])
  })
})

describe('listSelectedRequestIds', () => {
  test('returns stable sorted UUIDs and drops stack keys', () => {
    expect(
      listSelectedRequestIds(
        new Set([SECOND_UUID, SAMPLE_UUID, THIRD_UUID, STACK_KEY, 'p:42']),
      ),
    ).toEqual([SAMPLE_UUID, SECOND_UUID, THIRD_UUID])
  })

  test('keeps only canonical UUIDs from selection', () => {
    expect(
      listSelectedRequestIds(new Set([SECOND_UUID, SAMPLE_UUID, STACK_KEY])),
    ).toEqual([SAMPLE_UUID, SECOND_UUID])
  })
})

describe('inboxReviewItemKey', () => {
  test('identifies a row as request_id + vertical + system', () => {
    expect(
      inboxReviewItemKey({
        request_id: SAMPLE_UUID,
        vertical: 'data',
        system: 'cassandra',
      }),
    ).toBe(`${SAMPLE_UUID}::data::cassandra`)
  })

  test('uses request_id + vertical when system is missing', () => {
    expect(
      inboxReviewItemKey({ request_id: SAMPLE_UUID, vertical: 'communications' }),
    ).toBe(`${SAMPLE_UUID}::communications`)
    expect(
      inboxReviewItemKey({
        request_id: SAMPLE_UUID,
        vertical: 'communications',
        system: '  ',
      }),
    ).toBe(`${SAMPLE_UUID}::communications`)
  })

  test('falls back to request_id when vertical and system are missing', () => {
    expect(inboxReviewItemKey({ request_id: SAMPLE_UUID })).toBe(SAMPLE_UUID)
    expect(inboxReviewItemKey({ request_id: SAMPLE_UUID, vertical: '  ' })).toBe(
      SAMPLE_UUID,
    )
    expect(
      inboxReviewItemKey({ request_id: SAMPLE_UUID, system: 'cassandra' }),
    ).toBe(SAMPLE_UUID)
  })

  test('keeps two systems of the same request + vertical distinct', () => {
    expect(
      inboxReviewItemKey({
        request_id: SAMPLE_UUID,
        vertical: 'people_hr',
        system: 'lever',
      }),
    ).not.toBe(
      inboxReviewItemKey({
        request_id: SAMPLE_UUID,
        vertical: 'people_hr',
        system: 'hr_alumni',
      }),
    )
  })

  test('owner coalesce keys the list by request_id when connections are present', () => {
    expect(
      inboxReviewItemKey({
        request_id: SAMPLE_UUID,
        vertical: 'test',
        system: 'cassandra',
        connections: [
          { system: 'cassandra', system_label: 'CA DROP' },
          { system: 'hr_alumni', system_label: 'Alumni Google Sheet' },
        ],
      }),
    ).toBe(SAMPLE_UUID)
  })
})

describe('isInboxReviewItemKey', () => {
  test('accepts UUID, UUID::vertical, and UUID::vertical::system', () => {
    expect(isInboxReviewItemKey(SAMPLE_UUID)).toBe(true)
    expect(isInboxReviewItemKey(`${SAMPLE_UUID}::communications`)).toBe(true)
    expect(isInboxReviewItemKey(`${SAMPLE_UUID}::data::cassandra`)).toBe(true)
  })

  test('rejects batch and stack keys', () => {
    expect(isInboxReviewItemKey('p:42')).toBe(false)
    expect(isInboxReviewItemKey(STACK_KEY)).toBe(false)
    expect(isInboxReviewItemKey('thread:batch:42')).toBe(false)
    expect(isInboxReviewItemKey(`${SAMPLE_UUID}::communications::`)).toBe(false)
  })
})

describe('inboxReviewItemVerticalLabel', () => {
  test('prefers API vertical_label', () => {
    expect(
      inboxReviewItemVerticalLabel({
        request_id: SAMPLE_UUID,
        vertical: 'communications',
        vertical_label: 'Axios HQ audiences',
      }),
    ).toBe('Axios HQ audiences')
  })

  test('falls back to catalog label, then null', () => {
    expect(
      inboxReviewItemVerticalLabel({
        request_id: SAMPLE_UUID,
        vertical: 'auth0',
      }),
    ).toBe('Auth0')
    expect(inboxReviewItemVerticalLabel({ request_id: SAMPLE_UUID })).toBeNull()
  })
})

describe('inboxReviewItemSystemLabel', () => {
  test('never shows CA DROP as a system name', () => {
    expect(
      inboxReviewItemSystemLabel({
        request_id: SAMPLE_UUID,
        system: 'cassandra',
        system_label: 'California DROP',
      }),
    ).toBeNull()
    expect(
      inboxReviewItemSystemLabel({
        request_id: SAMPLE_UUID,
        system: 'cassandra',
      }),
    ).toBeNull()
  })

  test('test vertical uses System A / System B placeholders', () => {
    expect(
      inboxReviewItemSystemLabel({
        request_id: SAMPLE_UUID,
        vertical: 'test',
        system: 'cassandra',
        system_label: 'CA DROP',
      }),
    ).toBe('System A')
    expect(
      inboxReviewItemSystemLabel({
        request_id: SAMPLE_UUID,
        vertical: 'test',
        system: 'hr_alumni',
        system_label: 'Alumni Google Sheet',
      }),
    ).toBe('System B')
  })

  test('other verticals show the real connection name', () => {
    expect(
      inboxReviewItemSystemLabel({
        request_id: SAMPLE_UUID,
        vertical: 'people_hr',
        system: 'hr_alumni',
      }),
    ).toBe('Alumni Google Sheet')
    expect(inboxReviewItemSystemLabel({ request_id: SAMPLE_UUID })).toBeNull()
  })
})

describe('inboxSystemFilterOptions', () => {
  test('remaps test vertical systems and drops CA DROP as a system', () => {
    expect(
      inboxSystemFilterOptions([
        { id: 'cassandra', label: 'CA DROP', vertical: 'test' },
        { id: 'hr_alumni', label: 'Alumni Google Sheet', vertical: 'test' },
      ]),
    ).toEqual([
      { id: 'cassandra', label: 'System A', vertical: 'test' },
      { id: 'hr_alumni', label: 'System B', vertical: 'test' },
    ])
    expect(
      inboxSystemFilterOptions([
        { id: 'cassandra', label: 'CA DROP', vertical: 'data' },
        { id: 'hr_alumni', label: 'Alumni Google Sheet', vertical: 'people_hr' },
      ]),
    ).toEqual([
      { id: 'hr_alumni', label: 'Alumni Google Sheet', vertical: 'people_hr' },
    ])
  })
})

describe('requestIdsFromSelectedReviewItems', () => {
  test('maps checked review items to request ids without selecting unchecked verticals', () => {
    const items = [
      { request_id: SAMPLE_UUID, vertical: 'communications' },
      { request_id: SAMPLE_UUID, vertical: 'salesforce' },
      { request_id: SECOND_UUID, vertical: 'communications' },
    ]
    expect(
      requestIdsFromSelectedReviewItems(
        items,
        new Set([inboxReviewItemKey(items[0]!)]),
      ),
    ).toEqual([SAMPLE_UUID])
  })
})

describe('selectedReviewTargets', () => {
  test('keeps two systems of the same request as two promote targets', () => {
    const items = [
      { request_id: SAMPLE_UUID, vertical: 'people_hr', system: 'lever' },
      { request_id: SAMPLE_UUID, vertical: 'people_hr', system: 'hr_alumni' },
    ]
    const targets = selectedReviewTargets(
      items,
      new Set(items.map((item) => inboxReviewItemKey(item))),
    )
    expect(targets).toEqual([
      { request_id: SAMPLE_UUID, vertical: 'people_hr', system: 'lever' },
      { request_id: SAMPLE_UUID, vertical: 'people_hr', system: 'hr_alumni' },
    ])
    expect(targets.every((target) => isRequestUuid(target.request_id))).toBe(true)
    expect(targets.map((target) => target.request_id).join('::')).not.toContain(
      '::people_hr',
    )
  })

  test('includes nullable system when the row is vertical-only', () => {
    const items = [
      { request_id: SAMPLE_UUID, vertical: 'communications' },
      { request_id: SAMPLE_UUID, vertical: 'salesforce' },
    ]
    expect(
      selectedReviewTargets(
        items,
        new Set(items.map((item) => inboxReviewItemKey(item))),
      ),
    ).toEqual([
      { request_id: SAMPLE_UUID, vertical: 'communications', system: null },
      { request_id: SAMPLE_UUID, vertical: 'salesforce', system: null },
    ])
  })
})

describe('matchingReviewPostFields', () => {
  test('sends request_id, vertical, and system separately — never the composite key', () => {
    const item = {
      request_id: SAMPLE_UUID,
      vertical: 'data',
      system: 'cassandra',
    }
    const key = inboxReviewItemKey(item)
    expect(key).toBe(`${SAMPLE_UUID}::data::cassandra`)
    expect(matchingReviewPostFields(item)).toEqual({
      request_id: SAMPLE_UUID,
      vertical: 'data',
      system: 'cassandra',
    })
    expect(isRequestUuid(key)).toBe(false)
    expect(isRequestUuid(matchingReviewPostFields(item).request_id)).toBe(true)
  })
})

describe('inboxItemSourceFilterKey', () => {
  test('uses intake_source only — not email/phone/ndz or catalog system', () => {
    expect(inboxItemSourceFilterKey({ intake_source: 'drop' })).toBe('drop')
    expect(
      inboxItemSourceFilterKey({
        intake_source: 'drop',
        matched_via: 'drop_hash_email',
      }),
    ).toBe('drop')
    expect(
      inboxItemSourceFilterKey({
        intake_source: 'webform',
        matched_via: 'phone',
        channels: ['ndz'],
      }),
    ).toBe('webform')
    expect(inboxItemSourceFilterKey({ matched_via: 'ndz' })).toBe('unknown')
    expect(
      inboxItemSourceFilterKey({
        intake_source: 'drop',
        system: 'axios_hq',
        matched_via: 'email',
      }),
    ).toBe('drop')
    expect(inboxItemSourceFilterKey({})).toBe('unknown')
  })

  test('email / phone / ndz are identifier surfaces, not source keys', () => {
    expect(isInboxIdentifierSurface('email')).toBe(true)
    expect(isInboxIdentifierSurface('phone')).toBe(true)
    expect(isInboxIdentifierSurface('ndz')).toBe(true)
    expect(isInboxIdentifierSurface('drop')).toBe(false)
  })
})

describe('inboxItemChannels', () => {
  test('infers email, phone, and ndz from matched_via', () => {
    expect(
      inboxItemChannels({
        request_id: SAMPLE_UUID,
        matched_via: 'drop_hash_email',
      }),
    ).toEqual(['email'])
    expect(
      inboxItemChannels({ request_id: SAMPLE_UUID, matched_via: 'email' }),
    ).toEqual(['email'])
    expect(
      inboxItemChannels({ request_id: SAMPLE_UUID, matched_via: 'phone' }),
    ).toEqual(['phone'])
    expect(
      inboxItemChannels({ request_id: SAMPLE_UUID, matched_via: 'ndz' }),
    ).toEqual(['ndz'])
    expect(
      inboxItemChannels({
        request_id: SAMPLE_UUID,
        matched_via: 'drop_hash_phone',
      }),
    ).toEqual(['phone'])
    expect(
      inboxItemChannels({
        request_id: SAMPLE_UUID,
        matched_via: 'drop_hash_ndz',
      }),
    ).toEqual(['ndz'])
  })

  test('uses matched_channels when present and ignores unknown tokens', () => {
    expect(
      inboxItemChannels({
        request_id: SAMPLE_UUID,
        matched_via: 'drop_hash_email',
        matched_channels: ['phone', 'not-a-channel', 'ndz'],
      }),
    ).toEqual(['email', 'phone', 'ndz'])
  })

  test('prefers coalesced channels and keeps email/phone/ndz order', () => {
    expect(
      inboxItemChannels({
        request_id: SAMPLE_UUID,
        matched_via: 'phone',
        channels: ['ndz', 'email'],
      }),
    ).toEqual(['email', 'phone', 'ndz'])
  })
})

describe('coalesceInboxReviewItems', () => {
  test('merges phone and email on the same request/vertical/system', () => {
    const email = {
      request_id: SAMPLE_UUID,
      vertical: 'data',
      system: 'cassandra',
      reason: 'matching.review',
      matched_via: 'drop_hash_email',
    }
    const phone = {
      request_id: SAMPLE_UUID,
      vertical: 'data',
      system: 'cassandra',
      reason: 'matching.phone',
      matched_via: 'phone',
    }
    const coalesced = coalesceInboxReviewItems([email, phone])
    expect(coalesced).toHaveLength(1)
    expect(coalesced[0]).toMatchObject({
      request_id: SAMPLE_UUID,
      vertical: 'data',
      system: 'cassandra',
      reason: 'matching.review',
      matched_via: 'drop_hash_email',
      channels: ['email', 'phone'],
    })
    expect(inboxItemChannels(coalesced[0]!)).toEqual(['email', 'phone'])
  })

  test('keeps distinct systems as separate rows', () => {
    const coalesced = coalesceInboxReviewItems([
      {
        request_id: SAMPLE_UUID,
        vertical: 'people_hr',
        system: 'lever',
        matched_via: 'email',
      },
      {
        request_id: SAMPLE_UUID,
        vertical: 'people_hr',
        system: 'hr_alumni',
        matched_via: 'phone',
      },
    ])
    expect(coalesced.map((item) => item.system)).toEqual(['lever', 'hr_alumni'])
    expect(coalesced.map((item) => inboxItemChannels(item))).toEqual([
      ['email'],
      ['phone'],
    ])
  })

  test('owner expand keeps one matching-review row per test system', () => {
    const coalesced = coalesceInboxReviewItems(
      expandInboxReviewBySystem([
        {
          request_id: SAMPLE_UUID,
          vertical: 'test',
          system: 'cassandra',
          system_label: 'CA DROP',
          matched_via: 'email',
        },
        {
          request_id: SAMPLE_UUID,
          vertical: 'test',
          system: 'hr_alumni',
          system_label: 'Alumni Google Sheet',
          matched_via: 'phone',
        },
      ]),
    )
    expect(coalesced).toHaveLength(2)
    expect(coalesced.map((row) => row.system)).toEqual(['cassandra', 'hr_alumni'])
    expect(coalesced.map((row) => inboxReviewItemSystemLabel(row))).toEqual([
      'System A',
      'System B',
    ])
    const targets = selectedReviewTargets(
      coalesced,
      new Set(coalesced.map((row) => inboxReviewItemKey(row))),
    )
    expect(targets).toEqual([
      { request_id: SAMPLE_UUID, vertical: 'test', system: 'cassandra' },
      { request_id: SAMPLE_UUID, vertical: 'test', system: 'hr_alumni' },
    ])
    expect(targets.every((target) => isRequestUuid(target.request_id))).toBe(true)
  })

  test('owner expand fans API connections into per-system rows', () => {
    const coalesced = coalesceInboxReviewItems(
      expandInboxReviewBySystem([
        {
          request_id: SAMPLE_UUID,
          vertical: 'test',
          system: 'cassandra',
          system_label: 'CA DROP',
          connections: [
            { system: 'cassandra', system_label: 'CA DROP', vertical: 'test' },
            { system: 'hr_alumni', system_label: 'Alumni Google Sheet', vertical: 'test' },
          ],
        },
      ]),
    )
    expect(coalesced).toHaveLength(2)
    expect(coalesced.map((row) => row.system)).toEqual(['cassandra', 'hr_alumni'])
    expect(coalesced.map((row) => inboxReviewItemSystemLabel(row))).toEqual([
      'System A',
      'System B',
    ])
  })

  test('coalesced row still POSTs UUID + vertical + system, never the composite key', () => {
    const coalesced = coalesceInboxReviewItems([
      {
        request_id: SAMPLE_UUID,
        vertical: 'data',
        system: 'cassandra',
        matched_via: 'email',
      },
      {
        request_id: SAMPLE_UUID,
        vertical: 'data',
        system: 'cassandra',
        matched_via: 'phone',
      },
    ])
    const item = coalesced[0]!
    const key = inboxReviewItemKey(item)
    const fields = matchingReviewPostFields(item)
    expect(key).toBe(`${SAMPLE_UUID}::data::cassandra`)
    expect(isRequestUuid(key)).toBe(false)
    expect(fields).toEqual({
      request_id: SAMPLE_UUID,
      vertical: 'data',
      system: 'cassandra',
    })
    expect(isRequestUuid(fields.request_id)).toBe(true)
    expect(Object.keys(fields)).not.toContain('channels')
    expect(
      selectedReviewTargets(coalesced, new Set([key])),
    ).toEqual([fields])
  })
})

describe('toggleSelectedRequestId', () => {
  test('adds and removes ids immutably', () => {
    const first = toggleSelectedRequestId(new Set(), 'aaaa')
    expect([...first]).toEqual(['aaaa'])
    const second = toggleSelectedRequestId(first, 'aaaa')
    expect([...second]).toEqual([])
  })
})

describe('toggleSelectedRequestGroup', () => {
  test('selects and clears a thread group', () => {
    const selected = toggleSelectedRequestGroup(new Set(), ['a', 'b'])
    expect(allRequestIdsSelected(selected, ['a', 'b'])).toBe(true)
    const cleared = toggleSelectedRequestGroup(selected, ['a', 'b'])
    expect(someRequestIdsSelected(cleared, ['a', 'b'])).toBe(false)
  })
})

describe('groupSelectedRequestIds', () => {
  test('groups batch rows and keeps individuals separate', () => {
    const selected = new Set(['r1', 'r2', 'r3'])
    const groups = groupSelectedRequestIds(
      [
        { request_id: 'r1', bulk_process_id: 42 },
        { request_id: 'r2', bulk_process_id: 42 },
        { request_id: 'r3', bulk_process_id: null },
      ],
      selected,
    )

    expect(groups).toEqual([
      {
        batchKey: 'batch:42',
        batchLabel: 'Batch #42',
        requestIds: ['r1', 'r2'],
      },
      {
        batchKey: 'request:r3',
        batchLabel: 'Individual',
        requestIds: ['r3'],
      },
    ])
  })
})

describe('selectionToolbarVisible', () => {
  test('hidden when nothing selected', () => {
    expect(selectionToolbarVisible(0)).toBe(false)
  })

  test('visible when one or more rows are checked', () => {
    expect(selectionToolbarVisible(1)).toBe(true)
    expect(selectionToolbarVisible(2)).toBe(true)
  })
})

describe('selectedStackMemberIds', () => {
  const stackMembers = [SAMPLE_UUID, SECOND_UUID, THIRD_UUID]

  test('returns only checked stack UUIDs, not the whole stack', () => {
    expect(
      selectedStackMemberIds(new Set([SAMPLE_UUID, SECOND_UUID]), stackMembers),
    ).toEqual([SAMPLE_UUID, SECOND_UUID])
  })

  test('returns all members only when every stack member is checked', () => {
    expect(
      selectedStackMemberIds(
        new Set([SAMPLE_UUID, SECOND_UUID, THIRD_UUID]),
        stackMembers,
      ),
    ).toEqual([SAMPLE_UUID, SECOND_UUID, THIRD_UUID])
  })

  test('drops stack keys from member list', () => {
    expect(
      selectedStackMemberIds(
        new Set([SAMPLE_UUID, STACK_KEY]),
        [SAMPLE_UUID, STACK_KEY, 'p:42'],
      ),
    ).toEqual([SAMPLE_UUID])
  })

  test('returns empty when nothing in the stack is checked', () => {
    expect(selectedStackMemberIds(new Set(), stackMembers)).toEqual([])
  })
})

describe('buildApplySelectionPayload', () => {
  test('uses only checked UUIDs, not stack keys', () => {
    const result = buildApplySelectionPayload(
      new Set([SAMPLE_UUID, STACK_KEY, 'p:42']),
      '3',
    )
    expect(result).toEqual({
      ok: true,
      payload: {
        requestIds: [SAMPLE_UUID],
        statusId: '3',
        responseStatus: 3,
      },
    })
  })

  test('two checked ids yield apply payload length 2', () => {
    const result = buildApplySelectionPayload(
      new Set([SECOND_UUID, SAMPLE_UUID]),
      '4',
    )
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.payload.requestIds).toHaveLength(2)
      expect(result.payload.requestIds).toEqual([SAMPLE_UUID, SECOND_UUID])
    }
  })
})

describe('applyInboxStatuses', () => {
  test('rejects empty request ids', () => {
    expect(applyInboxStatuses({ requestIds: [], statusId: '3' })).toEqual({
      ok: false,
      reason: 'empty_request_ids',
    })
  })

  test('rejects batch stack keys masquerading as request ids', () => {
    expect(
      applyInboxStatuses({
        requestIds: ['p:42', 'status:single_match'],
        statusId: '3',
      }),
    ).toEqual({
      ok: false,
      reason: 'empty_request_ids',
    })
  })

  test('rejects composite review keys masquerading as request ids', () => {
    expect(
      applyInboxStatuses({
        requestIds: [
          'p:42::single_match::matching',
          `${SAMPLE_UUID}::data::cassandra`,
        ],
        statusId: '3',
      }),
    ).toEqual({
      ok: false,
      reason: 'empty_request_ids',
    })
  })

  test('rejects missing status', () => {
    expect(
      applyInboxStatuses({
        requestIds: [SAMPLE_UUID],
        statusId: '   ',
      }),
    ).toEqual({
      ok: false,
      reason: 'missing_status',
    })
  })

  test('rejects invalid status id', () => {
    expect(
      applyInboxStatuses({
        requestIds: [SAMPLE_UUID],
        statusId: '9',
      }),
    ).toEqual({
      ok: false,
      reason: 'invalid_status',
    })
  })

  test('normalizes request ids and maps DROP status', () => {
    const second = '22222222-2222-4222-8222-222222222222'
    expect(
      applyInboxStatuses({
        requestIds: [second, SAMPLE_UUID, second],
        statusId: '4',
      }),
    ).toEqual({
      ok: true,
      payload: {
        requestIds: [SAMPLE_UUID, second],
        statusId: '4',
        responseStatus: 4,
      },
    })
  })
})

describe('STATUS_LAB_METHODS', () => {
  test('keeps ten method ids — option 9 is two-tier', () => {
    expect(STATUS_LAB_METHODS.map((row) => row.id)).toEqual([
      'native-select',
      'segmented',
      'radio-popover',
      'combobox',
      'split-button',
      'inline-chips',
      'command-palette',
      'stepper-confirm',
      'two-tier',
      'apply-selection',
    ])
    expect(STATUS_LAB_METHODS[8].id).toBe('two-tier')
  })
})

describe('readStatusLabMethod', () => {
  test('defaults to two-tier when storage is empty', () => {
    let previous: string | null = null
    try {
      previous = localStorage.getItem(STATUS_LAB_METHOD_STORAGE_KEY)
      localStorage.removeItem(STATUS_LAB_METHOD_STORAGE_KEY)
    } catch {
      /* no storage — helper already falls back */
    }

    expect(readStatusLabMethod()).toBe('two-tier')

    try {
      if (previous != null) {
        localStorage.setItem(STATUS_LAB_METHOD_STORAGE_KEY, previous)
      }
    } catch {
      /* ignore restore when storage is unavailable */
    }
  })
})

describe('inboxStatusLabApplyStatus DWID resolve', () => {
  afterEach(() => {
    api.getDropMatchingResultDetail.mockRestore?.()
    api.getOwnerVerticalMatchingResults.mockRestore?.()
    api.postDropMatchingResultPromote.mockRestore?.()
  })

  test('vertical target uses owner matching-results — never DROP detail', async () => {
    const drop = spyOn(api, 'getDropMatchingResultDetail').mockResolvedValue({
      matched_contacts: [{ dwid: 'drop-dwid' }],
    })
    const owner = spyOn(api, 'getOwnerVerticalMatchingResults').mockResolvedValue({
      matched_contacts: [{ dwid: 'owner-dwid' }],
    })
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    const item = {
      request_id: SAMPLE_UUID,
      vertical: 'people_hr',
      system: 'lever',
    }
    const result = await inboxStatusLabApplyStatus(
      [inboxReviewItemKey(item), SAMPLE_UUID],
      '3',
      [matchingReviewPostFields(item)],
    )

    expect(result).toEqual({
      succeeded: 1,
      failed: 0,
      requestIds: [SAMPLE_UUID],
      statusId: '3',
    })
    expect(drop).not.toHaveBeenCalled()
    expect(owner.mock.calls).toEqual([[SAMPLE_UUID, 'people_hr', 'lever']])
    expect(promote.mock.calls).toEqual([
      [
        SAMPLE_UUID,
        {
          response_status: 3,
          dwids: ['owner-dwid'],
          vertical: 'people_hr',
          system: 'lever',
        },
      ],
    ])
    expect(isRequestUuid(promote.mock.calls[0][0])).toBe(true)
  })

  test('two systems of one request fetch owner DWIDs per system', async () => {
    const drop = spyOn(api, 'getDropMatchingResultDetail').mockResolvedValue({
      matched_contacts: [{ dwid: 'drop-dwid' }],
    })
    const owner = spyOn(api, 'getOwnerVerticalMatchingResults').mockImplementation(
      async (_requestId, _vertical, system) => ({
        matched_contacts: [{ dwid: `${system}-dwid` }],
      }),
    )
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    await inboxStatusLabApplyStatus(
      [SAMPLE_UUID],
      '4',
      [
        {
          request_id: SAMPLE_UUID,
          vertical: 'people_hr',
          system: 'lever',
        },
        {
          request_id: SAMPLE_UUID,
          vertical: 'people_hr',
          system: 'hr_alumni',
        },
      ],
    )

    expect(drop).not.toHaveBeenCalled()
    expect(owner.mock.calls).toEqual([
      [SAMPLE_UUID, 'people_hr', 'lever'],
      [SAMPLE_UUID, 'people_hr', 'hr_alumni'],
    ])
    expect(promote.mock.calls.map((call) => call[0])).toEqual([
      SAMPLE_UUID,
      SAMPLE_UUID,
    ])
    expect(promote.mock.calls.map((call) => call[1])).toEqual([
      {
        response_status: 4,
        dwids: ['lever-dwid'],
        vertical: 'people_hr',
        system: 'lever',
      },
      {
        response_status: 4,
        dwids: ['hr_alumni-dwid'],
        vertical: 'people_hr',
        system: 'hr_alumni',
      },
    ])
  })

  test('vertical-only target still uses owner matching without system', async () => {
    const drop = spyOn(api, 'getDropMatchingResultDetail').mockResolvedValue({
      matched_contacts: [{ dwid: 'drop-dwid' }],
    })
    const owner = spyOn(api, 'getOwnerVerticalMatchingResults').mockResolvedValue({
      matched_contacts: [{ dwid: 'axios-hq-dwid' }],
    })
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    await inboxStatusLabApplyStatus(
      [SAMPLE_UUID],
      '3',
      [{ request_id: SAMPLE_UUID, vertical: 'communications', system: null }],
    )

    expect(drop).not.toHaveBeenCalled()
    expect(owner.mock.calls).toEqual([[SAMPLE_UUID, 'communications', undefined]])
    expect(promote.mock.calls).toEqual([
      [
        SAMPLE_UUID,
        {
          response_status: 3,
          dwids: ['axios-hq-dwid'],
          vertical: 'communications',
        },
      ],
    ])
  })

  test('ops/admin without vertical keeps DROP detail', async () => {
    const drop = spyOn(api, 'getDropMatchingResultDetail').mockResolvedValue({
      matched_contacts: [{ dwid: 'drop-dwid' }],
    })
    const owner = spyOn(api, 'getOwnerVerticalMatchingResults').mockResolvedValue({
      matched_contacts: [{ dwid: 'owner-dwid' }],
    })
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    await inboxStatusLabApplyStatus([SAMPLE_UUID], '3')

    expect(owner).not.toHaveBeenCalled()
    expect(drop.mock.calls).toEqual([[SAMPLE_UUID]])
    expect(promote.mock.calls).toEqual([
      [SAMPLE_UUID, { response_status: 3, dwids: ['drop-dwid'] }],
    ])
  })

  test('status 5 skips matching fetch and posts empty dwids', async () => {
    const drop = spyOn(api, 'getDropMatchingResultDetail').mockResolvedValue({
      matched_contacts: [{ dwid: 'drop-dwid' }],
    })
    const owner = spyOn(api, 'getOwnerVerticalMatchingResults').mockResolvedValue({
      matched_contacts: [{ dwid: 'owner-dwid' }],
    })
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    await inboxStatusLabApplyStatus(
      [SAMPLE_UUID],
      '5',
      [{ request_id: SAMPLE_UUID, vertical: 'communications', system: 'axios_hq' }],
    )

    expect(drop).not.toHaveBeenCalled()
    expect(owner).not.toHaveBeenCalled()
    expect(promote.mock.calls).toEqual([
      [
        SAMPLE_UUID,
        {
          response_status: 5,
          dwids: [],
          vertical: 'communications',
          system: 'axios_hq',
        },
      ],
    ])
  })

  test('owner matching 403 does not promote 3/4 without DWIDs', async () => {
    spyOn(api, 'getDropMatchingResultDetail').mockRejectedValue(
      new Error('Admin API 403'),
    )
    spyOn(api, 'getOwnerVerticalMatchingResults').mockRejectedValue(
      new Error('Admin API 403'),
    )
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    const result = await inboxStatusLabApplyStatus(
      [`${SAMPLE_UUID}::people_hr::lever`, SAMPLE_UUID],
      '3',
      [{ request_id: SAMPLE_UUID, vertical: 'people_hr', system: 'lever' }],
    )

    expect(promote).not.toHaveBeenCalled()
    expect(result).toEqual({
      succeeded: 0,
      failed: 1,
      requestIds: [SAMPLE_UUID],
      statusId: '3',
    })
  })

  test('empty matched people does not promote 3/4', async () => {
    spyOn(api, 'getDropMatchingResultDetail').mockResolvedValue({
      matched_contacts: [],
    })
    spyOn(api, 'getOwnerVerticalMatchingResults').mockResolvedValue({
      matched_contacts: [],
    })
    const promote = spyOn(api, 'postDropMatchingResultPromote').mockResolvedValue({})

    const result = await inboxStatusLabApplyStatus(
      [SAMPLE_UUID],
      '4',
      [{ request_id: SAMPLE_UUID, vertical: 'communications', system: 'axios_hq' }],
    )

    expect(promote).not.toHaveBeenCalled()
    expect(result.succeeded).toBe(0)
    expect(result.failed).toBe(1)
  })
})

describe('requirePromoteDwidsForStatus', () => {
  test('status 3/4 reject missing or empty DWIDs', () => {
    expect(() => requirePromoteDwidsForStatus(3, undefined)).toThrow(
      'status 3/4 requires at least one person id',
    )
    expect(() => requirePromoteDwidsForStatus(4, [])).toThrow(
      'status 3/4 requires at least one person id',
    )
    expect(requirePromoteDwidsForStatus(3, ['person-1'])).toEqual(['person-1'])
  })

  test('status 5 stays empty', () => {
    expect(requirePromoteDwidsForStatus(5, undefined)).toEqual([])
    expect(requirePromoteDwidsForStatus(5, ['person-1'])).toEqual([])
  })
})

describe('MATCHING_RESULT_LAB_METHODS', () => {
  test('keeps ten method ids — option 9 is two-tier', () => {
    expect(MATCHING_RESULT_LAB_METHODS.map((row) => row.id)).toEqual([
      'native-select',
      'segmented',
      'radio-popover',
      'combobox',
      'split-button',
      'inline-chips',
      'command-palette',
      'stepper-confirm',
      'two-tier',
      'apply-selection',
    ])
    expect(MATCHING_RESULT_LAB_METHODS[8].id).toBe('two-tier')
  })
})

describe('Results lab Matching tab DWID toolbar', () => {
  test('mounts MatchingResultsMethodToolbar with 10 options, default two-tier', async () => {
    const lab = await Bun.file(
      new URL('../routes/requests/matching-results-lab.tsx', import.meta.url),
    ).text()
    expect(lab).toContain('<OwnerMatchingReviewMethodToolbar')
    expect(lab).toContain('readOwnerMatchingReviewMethod()')
    expect(MATCHING_RESULT_LAB_METHODS).toHaveLength(10)
    expect(MATCHING_RESULT_LAB_METHODS[8]?.id).toBe('two-tier')

    const html = renderToStaticMarkup(
      createElement(MatchingResultsMethodToolbar, {
        method: 'two-tier',
        onMethodChange: () => undefined,
      }),
    )
    expect(html).toContain('DWID select view')
    expect(html).toContain('9 · Summary + rows (default)')
  })
})

describe('Inbox individual matching DWID toolbar', () => {
  test('needs-attention Matching tab pins two-tier and does not mount the 10-option selector', async () => {
    const inbox = await Bun.file(
      new URL('../routes/requests/needs-attention.tsx', import.meta.url),
    ).text()
    expect(inbox).not.toContain('MatchingResultsMethodToolbar')
    expect(inbox).not.toContain('readMatchingResultLabMethod')
    expect(inbox).toContain('<MatchingResultsLabView')
    expect(inbox).toContain('method="two-tier"')
    expect(inbox).toContain('hideVertical={dataOwnerPersona}')
    expect(inbox).toContain('minmax(10rem,14rem)')
  })
})

describe('readMatchingResultLabMethod', () => {
  test('defaults to two-tier when storage is empty', () => {
    let previous: string | null = null
    try {
      previous = localStorage.getItem(MATCHING_RESULT_LAB_METHOD_STORAGE_KEY)
      localStorage.removeItem(MATCHING_RESULT_LAB_METHOD_STORAGE_KEY)
    } catch {
      /* no storage — helper already falls back */
    }

    expect(readMatchingResultLabMethod()).toBe('two-tier')

    try {
      if (previous != null) {
        localStorage.setItem(MATCHING_RESULT_LAB_METHOD_STORAGE_KEY, previous)
      }
    } catch {
      /* ignore restore when storage is unavailable */
    }
  })
})

describe('matchingReviewPromoteToast', () => {
  test('pending review does not claim fulfilled or matching-complete', () => {
    const copy = matchingReviewPromoteToast({ review_status: 'pending' })
    expect(copy.title).toBe('System confirmed')
    expect(copy.title.toLowerCase()).not.toContain('fulfill')
    expect(copy.title.toLowerCase()).not.toContain('complete')
    expect(copy.description?.toLowerCase()).toContain('stays open')
  })

  test('approved review says matching review approved — not request fulfilled', () => {
    const copy = matchingReviewPromoteToast({ review_status: 'approved' })
    expect(copy.title).toBe('Matching review approved')
    expect(copy.title.toLowerCase()).not.toContain('fulfill')
  })

  test('incomplete disposition while pending does not say approved', () => {
    const copy = matchingReviewPromoteToast({
      review_status: 'pending',
      disposition: { recorded: false },
    })
    expect(copy.variant).toBe('warning')
    expect(copy.title).toBe('Matching confirmed — disposition incomplete')
    expect(copy.title.toLowerCase()).not.toContain('approved')
  })
})

describe('matchingReviewBulkPromoteToast', () => {
  test('all pending does not claim requests fulfilled', () => {
    const copy = matchingReviewBulkPromoteToast([
      { review_status: 'pending' },
      { review_status: 'pending' },
    ])
    expect(copy.title).toBe('Systems confirmed')
    expect(copy.description).toContain('still open')
    expect(`${copy.title} ${copy.description}`.toLowerCase()).not.toContain('fulfill')
  })
})
