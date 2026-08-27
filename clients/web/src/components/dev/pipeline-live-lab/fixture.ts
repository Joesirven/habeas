/** Counts only — 2026-08-27 mid-flight batch snapshot. No PII. */

export type PipelineLiveStageId = 'matching' | 'review' | 'fulfillment'

export const PIPELINE_LIVE_STAGES: readonly { id: PipelineLiveStageId; label: string }[] = [
  { id: 'matching', label: 'Matching' },
  { id: 'review', label: 'Review' },
  { id: 'fulfillment', label: 'Fulfillment' },
]

export type StageCounts = {
  total: number
  open: number
  success: number
  failed: number
  inFlight: number
}

export type VerticalFixtureRow = {
  id: string
  label: string
  systems: readonly string[]
  live: boolean
  catalogOnly: boolean
  stages: Record<PipelineLiveStageId, StageCounts>
}

const ZERO: StageCounts = { total: 0, open: 0, success: 0, failed: 0, inFlight: 0 }

function counts(partial: Partial<StageCounts> & { total: number }): StageCounts {
  return { open: 0, success: 0, failed: 0, inFlight: 0, ...partial }
}

export const PIPELINE_LIVE_FIXTURE = {
  snapshotDate: '2026-08-27',
  batchLabel: 'Aug 27 · CA DROP',
  processId: 512,
  totalRequests: 1_843_251,
} as const

export const PIPELINE_LIVE_VERTICALS: readonly VerticalFixtureRow[] = [
  {
    id: 'data',
    label: 'Data',
    systems: ['DROP hash index'],
    live: true,
    catalogOnly: false,
    stages: {
      matching: counts({ total: 1_843_251, success: 1_843_251 }),
      review: counts({ total: 12_480, success: 9_068, open: 3_412 }),
      fulfillment: counts({ total: 9_068, success: 4_120, inFlight: 612, open: 4_336 }),
    },
  },
  {
    id: 'auth0',
    label: 'Auth0',
    systems: ['Auth0'],
    live: true,
    catalogOnly: false,
    stages: {
      matching: counts({
        total: 1_843_251,
        success: 1_105_950,
        inFlight: 18_400,
        failed: 212,
        open: 718_689,
      }),
      review: counts({ total: 96, success: 25, open: 71 }),
      fulfillment: counts({ total: 0 }),
    },
  },
  {
    id: 'communications',
    label: 'Communications',
    systems: ['Axios HQ'],
    live: true,
    catalogOnly: false,
    stages: {
      matching: counts({ total: 1_843_251, success: 1_843_248, failed: 3 }),
      review: counts({ total: 142, success: 104, open: 38 }),
      fulfillment: counts({ total: 104, open: 104 }),
    },
  },
  {
    id: 'people_hr',
    label: 'People/HR',
    systems: ['Lever', 'Paylocity'],
    live: true,
    catalogOnly: false,
    stages: {
      matching: counts({ total: 1_843_251, open: 1_843_251 }),
      review: counts({ total: 0 }),
      fulfillment: counts({ total: 0 }),
    },
  },
  {
    id: 'test',
    label: 'Test vertical',
    systems: ['System A', 'System B'],
    live: true,
    catalogOnly: false,
    stages: {
      matching: counts({ total: 240, success: 240 }),
      review: counts({ total: 6, success: 4, open: 2 }),
      fulfillment: counts({ total: 4, success: 4 }),
    },
  },
  {
    id: 'cassandra',
    label: 'Cassandra',
    systems: ['Cassandra'],
    live: false,
    catalogOnly: true,
    stages: { matching: { ...ZERO }, review: { ...ZERO }, fulfillment: { ...ZERO } },
  },
  {
    id: 'bizdev',
    label: 'BizDev',
    systems: ['BizDev'],
    live: false,
    catalogOnly: true,
    stages: { matching: { ...ZERO }, review: { ...ZERO }, fulfillment: { ...ZERO } },
  },
]

export const LIVE_VERTICALS: readonly VerticalFixtureRow[] = PIPELINE_LIVE_VERTICALS.filter(
  (row) => row.live,
)

export const CATALOG_ONLY_VERTICALS: readonly VerticalFixtureRow[] =
  PIPELINE_LIVE_VERTICALS.filter((row) => row.catalogOnly)

export function stagePercent(counts: StageCounts): number {
  if (counts.total <= 0) return 0
  return Math.round((counts.success / counts.total) * 100)
}

/** Worker-done = nothing left open and nothing in flight (failures do not block done). */
export function stageWorkerDone(counts: StageCounts): boolean {
  return counts.total > 0 && counts.open === 0 && counts.inFlight === 0
}

export function stageStarted(counts: StageCounts): boolean {
  return counts.success > 0 || counts.failed > 0 || counts.inFlight > 0
}

export function aggregateStage(stage: PipelineLiveStageId): StageCounts {
  const totals = { total: 0, open: 0, success: 0, failed: 0, inFlight: 0 }
  for (const vertical of LIVE_VERTICALS) {
    const countsForStage = vertical.stages[stage]
    totals.total += countsForStage.total
    totals.open += countsForStage.open
    totals.success += countsForStage.success
    totals.failed += countsForStage.failed
    totals.inFlight += countsForStage.inFlight
  }
  return totals
}

/** First stage (Matching → Review → Fulfillment order) with work that is not worker-done. */
export function verticalCurrentStage(vertical: VerticalFixtureRow): PipelineLiveStageId | null {
  for (const stage of PIPELINE_LIVE_STAGES) {
    const counts = vertical.stages[stage.id]
    if (counts.total > 0 && !stageWorkerDone(counts)) return stage.id
  }
  return null
}

export type StageVisual = {
  state: 'complete' | 'running' | 'queued' | 'idle'
  light: 'emerald' | 'sky' | 'amber' | 'red' | 'mute'
  pulse: boolean
}

export function stageVisual(counts: StageCounts): StageVisual {
  if (counts.total <= 0) return { state: 'idle', light: 'mute', pulse: false }
  if (counts.open === 0 && counts.inFlight === 0) {
    return { state: 'complete', light: counts.failed > 0 ? 'amber' : 'emerald', pulse: false }
  }
  if (counts.success === 0 && counts.failed === 0 && counts.inFlight === 0) {
    return { state: 'queued', light: 'sky', pulse: false }
  }
  return { state: 'running', light: 'emerald', pulse: true }
}

export function microBarTone(visual: StageVisual): 'navy' | 'emerald' | 'amber' {
  if (visual.state === 'complete') return visual.light === 'amber' ? 'amber' : 'emerald'
  return 'navy'
}

export function formatCount(value: number): string {
  return value.toLocaleString('en-US')
}

export function formatPercent(counts: StageCounts): string {
  if (counts.total <= 0) return '—'
  return `${stagePercent(counts)}%`
}
