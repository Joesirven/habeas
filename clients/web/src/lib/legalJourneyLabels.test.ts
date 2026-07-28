// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  COARSE_STAGE_ORDER,
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
    expect(stageLabel('data_owner_review')).toBe('data owner review')
    expect(stageLabel('legal_review')).toBe('legal / pre-fulfillment')
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
})
