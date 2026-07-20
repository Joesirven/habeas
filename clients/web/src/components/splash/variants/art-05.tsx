import type { CSSProperties, ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-05.css'

const DEPTH = 10

type ExtrudeProps = {
  text: string
  /** Depth layer count (face is last). */
  layers?: number
  className?: string
  /** Secondary line under the hero (smaller, delayed). */
  sub?: string
}

/**
 * Stripe-extruded 3D wordmark — stacked offset copies + striped face.
 * Motions live on parent variant class (push vs sweep).
 */
function StripeExtrude({ text, layers = DEPTH, className = '', sub }: ExtrudeProps) {
  const depth = Math.max(3, layers)
  return (
    <div className={`art-05-lockup ${className}`.trim()}>
      <div className="art-05-extrude badge-bloom" aria-hidden>
        {Array.from({ length: depth }, (_, i) => {
          const isFace = i === depth - 1
          return (
            <span
              key={i}
              className={
                isFace ? 'art-05-layer art-05-layer-face' : 'art-05-layer art-05-layer-depth'
              }
              style={
                {
                  '--i': i,
                  '--n': depth - 1,
                  '--t': i / (depth - 1),
                } as CSSProperties
              }
            >
              {text}
            </span>
          )
        })}
      </div>
      {sub ? (
        <p className="art-05-sub" aria-hidden>
          {sub}
        </p>
      ) : null}
      <span className="art-05-sr-only">{text}{sub ? ` — ${sub}` : ''}</span>
    </div>
  )
}

/**
 * v9 — EXTRUDE PUSH: giant DPP depth layers punch forward from black,
 * then stripe face locks; secondary Habeas line settles under.
 */
function V9(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-05-v9" {...props}>
      <StripeExtrude
        text="DPP"
        layers={12}
        className="art-05-mode-push"
        sub="Habeas Data Privacy Platform"
      />
    </BadgeStage>
  )
}

/**
 * v10 — EXTRUDE SWEEP: full Habeas line stripes wipe in from the left
 * while depth slabs cascade down-right (opposite of push).
 */
function V10(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-05-v10" {...props}>
      <StripeExtrude
        text="Habeas"
        layers={10}
        className="art-05-mode-sweep"
        sub="Data Privacy Platform"
      />
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  9: V9,
  10: V10,
}

export const art05: SplashVariantModule = {
  meta: [
    {
      id: 9,
      name: 'StripeExtrude Push',
      blurb: 'Giant DPP punches forward in silver/blue depth layers; stripe face locks.',
    },
    {
      id: 10,
      name: 'StripeExtrude Sweep',
      blurb: 'Habeas stripes wipe left→right while depth slabs cascade down-right.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[9](props),
}
