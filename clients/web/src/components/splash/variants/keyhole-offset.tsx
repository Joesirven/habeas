import { useEffect, useState, type ReactNode } from 'react'

import type { SplashStageProps, SplashVariantModule } from '../types'
import './keyhole-offset.css'

/** Keyhole Offset brand mark — locked hex, not the CRT-lab splash palette. */
const KEYHOLE_FILL = '#2E4CF6'

/** Keyhole Offset mark — rounded square, offset circle, keyhole slot. */
function KeyholeSvg() {
  return (
    <svg className="keyhole-svg" viewBox="0 0 64 64" width={120} height={120} aria-hidden>
      <rect className="keyhole-square" width="64" height="64" rx="16" fill={KEYHOLE_FILL} />
      <circle className="keyhole-circle" cx="27" cy="25" r="9" fill="#fff" />
      <polygon className="keyhole-slot" points="22,32 32,32 36,49 18,49" fill="#fff" />
    </svg>
  )
}

/** Slot Slide-In — square + circle settle immediately, slot drops in and clicks home. */
function SlotSlideIn({
  autoFinish,
  durationMs = 1400,
  onDone,
  className = '',
}: SplashStageProps) {
  const [phase, setPhase] = useState<'in' | 'out'>('in')

  useEffect(() => {
    if (!autoFinish) return
    const t1 = window.setTimeout(() => setPhase('out'), Math.max(durationMs - 350, 800))
    const t2 = window.setTimeout(() => onDone?.(), durationMs)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
    }
  }, [autoFinish, durationMs, onDone])

  return (
    <div
      className={`keyhole-stage keyhole-phase-${phase} ${className}`.trim()}
      role="status"
      aria-label="Signing in to Data Privacy Platform"
    >
      <p className="keyhole-sr-only">Habeas Data Privacy Platform</p>
      <div className="keyhole-lockup">
        <KeyholeSvg />
      </div>
    </div>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  21: SlotSlideIn,
}

export const KEYHOLE_SLOT_SLIDE_IN_ID = 21

export const keyholeOffset: SplashVariantModule = {
  meta: [
    {
      id: KEYHOLE_SLOT_SLIDE_IN_ID,
      name: 'Slot Slide-In',
      blurb:
        'Keyhole Offset mark — square and circle fade/scale in, then the slot slides up from below and clicks into place with a slight overshoot.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[KEYHOLE_SLOT_SLIDE_IN_ID](props),
}
