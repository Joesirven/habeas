import type { CSSProperties, ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-10.css'

const BRAND = 'CATAPRIVACY'
const PLATFORM = 'PLATFORM'

/**
 * Split lockup — giant CATAPRIVACY + PLATFORM as co-heroes. Type is the art.
 */

function SplitLockup({ mode }: { mode: 'shear' | 'stack' }) {
  return (
    <div className={`art-10-lockup art-10-mode-${mode}`} aria-hidden>
      <div className="art-10-glow" />

      <div className="art-10-row">
        <p className="art-10-habeas">
          {BRAND.split('').map((ch, i) => (
            <span
              key={`c-${i}`}
              className="art-10-letter art-10-letter-cat"
              style={{ '--i': i } as CSSProperties}
            >
              {ch}
            </span>
          ))}
        </p>

        <span className="art-10-rule" />

        <p className="art-10-dpp">
          {PLATFORM.split('').map((ch, i) => (
            <span
              key={`d-${i}`}
              className="art-10-letter art-10-letter-dpp"
              style={{ '--i': i } as CSSProperties}
            >
              {ch}
            </span>
          ))}
        </p>
      </div>
    </div>
  )
}

/**
 * v19 — Horizontal shear assemble: HABEAS flies in from the left,
 * DPP from the right; center rule draws; secondary rises under.
 */
function V19(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-10-v19" {...props}>
      <div className="art-10-stage badge-bloom">
        <SplitLockup mode="shear" />
      </div>
    </BadgeStage>
  )
}

/**
 * v20 — Vertical stack assemble: HABEAS drops, DPP rises into the
 * split; letters cascade; secondary letter-spacing expands to lock.
 */
function V20(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-10-v20" {...props}>
      <div className="art-10-stage badge-bloom">
        <SplitLockup mode="stack" />
      </div>
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  19: V19,
  20: V20,
}

export const art10: SplashVariantModule = {
  meta: [
    {
      id: 19,
      name: 'Split Shear',
      blurb: 'HABEAS + DPP shear in from opposite sides; rule draws; secondary rises.',
    },
    {
      id: 20,
      name: 'Split Stack',
      blurb: 'HABEAS drops, DPP rises; letter cascade; secondary expands to lock.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[19](props),
}
