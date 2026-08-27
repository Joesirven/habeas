export const MATCH_QUALITY_LAB_VARIANT_IDS = [
  'a',
  'b',
  'c',
  'd',
  'e',
  'f',
  'g',
  'h',
] as const

export type MatchQualityLabVariantId = (typeof MATCH_QUALITY_LAB_VARIANT_IDS)[number]

export type MatchQualityLabSearch = {
  v?: MatchQualityLabVariantId
}

export function parseMatchQualityLabSearch(
  search: Record<string, unknown>,
): MatchQualityLabSearch {
  const raw = typeof search.v === 'string' ? search.v.trim().toLowerCase() : ''
  if ((MATCH_QUALITY_LAB_VARIANT_IDS as readonly string[]).includes(raw)) {
    return { v: raw as MatchQualityLabVariantId }
  }
  return { v: 'a' }
}

export const MATCH_QUALITY_VARIANT_META: Record<
  MatchQualityLabVariantId,
  { letter: string; title: string; blurb: string }
> = {
  a: {
    letter: 'A',
    title: 'Dense KPI table',
    blurb:
      'Parameter rows × rate columns. Email 0% exact / any-hit is a fail Badge (breach).',
  },
  b: {
    letter: 'B',
    title: 'Alert rail',
    blurb: 'P0 banner for Email 0%, then the same dense rate table.',
  },
  c: {
    letter: 'C',
    title: 'Parameter matrix',
    blurb: 'Badge cells for exact, any-hit, and zero-hit — not a number grid.',
  },
  d: {
    letter: 'D',
    title: 'Funnel',
    blurb: 'Requests → any-hit → exact → distinct Habeas people (exact).',
  },
  e: {
    letter: 'E',
    title: 'Coverage vs match',
    blurb: 'Hash-index coverage on the left; parameter match rates on the right.',
  },
  f: {
    letter: 'F',
    title: 'Vertical split',
    blurb:
      'Data (DROP hash) live counts. Auth0: four snapshots, 0 hits. Catalog-only verticals stay grey.',
  },
  g: {
    letter: 'G',
    title: 'Running vs batch',
    blurb:
      'Dual rate columns. Batch is this 2026-08-26 snapshot. Running matches batch for now.',
  },
  h: {
    letter: 'H',
    title: 'Breaches-only ticker',
    blurb:
      'Email 0% and the email_hash coverage gap. Healthy Phone / NDZ rates stay behind a toggle.',
  },
}
