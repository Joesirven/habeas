import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { HabeasLogoImg, HabeasOrbArrow, DppTitle, PresentationLine } from '../shared'
import { SPLASH_PALETTE } from '../palette'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './batch-e.css'

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
    const t1 = window.setTimeout(() => setPhase('hold'), 900)
    const t2 = window.setTimeout(() => setPhase('out'), durationMs - 500)
    const t3 = window.setTimeout(() => onDone?.(), durationMs)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [autoFinish, durationMs, onDone])

  return (
    <div
      className={`splash-e-stage ${variantClass} splash-e-phase-${phase} ${className}`}
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

/** Deep zoom: distant mark races to full frame, then DPP fades in. */
function V13(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-e-v13" durationMs={4000} {...props}>
      <div className="splash-e-v13-field" aria-hidden>
        <span className="splash-e-v13-ring splash-e-v13-ring-a" />
        <span className="splash-e-v13-ring splash-e-v13-ring-b" />
        <span className="splash-e-v13-ring splash-e-v13-ring-c" />
        <span className="splash-e-v13-horizon" />
      </div>
      <div className="splash-e-v13-zoom">
        <HabeasLogoImg className="splash-e-v13-mark" />
      </div>
      <div className="splash-e-v13-lock">
        <DppTitle className="splash-e-v13-dpp" />
        <PresentationLine className="splash-e-v13-tag" />
      </div>
    </Stage>
  )
}

/** Wordmark drops with overshoot; blue flash sting on impact; DPP follows. */
function V14(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-e-v14" durationMs={3600} {...props}>
      <div className="splash-e-v14-sting" aria-hidden />
      <div className="splash-e-v14-bars" aria-hidden>
        <span />
        <span />
        <span />
      </div>
      <div className="splash-e-v14-drop">
        <HabeasLogoImg className="splash-e-v14-mark" />
      </div>
      <div className="splash-e-v14-card">
        <DppTitle className="splash-e-v14-dpp" />
        <PresentationLine className="splash-e-v14-tag" />
      </div>
    </Stage>
  )
}

/** Orb flies horizontal; title card locks center after the pass. */
function V15(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-e-v15" durationMs={4000} {...props}>
      <div className="splash-e-v15-trail" aria-hidden>
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="splash-e-v15-flyer">
        <HabeasOrbArrow size={128} />
      </div>
      <div className="splash-e-v15-title">
        <HabeasLogoImg className="splash-e-v15-mark" />
        <DppTitle className="splash-e-v15-dpp" />
        <PresentationLine className="splash-e-v15-tag" />
      </div>
    </Stage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  13: V13,
  14: V14,
  15: V15,
}

export const batchE: SplashVariantModule = {
  meta: [
    { id: 13, name: 'Fanfare Zoom', blurb: 'Deep zoom into Habeas mark.' },
    { id: 14, name: 'Sting Drop', blurb: 'Wordmark drops with settle.' },
    { id: 15, name: 'Flyby Orb', blurb: 'Orb flies past; title locks.' },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[13](props),
}
