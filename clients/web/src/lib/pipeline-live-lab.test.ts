// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import {
  CATALOG_ONLY_VERTICALS,
  PIPELINE_LIVE_FIXTURE,
  PIPELINE_LIVE_VERTICALS,
} from '../components/dev/pipeline-live-lab/fixture'
import {
  PIPELINE_LIVE_LAB_VARIANT_IDS,
  parsePipelineLiveLabSearch,
} from '../components/dev/pipeline-live-lab/types'

describe('parsePipelineLiveLabSearch', () => {
  test('defaults to a when v is missing or unknown', () => {
    expect(parsePipelineLiveLabSearch({})).toEqual({ v: 'a' })
    expect(parsePipelineLiveLabSearch({ v: 'z' })).toEqual({ v: 'a' })
    expect(parsePipelineLiveLabSearch({ v: 1 })).toEqual({ v: 'a' })
    expect(parsePipelineLiveLabSearch({ v: 'A' })).toEqual({ v: 'a' })
  })

  test('accepts eight variant ids a–h', () => {
    expect([...PIPELINE_LIVE_LAB_VARIANT_IDS]).toEqual([
      'a',
      'b',
      'c',
      'd',
      'e',
      'f',
      'g',
      'h',
    ])
    for (const id of PIPELINE_LIVE_LAB_VARIANT_IDS) {
      expect(parsePipelineLiveLabSearch({ v: id })).toEqual({ v: id })
    }
  })
})

function fixtureRow(id: string) {
  return PIPELINE_LIVE_VERTICALS.find((row) => row.id === id)
}

function collectStrings(value: unknown, out: string[] = []): string[] {
  if (typeof value === 'string') {
    out.push(value)
  } else if (Array.isArray(value)) {
    for (const item of value) collectStrings(item, out)
  } else if (value !== null && typeof value === 'object') {
    for (const item of Object.values(value as Record<string, unknown>)) {
      collectStrings(item, out)
    }
  }
  return out
}

function collectKeys(value: unknown): string[] {
  const keys: string[] = []
  JSON.stringify(value, (key, nested) => {
    keys.push(key)
    return nested
  })
  return keys
}

describe('pipeline-live fixture — counts only, no PII', () => {
  const payload = { fixture: PIPELINE_LIVE_FIXTURE, verticals: PIPELINE_LIVE_VERTICALS }

  test('no emails, 64-hex hashes, or dwid fields anywhere in the lab payload', () => {
    const strings = collectStrings(payload)
    expect(strings.some((value) => value.includes('@'))).toBe(false)
    expect(strings.some((value) => /\b[0-9a-f]{64}\b/i.test(value))).toBe(false)
    expect(collectKeys(payload).some((key) => /dwid/i.test(key))).toBe(false)
  })

  test('catalog system label DROP hash index is allowed — it is a name, not a hash', () => {
    const strings = collectStrings(PIPELINE_LIVE_VERTICALS)
    expect(strings).toContain('DROP hash index')
    expect(strings.some((value) => value.includes('@'))).toBe(false)
    expect(strings.some((value) => /\b[0-9a-f]{64}\b/i.test(value))).toBe(false)
  })

  test('batch header is a dated counts snapshot; Test vertical shows System A / System B', () => {
    expect(PIPELINE_LIVE_FIXTURE.snapshotDate).toBe('2026-08-27')
    const testVertical = fixtureRow('test')
    expect(testVertical).toBeDefined()
    expect(testVertical?.systems).toContain('System A')
    expect(testVertical?.systems).toContain('System B')
  })
})

describe('pipeline-live fixture — catalog-only grey concept', () => {
  test('cassandra and bizdev are present, not live, and flagged catalog-only', () => {
    for (const id of ['cassandra', 'bizdev']) {
      const row = fixtureRow(id)
      expect(row).toBeDefined()
      expect(row?.live).toBe(false)
      expect(row?.catalogOnly).toBe(true)
    }
    expect(CATALOG_ONLY_VERTICALS.map((row) => row.id).sort()).toEqual([
      'bizdev',
      'cassandra',
    ])
  })

  test('data, auth0, communications, people_hr are live and not catalog-only', () => {
    for (const id of ['data', 'auth0', 'communications', 'people_hr']) {
      const row = fixtureRow(id)
      expect(row).toBeDefined()
      expect(row?.live).toBe(true)
      expect(row?.catalogOnly).toBe(false)
    }
  })
})
