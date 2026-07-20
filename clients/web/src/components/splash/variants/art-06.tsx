import type { ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-06.css'

const HERO = 'Habeas'
const SUB = 'Data Privacy Platform'

/** Layered SVG neon tube — outline / glow / core. Motions differ via CSS. */
function NeonLockup({ motion }: { motion: 'v11' | 'v12' }) {
  const uid = `art06-${motion}`
  return (
    <div className={`art-06-lockup badge-bloom art-06-${motion}-lockup`} aria-hidden>
      {/* Soft tube halo behind type */}
      <div className="art-06-halo" />

      {/* Horizontal neon rails — primitive geometry first */}
      <svg className="art-06-rails" viewBox="0 0 560 24" width="100%" height="18" aria-hidden>
        <line className="art-06-rail art-06-rail-a" x1="40" y1="8" x2="520" y2="8" />
        <line className="art-06-rail art-06-rail-b" x1="80" y1="16" x2="480" y2="16" />
      </svg>

      <svg
        className={`art-06-neon art-06-neon-${motion}`}
        viewBox="0 0 640 200"
        role="img"
        aria-label={`${HERO} ${SUB}`}
      >
        <defs>
          <filter id={`${uid}-bloom`} x="-20%" y="-40%" width="140%" height="180%">
            <feGaussianBlur in="SourceGraphic" stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Outer soft glow (blue) */}
        <g className="art-06-layer art-06-glow-blue" filter={`url(#${uid}-bloom)`}>
          <text
            className="art-06-hero-text"
            x="320"
            y="78"
            textAnchor="middle"
            fill="none"
            stroke="var(--cat-blue)"
            strokeWidth="6"
          >
            {HERO}
          </text>
          <text
            className="art-06-sub-text"
            x="320"
            y="148"
            textAnchor="middle"
            fill="none"
            stroke="var(--cat-blue-deep)"
            strokeWidth="3.5"
          >
            {SUB}
          </text>
        </g>

        {/* Mid silver fringe */}
        <g className="art-06-layer art-06-glow-silver">
          <text
            className="art-06-hero-text"
            x="320"
            y="78"
            textAnchor="middle"
            fill="none"
            stroke="var(--cat-silver)"
            strokeWidth="2.75"
          >
            {HERO}
          </text>
          <text
            className="art-06-sub-text"
            x="320"
            y="148"
            textAnchor="middle"
            fill="none"
            stroke="var(--cat-silver)"
            strokeWidth="1.75"
          >
            {SUB}
          </text>
        </g>

        {/* Sharp outline tube */}
        <g className="art-06-layer art-06-outline">
          <text
            className="art-06-hero-text art-06-outline-hero"
            x="320"
            y="78"
            textAnchor="middle"
            fill="none"
            stroke="var(--cat-silver-hi)"
            strokeWidth="1.35"
          >
            {HERO}
          </text>
          <text
            className="art-06-sub-text art-06-outline-sub"
            x="320"
            y="148"
            textAnchor="middle"
            fill="none"
            stroke="var(--cat-blue)"
            strokeWidth="1.1"
          >
            {SUB}
          </text>
        </g>

        {/* Hot core fill */}
        <g className="art-06-layer art-06-core">
          <text
            className="art-06-hero-text art-06-core-hero"
            x="320"
            y="78"
            textAnchor="middle"
            fill="var(--cat-silver-hi)"
          >
            {HERO}
          </text>
          <text
            className="art-06-sub-text art-06-core-sub"
            x="320"
            y="148"
            textAnchor="middle"
            fill="var(--cat-silver)"
          >
            {SUB}
          </text>
        </g>
      </svg>

      <svg className="art-06-rails art-06-rails-bot" viewBox="0 0 560 24" width="100%" height="18" aria-hidden>
        <line className="art-06-rail art-06-rail-c" x1="80" y1="8" x2="480" y2="8" />
        <line className="art-06-rail art-06-rail-d" x1="40" y1="16" x2="520" y2="16" />
      </svg>
    </div>
  )
}

/** v11 — Outline stroke-draws, then tube core ignites, blue/silver bloom pulse. */
function V11(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-06-v11" {...props}>
      <NeonLockup motion="v11" />
    </BadgeStage>
  )
}

/** v12 — Bloom halo expands first (tube power-on), then outline snaps sharp. */
function V12(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-06-v12" {...props}>
      <NeonLockup motion="v12" />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  11: V11,
  12: V12,
}

export const art06: SplashVariantModule = {
  meta: [
    {
      id: 11,
      name: 'Neon Outline Draw',
      blurb: 'Outline stroke-draws, tube core ignites, then blue/silver bloom pulse.',
    },
    {
      id: 12,
      name: 'Neon Tube Ignite',
      blurb: 'Bloom halo expands first (tube power-on), then outline snaps sharp.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[11](props),
}
