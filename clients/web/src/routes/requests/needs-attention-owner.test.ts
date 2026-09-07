// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, mock, test } from 'bun:test'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'

// The /dev/pipeline-live page calls Vite-only `import.meta.glob` at module scope,
// which crashes hermetic `bun test` loads through router.tsx → lab-routes.tsx.
// Mock the page module so the router import graph stays loadable; the lab path
// assert below reads lab-routes.tsx as text and is unaffected by this mock.
// The router import must stay dynamic so this mock registers before router.tsx
// evaluates its top-level `await import('@/lab-routes')`.
mock.module('../dev/pipeline-live', () => ({
  PipelineLiveLabPage: () => null,
  parsePipelineLiveLabSearch: (search: Record<string, unknown>) => {
    const raw = typeof search?.v === 'string' ? search.v.trim().toLowerCase() : ''
    const ids = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h']
    return { v: ids.includes(raw) ? raw : 'a' }
  },
}))

const { mergeNeedsAttentionSearch, parseNeedsAttentionSearch } = await import('../../router')

import {
  INBOX_POLL_INTERVAL_MS,
  INBOX_POLL_MAX_INTERVAL_MS,
  inboxRefetchInterval,
  isOwnerVerticalTask,
  mergeOwnerFulfillmentItems,
  ownerFulfillmentItemFromApproval,
  ownerFulfillmentItemFromRequest,
  type MatchingResultRow,
  type NeedsAttentionItem,
} from '../../lib/api'
import {
  coalesceInboxReviewItems,
  expandInboxReviewBySystem,
  inboxItemChannels,
  inboxReviewItemKey,
  inboxReviewItemVerticalLabel,
  requestIdsFromSelectedReviewItems,
  selectedReviewTargets,
} from '../../lib/inbox-status-lab'
import { isRequestUuid, labsEnabled } from '../../lib/utils'
import {
  matchingLabPeopleSource,
  matchingResultRowToInboxItem,
} from '../../components/matching-results-lab/matching-results-lab-types'
import { matchingDetailIsNotLive } from '../../components/requests/RequestTriageDialog'
import { isAuth0MatchingScope } from '../../components/requests/RequestDetailOverlay'
import {
  DATA_OWNER_INBOX_KIND_TABS,
  buildGroupedInboxRows,
  dropStatusPill,
  hideInboxVerticalFilter,
  inboxItemSystemId,
  inboxItemTitle,
  inboxStackCountCaption,
  inboxThreadMicroLabel,
  isAutomaticFulfillmentVertical,
  isOwnerFulfillmentItem,
  inboxCatalogFilterChange,
  inboxItemSourceIds,
  DuePill,
  InboxCatalogFilterToolbar,
  InboxQueueRows,
  mergeInboxCatalogSearch,
  ownerAssignCandidateEmails,
  ownerFulfillmentVerticalRows,
  ownerVisibleInboxItems,
  matchTypeLabel,
  ownerMatchResultLabel,
  resolveInboxAssignCandidates,
  stackMatchingStatusSummary,
  suggestedBulkFulfillStatus,
  batchClusterAsSubsteps,
  CATALOG_ONLY_NOT_LIVE_LABEL,
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
    expect(isAutomaticFulfillmentVertical('axios_hq')).toBe(false)
  })

  test('assigned-only SaaS is waiting on kickoff; cluster kicked_off stays true', () => {
    const rows = ownerFulfillmentVerticalRows({
      cluster: [
        {
          vertical: 'communications',
          label: 'Communications',
          live: true,
          actionable: true,
          matching_status: 'complete',
          disposition_status: 3,
          selected_dwid_count: 1,
          kicked_off: true,
          identity_required: false,
          identity_verified: null,
          fulfillment_status: 'in_progress',
          fulfillment_steps: [],
          blocker: null,
        },
      ],
      assignedVerticals: ['communications', 'people_hr'],
      assignedLabels: [
        { vertical_id: 'people_hr', display_label: 'People / HR' },
      ],
    })
    expect(rows).toEqual([
      {
        vertical: 'communications',
        label: 'Communications',
        kickedOff: true,
      },
      {
        vertical: 'people_hr',
        label: 'People / HR',
        kickedOff: false,
      },
    ])
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
  test('matching rows keep title and show vertical_label as the badge', () => {
    const comms = matchingItem({
      vertical: 'communications',
      vertical_label: 'Communications',
      match_type: 'single_match',
    })
    expect(inboxReviewItemVerticalLabel(comms)).toBe('Communications')
    expect(inboxItemTitle(comms)).not.toContain('Communications')
  })

  test('matching title uses system name, not id-first mono', () => {
    const sheet = matchingItem({
      vertical: 'bizdev',
      vertical_label: 'BizDev',
      system: 'bizdev_contacts',
      system_label: 'Contact Us Google Sheet',
      color_token: 'teal',
    })
    expect(inboxItemTitle(sheet)).toBe('Contact Us Google Sheet')
    expect(inboxItemTitle(sheet)).not.toBe('bizdev_contacts')
    expect(inboxItemTitle(sheet)).not.toContain('Communications')
  })

  test('sheet/SaaS match detail is not live; CA DROP is', () => {
    expect(
      matchingDetailIsNotLive({
        matched_contacts_status: 'not_live',
        result_kind: 'sheet_stub',
      }),
    ).toBe(true)
    expect(
      matchingDetailIsNotLive({
        matched_contacts_status: 'ok',
        result_kind: 'ca_drop',
      }),
    ).toBe(false)
    expect(matchingDetailIsNotLive({ result_kind: 'saas_stub' })).toBe(true)
  })

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

describe('owner inbox row identity', () => {
  test('connection keys stay distinct before owner coalesce', () => {
    const requestId = '11111111-1111-4111-8111-111111111111'
    const lever = matchingItem({
      request_id: requestId,
      vertical: 'people_hr',
      vertical_label: 'People / HR',
      system: 'lever',
      system_label: 'Lever',
      color_token: 'light',
    })
    const alumni = matchingItem({
      request_id: requestId,
      vertical: 'people_hr',
      vertical_label: 'People / HR',
      system: 'hr_alumni',
      system_label: 'Alumni Google Sheet',
      color_token: 'slate',
    })
    expect(inboxReviewItemKey(lever)).toBe(`${requestId}::people_hr::lever`)
    expect(inboxReviewItemKey(alumni)).toBe(`${requestId}::people_hr::hr_alumni`)
    expect(inboxReviewItemKey(lever)).not.toBe(inboxReviewItemKey(alumni))
    expect(inboxItemSystemId(lever)).toBe('lever')
    expect(inboxItemTitle(alumni)).toBe('Alumni Google Sheet')
  })

  test('owner list shows one matching-review row per test system (A / B)', () => {
    const requestId = '11111111-1111-4111-8111-111111111111'
    const drop = matchingItem({
      request_id: requestId,
      vertical: 'test',
      vertical_label: 'Test vertical',
      system: 'cassandra',
      system_label: 'CA DROP',
      color_token: 'navy',
      matched_via: 'drop_hash_email',
    })
    const alumni = matchingItem({
      request_id: requestId,
      vertical: 'test',
      vertical_label: 'Test vertical',
      system: 'hr_alumni',
      system_label: 'Alumni Google Sheet',
      color_token: 'slate',
      matched_via: 'phone',
    })
    const coalesced = coalesceInboxReviewItems(expandInboxReviewBySystem([drop, alumni]))
    expect(coalesced).toHaveLength(2)
    expect(inboxItemTitle(coalesced[0]!)).toBe('System A')
    expect(inboxItemTitle(coalesced[1]!)).toBe('System B')
    expect(inboxItemTitle(coalesced[0]!)).not.toBe('CA DROP')
    expect(inboxItemTitle(coalesced[1]!)).not.toBe('Alumni Google Sheet')

    const rows = buildGroupedInboxRows(coalesced, {
      byDateSource: false,
      bySystem: false,
      byStatus: false,
    })
    expect(rows).toHaveLength(2)
    expect(rows.every((row) => row.kind === 'request')).toBe(true)

    const html = renderToStaticMarkup(
      createElement(InboxQueueRows, {
        groupingActive: false,
        rows,
        selectedKeys: new Set(),
        activeTarget: null,
        expandedThreads: new Set(),
        dataOwnerPersona: true,
        onToggleThreadSelect: () => undefined,
        onToggleThreadExpand: () => undefined,
        onOpenThread: () => undefined,
        onToggleItem: () => undefined,
        onOpenItem: () => undefined,
      }),
    )
    expect(html).toContain('System A')
    expect(html).toContain('System B')
    expect(html).not.toContain('CA DROP')
    expect(html).not.toContain('Alumni Google Sheet')
  })

  test('shared queue chrome has no CA CSV filename and shows connector status', () => {
    const requestId = '11111111-1111-4111-8111-111111111111'
    const item = matchingItem({
      request_id: requestId,
      vertical: 'test',
      vertical_label: 'Test vertical',
      system: 'hr_alumni',
      system_label: 'Alumni Google Sheet',
      source_csv_filename: '20260717_broker_Email.csv',
      bulk_process_id: null,
    })
    const rows = buildGroupedInboxRows([item], {
      byDateSource: false,
      bySystem: false,
      byStatus: false,
    })
    const html = renderToStaticMarkup(
      createElement(InboxQueueRows, {
        groupingActive: false,
        rows,
        selectedKeys: new Set(),
        activeTarget: null,
        expandedThreads: new Set(),
        dataOwnerPersona: true,
        connectorReminders: [
          {
            code: 'upload_stale',
            system: 'hr_alumni',
            vertical_id: 'test',
            severity: 'overdue',
          },
        ],
        onToggleThreadSelect: () => undefined,
        onToggleThreadExpand: () => undefined,
        onOpenThread: () => undefined,
        onToggleItem: () => undefined,
        onOpenItem: () => undefined,
      }),
    )
    expect(html).toContain('Needs refresh')
    expect(html).not.toContain('CSV')
    expect(html).not.toContain('20260717_broker_Email')
    expect(html).not.toContain('cassandra')
  })

  test('Tasks tab keeps only the owner assigned vertical', () => {
    const requestId = '11111111-1111-1111-1111-111111111111'
    const comms = matchingItem({
      request_id: requestId,
      vertical: 'communications',
    })
    const hr = matchingItem({
      request_id: requestId,
      vertical: 'people_hr',
    })
    expect(isOwnerVerticalTask(comms, ['communications'])).toBe(true)
    expect(isOwnerVerticalTask(hr, ['communications'])).toBe(false)
  })

  test('bulk apply sends request UUIDs + system, not composite keys', () => {
    const requestId = '11111111-1111-4111-8111-111111111111'
    const lever = matchingItem({
      request_id: requestId,
      vertical: 'people_hr',
      system: 'lever',
    })
    const alumni = matchingItem({
      request_id: requestId,
      vertical: 'people_hr',
      system: 'hr_alumni',
    })
    const ids = requestIdsFromSelectedReviewItems(
      [lever],
      new Set([inboxReviewItemKey(lever)]),
    )
    expect(ids).toEqual([requestId])
    expect(ids[0]).not.toContain('::')
    const coalesced = coalesceInboxReviewItems(expandInboxReviewBySystem([lever, alumni]))
    const targets = selectedReviewTargets(
      coalesced,
      new Set(coalesced.map((row) => inboxReviewItemKey(row))),
    )
    expect(targets).toEqual([
      { request_id: requestId, vertical: 'people_hr', system: 'lever' },
      { request_id: requestId, vertical: 'people_hr', system: 'hr_alumni' },
    ])
    expect(targets.every((target) => isRequestUuid(target.request_id))).toBe(true)
    expect(targets.every((target) => !target.request_id.includes('::'))).toBe(true)
    expect(targets.some((target) => target.system === 'lever')).toBe(true)
    expect(targets.some((target) => target.system === 'hr_alumni')).toBe(true)
  })

  test('owner cannot see other verticals’ matching rows', () => {
    const requestId = '11111111-1111-4111-8111-111111111111'
    const assigned = matchingItem({
      request_id: requestId,
      vertical: 'people_hr',
      system: 'lever',
    })
    const other = matchingItem({
      request_id: requestId,
      vertical: 'communications',
      system: 'axios_hq',
    })
    const visible = ownerVisibleInboxItems([assigned, other], ['people_hr'])
    expect(visible).toEqual([assigned])
    expect(visible.some((item) => item.vertical === 'communications')).toBe(false)
  })
})

describe('inboxCatalogFilterChange', () => {
  test('vertical change clears system; system change is scoped', () => {
    expect(inboxCatalogFilterChange('vertical', 'people_hr')).toEqual({
      vertical: 'people_hr',
      system: undefined,
    })
    expect(inboxCatalogFilterChange('vertical', undefined)).toEqual({
      vertical: undefined,
      system: undefined,
    })
    expect(inboxCatalogFilterChange('system', 'lever')).toEqual({ system: 'lever' })
    expect(inboxCatalogFilterChange('system', undefined)).toEqual({ system: undefined })
  })
})

describe('hideInboxVerticalFilter (owner / user)', () => {
  const multipleAssigned = ['data', 'test', 'communications']

  test('omits Vertical for data_owner even with multiple assigned verticals', () => {
    expect(multipleAssigned.length).toBeGreaterThan(1)
    expect(hideInboxVerticalFilter(true, multipleAssigned)).toBe(true)
    expect(hideInboxVerticalFilter(true, ['data'])).toBe(true)
    expect(hideInboxVerticalFilter(true, [])).toBe(true)
  })

  test('omits Vertical for data_user even with multiple assigned verticals', () => {
    const dataUserPersona = true
    expect(hideInboxVerticalFilter(dataUserPersona, multipleAssigned)).toBe(true)
  })

  test('ops still shows Vertical; system filter stays when multiple systems', () => {
    expect(hideInboxVerticalFilter(false, multipleAssigned)).toBe(false)
    expect(inboxCatalogFilterChange('system', 'cassandra')).toEqual({
      system: 'cassandra',
    })
    expect(inboxCatalogFilterChange('system', undefined)).toEqual({
      system: undefined,
    })
  })

  test('toolbar markup omits Vertical for owner/user and never renders catalog System', () => {
    const verticalOptions = multipleAssigned.map((id) => ({ id, label: id }))
    const ownerHtml = renderToStaticMarkup(
      createElement(InboxCatalogFilterToolbar, {
        vertical: undefined,
        verticalOptions,
        onPatch: () => undefined,
        hideVertical: hideInboxVerticalFilter(true, multipleAssigned),
      }),
    )
    expect(ownerHtml).not.toContain('aria-label="Vertical"')
    expect(ownerHtml).not.toContain('aria-label="System"')

    const opsHtml = renderToStaticMarkup(
      createElement(InboxCatalogFilterToolbar, {
        vertical: undefined,
        verticalOptions,
        onPatch: () => undefined,
        hideVertical: hideInboxVerticalFilter(false, multipleAssigned),
      }),
    )
    expect(opsHtml).toContain('aria-label="Vertical"')
    expect(opsHtml).not.toContain('aria-label="System"')
    expect(opsHtml).not.toMatch(/<select[^>]*aria-label="System"/)
    expect(ownerHtml).not.toMatch(/<select[^>]*aria-label="System"/)
  })
})

function hideVerticalExpressions(source: string): string[] {
  return [...source.matchAll(/hideVertical=\{([\s\S]*?)\}/g)].map((match) =>
    match[1].trim(),
  )
}

describe('hideVertical production call-site source lock', () => {
  const pages = [
    ['needs-attention.tsx', new URL('./needs-attention.tsx', import.meta.url)],
    [
      'matching-results-lab.tsx',
      new URL('./matching-results-lab.tsx', import.meta.url),
    ],
  ] as const

  for (const [name, url] of pages) {
    test(`${name} wires hideVertical to dataOwnerPersona, not a verticals-length gate`, async () => {
      const source = await Bun.file(url).text()
      if (name === 'matching-results-lab.tsx') {
        expect(source).toContain('canAccessOpsSurfaces')
        expect(source).toContain('ForbiddenState')
        expect(source).toMatch(/if\s*\(\s*!canAccessOpsSurfaces\(\s*role\s*\)\s*\)/)
        expect(source).toContain('return <ForbiddenState />')
      }
      expect(source).toContain('hideVertical={dataOwnerPersona}')
      const sites = hideVerticalExpressions(source)
      expect(sites.length).toBeGreaterThan(0)
      for (const expr of sites) {
        expect(expr).toBe('dataOwnerPersona')
        expect(expr).not.toMatch(/length/)
        expect(expr).not.toMatch(/verticals\s*\?/)
        expect(expr).not.toMatch(/<=\s*1/)
        expect(expr).not.toMatch(/<\s*2/)
      }
    })
  }
})

describe('parseNeedsAttentionSearch + mergeNeedsAttentionSearch', () => {
  test('parses optional source and step without dropping vertical / system / kind', () => {
    expect(
      parseNeedsAttentionSearch({
        kind: 'matching',
        vertical: 'people_hr',
        system: 'lever',
        source: 'drop',
        step: 'fulfillment',
      }),
    ).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      system: 'lever',
      source: 'drop',
      step: 'fulfillment',
    })
    expect(parseNeedsAttentionSearch({ source: 'email', step: 'ingest' })).toEqual({
      step: 'ingest',
    })
    expect(parseNeedsAttentionSearch({ source: 'phone', step: 'notice' })).toEqual({
      step: 'notice',
    })
    expect(parseNeedsAttentionSearch({ source: 'ndz', step: 'matching' })).toEqual({
      step: 'matching',
    })
    expect(mergeNeedsAttentionSearch({ source: 'phone' }, {})).toEqual({})
    expect(inboxItemSourceIds({ intake_source: 'drop', matched_via: 'phone' })).toEqual([
      'drop',
    ])
    expect(inboxItemSourceIds({ intake_source: 'phone' })).toEqual([])
    expect(parseNeedsAttentionSearch({ step: 'review' })).toEqual({})
    expect(parseNeedsAttentionSearch({ source: '  ', step: '' })).toEqual({})
    expect(
      parseNeedsAttentionSearch({
        kind: 'fulfillment',
        vertical: 'communications',
        system: 'axios_hq',
      }),
    ).toEqual({
      kind: 'fulfillment',
      vertical: 'communications',
      system: 'axios_hq',
    })
  })

  test('merge omitted keys keep current; explicit undefined clears source and step', () => {
    const current = {
      kind: 'matching' as const,
      vertical: 'people_hr',
      system: 'lever',
      source: 'drop',
      step: 'matching' as const,
    }
    expect(mergeNeedsAttentionSearch(current, { source: undefined })).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      system: 'lever',
      step: 'matching',
    })
    expect(mergeNeedsAttentionSearch(current, { step: undefined })).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      system: 'lever',
      source: 'drop',
    })
    expect(mergeNeedsAttentionSearch(current, {})).toEqual(current)
    expect(
      mergeNeedsAttentionSearch(current, {
        source: undefined,
        step: undefined,
      }),
    ).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      system: 'lever',
    })
    expect(
      mergeNeedsAttentionSearch(current, { vertical: undefined, system: undefined }),
    ).toEqual({
      kind: 'matching',
      source: 'drop',
      step: 'matching',
    })
  })
})

describe('mergeInboxCatalogSearch (All / clear)', () => {
  test('omitted keys keep current; explicit undefined clears', () => {
    const current = {
      kind: 'matching' as const,
      vertical: 'people_hr',
      system: 'lever',
    }
    expect(mergeInboxCatalogSearch(current, { system: undefined })).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
    })
    expect(mergeInboxCatalogSearch(current, {})).toEqual(current)
    expect(
      mergeInboxCatalogSearch(current, { vertical: undefined, system: undefined }),
    ).toEqual({ kind: 'matching' })
  })

  test('source and step use key presence; existing vertical / system / kind stay', () => {
    const current = {
      kind: 'matching' as const,
      vertical: 'people_hr',
      system: 'lever',
      source: 'drop',
      step: 'matching' as const,
    }
    expect(mergeInboxCatalogSearch(current, { source: undefined })).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      system: 'lever',
      step: 'matching',
    })
    expect(mergeInboxCatalogSearch(current, { step: undefined })).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      system: 'lever',
      source: 'drop',
    })
    expect(mergeInboxCatalogSearch(current, {})).toEqual(current)
    expect(mergeInboxCatalogSearch(current, { system: undefined })).toEqual({
      kind: 'matching',
      vertical: 'people_hr',
      source: 'drop',
      step: 'matching',
    })
  })
})

describe('coalesce phone + email onto one inbox row', () => {
  test('same request/vertical/system is one matching-review row without channel chips', () => {
    const requestId = '11111111-1111-4111-8111-111111111111'
    const email = matchingItem({
      request_id: requestId,
      vertical: 'data',
      system: 'cassandra',
      system_label: 'Cassandra',
      matched_via: 'drop_hash_email',
      match_type: 'single_match',
    })
    const phone = matchingItem({
      request_id: requestId,
      vertical: 'data',
      system: 'cassandra',
      system_label: 'Cassandra',
      matched_via: 'phone',
      match_type: 'not_found',
    })
    const coalesced = coalesceInboxReviewItems([email, phone])
    expect(coalesced).toHaveLength(1)
    expect(inboxReviewItemKey(coalesced[0]!)).toBe(`${requestId}::data::cassandra`)
    expect(inboxItemChannels(coalesced[0]!)).toEqual(['email', 'phone'])

    const rows = buildGroupedInboxRows(coalesced, {
      byDateSource: false,
      bySystem: false,
      byStatus: false,
    })
    expect(rows).toHaveLength(1)
    expect(rows[0]?.kind).toBe('request')

    const html = renderToStaticMarkup(
      createElement(InboxQueueRows, {
        groupingActive: false,
        rows,
        selectedKeys: new Set(),
        activeTarget: null,
        expandedThreads: new Set(),
        dataOwnerPersona: true,
        onToggleThreadSelect: () => undefined,
        onToggleThreadExpand: () => undefined,
        onOpenThread: () => undefined,
        onToggleItem: () => undefined,
        onOpenItem: () => undefined,
      }),
    )
    expect(html).not.toContain('Email')
    expect(html).not.toContain('Phone')
    expect(html).not.toContain('NDZ')
    expect(html).not.toContain('aria-label="Email"')
    expect(html).not.toContain('aria-label="Phone"')
    expect(html).toContain('text-xs')
    expect(html).toContain('leading-normal')
    expect(html).not.toContain('text-[0.55rem]')
    expect(html).not.toContain('py-px')
    expect(html).not.toMatch(/batch thread/i)
    expect(html).not.toMatch(/batch stack/i)
  })
})

describe('owner assign candidates', () => {
  test('owners may only pick vertical members, legal, or super_admin', () => {
    expect(
      ownerAssignCandidateEmails({
        verticalMemberEmails: ['owner@example.com', 'user@example.com'],
        legalOperatorEmails: ['legal@example.com'],
        superAdminEmails: ['admin@example.com'],
      }),
    ).toEqual([
      'admin@example.com',
      'legal@example.com',
      'owner@example.com',
      'user@example.com',
    ])

    const ownerList = resolveInboxAssignCandidates({
      dataOwnerPersona: true,
      selfEmail: 'me@example.com',
      itemAssigneeEmails: ['stranger@example.com'],
      verticalMemberEmails: ['owner@example.com'],
      operators: [
        { email: 'legal@example.com', kind: 'legal' },
        { email: 'admin@example.com', kind: 'super_admin' },
        { email: 'ops@example.com', kind: 'admin' },
      ],
    })
    expect(ownerList).toEqual([
      'admin@example.com',
      'legal@example.com',
      'owner@example.com',
    ])
    expect(ownerList).not.toContain('stranger@example.com')
    expect(ownerList).not.toContain('me@example.com')
    expect(ownerList).not.toContain('ops@example.com')

    const opsList = resolveInboxAssignCandidates({
      dataOwnerPersona: false,
      selfEmail: 'me@example.com',
      itemAssigneeEmails: ['stranger@example.com'],
      operators: [{ email: 'legal@example.com', kind: 'legal' }],
    })
    expect(opsList).toEqual([
      'legal@example.com',
      'me@example.com',
      'stranger@example.com',
    ])
  })
})

describe('inbox group labels — no batch thread / batch stack', () => {
  test('exported micro and captions never say batch thread or batch stack', () => {
    for (const kind of [
      'date_source',
      'system',
      'status',
      'batch_type',
      'batch_status',
    ] as const) {
      const label = inboxThreadMicroLabel(kind)
      expect(label.toLowerCase()).not.toContain('batch thread')
      expect(label.toLowerCase()).not.toContain('batch stack')
      expect(label).not.toBe('Type')
    }
    expect(inboxStackCountCaption(1).toLowerCase()).not.toContain('batch thread')
    expect(inboxStackCountCaption(4).toLowerCase()).not.toContain('batch stack')
    expect(inboxThreadMicroLabel('date_source')).toBe('Batch')
    expect(inboxThreadMicroLabel('system')).toBe('System')
    expect(inboxThreadMicroLabel('status')).toBe('Status')
    expect(inboxThreadMicroLabel('batch_status')).toBe('Batch · Status')
  })

  test('source file has no leftover batch thread / batch stack copy', async () => {
    const source = await Bun.file(
      new URL('./needs-attention.tsx', import.meta.url),
    ).text()
    expect(source.toLowerCase()).not.toMatch(/batch thread/)
    expect(source.toLowerCase()).not.toMatch(/batch stack/)
    expect(source).not.toContain('Overdue · ${when}')
  })
})

describe('System / Group by wiring', () => {
  test('date+source is the default stack; System groups by catalog system', () => {
    const drop = matchingItem({
      requested_at: '2026-08-21T12:00:00Z',
      intake_source: 'drop',
      vertical: 'data',
      system: 'cassandra',
      system_label: 'Cassandra',
    })
    const sheet = matchingItem({
      request_id: '22222222-2222-4222-8222-222222222222',
      requested_at: '2026-08-21T13:00:00Z',
      intake_source: 'drop',
      vertical: 'bizdev',
      system: 'bizdev_contacts',
      system_label: 'Contact Us Google Sheet',
    })
    const dateRows = buildGroupedInboxRows([drop, sheet], {
      byDateSource: true,
      bySystem: false,
      byStatus: false,
    })
    expect(dateRows).toHaveLength(1)
    expect(dateRows[0]?.kind).toBe('thread')
    if (dateRows[0]?.kind === 'thread') {
      expect(dateRows[0].batchLabel).toMatch(/CA DROP/)
      expect(dateRows[0].batchLabel).not.toMatch(/#/)
    }

    const systemRows = buildGroupedInboxRows([drop, sheet], {
      byDateSource: false,
      bySystem: true,
      byStatus: false,
    })
    expect(systemRows.map((row) => (row.kind === 'thread' ? row.batchLabel : ''))).toEqual(
      ['Unassigned system', 'Contact Us Google Sheet'],
    )

    const batchAndStatus = buildGroupedInboxRows(
      [
        matchingItem({
          requested_at: '2026-08-21T12:00:00Z',
          match_type: 'single_match',
        }),
        matchingItem({
          request_id: '22222222-2222-4222-8222-222222222222',
          requested_at: '2026-08-21T13:00:00Z',
          match_type: 'not_found',
        }),
      ],
      { byDateSource: true, bySystem: false, byStatus: true },
    )
    expect(batchAndStatus).toHaveLength(2)
    expect(
      batchAndStatus.map((row) => (row.kind === 'thread' ? row.batchLabel : '')),
    ).toEqual([
      expect.stringMatching(/CA DROP · Single match/),
      expect.stringMatching(/CA DROP · Not found/),
    ])
  })

  test('page wires Group by / System popover, not Type chips or catalog System', async () => {
    const pages = [
      new URL('./needs-attention.tsx', import.meta.url),
      new URL('./matching-results-lab.tsx', import.meta.url),
    ]
    for (const url of pages) {
      const source = await Bun.file(url).text()
      expect(source).toContain('InboxViewSettingsPopover')
      expect(source).toContain('<InboxQueueRows')
      expect(source).toContain('INBOX_LIST_EXPANDED_COLS')
      expect(source).toContain('INBOX_LIST_HOVER_FLYOUT')
      expect(source).not.toContain('22rem')
      if (url.pathname.endsWith('needs-attention.tsx')) {
        expect(source).toContain('minmax(10rem,14rem)')
        expect(source).toContain('md:w-[14rem]')
        expect(source).toContain('md:grid-cols-[3rem_minmax(0,1fr)]')
      }
      expect(source).toContain('groupBySystem')
      expect(source).toContain('groupByBatch')
      expect(source).toContain('hideVertical={dataOwnerPersona}')
      expect(source).toContain('expandInboxReviewBySystem')
      if (url.pathname.endsWith('needs-attention.tsx')) {
        expect(source).not.toContain('MatchingResultsMethodToolbar')
        expect(source).not.toContain('readMatchingResultLabMethod')
        expect(source).toContain('<MatchingResultsLabView')
        expect(source).toContain('method="two-tier"')
        expect(source).toContain('Auth0MatchCandidatesList')
        expect(source).toContain('isAuth0MatchingScope')
      } else {
        expect(source).toContain('OwnerMatchingReviewMethodToolbar')
      }
      if (url.pathname.endsWith('needs-attention.tsx')) {
        expect(source).toContain('TooltipProvider')
        expect(source).toContain('InboxDueHint')
        expect(source).toContain('InboxMatchHint')
        expect(source).toContain('InboxConnectorStatusHint')
        expect(source).toContain('aggregateOwnerSystemWorkbenchSubsteps')
        expect(source).not.toContain('source_csv_filename?.split')
        expect(source).not.toContain('Bulk #{bulkFilter}')
        expect(source).not.toContain('<InboxSystemChips')
        expect(source).not.toMatch(/InboxQueueRows[\s\S]*<InboxSystemChips/)
        expect(source).not.toMatch(
          /InboxQueueRows[\s\S]*\{inboxItemTitle\(item\)\}[\s\S]{0,500}emailInitials\(assignee\)/,
        )
        expect(source).not.toMatch(
          /InboxQueueRows[\s\S]*Requester state · \$\{item\.requestor_state\}/,
        )
        expect(source).not.toMatch(/dataOwnerPersona \? 'Requests' : 'All requests'/)
      } else {
        expect(source).toContain('canAccessOpsSurfaces')
        expect(source).toContain('ForbiddenState')
        expect(source).toMatch(/if\s*\(\s*!canAccessOpsSurfaces\(\s*role\s*\)\s*\)/)
        expect(source).toContain('return <ForbiddenState />')
        expect(source).not.toContain('MatchingResultsLabToolbar')
        expect(source).not.toMatch(/dataOwnerPersona \? 'Requests' : 'All requests'/)
      }
      expect(source).not.toContain('label="Type"')
      expect(source).not.toContain('label="Group"')
      expect(source).not.toContain('label="System"')
      expect(source).not.toMatch(/stackKind: 'type'/)
      expect(source).not.toMatch(/stackKind: 'batch'/)
    }
  })
})

describe('matchingResultRowToInboxItem + people source by vertical', () => {
  function landedRow(overrides: Partial<MatchingResultRow> = {}): MatchingResultRow {
    return {
      request_id: '11111111-1111-4111-8111-111111111111',
      matched: true,
      match_count: 1,
      match_type: 'single_match',
      matched_via: 'drop_hash_email',
      recorded_at: '2026-08-25T12:00:00Z',
      requestor_state: 'CA',
      review_status: 'pending',
      approval_id: null,
      recommended_response_status: 3,
      ...overrides,
    }
  }

  test('maps landed matching_results row to matching inbox item on data', () => {
    const row = landedRow()
    const item = matchingResultRowToInboxItem(row)
    expect(item.kind).toBe('matching')
    expect(item.vertical).toBe('data')
    expect(item.intake_source).toBe('drop')
    expect(item.current_stage).toBe('matching.review')
    expect(item.received_at).toBe(row.recorded_at)
    expect(item.requested_at).toBe(row.recorded_at)
    expect(item.request_id).toBe(row.request_id)
    expect(item.match_type).toBe('single_match')
    expect(item.reason).toBe('matching_result')
  })

  test('approved review_status becomes matching.approved', () => {
    const item = matchingResultRowToInboxItem(landedRow({ review_status: 'approved' }))
    expect(item.kind).toBe('matching')
    expect(item.vertical).toBe('data')
    expect(item.current_stage).toBe('matching.approved')
  })

  test('people source is vertical-first: data→mdr, auth0→auth0, lever→null', () => {
    expect(matchingLabPeopleSource('cassandra', 'data')).toBe('mdr')
    expect(matchingLabPeopleSource(null, 'data')).toBe('mdr')
    expect(matchingLabPeopleSource('auth0', 'auth0')).toBe('auth0')
    expect(matchingLabPeopleSource(null, 'auth0')).toBe('auth0')
    expect(matchingLabPeopleSource('lever', 'lever')).toBeNull()
    expect(matchingLabPeopleSource(null, 'lever')).toBeNull()
    expect(matchingLabPeopleSource('cassandra', 'lever')).toBeNull()
    expect(matchingLabPeopleSource('cassandra', null)).toBeNull()
    expect(matchingLabPeopleSource('paylocity', 'paylocity')).toBeNull()
    expect(matchingLabPeopleSource('axios_hq', 'axios_hq')).toBeNull()
  })
})

describe('Auth0 matching scope', () => {
  test('treats auth0 vertical or system as in-scope', () => {
    expect(isAuth0MatchingScope('auth0', 'cassandra')).toBe(true)
    expect(isAuth0MatchingScope('people_hr', 'auth0')).toBe(true)
    expect(isAuth0MatchingScope('tech', 'auth0')).toBe(true)
    expect(isAuth0MatchingScope(' AUTH0 ', null)).toBe(true)
    expect(isAuth0MatchingScope('people_hr', 'lever')).toBe(false)
    expect(isAuth0MatchingScope(null, null)).toBe(false)
  })

  test('inbox Auth0 candidate list uses item system, not ownerSystem', async () => {
    const source = await Bun.file(
      new URL('./needs-attention.tsx', import.meta.url),
    ).text()
    expect(source).toMatch(
      /isAuth0MatchingScope\(\s*item\.vertical,\s*inboxItemSystemId\(item\)\s*\)/,
    )
    expect(source).not.toMatch(
      /isAuth0MatchingScope\(\s*item\.vertical,\s*ownerSystem\s*\)/,
    )
  })
})

describe('production owner walkthrough — no design-lab chrome', () => {
  test('labsEnabled is on under bun test / Vite DEV', () => {
    expect(labsEnabled()).toBe(true)
  })
  test('inbox pins two-tier matching and does not mount the 10-way toolbar', async () => {
    const source = await Bun.file(
      new URL('./needs-attention.tsx', import.meta.url),
    ).text()
    expect(source).toContain('<MatchingResultsLabView')
    expect(source).toContain('method="two-tier"')
    expect(source).not.toContain('MatchingResultsMethodToolbar')
    expect(source).not.toContain('DWID select view')
    expect(source).not.toContain('readMatchingResultLabMethod')
    expect(source).not.toContain('setMatchingMethod')
  })

  test('NavMenu hides Results lab and Settings labs from data_owner', async () => {
    const source = await Bun.file(
      new URL('../../components/NavMenu.tsx', import.meta.url),
    ).text()
    expect(source).toContain('showDevLabs')
    expect(source).toContain('labsEnabled()')
    expect(source).toContain("role === 'super_admin'")
    expect(source).not.toContain(
      "showResultsLab: !legalAdminNav && (showOps || role === 'data_owner' || role === 'data_user')",
    )
    expect(source).toContain(
      'showResultsLab: labsOn && showOps && !legalAdminNav && !isOwnerPersona',
    )
    expect(source).toContain('settingsGroup(showOwnerConnectors, showDevLabs)')
    expect(source).toContain('const showDevLabs = labsOn && role === \'super_admin\'')
  })

  test('router loads lab-routes only from a Vite-droppable labs branch', async () => {
    const router = await Bun.file(
      new URL('../../router.tsx', import.meta.url),
    ).text()
    const labs = await Bun.file(
      new URL('../../lab-routes.tsx', import.meta.url),
    ).text()
    expect(router).toContain("path: '/owner/connectors'")
    expect(router).toContain("import('@/lab-routes')")
    expect(router).toContain("VITE_ENABLE_LABS === 'true'")
    expect(router).toContain('!import.meta.env.PROD')
    expect(router).not.toContain("path: '/dev/owner-map-alternatives'")
    expect(router).not.toContain('@/routes/dev/')
    expect(router).not.toContain('matching-results-lab')
    expect(labs).toContain("path: '/dev/owner-map-alternatives'")
    expect(labs).toContain("path: '/dev/mapping-workbench-samples'")
    expect(labs).toContain("path: '/dev/match-quality'")
    expect(labs).toContain("path: '/dev/pipeline-live'")
    expect(labs).toContain("path: '/dev/sheets-oauth'")
    expect(labs).toContain("path: '/dev/drop-prod-cutover'")
    expect(labs).toContain("path: '/requests/matching-results-lab'")
    expect(labs).not.toContain("path: '/owner/connectors'")
  })
})

describe('DuePill', () => {
  test('overdue shows Overdue without datetime', () => {
    const html = renderToStaticMarkup(
      createElement(DuePill, {
        item: matchingItem({ requested_at: '2020-01-01T00:00:00Z' }),
      }),
    )
    expect(html).toContain('>Overdue<')
    expect(html).not.toContain('·')
    expect(html).not.toMatch(/\d{1,2}:\d{2}/)
  })
})

describe('batchClusterAsSubsteps not-live labels', () => {
  test('live:false rows use catalog-only / not-live, not Soon', () => {
    const steps = batchClusterAsSubsteps(
      [
        {
          vertical: 'communications',
          label: 'Communications',
          live: false,
          actionable: false,
          matching_status: 'not_started',
          fulfillment_status: null,
          member_status_counts: {},
        },
        {
          vertical: 'data',
          label: 'Data',
          live: true,
          actionable: true,
          matching_status: 'in_progress',
          fulfillment_status: null,
          member_status_counts: {},
        },
      ],
      'matching',
    )
    expect(steps.find((step) => step.key === 'matching-communications')?.statusLabel).toBe(
      CATALOG_ONLY_NOT_LIVE_LABEL,
    )
    expect(steps.find((step) => step.key === 'matching-communications')?.statusLabel).not.toBe(
      'Soon',
    )
    expect(steps.find((step) => step.key === 'matching-data')?.statusLabel).toBe(
      'In progress',
    )
  })

  test('member counts still win over the catalog-only label', () => {
    const steps = batchClusterAsSubsteps(
      [
        {
          vertical: 'communications',
          label: 'Communications',
          live: false,
          actionable: false,
          matching_status: 'not_started',
          fulfillment_status: null,
          member_status_counts: { not_started: 2 },
        },
      ],
      'matching',
    )
    expect(steps[0]?.statusLabel).toBe('2 not started')
    expect(steps[0]?.statusLabel).not.toBe('Soon')
  })
})

describe('stack matching status badge', () => {
  test('summarizes single / multi / not-found counts', () => {
    const summary = stackMatchingStatusSummary(
      [
        matchingItem({ match_type: 'single_match' }),
        matchingItem({ match_type: 'single_match' }),
        matchingItem({ match_type: 'multi_match' }),
        matchingItem({ match_type: 'not_found' }),
      ],
      false,
    )
    expect(summary.mixed).toBe(true)
    expect(summary.label).toContain('2 Single match')
    expect(summary.label).toContain('1 Multi-person')
    expect(summary.label).toContain('1 Not found')
  })
})

describe('inbox poll cadence', () => {
  const query = (fetchStatus: string, fetchFailureCount = 0) => ({
    state: { fetchStatus, fetchFailureCount },
  })

  test('holds the timer while a fetch is still outstanding', () => {
    expect(inboxRefetchInterval(query('fetching'))).toBe(false)
  })

  test('polls on the base interval once idle and healthy', () => {
    expect(inboxRefetchInterval(query('idle'))).toBe(INBOX_POLL_INTERVAL_MS)
  })

  test('backs off exponentially while admin-api sheds the inbox', () => {
    expect(inboxRefetchInterval(query('idle', 1))).toBe(INBOX_POLL_INTERVAL_MS * 2)
    expect(inboxRefetchInterval(query('idle', 2))).toBe(INBOX_POLL_INTERVAL_MS * 4)
  })

  test('caps the backoff', () => {
    expect(inboxRefetchInterval(query('idle', 50))).toBe(INBOX_POLL_MAX_INTERVAL_MS)
  })
})
