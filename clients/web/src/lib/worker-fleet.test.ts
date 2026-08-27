// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import type { FleetWorkersPayload } from './api'
import {
  attemptTableForWorker,
  buildJobFilterOptions,
  formatMonthDaysInput,
  formatScheduleCadence,
  orderedWorkerKeys,
  parseMonthDaysInput,
  resolveAttemptColumns,
  supportsUnifiedRuns,
  workerByKey,
  workerDisplayLabel,
  workersSupportingUnifiedRuns,
} from './worker-fleet'

const SAMPLE: FleetWorkersPayload = {
  discovery_mode: 'gcp',
  discovery_warnings: [],
  workers: [
    {
      worker_key: 'matching',
      label: 'Matching',
      deployed: true,
      scheduled: true,
      service_name: 'matching-dev',
      base_url: null,
      sources: ['cloud_run', 'scheduler'],
      schedule_job_keys: ['matching'],
      attempt_table: 'matching_attempts',
      health: { ok: true, status_code: 200 },
      supports_unified_runs: true,
    },
    {
      worker_key: 'mailchimp',
      label: 'Mailchimp',
      deployed: true,
      scheduled: false,
      service_name: 'mailchimp-dev',
      base_url: null,
      sources: ['cloud_run'],
      schedule_job_keys: [],
      attempt_table: 'mailchimp_attempts',
      health: { ok: false, status_code: 503 },
    },
  ],
}

describe('worker-fleet helpers', () => {
  test('orderedWorkerKeys preserves API order', () => {
    expect(orderedWorkerKeys(SAMPLE)).toEqual(['matching', 'mailchimp'])
  })

  test('workerByKey + attemptTableForWorker', () => {
    expect(workerByKey(SAMPLE, 'mailchimp')?.label).toBe('Mailchimp')
    expect(attemptTableForWorker(SAMPLE, 'matching')).toBe('matching_attempts')
    expect(attemptTableForWorker(SAMPLE, 'missing')).toBeNull()
  })

  test('buildJobFilterOptions includes All + discovery labels', () => {
    expect(buildJobFilterOptions(SAMPLE)).toEqual([
      { value: '', label: 'All workers' },
      { value: 'matching', label: 'Matching' },
      { value: 'mailchimp', label: 'Mailchimp' },
    ])
  })

  test('supportsUnifiedRuns trusts API flag only', () => {
    expect(supportsUnifiedRuns(SAMPLE.workers[0]!)).toBe(true)
    expect(supportsUnifiedRuns(SAMPLE.workers[1]!)).toBe(false)
    expect(workersSupportingUnifiedRuns(SAMPLE).map((w) => w.worker_key)).toEqual(['matching'])
  })

  test('workerDisplayLabel prefers label', () => {
    expect(workerDisplayLabel(SAMPLE.workers[0]!)).toBe('Matching')
  })

  test('resolveAttemptColumns never invents', () => {
    expect(resolveAttemptColumns({})).toEqual([])
    expect(resolveAttemptColumns({ columns: ['id', 'status'] })).toEqual(['id', 'status'])
    expect(resolveAttemptColumns({ filterable_columns: ['step'] })).toEqual(['step'])
  })

  test('helper source has no hardcoded production worker allowlist', async () => {
    const src = await Bun.file(new URL('./worker-fleet.ts', import.meta.url)).text()
    expect(src).not.toMatch(/WORKER_ORDER/)
    expect(src).not.toMatch(/drop_connector_download/)
    expect(src).not.toMatch(/\['matching',\s*'fulfillment'/)
    expect(src).not.toMatch(/hash_index_refresh'/)
  })

  test('formatScheduleCadence and month-day input helpers', () => {
    expect(formatScheduleCadence('every_15_days')).toBe('Every 15 days')
    expect(formatScheduleCadence('on_1st_and_15th')).toBe('1st and 15th of the month')
    expect(parseMonthDaysInput('1, 15')).toEqual([1, 15])
    expect(parseMonthDaysInput('15 1 15')).toEqual([1, 15])
    expect(formatMonthDaysInput([1, 15])).toBe('1, 15')
  })
})
