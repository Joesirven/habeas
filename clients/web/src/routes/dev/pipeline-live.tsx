// @ts-nocheck — /dev paths are omitted from the product router Register.
/**
 * Temporary lab — eight multi-vertical pipeline live-progress layouts.
 * Not primary nav. Tear down after pick. Fixture counts only: no PII.
 */
import { Link, useNavigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { VariantAVerticalRows } from '@/components/dev/pipeline-live-lab/variant-a-vertical-rows'
import { VariantBMatrix } from '@/components/dev/pipeline-live-lab/variant-b-matrix'
import { VariantCSlicedBar } from '@/components/dev/pipeline-live-lab/variant-c-sliced-bar'
import { VariantDJourneyClusters } from '@/components/dev/pipeline-live-lab/variant-d-journey-clusters'
import { VariantELeadLag } from '@/components/dev/pipeline-live-lab/variant-e-lead-lag'
import { VariantFReviewQueue } from '@/components/dev/pipeline-live-lab/variant-f-review-queue'
import { VariantGFulfillmentWave } from '@/components/dev/pipeline-live-lab/variant-g-fulfillment-wave'
import { VariantHPostureStrip } from '@/components/dev/pipeline-live-lab/variant-h-posture-strip'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  PIPELINE_LIVE_LAB_VARIANT_IDS,
  PIPELINE_LIVE_VARIANT_META,
  parsePipelineLiveLabSearch,
  type PipelineLiveLabSearch,
  type PipelineLiveLabVariantId,
} from '@/components/dev/pipeline-live-lab/types'

export {
  PIPELINE_LIVE_LAB_VARIANT_IDS,
  parsePipelineLiveLabSearch,
  type PipelineLiveLabSearch,
  type PipelineLiveLabVariantId,
}

const VARIANT_VIEWS: Record<PipelineLiveLabVariantId, () => ReactNode> = {
  a: () => <VariantAVerticalRows />,
  b: () => <VariantBMatrix />,
  c: () => <VariantCSlicedBar />,
  d: () => <VariantDJourneyClusters />,
  e: () => <VariantELeadLag />,
  f: () => <VariantFReviewQueue />,
  g: () => <VariantGFulfillmentWave />,
  h: () => <VariantHPostureStrip />,
}

export function PipelineLiveLabPage({
  search,
}: {
  search?: PipelineLiveLabSearch
}) {
  const navigate = useNavigate()
  const variant = search?.v ?? 'a'
  const meta = PIPELINE_LIVE_VARIANT_META[variant]
  const View = VARIANT_VIEWS[variant]

  return (
    <section className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="space-y-1">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Temporary · not in primary nav
        </p>
        <h1 className="text-xl font-semibold text-ink">Pipeline live progress</h1>
        <p className="max-w-3xl text-sm text-ink-soft">
          Eight fixture layouts for multi-vertical matching / review / fulfillment posture on the
          expanded batch card (2026-08-27 mid-flight snapshot, counts only). Default is{' '}
          <strong>A · Vertical rows</strong>. Switch with the control below or{' '}
          <span className="font-mono text-xs">?v=a</span> through{' '}
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
          if (!(PIPELINE_LIVE_LAB_VARIANT_IDS as readonly string[]).includes(next)) return
          void navigate({
            to: '/dev/pipeline-live',
            search: { v: next as PipelineLiveLabVariantId },
            replace: true,
          })
        }}
      >
        <TabsList className="flex h-auto min-h-8 w-full flex-wrap justify-start gap-0.5">
          {PIPELINE_LIVE_LAB_VARIANT_IDS.map((id) => (
            <TabsTrigger key={id} value={id} className="px-2">
              {PIPELINE_LIVE_VARIANT_META[id].letter} {PIPELINE_LIVE_VARIANT_META[id].title}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <p className="text-xs leading-relaxed text-mute">{meta.blurb}</p>
      {View()}
    </section>
  )
}
