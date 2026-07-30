import { Link } from '@tanstack/react-router'

import {
  JOURNEY_CHROME_VARIANTS,
  JourneyChromeProbe,
  type JourneyChromeVariantId,
} from '@/components/dev/JourneyChromeProbes'

const VARIANT_IDS = new Set(JOURNEY_CHROME_VARIANTS.map((v) => v.id))

function isVariantId(value: string): value is JourneyChromeVariantId {
  return VARIANT_IDS.has(value as JourneyChromeVariantId)
}

/** Temporary brainstorm lab — remove after journey chrome decision. */
export function JourneyChromeVariantPage({ variant }: { variant: string }) {
  if (!isVariantId(variant)) {
    return (
      <section className="space-y-3">
        <p className="text-sm text-ink">Unknown journey chrome variant: {variant}</p>
        <Link to="/dev/journey-chrome" className="text-sm underline underline-offset-2">
          Back to lab
        </Link>
      </section>
    )
  }
  return <JourneyChromeProbe variant={variant} />
}
