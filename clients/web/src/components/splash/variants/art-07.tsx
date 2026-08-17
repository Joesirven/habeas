import type { ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-07.css'

/**
 * TYPE LOCKUP v3 — Habeas orb + dashed arrow support a hero wordmark.
 * Type leads; orb supports. Spelling: Habeas.
 */

type LockupMode = 'type-lead' | 'arrow-rail'

/** Brand orb + dashed arrow — supporting motif only (palette CSS vars). */
function SupportOrbArrow() {
  return (
    <svg
      className="art-07-orb-arrow"
      viewBox="0 0 160 72"
      width="160"
      height="72"
      aria-hidden
    >
      <defs>
        <radialGradient id="art07-orb-grad" cx="36%" cy="30%" r="68%">
          <stop offset="0%" stopColor="var(--cat-silver-hi)" stopOpacity="0.95" />
          <stop offset="38%" stopColor="var(--cat-blue)" />
          <stop offset="78%" stopColor="var(--cat-blue-deep)" />
          <stop offset="100%" stopColor="var(--cat-black)" stopOpacity="0.45" />
        </radialGradient>
      </defs>

      <ellipse className="art-07-orb-wash" cx="36" cy="34" rx="34" ry="30" />

      <g className="art-07-orb-root">
        <circle
          className="art-07-orb-rim"
          cx="36"
          cy="34"
          r="22"
          fill="none"
          stroke="var(--cat-silver)"
          strokeWidth="1.4"
        />
        <circle className="art-07-orb" cx="36" cy="34" r="18" fill="url(#art07-orb-grad)" />
        <circle
          className="art-07-orb-spec"
          cx="29"
          cy="27"
          r="5.5"
          fill="var(--cat-silver-hi)"
          opacity="0.7"
        />
      </g>

      <g className="art-07-arrow" fill="none" strokeLinecap="square">
        <path
          className="art-07-arrow-dash"
          d="M62 52 H128"
          stroke="var(--cat-blue)"
          strokeWidth="2.6"
          strokeDasharray="7 5"
        />
        <path
          className="art-07-arrow-head"
          d="M128 52 L146 52 L138 44 M146 52 L138 60"
          stroke="var(--cat-blue)"
          strokeWidth="2.6"
        />
      </g>
    </svg>
  )
}

function TypeOrbLockup({ mode }: { mode: LockupMode }) {
  const root =
    mode === 'type-lead'
      ? 'art-07-lockup art-07-mode-type-lead badge-bloom'
      : 'art-07-lockup art-07-mode-arrow-rail badge-bloom'

  return (
    <div className={root}>
      <div className="art-07-glow" aria-hidden />

      <div className="art-07-type">
        <p className="art-07-brand">Habeas</p>
        <p className="art-07-product">Platform</p>
        <p className="art-07-dpp">DPP</p>
      </div>

      <div className="art-07-support" aria-hidden>
        <SupportOrbArrow />
      </div>
    </div>
  )
}

/**
 * v13 — Type leads: Habeas locks, product line rises, then orb blooms
 * and dashed arrow stroke-draws as underline support.
 */
function V13(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-07-v13" {...props}>
      <TypeOrbLockup mode="type-lead" />
    </BadgeStage>
  )
}

/**
 * v14 — Arrow rail first: dashed arrow draws, orb seats left, then hero
 * type drops onto the rail (type still dominates the lockup).
 */
function V14(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-07-v14" {...props}>
      <TypeOrbLockup mode="arrow-rail" />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  13: V13,
  14: V14,
}

export const art07: SplashVariantModule = {
  meta: [
    {
      id: 13,
      name: 'TypeLead Orb',
      blurb: 'Hero Habeas wordmark locks first; orb + dashed arrow settle as support.',
    },
    {
      id: 14,
      name: 'ArrowRail Lock',
      blurb: 'Dashed arrow draws a rail, orb seats, hero type drops onto the lockup.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[13](props),
}
