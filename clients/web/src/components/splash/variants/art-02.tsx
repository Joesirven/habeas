import type { CSSProperties, ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-02.css'

const LINES = [
  { key: 'brand', text: 'CATAPRIVACY', tone: 'brand' },
  { key: 'base', text: 'PLATFORM', tone: 'base' },
] as const

type LockupMode = 'cascade' | 'converge'

function StackedLockup({ mode }: { mode: LockupMode }) {
  const root =
    mode === 'cascade'
      ? 'art-02-lockup art-02-mode-cascade badge-bloom'
      : 'art-02-lockup art-02-mode-converge badge-bloom'

  return (
    <div className={root} aria-hidden>
      <div className="art-02-glow" />
      <div className="art-02-spine" />
      <ul className="art-02-stack">
        {LINES.map((line, i) => (
          <li
            key={line.key}
            className={`art-02-line art-02-line-${line.tone}`}
            style={{ '--i': i } as CSSProperties}
          >
            <span className="art-02-line-text">{line.text}</span>
            {i < LINES.length - 1 ? <span className="art-02-rule" /> : null}
          </li>
        ))}
      </ul>
    </div>
  )
}

/** v3 — Cascade drop: lines fall top→bottom, then hairlines snap. */
function V3(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-02-v3" {...props}>
      <StackedLockup mode="cascade" />
    </BadgeStage>
  )
}

/** v4 — Lateral converge: lines slide from alternating sides and lock. */
function V4(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-02-v4" {...props}>
      <StackedLockup mode="converge" />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  3: V3,
  4: V4,
}

export const art02: SplashVariantModule = {
  meta: [
    {
      id: 3,
      name: 'Stacked Cascade',
      blurb: 'Three-line Habeas lockup drops top→bottom, then hairlines snap.',
    },
    {
      id: 4,
      name: 'Stacked Converge',
      blurb: 'Three-line Habeas lockup slides from alternating sides and locks.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[3](props),
}
