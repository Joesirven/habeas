export const PIPELINE_LIVE_LAB_VARIANT_IDS = [
  'a',
  'b',
  'c',
  'd',
  'e',
  'f',
  'g',
  'h',
] as const

export type PipelineLiveLabVariantId = (typeof PIPELINE_LIVE_LAB_VARIANT_IDS)[number]

export type PipelineLiveLabSearch = {
  v?: PipelineLiveLabVariantId
}

export function parsePipelineLiveLabSearch(
  search: Record<string, unknown>,
): PipelineLiveLabSearch {
  const raw = typeof search.v === 'string' ? search.v.trim().toLowerCase() : ''
  if ((PIPELINE_LIVE_LAB_VARIANT_IDS as readonly string[]).includes(raw)) {
    return { v: raw as PipelineLiveLabVariantId }
  }
  return { v: 'a' }
}

export const PIPELINE_LIVE_VARIANT_META: Record<
  PipelineLiveLabVariantId,
  { letter: string; title: string; blurb: string }
> = {
  a: {
    letter: 'A',
    title: 'Vertical rows',
    blurb:
      'Stage strip stays as-is; the selected stage gains a dense per-vertical table — Finished · In flight · Queued · Failed · % with inline micro-bars. Row order is catalog order, stable while counters tick.',
  },
  b: {
    letter: 'B',
    title: 'Stage × vertical matrix',
    blurb:
      'Rows = verticals, columns = Matching · Review · Fulfillment. The whole batch posture in one glance; any cell carrying failures is the story, grey cells are not-started or catalog-only.',
  },
  c: {
    letter: 'C',
    title: 'Sliced stage bar',
    blurb:
      'The selected stage becomes one bar sliced by vertical — equal-width slices, each filled to its own percent, labeled beneath. The lagging slice is the short one; no legend decoding.',
  },
  d: {
    letter: 'D',
    title: 'Journey clusters',
    blurb:
      'Each live vertical gets its own mini Matching → Review → Fulfillment rail with a current-stage pulse — the batch card speaks the request journey workbench language.',
  },
  e: {
    letter: 'E',
    title: 'Lead/lag ladder',
    blurb:
      'Verticals sorted least-complete-first while the stage runs, failures pinned above laggards. The top row is always what is holding the batch up.',
  },
  f: {
    letter: 'F',
    title: 'Review-first queue',
    blurb:
      'The Review tab as the operator’s work queue — per-vertical open-review counts heroed in amber, matching percent demoted to muted context.',
  },
  g: {
    letter: 'G',
    title: 'Fulfillment wave',
    blurb:
      'Per-vertical columns of compact state tiles (Queued · In flight · Failed · Finished) — fulfillment reads as a race, the laggard visible by shape before numbers.',
  },
  h: {
    letter: 'H',
    title: 'Posture strip + drill',
    blurb:
      'One collapsed line per stage — worst vertical percent plus “k of n verticals done” — expanding in place to per-vertical rows. Progressive disclosure, collapsed by default.',
  },
}
