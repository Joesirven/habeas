import type { CSSProperties, ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-04.css'

const HERO = 'Habeas Platform'

/** Teletext rows — each glyph is a discrete CRT cell. */
const TELETEXT_ROWS = ['Habeas', 'Platform'] as const

function TeletextCells({ text, rowIndex }: { text: string; rowIndex: number }) {
  return (
    <p className="art-04-tt-row" style={{ '--row': rowIndex } as CSSProperties}>
      {[...text].map((ch, i) => (
        <span
          key={`${rowIndex}-${i}`}
          className={`art-04-tt-cell${ch === ' ' ? ' art-04-tt-space' : ''}`}
          style={{ '--i': i } as CSSProperties}
        >
          {ch === ' ' ? '\u00a0' : ch}
        </span>
      ))}
    </p>
  )
}

/** v7 — Blocky teletext grid; characters snap in as CRT tiles. */
function TeletextLockup() {
  return (
    <div className="art-04-lockup art-04-teletext badge-bloom">
      <p className="art-04-sr-only">{HERO}</p>
      <div className="art-04-crt" aria-hidden>
        <div className="art-04-crt-bezel">
          <header className="art-04-tt-bar">
            <span className="art-04-tt-page">P100</span>
            <span className="art-04-tt-clock">TELETEXT</span>
          </header>
          <div className="art-04-tt-grid">
            <div className="art-04-tt-scan" />
            {TELETEXT_ROWS.map((row, ri) => (
              <div key={row} className="art-04-tt-line">
                <TeletextCells text={row} rowIndex={ri} />
              </div>
            ))}
          </div>
          <p className="art-04-tt-tag">DPP</p>
        </div>
      </div>
    </div>
  )
}

/** v8 — Caret types the full name letter-by-letter on a CRT plate. */
function TypewriterLockup() {
  return (
    <div className="art-04-lockup art-04-typewriter badge-bloom">
      <p className="art-04-sr-only">{HERO}</p>
      <div className="art-04-crt" aria-hidden>
        <div className="art-04-crt-bezel art-04-crt-type">
          <div className="art-04-tw-plate">
            <p className="art-04-tw-line">
              {[...HERO].map((ch, i) => (
                <span
                  key={i}
                  className={`art-04-tw-char${ch === ' ' ? ' art-04-tw-space' : ''}`}
                  style={{ '--i': i } as CSSProperties}
                >
                  {ch === ' ' ? '\u00a0' : ch}
                </span>
              ))}
              <span className="art-04-tw-caret" aria-hidden />
            </p>
            <p className="art-04-tw-tag">DPP</p>
          </div>
        </div>
      </div>
    </div>
  )
}

/** v7 — Teletext cells snap onto a scanline grid; hold soft-scans. */
function V7(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-04-v7" {...props}>
      <TeletextLockup />
    </BadgeStage>
  )
}

/** v8 — Typewriter caret types Habeas Data Privacy Platform. */
function V8(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-04-v8" {...props}>
      <TypewriterLockup />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  7: V7,
  8: V8,
}

export const art04: SplashVariantModule = {
  meta: [
    {
      id: 7,
      name: 'Teletext Lockup',
      blurb: 'CRT teletext grid; Habeas Data Privacy Platform snaps in as discrete cells.',
    },
    {
      id: 8,
      name: 'Typewriter CRT',
      blurb: 'Caret types Habeas Data Privacy Platform letter-by-letter on a CRT plate.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[7](props),
}
