/** Counts only — 2026-08-26 prod snapshot. No PII. */

export type ParameterId = 'email' | 'ndz' | 'phone'

export type ParameterRow = {
  id: ParameterId
  label: string
  requests: number
  exact: number
  anyHit: number
  multi: number
  breach: boolean
}

export const MATCH_QUALITY_PARAMETERS: readonly ParameterRow[] = [
  {
    id: 'email',
    label: 'Email',
    requests: 607_239,
    exact: 0,
    anyHit: 0,
    multi: 0,
    breach: true,
  },
  {
    id: 'ndz',
    label: 'NDZ',
    requests: 746_115,
    exact: 407_913,
    anyHit: 411_655,
    multi: 3_742,
    breach: false,
  },
  {
    id: 'phone',
    label: 'Phone',
    requests: 489_897,
    exact: 236_402,
    anyHit: 304_305,
    multi: 67_903,
    breach: false,
  },
]

export const MATCH_QUALITY_FIXTURE = {
  snapshotDate: '2026-08-26',
  totalRequests: 1_843_251,
  distinctPeopleExact: 442_624,
  intakeSource: 'drop',
  requestorState: 'CA',
  requestType: 'delete',
  coverage: [
    {
      mart: 'email_hash',
      states: 0,
      note: 'CA unknown / likely 0',
      gap: true,
    },
    {
      mart: 'phone_hash',
      states: 51,
      note: '51 states',
      gap: false,
    },
    {
      mart: 'ndz_hash',
      states: 51,
      note: '51 states',
      gap: false,
    },
  ],
  auth0Snapshots: [
    { id: 'snap-1', label: 'Snapshot 1', hits: 0 },
    { id: 'snap-2', label: 'Snapshot 2', hits: 0 },
    { id: 'snap-3', label: 'Snapshot 3', hits: 0 },
    { id: 'snap-4', label: 'Snapshot 4', hits: 0 },
  ],
  catalogOnly: [
    { id: 'axios_hq', label: 'Axios HQ', vertical: 'Communications' },
    { id: 'lever', label: 'Lever', vertical: 'People/HR' },
    { id: 'paylocity', label: 'Paylocity', vertical: 'People/HR' },
    { id: 'cassandra', label: 'Cassandra', vertical: 'Infrastructure' },
  ],
} as const

export function parameterZeroHit(row: ParameterRow): number {
  return Math.max(0, row.requests - row.anyHit)
}

export function funnelTotals() {
  const anyHit = MATCH_QUALITY_PARAMETERS.reduce((sum, row) => sum + row.anyHit, 0)
  const exact = MATCH_QUALITY_PARAMETERS.reduce((sum, row) => sum + row.exact, 0)
  return {
    requests: MATCH_QUALITY_FIXTURE.totalRequests,
    anyHit,
    exact,
    people: MATCH_QUALITY_FIXTURE.distinctPeopleExact,
  }
}

export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

export function formatRate(hits: number, requests: number): string {
  if (requests <= 0) return '—'
  if (hits === 0) return '0%'
  const pct = (hits / requests) * 100
  if (pct > 0 && pct < 0.05) return '<0.1%'
  return `${pct.toFixed(1)}%`
}

export function rateTone(hits: number, requests: number): 'fail' | 'ok' | 'wait' {
  if (requests <= 0) return 'wait'
  if (hits === 0) return 'fail'
  return 'ok'
}
