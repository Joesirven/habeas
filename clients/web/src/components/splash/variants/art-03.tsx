import type { ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-03.css'

type LockupMotion = 'spread' | 'cascade'

/**
 * Type hero — giant DPP monogram expands into
 * “Habeas Data Privacy Platform”. Palette tokens only.
 */
function TypeLockup({ motion }: { motion: LockupMotion }) {
  const root =
    motion === 'spread' ? 'art-03-lockup art-03-spread' : 'art-03-lockup art-03-cascade'

  return (
    <div className={root} aria-hidden>
      <div className="art-03-mono" aria-hidden>
        <span className="art-03-glyph" data-i="0">
          D
        </span>
        <span className="art-03-glyph" data-i="1">
          P
        </span>
        <span className="art-03-glyph" data-i="2">
          P
        </span>
      </div>
      <p className="art-03-full">
        <span className="art-03-brand">Habeas</span>
        <span className="art-03-product">Data Privacy Platform</span>
      </p>
    </div>
  )
}

/** v5 — Monogram slams; glyphs track-out; full name blooms in the spread. */
function V5(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-03-v5" {...props}>
      <TypeLockup motion="spread" />
    </BadgeStage>
  )
}

/** v6 — Monogram holds, then lifts; stacked name cascades open below. */
function V6(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-03-v6" {...props}>
      <TypeLockup motion="cascade" />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  5: V5,
  6: V6,
}

export const art03: SplashVariantModule = {
  meta: [
    {
      id: 5,
      name: 'TypeLockup Spread',
      blurb: 'Giant DPP slams, glyphs track-out, Habeas Data Privacy Platform blooms.',
    },
    {
      id: 6,
      name: 'TypeLockup Cascade',
      blurb: 'Giant DPP lifts; Habeas Data Privacy Platform cascades open below.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[5](props),
}
