// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  COARSE_STAGE_ORDER,
  NOTICE_APPROVAL,
  WORKBENCH_STAGE_ORDER,
  actionReasonLabel,
  deriveWorkbenchChromeFromOpsJourney,
  queueStatusLabel,
  stageLabel,
  stageReachLabel,
  verticalLabel,
  workbenchStageLabel,
  workbenchStatusLabel,
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

  test('verticalLabel maps live + coming-soon catalog entries', () => {
    expect(verticalLabel('communications')).toBe('Communications')
    expect(verticalLabel('people_hr')).toBe('People/HR')
    expect(verticalLabel('data')).toBe('Data')
    expect(verticalLabel('mailchimp')).toBe('Mailchimp')
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
})
