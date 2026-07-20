import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { HabeasLogoImg, HabeasOrbArrow, DppTitle, PresentationLine } from '../shared'
import { SPLASH_PALETTE } from '../palette'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './batch-c.css'

function Stage({
  variantClass,
  children,
  autoFinish,
  durationMs = 3800,
  onDone,
  className = '',
}: SplashStageProps & { variantClass: string; children: ReactNode }) {
  const [phase, setPhase] = useState<'in' | 'hold' | 'out'>('in')
  useEffect(() => {
    if (!autoFinish) return
    const holdAt = Math.min(700, Math.floor(durationMs * 0.18))
    const outAt = durationMs - 550
    const t1 = window.setTimeout(() => setPhase('hold'), holdAt)
    const t2 = window.setTimeout(() => setPhase('out'), outAt)
    const t3 = window.setTimeout(() => onDone?.(), durationMs)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [autoFinish, durationMs, onDone])

  return (
    <div
      className={`splash-c-stage ${variantClass} splash-c-phase-${phase} ${className}`}
      style={
        {
          '--cat-black': SPLASH_PALETTE.black,
          '--cat-silver': SPLASH_PALETTE.silver,
          '--cat-silver-hi': SPLASH_PALETTE.silverHi,
          '--cat-blue': SPLASH_PALETTE.blue,
          '--cat-blue-deep': SPLASH_PALETTE.blueDeep,
        } as CSSProperties
      }
      role="status"
      aria-label="CataPriv Platform loading"
    >
      {children}
    </div>
  )
}

/** Soft PBS — quiet station card: generous space, gentle fade-up, faint underline. */
function V7(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-c-v7" {...props} durationMs={props.durationMs ?? 3600}>
      <div className="splash-c-v7-field" aria-hidden />
      <div className="splash-c-v7-card">
        <HabeasLogoImg className="splash-c-v7-logo" />
        <span className="splash-c-v7-rule" aria-hidden />
        <DppTitle className="splash-c-v7-dpp" />
        <PresentationLine className="splash-c-v7-tag" />
      </div>
    </Stage>
  )
}

/** Crossfade Mark — orb dissolves into wordmark, then DPP arrives later. */
function V8(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-c-v8" {...props} durationMs={props.durationMs ?? 4200}>
      <div className="splash-c-v8-stack">
        <div className="splash-c-v8-mark-slot">
          <HabeasOrbArrow size={112} />
          <HabeasLogoImg className="splash-c-v8-logo" />
        </div>
        <DppTitle className="splash-c-v8-dpp" />
        <PresentationLine className="splash-c-v8-tag" />
      </div>
    </Stage>
  )
}

/** Lower Third — logo holds; DPP chyron slides up from the bottom rail. */
function V9(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-c-v9" {...props} durationMs={props.durationMs ?? 3900}>
      <div className="splash-c-v9-frame">
        <div className="splash-c-v9-logo-zone">
          <HabeasLogoImg className="splash-c-v9-logo" />
        </div>
        <div className="splash-c-v9-chyron">
          <span className="splash-c-v9-bar" aria-hidden />
          <div className="splash-c-v9-copy">
            <DppTitle className="splash-c-v9-dpp" />
            <PresentationLine className="splash-c-v9-tag" />
          </div>
        </div>
      </div>
    </Stage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  7: V7,
  8: V8,
  9: V9,
}

export const batchC: SplashVariantModule = {
  meta: [
    { id: 7, name: 'Soft PBS', blurb: 'Quiet fade; polite station card.' },
    { id: 8, name: 'Crossfade Mark', blurb: 'Orb dissolves into wordmark.' },
    { id: 9, name: 'Lower Third', blurb: 'DPP slides up like a broadcast chyron.' },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[7](props),
}
