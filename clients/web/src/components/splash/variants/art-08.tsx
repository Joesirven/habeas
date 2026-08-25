import type { CSSProperties, ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-08.css'

const WORDS = ['Habeas', 'Platform'] as const

function ChyronTitle({ stagger }: { stagger?: boolean }) {
  if (!stagger) {
    return <p className="art-08-title">Habeas Platform</p>
  }
  return (
    <p className="art-08-title art-08-title-stagger">
      {WORDS.map((word, i) => (
        <span
          key={word}
          className="art-08-word"
          style={{ '--i': i } as CSSProperties}
        >
          {word}
        </span>
      ))}
    </p>
  )
}

/**
 * v15 — Classic broadcast lower-third: blue rail ticks, band slides up
 * from the bottom edge, full name rides in as one TV news ID plate.
 */
function V15(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-08-v15" {...props}>
      <div className="art-08-frame">
        <div className="art-08-sky" aria-hidden>
          <span className="art-08-bug">CAT</span>
          <span className="art-08-hairline" />
        </div>
        <div className="art-08-chyron badge-bloom">
          <span className="art-08-rail" aria-hidden />
          <div className="art-08-band">
            <ChyronTitle />
            <p className="art-08-tag">Station ID</p>
          </div>
        </div>
      </div>
    </BadgeStage>
  )
}

/**
 * v16 — Wipe-assemble chyron: band expands from left, rail drops,
 * then each word of Habeas Data Privacy Platform snaps in sequence.
 */
function V16(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-08-v16" {...props}>
      <div className="art-08-frame">
        <div className="art-08-sky" aria-hidden>
          <span className="art-08-bug">CAT</span>
          <span className="art-08-hairline" />
        </div>
        <div className="art-08-chyron badge-bloom">
          <span className="art-08-rail" aria-hidden />
          <div className="art-08-band">
            <ChyronTitle stagger />
            <p className="art-08-tag">Station ID</p>
          </div>
        </div>
      </div>
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  15: V15,
  16: V16,
}

export const art08: SplashVariantModule = {
  meta: [
    {
      id: 15,
      name: 'ChyronSlide A',
      blurb: 'Lower-third slides up like a TV news ID; full name rides the plate.',
    },
    {
      id: 16,
      name: 'ChyronAssemble B',
      blurb: 'Band wipes from left; Habeas Data Privacy Platform words snap in.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[15](props),
}
