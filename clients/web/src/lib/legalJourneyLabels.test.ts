// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  COARSE_STAGE_ORDER,
  NOTICE_APPROVAL,
  actionReasonLabel,
  queueStatusLabel,
  stageLabel,
  stageReachLabel,
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
})
