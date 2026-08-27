// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import { formatStageEstLabel, stageWorkerDone } from './stage-live'

describe('stageWorkerDone', () => {
  test('done only when nothing open and nothing in flight', () => {
    expect(stageWorkerDone({ open: 0, in_flight: 0 })).toBe(true)
  })

  test('open work means not done', () => {
    expect(stageWorkerDone({ open: 1, in_flight: 0 })).toBe(false)
  })

  test('in-flight work means not done even with zero open', () => {
    expect(stageWorkerDone({ open: 0, in_flight: 3 })).toBe(false)
  })

  test('both open and in-flight means not done', () => {
    expect(stageWorkerDone({ open: 5, in_flight: 2 })).toBe(false)
  })
})

describe('formatStageEstLabel', () => {
  test('names the stage with percent and err (plan A6)', () => {
    expect(formatStageEstLabel('Matching', 82, 1)).toBe('Matching 82% · err 1%')
  })

  test('rounds percent and err to whole numbers', () => {
    expect(formatStageEstLabel('Review', 82.4, 0.6)).toBe('Review 82% · err 1%')
  })

  test('keeps a zero err clause — 0% is informative on the ops console', () => {
    expect(formatStageEstLabel('Matching', 100, 0)).toBe('Matching 100% · err 0%')
  })

  test('omits the err clause when err is null or non-finite', () => {
    expect(formatStageEstLabel('Matching', 50, null)).toBe('Matching 50%')
    expect(formatStageEstLabel('Matching', 50, Number.NaN)).toBe('Matching 50%')
  })

  test('unknown percent renders an em dash', () => {
    expect(formatStageEstLabel('Fulfillment', null)).toBe('Fulfillment —')
    expect(formatStageEstLabel('Fulfillment', undefined)).toBe('Fulfillment —')
    expect(formatStageEstLabel('Fulfillment', Number.NaN)).toBe('Fulfillment —')
  })

  test('unknown percent still carries a known err', () => {
    expect(formatStageEstLabel('Fulfillment', null, 2)).toBe('Fulfillment — · err 2%')
  })
})
