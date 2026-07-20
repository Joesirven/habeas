import type { ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-01.css'

const HERO = 'Habeas Data Privacy Platform'

/** Multi-line SVG chrome mark — stroke layer + metal fill layer. */
function ChromeSvgMark({ mode }: { mode: 'stroke' | 'wipe' }) {
  const metalId = `art-01-metal-${mode}`
  const shineId = `art-01-shine-${mode}`
  const clipId = `art-01-clip-${mode}`

  return (
    <svg
      className={`art-01-chrome-svg art-01-svg-${mode}`}
      viewBox="0 0 720 200"
      width="720"
      height="200"
      aria-hidden
    >
      <defs>
        <linearGradient id={metalId} x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="var(--cat-silver-hi)" />
          <stop offset="32%" stopColor="var(--cat-silver)" />
          <stop offset="55%" stopColor="var(--cat-blue)" />
          <stop offset="78%" stopColor="var(--cat-silver)" />
          <stop offset="100%" stopColor="var(--cat-silver-hi)" />
        </linearGradient>
        <linearGradient id={shineId} x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="var(--cat-silver-hi)" stopOpacity="0" />
          <stop offset="42%" stopColor="var(--cat-silver-hi)" stopOpacity="0" />
          <stop offset="50%" stopColor="var(--cat-silver-hi)" stopOpacity="0.95" />
          <stop offset="58%" stopColor="var(--cat-blue)" stopOpacity="0.55" />
          <stop offset="100%" stopColor="var(--cat-silver-hi)" stopOpacity="0" />
        </linearGradient>
        <clipPath id={clipId}>
          <text x="360" y="78" textAnchor="middle" className="art-01-svg-text">
            Habeas
          </text>
          <text x="360" y="128" textAnchor="middle" className="art-01-svg-text art-01-svg-sub">
            Data Privacy Platform
          </text>
        </clipPath>
      </defs>

      {/* Soft bloom disc behind type */}
      <ellipse className="art-01-bloom-disc" cx="360" cy="100" rx="280" ry="72" />

      {/* Stroke outline — v1 draws this */}
      <g className="art-01-stroke-layer">
        <text
          x="360"
          y="78"
          textAnchor="middle"
          className="art-01-svg-text art-01-stroke"
          fill="none"
        >
          Habeas
        </text>
        <text
          x="360"
          y="128"
          textAnchor="middle"
          className="art-01-svg-text art-01-svg-sub art-01-stroke"
          fill="none"
        >
          Data Privacy Platform
        </text>
      </g>

      {/* Metal fill */}
      <g className="art-01-fill-layer">
        <text
          x="360"
          y="78"
          textAnchor="middle"
          className="art-01-svg-text art-01-fill"
          fill={`url(#${metalId})`}
        >
          Habeas
        </text>
        <text
          x="360"
          y="128"
          textAnchor="middle"
          className="art-01-svg-text art-01-svg-sub art-01-fill"
          fill={`url(#${metalId})`}
        >
          Data Privacy Platform
        </text>
      </g>

      {/* Specular shine band — v2 wipes this across clipped type */}
      <rect
        className="art-01-shine-band"
        x="-120"
        y="20"
        width="160"
        height="160"
        fill={`url(#${shineId})`}
        clipPath={`url(#${clipId})`}
      />
    </svg>
  )
}

function ChromeLockup({ mode }: { mode: 'stroke' | 'wipe' }) {
  return (
    <div className={`art-01-lockup art-01-mode-${mode} badge-bloom`}>
      <p className="art-01-sr-only">{HERO}</p>
      <ChromeSvgMark mode={mode} />
      <div className="art-01-hairline" aria-hidden />
    </div>
  )
}

/** v1 — Chrome outline stroke-draws, then metal fill settles. */
function V1(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-01-v1" {...props}>
      <ChromeLockup mode="stroke" />
    </BadgeStage>
  )
}

/** v2 — Metal fill clips in, then a specular shine wipe crosses the mark. */
function V2(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-01-v2" {...props}>
      <ChromeLockup mode="wipe" />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  1: V1,
  2: V2,
}

export const art01: SplashVariantModule = {
  meta: [
    {
      id: 1,
      name: 'Chrome Stroke Draw',
      blurb: 'Silver/blue outline stroke-draws “Habeas Data Privacy Platform”, then metal fill settles.',
    },
    {
      id: 2,
      name: 'Chrome Shine Wipe',
      blurb: 'Chrome fill clips open, then a specular shine wipe sweeps the wordmark.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[1](props),
}
