import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { HabeasLogoImg, DppTitle, PixelCat, PresentationLine } from '../shared'
import { SPLASH_PALETTE } from '../palette'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './batch-f.css'

function Stage({
  variantClass,
  children,
  autoFinish,
  durationMs = 3400,
  onDone,
  className = '',
}: SplashStageProps & { variantClass: string; children: ReactNode }) {
  const [phase, setPhase] = useState<'in' | 'hold' | 'out'>('in')
  useEffect(() => {
    if (!autoFinish) return
    const t1 = window.setTimeout(() => setPhase('hold'), 500)
    const t2 = window.setTimeout(() => setPhase('out'), durationMs - 450)
    const t3 = window.setTimeout(() => onDone?.(), durationMs)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [autoFinish, durationMs, onDone])

  return (
    <div
      className={`splash-f-stage ${variantClass} splash-f-phase-${phase} ${className}`}
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

/** v16 — engineering test pattern: circle + crosshairs dissolve into title card. */
function V16(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-f-v16" {...props}>
      <div className="splash-f-v16-bars" aria-hidden>
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="splash-f-v16-pattern" aria-hidden>
        <div className="splash-f-v16-circle" />
        <div className="splash-f-v16-cross-h" />
        <div className="splash-f-v16-cross-v" />
        <div className="splash-f-v16-dot" />
      </div>
      <div className="splash-f-v16-card">
        <HabeasLogoImg />
        <DppTitle />
        <PresentationLine />
      </div>
    </Stage>
  )
}

/** v17 — cheap late-night starfield bumper; logo flies in from deep space. */
function V17(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-f-v17" {...props}>
      <div className="splash-f-v17-field" aria-hidden>
        {Array.from({ length: 36 }, (_, i) => (
          <span key={i} className={`splash-f-v17-star splash-f-v17-star-${i % 6}`} />
        ))}
      </div>
      <div className="splash-f-v17-warp" aria-hidden />
      <div className="splash-f-v17-card">
        <HabeasLogoImg />
        <DppTitle />
        <PresentationLine />
      </div>
    </Stage>
  )
}

/** v18 — VHS tracking tears / jitter, then lock to a clean card. */
function V18(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-f-v18" {...props}>
      <div className="splash-f-v18-noise" aria-hidden />
      <div className="splash-f-v18-tears" aria-hidden>
        <span />
        <span />
        <span />
        <span />
      </div>
      <div className="splash-f-v18-scan" aria-hidden />
      <div className="splash-f-v18-card">
        <HabeasLogoImg />
        <DppTitle />
        <PresentationLine />
      </div>
    </Stage>
  )
}

/** v19 — vertical-hold roll / channel flip into the title. */
function V19(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-f-v19" {...props}>
      <div className="splash-f-v19-chiron" aria-hidden>
        CH 03 → 07
      </div>
      <div className="splash-f-v19-roll">
        <div className="splash-f-v19-ghost" aria-hidden>
          <HabeasLogoImg />
          <DppTitle />
        </div>
        <div className="splash-f-v19-card">
          <HabeasLogoImg />
          <DppTitle />
          <PresentationLine />
        </div>
        <div className="splash-f-v19-ghost splash-f-v19-ghost-b" aria-hidden>
          <HabeasLogoImg />
          <DppTitle />
        </div>
      </div>
      <div className="splash-f-v19-flash" aria-hidden />
    </Stage>
  )
}

/** v20 — cartoon bounce-drop + PixelCat lick settle (not a network sting). */
function V20(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-f-v20" {...props}>
      <div className="splash-f-v20-floor" aria-hidden />
      <div className="splash-f-v20-stack">
        <div className="splash-f-v20-logo-wrap">
          <HabeasLogoImg />
        </div>
        <div className="splash-f-v20-cat">
          <PixelCat size={72} />
        </div>
        <div className="splash-f-v20-copy">
          <DppTitle />
          <PresentationLine />
        </div>
      </div>
    </Stage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  16: V16,
  17: V17,
  18: V18,
  19: V19,
  20: V20,
}

export const batchF: SplashVariantModule = {
  meta: [
    { id: 16, name: 'Test Pattern', blurb: 'Circle/bars morph to logo.' },
    { id: 17, name: 'Starfield In', blurb: 'Cheap space bumper fly-in.' },
    { id: 18, name: 'VHS Recover', blurb: 'Tracking lines then lock.' },
    { id: 19, name: 'Channel Flip', blurb: 'Vertical hold roll to card.' },
    { id: 20, name: 'Bounce Settle', blurb: 'Logo bounce then DPP.' },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[16](props),
}
