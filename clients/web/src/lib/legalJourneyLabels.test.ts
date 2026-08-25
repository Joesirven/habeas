// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  COARSE_STAGE_ORDER,
  NOTICE_APPROVAL,
  WORKBENCH_STAGE_ORDER,
  actionReasonLabel,
  isWorkbenchStageKey,
  aggregateOwnerSystemWorkbenchSubsteps,
  aggregateStackWorkbenchChrome,
  deriveWorkbenchChromeFromOpsJourney,
  formatStackSubstepCounts,
  preferStackChromeStages,
  queueStatusLabel,
  stageLabel,
  stageReachLabel,
  verticalLabel,
  workbenchStageLabel,
  workbenchStatusLabel,
  catalogSystemDisplayLabel,
} from './legalJourneyLabels'

describe('legalJourneyLabels', () => {
  test('COARSE_STAGE_ORDER matches KD29 API keys', () => {
    expect(COARSE_STAGE_ORDER).toEqual([
      'receive',
      'matching',
      'data_owner_review',
      'legal_review',
      'fulfillment',
      'delivery_notice',
    ])
  })

  test('stageLabel maps KD29 user-facing labels', () => {
    expect(stageLabel('receive')).toBe('receive')
    expect(stageLabel('matching')).toBe('matching')
    expect(stageLabel('data_owner_review')).toBe('data owner review')
    expect(stageLabel('legal_review')).toBe('legal / pre-fulfillment')
    expect(stageLabel('fulfillment')).toBe('fulfillment')
    expect(stageLabel('delivery_notice')).toBe('delivery / DROP notice')
  })

  test('stageLabel normalizes legacy keys', () => {
    expect(stageLabel('triage')).toBe('receive')
    expect(stageLabel('review')).toBe('data owner review')
  })

  test('stageLabel falls back for unknown keys', () => {
    expect(stageLabel('custom_stage')).toBe('custom stage')
  })

  test('stageReachLabel delegates to stageLabel', () => {
    expect(stageReachLabel('fulfillment')).toBe(stageLabel('fulfillment'))
  })

  test('actionReasonLabel maps known technical reasons', () => {
    expect(actionReasonLabel('notice.review')).toBe(
      'Fulfillment notice pending',
    )
    expect(actionReasonLabel('matching.review')).toBe(
      'Matching review pending',
    )
    expect(actionReasonLabel('fulfillment.kickoff')).toBe(
      'Fulfillment kickoff pending',
    )
    expect(actionReasonLabel('fulfillment.kickoff_not_approved')).toBe(
      'Fulfillment kickoff not approved',
    )
    expect(actionReasonLabel('access.delivery')).toBe(
      'Access delivery pending',
    )
    expect(actionReasonLabel('delivery.confirm')).toBe(
      'Delivery confirmation pending',
    )
    expect(actionReasonLabel('workflow.assignment')).toBe('Assignment pending')
  })

  test('actionReasonLabel falls back like inbox reasonLabel', () => {
    expect(actionReasonLabel('custom.reason_key')).toBe('custom · reason key')
    expect(actionReasonLabel('  notice.review  ')).toBe(
      'Fulfillment notice pending',
    )
  })

  test('queueStatusLabel reflects pending vs approved', () => {
    expect(queueStatusLabel('notice.review')).toBe(
      'Fulfillment notice pending',
    )
    expect(queueStatusLabel('notice.review', 'pending')).toBe(
      'Fulfillment notice pending',
    )
    expect(queueStatusLabel('notice.review', 'approved')).toBe(
      'Fulfillment notice approved',
    )
    expect(queueStatusLabel('matching.review', 'approved')).toBe(
      'Matching review approved',
    )
    expect(queueStatusLabel('fulfillment.kickoff', 'approved')).toBe(
      'Fulfillment kickoff approved',
    )
  })

  test('NOTICE_APPROVAL exposes human copy without wire keys', () => {
    expect(NOTICE_APPROVAL.noun).toBe('Fulfillment notice pending')
    expect(NOTICE_APPROVAL.action).toBe('Approve fulfillment notice')
    expect(NOTICE_APPROVAL.confirmTitle).toBe('Approve fulfillment notice?')
    expect(NOTICE_APPROVAL.hint).toContain('weekly upload batch')
    expect(NOTICE_APPROVAL.hint).toContain('fulfilled DROP row')
    expect(NOTICE_APPROVAL.empty).toBe('No fulfillment notices waiting.')
    expect(NOTICE_APPROVAL.beforeUpload).toBe(
      'Fulfillment notice pending — weekly upload',
    )
    for (const value of Object.values(NOTICE_APPROVAL)) {
      expect(value).not.toContain('notice.review')
    }
    for (const reason of [
      'notice.review',
      'matching.review',
      'access.delivery',
      'delivery.confirm',
      'workflow.assignment',
    ]) {
      expect(actionReasonLabel(reason)).not.toContain(reason)
    }
  })

  test('WORKBENCH_STAGE_ORDER matches KTD2 four-stage rail', () => {
    expect(WORKBENCH_STAGE_ORDER).toEqual([
      'ingest',
      'matching',
      'fulfillment',
      'notice',
    ])
  })

  test('workbenchStageLabel maps the four high-level stages', () => {
    expect(workbenchStageLabel('ingest')).toBe('Ingest')
    expect(workbenchStageLabel('matching')).toBe('Matching')
    expect(workbenchStageLabel('fulfillment')).toBe('Fulfillment')
    expect(workbenchStageLabel('notice')).toBe('Notice')
    expect(workbenchStageLabel('custom_stage')).toBe('custom stage')
  })

  test('isWorkbenchStageKey accepts only the four high-level stages', () => {
    expect(isWorkbenchStageKey('ingest')).toBe(true)
    expect(isWorkbenchStageKey('matching')).toBe(true)
    expect(isWorkbenchStageKey('fulfillment')).toBe(true)
    expect(isWorkbenchStageKey('notice')).toBe(true)
    expect(isWorkbenchStageKey('overview')).toBe(false)
    expect(isWorkbenchStageKey('steps')).toBe(false)
    expect(isWorkbenchStageKey('activity')).toBe(false)
  })

  test('verticalLabel maps catalog entries', () => {
    expect(verticalLabel('communications')).toBe('Communications')
    expect(verticalLabel('people_hr')).toBe('People/HR')
    expect(verticalLabel('data')).toBe('Data')
    expect(verticalLabel('axios_hq')).toBe('Axios HQ')
    expect(verticalLabel('lever')).toBe('Lever')
    expect(verticalLabel('paylocity')).toBe('Paylocity')
    expect(verticalLabel('auth0')).toBe('Auth0')
    expect(verticalLabel('cassandra')).toBe('Cassandra')
    expect(verticalLabel('unknown_vendor')).toBe('unknown vendor')
  })

  test('workbenchStatusLabel maps StageStatus values', () => {
    expect(workbenchStatusLabel('not_started')).toBe('Not started')
    expect(workbenchStatusLabel('in_progress')).toBe('In progress')
    expect(workbenchStatusLabel('waiting')).toBe('Waiting')
    expect(workbenchStatusLabel('complete')).toBe('Complete')
    expect(workbenchStatusLabel('failed')).toBe('Failed')
    expect(workbenchStatusLabel('skipped')).toBe('Skipped')
  })

  test('deriveWorkbenchChromeFromOpsJourney returns four stages, never KD29 six', () => {
    const chrome = deriveWorkbenchChromeFromOpsJourney({
      intake_source: 'drop',
      current_stage: 'match',
      request_type: 'delete',
      stages: [
        { stage: 'received', label: 'Received', status: 'complete' },
        { stage: 'download', label: 'Download', status: 'complete' },
        { stage: 'land', label: 'Land', status: 'complete' },
        { stage: 'promote', label: 'Promote', status: 'complete' },
        { stage: 'match', label: 'Match', status: 'in_progress' },
        { stage: 'review', label: 'Review', status: 'not_started' },
        { stage: 'fulfill', label: 'Fulfill', status: 'not_started' },
        { stage: 'notice', label: 'Notice', status: 'not_started' },
      ],
    })
    expect(chrome.stages.map((stage) => stage.stage)).toEqual([
      'ingest',
      'matching',
      'fulfillment',
      'notice',
    ])
    expect(chrome.stages).toHaveLength(4)
    expect(chrome.current_stage).toBe('matching')
    expect(chrome.substeps.filter((step) => step.parent === 'ingest').map((s) => s.key)).toEqual([
      'received',
      'download',
      'land',
      'promote',
    ])
    expect(chrome.substeps.some((step) => step.key === 'notice')).toBe(true)
  })

  test('deriveWorkbenchChromeFromOpsJourney conditions notice substeps on access vs drop', () => {
    const access = deriveWorkbenchChromeFromOpsJourney({
      intake_source: 'webform',
      current_stage: 'fulfill',
      request_type: 'access',
      stages: [
        { stage: 'received', label: 'Received', status: 'complete' },
        { stage: 'match', label: 'Match', status: 'complete' },
        { stage: 'fulfill', label: 'Fulfill', status: 'in_progress' },
        { stage: 'delivery', label: 'Delivery', status: 'not_started' },
      ],
    })
    expect(access.substeps.some((step) => step.key === 'delivery')).toBe(true)
    expect(access.substeps.some((step) => step.key === 'notice')).toBe(false)

    const drop = deriveWorkbenchChromeFromOpsJourney({
      intake_source: 'drop',
      current_stage: 'notice',
      request_type: 'delete',
      stages: [
        { stage: 'notice', label: 'Notice', status: 'waiting' },
        { stage: 'delivery', label: 'Delivery', status: 'not_started' },
      ],
    })
    expect(drop.substeps.some((step) => step.key === 'notice')).toBe(true)
    expect(drop.substeps.some((step) => step.key === 'delivery')).toBe(false)
  })

  test('formatStackSubstepCounts lists non-zero statuses in funnel order', () => {
    expect(
      formatStackSubstepCounts({ complete: 8, in_progress: 2, not_started: 2 }),
    ).toBe('8 complete · 2 in progress · 2 not started')
  })

  test('catalogSystemDisplayLabel keeps CA DROP as source-only', () => {
    expect(catalogSystemDisplayLabel('cassandra', { systemLabel: 'CA DROP' })).toBeNull()
    expect(
      catalogSystemDisplayLabel('cassandra', { vertical: 'test', systemLabel: 'CA DROP' }),
    ).toBe('System A')
    expect(
      catalogSystemDisplayLabel('hr_alumni', {
        vertical: 'test',
        systemLabel: 'Alumni Google Sheet',
      }),
    ).toBe('System B')
    expect(
      catalogSystemDisplayLabel('hr_alumni', { vertical: 'people_hr' }),
    ).toBe('Alumni Google Sheet')
  })

  test('aggregateOwnerSystemWorkbenchSubsteps splits batch stages by connection, not fake requests', () => {
    const requestA = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
    const requestB = 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'
    const substeps = aggregateOwnerSystemWorkbenchSubsteps([
      {
        request_id: requestA,
        current_stage: 'review',
        vertical: 'test',
        connections: [
          { system: 'cassandra', system_label: 'CA DROP', current_stage: 'review' },
          { system: 'hr_alumni', system_label: 'Alumni Google Sheet', current_stage: 'match' },
        ],
      },
      {
        request_id: requestB,
        current_stage: 'fulfill',
        vertical: 'test',
        connections: [
          { system: 'cassandra', system_label: 'CA DROP', current_stage: 'fulfill' },
          { system: 'hr_alumni', system_label: 'Alumni Google Sheet', current_stage: 'review' },
        ],
      },
    ])
    const matching = substeps.filter((step) => step.parent === 'matching')
    expect(matching.map((step) => step.label)).toEqual(['System A', 'System B'])
    expect(matching.find((step) => step.key === 'matching-cassandra')?.statusLabel).toBe(
      '1 complete · 1 in progress',
    )
    expect(matching.find((step) => step.key === 'matching-hr_alumni')?.statusLabel).toBe(
      '2 in progress',
    )
    const fulfillment = substeps.filter((step) => step.parent === 'fulfillment')
    expect(fulfillment.find((step) => step.key === 'fulfillment-cassandra')?.statusLabel).toBe(
      '1 in progress · 1 not started',
    )
    expect(substeps.every((step) => !step.key.includes(requestA))).toBe(true)
    expect(substeps.filter((step) => step.parent === 'ingest')).toHaveLength(2)
  })

  test('aggregateStackWorkbenchChrome counts ingest substeps across members, not the first pipeline', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'download',
        intake_source: 'drop',
      },
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'promote',
        intake_source: 'drop',
      },
      {
        request_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
        current_stage: 'review',
        intake_source: 'drop',
      },
    ])
    expect(chrome.member_count).toBe(3)
    const ingest = Object.fromEntries(
      chrome.substeps
        .filter((step) => step.parent === 'ingest')
        .map((step) => [step.key, step.statusLabel]),
    )
    expect(ingest).toEqual({
      received: '3 complete',
      download: '2 complete · 1 in progress',
      land: '2 complete · 1 not started',
      promote: '1 complete · 1 in progress · 1 not started',
    })
    const matching = Object.fromEntries(
      chrome.substeps
        .filter((step) => step.parent === 'matching')
        .map((step) => [step.key, step.statusLabel]),
    )
    expect(matching).toEqual({
      match: '1 complete · 2 not started',
      review: '1 in progress · 2 not started',
    })
    const fulfill = chrome.substeps.find((step) => step.key === 'fulfill')
    const notice = chrome.substeps.find((step) => step.key === 'notice')
    expect(fulfill?.statusLabel).toBe('3 not started')
    expect(notice?.statusLabel).toBe('3 not started')
  })

  test('aggregateStackWorkbenchChrome dedupes the same request across vertical rows', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
        kind: 'matching',
      },
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
        kind: 'matching',
      },
    ])
    expect(chrome.member_count).toBe(1)
    expect(chrome.substeps.find((step) => step.key === 'review')?.statusLabel).toBe(
      '1 in progress',
    )
  })

  test('aggregateStackWorkbenchChrome keeps the first row when the same request_id later advances', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
      },
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'fulfill',
        intake_source: 'drop',
      },
    ])
    expect(chrome.member_count).toBe(1)
    expect(chrome.substeps.find((step) => step.key === 'review')?.statusLabel).toBe(
      '1 in progress',
    )
    expect(chrome.substeps.find((step) => step.key === 'fulfill')?.statusLabel).toBe(
      '1 not started',
    )
  })

  test('aggregateStackWorkbenchChrome treats empty or blank-id members as an empty stack', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: '   ',
        current_stage: 'fulfill',
        intake_source: 'drop',
      },
    ])
    expect(chrome.member_count).toBe(0)
    expect(chrome.current_stage).toBe('ingest')
    expect(chrome.substeps).toEqual([])
    expect(chrome.split_posture).toBe(false)
    expect(chrome.stages.map((stage) => [stage.stage, stage.status])).toEqual([
      ['ingest', 'not_started'],
      ['matching', 'not_started'],
      ['fulfillment', 'not_started'],
      ['notice', 'not_started'],
    ])
    expect(aggregateStackWorkbenchChrome([]).member_count).toBe(0)
  })

  test('aggregateStackWorkbenchChrome labels every DROP vs access notice path separately', () => {
    const drop = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'notice',
        intake_source: 'drop',
      },
    ])
    expect(drop.substeps.find((step) => step.key === 'notice')?.statusLabel).toBe(
      '1 in progress',
    )
    expect(drop.substeps.some((step) => step.key === 'delivery')).toBe(false)
    expect(drop.substeps.some((step) => step.key === 'template_notice')).toBe(false)

    const access = aggregateStackWorkbenchChrome([
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'delivery',
        intake_source: 'webform',
        request_type: 'access',
        kind: 'delivery',
      },
    ])
    expect(access.substeps.find((step) => step.key === 'delivery')?.statusLabel).toBe(
      '1 in progress',
    )
    expect(access.substeps.some((step) => step.key === 'notice')).toBe(false)
    expect(access.substeps.filter((step) => step.parent === 'ingest').map((s) => s.key)).toEqual(
      ['received', 'triage'],
    )
  })

  test('aggregateStackWorkbenchChrome surfaces template_notice after fulfill on non-DROP delete', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'notice',
        intake_source: 'webform',
        request_type: 'delete',
      },
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'fulfill',
        intake_source: 'webform',
        request_type: 'opt_out',
      },
    ])
    const byKey = Object.fromEntries(
      chrome.substeps.map((step) => [step.key, step.statusLabel]),
    )
    expect(byKey.triage).toBe('2 complete')
    expect(byKey.fulfill).toBe('1 complete · 1 in progress')
    expect(byKey.template_notice).toBe('1 in progress')
    expect(chrome.substeps.some((step) => step.key === 'notice')).toBe(false)
    expect(chrome.substeps.some((step) => step.key === 'delivery')).toBe(false)
    expect(chrome.substeps.every((step) => (step.statusLabel ?? '').length > 0)).toBe(true)
  })

  test('aggregateStackWorkbenchChrome counts mixed DROP + access members without first-member collapse', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
      },
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'delivery',
        intake_source: 'webform',
        request_type: 'access',
        kind: 'delivery',
      },
    ])
    expect(chrome.member_count).toBe(2)
    const byKey = Object.fromEntries(
      chrome.substeps.map((step) => [step.key, step.statusLabel]),
    )
    expect(byKey).toMatchObject({
      received: '2 complete',
      download: '1 complete',
      land: '1 complete',
      promote: '1 complete',
      triage: '1 complete',
      match: '2 complete',
      review: '1 complete · 1 in progress',
      fulfill: '1 complete · 1 not started',
      notice: '1 not started',
      delivery: '1 in progress',
    })
    expect(Object.keys(byKey).sort()).toEqual(
      [
        'delivery',
        'download',
        'fulfill',
        'land',
        'match',
        'notice',
        'promote',
        'received',
        'review',
        'triage',
      ].sort(),
    )
    expect(chrome.substeps.every((step) => /\d+ /.test(step.statusLabel ?? ''))).toBe(true)
    expect(chrome.stages).toHaveLength(4)
  })

  test('aggregateStackWorkbenchChrome rolls waiting and failed current-substep statuses', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'notice',
        intake_source: 'drop',
        status: 'waiting',
      },
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'delivery',
        intake_source: 'webform',
        request_type: 'access',
        status: 'failed',
      },
      {
        request_id: 'cccccccc-cccc-cccc-cccc-cccccccccccc',
        current_stage: 'review',
        intake_source: 'drop',
        status: 'waiting',
      },
    ])
    expect(chrome.substeps.find((step) => step.key === 'notice')?.statusLabel).toBe(
      '1 waiting · 1 not started',
    )
    expect(chrome.substeps.find((step) => step.key === 'delivery')?.statusLabel).toBe(
      '1 failed',
    )
    expect(chrome.substeps.find((step) => step.key === 'review')?.statusLabel).toBe(
      '2 complete · 1 waiting',
    )
    expect(
      formatStackSubstepCounts({ complete: 8, waiting: 1, failed: 1, in_progress: 2 }),
    ).toBe('8 complete · 2 in progress · 1 waiting · 1 failed')
  })

  test('aggregateStackWorkbenchChrome marks split_posture when matching lags fulfillment', () => {
    const chrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
      },
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'fulfill',
        intake_source: 'drop',
      },
    ])
    expect(chrome.split_posture).toBe(true)
    expect(chrome.stages.find((stage) => stage.stage === 'matching')?.status).toBe(
      'in_progress',
    )
    expect(chrome.stages.find((stage) => stage.stage === 'fulfillment')?.status).toBe(
      'in_progress',
    )
    expect(chrome.substeps.find((step) => step.key === 'review')?.statusLabel).toBe(
      '1 complete · 1 in progress',
    )
    expect(chrome.substeps.find((step) => step.key === 'fulfill')?.statusLabel).toBe(
      '1 in progress · 1 not started',
    )
  })

  test('preferStackChromeStages uses stack rollups once a stack has more than one request', () => {
    const stackChrome = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
      },
      {
        request_id: 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
        current_stage: 'fulfill',
        intake_source: 'drop',
      },
    ])
    const apiFirstMemberStages = [
      {
        stage: 'ingest' as const,
        label: 'Ingest',
        status: 'complete' as const,
        blocker: null,
      },
      {
        stage: 'matching' as const,
        label: 'Matching',
        status: 'in_progress' as const,
        blocker: 'first-member-only',
      },
      {
        stage: 'fulfillment' as const,
        label: 'Fulfillment',
        status: 'not_started' as const,
        blocker: null,
      },
      {
        stage: 'notice' as const,
        label: 'Notice',
        status: 'not_started' as const,
        blocker: null,
      },
    ]
    expect(preferStackChromeStages(apiFirstMemberStages, stackChrome)).toBe(stackChrome.stages)
    expect(preferStackChromeStages(apiFirstMemberStages, stackChrome)[1]?.blocker).toBeNull()

    const single = aggregateStackWorkbenchChrome([
      {
        request_id: 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
        current_stage: 'review',
        intake_source: 'drop',
      },
    ])
    expect(preferStackChromeStages(apiFirstMemberStages, single)).toBe(apiFirstMemberStages)
    expect(preferStackChromeStages(undefined, single)).toBe(single.stages)
    expect(preferStackChromeStages(apiFirstMemberStages, null)).toBe(apiFirstMemberStages)
    expect(preferStackChromeStages(undefined, undefined)).toEqual([])
  })
})
