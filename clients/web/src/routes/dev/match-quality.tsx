// @ts-nocheck — /dev paths are omitted from the product router Register.
/**
 * Temporary lab — eight match-quality layouts. Not primary nav.
 * Tear down after pick. Fixture counts only: no PII.
 */
import { Link, useNavigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { VariantADenseKpi } from '@/components/dev/match-quality-lab/variant-a-dense-kpi'
import { VariantBAlertRail } from '@/components/dev/match-quality-lab/variant-b-alert-rail'
import { VariantCParameterMatrix } from '@/components/dev/match-quality-lab/variant-c-parameter-matrix'
import { VariantDFunnel } from '@/components/dev/match-quality-lab/variant-d-funnel'
import { VariantECoverageVsMatch } from '@/components/dev/match-quality-lab/variant-e-coverage-vs-match'
import { VariantFVerticalSplit } from '@/components/dev/match-quality-lab/variant-f-vertical-split'
import { VariantGRunningVsBatch } from '@/components/dev/match-quality-lab/variant-g-running-vs-batch'
import { VariantHBreachesOnly } from '@/components/dev/match-quality-lab/variant-h-breaches-only'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  MATCH_QUALITY_LAB_VARIANT_IDS,
  MATCH_QUALITY_VARIANT_META,
  parseMatchQualityLabSearch,
  type MatchQualityLabSearch,
  type MatchQualityLabVariantId,
} from '@/components/dev/match-quality-lab/types'

export {
  MATCH_QUALITY_LAB_VARIANT_IDS,
  parseMatchQualityLabSearch,
  type MatchQualityLabSearch,
  type MatchQualityLabVariantId,
}

const VARIANT_VIEWS: Record<MatchQualityLabVariantId, () => ReactNode> = {
  a: () => <VariantADenseKpi />,
  b: () => <VariantBAlertRail />,
  c: () => <VariantCParameterMatrix />,
  d: () => <VariantDFunnel />,
  e: () => <VariantECoverageVsMatch />,
  f: () => <VariantFVerticalSplit />,
  g: () => <VariantGRunningVsBatch />,
  h: () => <VariantHBreachesOnly />,
}

export function MatchQualityLabPage({
  search,
}: {
  search?: MatchQualityLabSearch
}) {
  const navigate = useNavigate()
  const variant = search?.v ?? 'a'
  const meta = MATCH_QUALITY_VARIANT_META[variant]
  const View = VARIANT_VIEWS[variant]

  return (
    <section className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="space-y-1">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Temporary · not in primary nav
        </p>
        <h1 className="text-xl font-semibold text-ink">Match quality</h1>
        <p className="max-w-3xl text-sm text-ink-soft">
          Eight fixture layouts for DROP hash match rates (2026-08-26 prod snapshot, counts
          only). Default is <strong>A · Dense KPI table</strong>. Switch with the control
          below or <span className="font-mono text-xs">?v=a</span> through{' '}
          <span className="font-mono text-xs">?v=h</span>.{' '}
          <Link className="text-habeas-navy underline-offset-2 hover:underline" to="/dev">
            All labs
          </Link>
          .
        </p>
      </header>

      <Tabs
        value={variant}
        onValueChange={(next) => {
          if (!(MATCH_QUALITY_LAB_VARIANT_IDS as readonly string[]).includes(next)) return
          void navigate({
            to: '/dev/match-quality',
            search: { v: next as MatchQualityLabVariantId },
            replace: true,
          })
        }}
      >
        <TabsList className="flex h-auto min-h-8 w-full flex-wrap justify-start gap-0.5">
          {MATCH_QUALITY_LAB_VARIANT_IDS.map((id) => (
            <TabsTrigger key={id} value={id} className="px-2">
              {MATCH_QUALITY_VARIANT_META[id].letter} {MATCH_QUALITY_VARIANT_META[id].title}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <p className="text-xs leading-relaxed text-mute">{meta.blurb}</p>
      {View()}
    </section>
  )
}
