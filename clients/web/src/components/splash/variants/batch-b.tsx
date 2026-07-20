import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { HabeasLogoImg, HabeasOrbArrow, DppTitle } from '../shared'
import { SPLASH_PALETTE } from '../palette'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './batch-b.css'

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
      className={`splash-b-stage ${variantClass} splash-b-phase-${phase} ${className}`}
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

/** 1985 wireframe sphere — latitude / longitude lattice, no fill. */
function WireframeOrb({ size = 160 }: { size?: number }) {
  const cx = 60
  const cy = 52
  const rx = 40
  const ry = 40
  const lats = [-0.72, -0.4, 0, 0.4, 0.72]
  const longs = [-0.85, -0.5, 0, 0.5, 0.85]

  return (
    <div className="splash-b-wire-spin" style={{ width: size, height: (size * 110) / 120 }}>
      <svg
        className="splash-b-wire-orb"
        viewBox="0 0 120 110"
        width={size}
        height={(size * 110) / 120}
        aria-hidden
      >
        <g fill="none" strokeLinecap="square">
          <ellipse
            cx={cx}
            cy={cy}
            rx={rx}
            ry={ry}
            stroke={SPLASH_PALETTE.blueDeep}
            strokeWidth="1.5"
          />
          {lats.map((t) => {
            const y = cy + t * ry
            const half = Math.sqrt(Math.max(0, 1 - t * t)) * rx
            return (
              <ellipse
                key={`lat-${t}`}
                cx={cx}
                cy={y}
                rx={half}
                ry={Math.max(3, half * 0.22)}
                stroke={SPLASH_PALETTE.blue}
                strokeWidth="1"
                opacity={0.85}
              />
            )
          })}
          {longs.map((t) => {
            const x = cx + t * rx * 0.92
            const half = Math.sqrt(Math.max(0, 1 - t * t)) * ry
            return (
              <ellipse
                key={`long-${t}`}
                cx={x}
                cy={cy}
                rx={Math.max(3, half * 0.18)}
                ry={half}
                stroke={SPLASH_PALETTE.blue}
                strokeWidth="1"
                opacity={0.7}
              />
            )
          })}
          <circle cx={cx - 14} cy={cy - 16} r="3" fill={SPLASH_PALETTE.silverHi} opacity="0.45" />
        </g>
      </svg>
    </div>
  )
}

/** Oversized dashed arrow used as a progress track. */
function ArrowLoaderTrack({ size = 220 }: { size?: number }) {
  return (
    <svg
      className="splash-b-arrow-loader"
      viewBox="0 0 200 48"
      width={size}
      height={(size * 48) / 200}
      aria-hidden
    >
      <path
        className="splash-b-arrow-rail"
        d="M8 24 H160"
        fill="none"
        stroke={SPLASH_PALETTE.blueDeep}
        strokeWidth="2"
        strokeDasharray="4 6"
        opacity="0.35"
      />
      <path
        className="splash-b-arrow-progress"
        d="M8 24 H160"
        fill="none"
        stroke={SPLASH_PALETTE.blue}
        strokeWidth="3"
        strokeLinecap="square"
        strokeDasharray="8 6"
      />
      <path
        className="splash-b-arrow-head"
        d="M160 24 L178 24 L168 14 M178 24 L168 34"
        fill="none"
        stroke={SPLASH_PALETTE.blue}
        strokeWidth="3"
        strokeLinecap="square"
        strokeLinejoin="miter"
      />
    </svg>
  )
}

/** Silver vector wordmark for chrome draw-on (not the raster logo). */
function SilverWordmark({ className = '' }: { className?: string }) {
  return (
    <svg
      className={`splash-b-wordmark ${className}`.trim()}
      viewBox="0 0 320 48"
      width={280}
      height={42}
      aria-hidden
    >
      <text
        x="160"
        y="36"
        textAnchor="middle"
        fill="none"
        stroke={SPLASH_PALETTE.silver}
        strokeWidth="1.35"
        className="splash-b-wordmark-stroke"
      >
        HABEAS
      </text>
      <text
        x="160"
        y="36"
        textAnchor="middle"
        fill={SPLASH_PALETTE.silverHi}
        className="splash-b-wordmark-fill"
      >
        HABEAS
      </text>
    </svg>
  )
}

/** v4 — wireframe sphere rotates; silver wordmark + DPP hold. */
function V4(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-b-v4" durationMs={3600} {...props}>
      <div className="splash-b-v4-stack">
        <div className="splash-b-v4-orb-wrap">
          <WireframeOrb size={180} />
          <HabeasOrbArrow size={56} />
        </div>
        <p className="splash-b-silver-mark">HABEAS</p>
        <DppTitle />
      </div>
    </Stage>
  )
}

/** v5 — dashed arrow loads; then logo + DPP snap in. */
function V5(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-b-v5" durationMs={3800} {...props}>
      <div className="splash-b-v5-stack">
        <ArrowLoaderTrack size={260} />
        <div className="splash-b-v5-reveal">
          <HabeasLogoImg />
          <DppTitle />
        </div>
      </div>
    </Stage>
  )
}

/** v6 — static orb; silver wordmark stroke/clip draws on; DPP fades. */
function V6(props: SplashStageProps) {
  return (
    <Stage variantClass="splash-b-v6" durationMs={4000} {...props}>
      <div className="splash-b-v6-frame">
        <div className="splash-b-v6-orb-slot" aria-hidden>
          <HabeasOrbArrow size={110} />
        </div>
        <div className="splash-b-v6-copy">
          <div className="splash-b-v6-draw">
            <SilverWordmark />
          </div>
          <DppTitle />
        </div>
      </div>
    </Stage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  4: V4,
  5: V5,
  6: V6,
}

export const batchB: SplashVariantModule = {
  meta: [
    { id: 4, name: 'Orb Spin', blurb: 'Wireframe sphere rotates; silver wordmark holds.' },
    { id: 5, name: 'Arrow Loader', blurb: 'Dashed arrow is the progress bar; logo snaps on.' },
    { id: 6, name: 'Chrome Build', blurb: 'Silver wordmark draws on over a static orb.' },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[4](props),
}
