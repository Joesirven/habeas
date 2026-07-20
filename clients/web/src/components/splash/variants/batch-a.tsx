import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { HabeasLogoImg, DppTitle, PresentationLine } from '../shared'
import { SPLASH_PALETTE } from '../palette'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './batch-a.css'

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
      className={`splash-a-stage ${variantClass} splash-a-phase-${phase} ${className}`}
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

const SCAN_BANDS = 14

/** v1 — Heavy analog snow clears; logo locks; title follows. */
function V1(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-a-v1" durationMs={3800} {...props}>
      <div className="splash-a-v1-snow splash-a-v1-snow-coarse" aria-hidden />
      <div className="splash-a-v1-snow splash-a-v1-snow-fine" aria-hidden />
      <div className="splash-a-v1-snow splash-a-v1-snow-blue" aria-hidden />
      <div className="splash-a-v1-scanlines" aria-hidden />
      <div className="splash-a-v1-lockbar" aria-hidden />
      <div className="splash-a-v1-card">
        <div className="splash-a-v1-logo-lock">
          <HabeasLogoImg className="splash-a-v1-logo" />
          <div className="splash-a-v1-fringe splash-a-v1-fringe-l" aria-hidden />
          <div className="splash-a-v1-fringe splash-a-v1-fringe-r" aria-hidden />
        </div>
        <div className="splash-a-v1-copy">
          <DppTitle className="splash-a-v1-title" />
          <PresentationLine className="splash-a-v1-tag" />
        </div>
      </div>
    </Stage>
  )
}

/** v2 — Logo builds top→bottom as horizontal scan / Venetian blinds. */
function V2(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-a-v2" durationMs={4000} {...props}>
      <div className="splash-a-v2-beam" aria-hidden />
      <div className="splash-a-v2-field">
        <div className="splash-a-v2-assemble">
          <HabeasLogoImg className="splash-a-v2-logo" />
          <div className="splash-a-v2-blinds" aria-hidden>
            {Array.from({ length: SCAN_BANDS }, (_, i) => (
              <span
                key={i}
                className="splash-a-v2-blind"
                style={{ '--i': i, '--n': SCAN_BANDS } as CSSProperties}
              />
            ))}
          </div>
          <div className="splash-a-v2-sweep" aria-hidden />
        </div>
        <div className="splash-a-v2-copy">
          <DppTitle className="splash-a-v2-title" />
          <PresentationLine className="splash-a-v2-tag" />
        </div>
      </div>
    </Stage>
  )
}

/** v3 — Pure black → phosphor bloom / CRT tube power-on → title card. */
function V3(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-a-v3" durationMs={4200} {...props}>
      <div className="splash-a-v3-tube" aria-hidden>
        <div className="splash-a-v3-dot" />
        <div className="splash-a-v3-hline" />
        <div className="splash-a-v3-expand" />
        <div className="splash-a-v3-bloom" />
      </div>
      <svg className="splash-a-v3-phosphor-ring" viewBox="0 0 200 200" aria-hidden>
        <circle cx="100" cy="100" r="78" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="100" cy="100" r="52" fill="none" stroke="currentColor" strokeWidth="0.75" opacity="0.55" />
      </svg>
      <div className="splash-a-v3-card">
        <HabeasLogoImg className="splash-a-v3-logo" />
        <DppTitle className="splash-a-v3-title" />
        <PresentationLine className="splash-a-v3-tag" />
      </div>
    </Stage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  1: V1,
  2: V2,
  3: V3,
}

export const batchA: SplashVariantModule = {
  meta: [
    { id: 1, name: 'CRT Snow Lock', blurb: 'Analog snow clears; Habeas locks in.' },
    { id: 2, name: 'Scan Assemble', blurb: 'Logo builds from horizontal scan bands.' },
    { id: 3, name: 'Power Tube', blurb: 'Black → phosphor bloom → title card.' },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[1](props),
}
