// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  MATCH_QUALITY_LAB_VARIANT_IDS,
  parseMatchQualityLabSearch,
} from '../components/dev/match-quality-lab/types'

describe('parseMatchQualityLabSearch', () => {
  test('defaults to a when v is missing or unknown', () => {
    expect(parseMatchQualityLabSearch({})).toEqual({ v: 'a' })
    expect(parseMatchQualityLabSearch({ v: 'z' })).toEqual({ v: 'a' })
    expect(parseMatchQualityLabSearch({ v: 1 })).toEqual({ v: 'a' })
    expect(parseMatchQualityLabSearch({ v: 'A' })).toEqual({ v: 'a' })
  })

  test('accepts eight variant ids a–h', () => {
    expect([...MATCH_QUALITY_LAB_VARIANT_IDS]).toEqual([
      'a',
      'b',
      'c',
      'd',
      'e',
      'f',
      'g',
      'h',
    ])
    for (const id of MATCH_QUALITY_LAB_VARIANT_IDS) {
      expect(parseMatchQualityLabSearch({ v: id })).toEqual({ v: id })
    }
  })
})
