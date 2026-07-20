import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { SPLASH_PALETTE } from './palette'
import type { SplashStageProps } from './types'

type BadgeStageProps = SplashStageProps & {
  variantClass: string
  children: ReactNode
}

/** Full-bleed black void stage for illustrated badge bumpers. */
export function BadgeStage({
  variantClass,
  children,
  autoFinish,
  durationMs = 3800,
  onDone,
  className = '',
}: BadgeStageProps) {
  const [phase, setPhase] = useState<'in' | 'hold' | 'out'>('in')

  useEffect(() => {
    if (!autoFinish) return
    const t1 = window.setTimeout(() => setPhase('hold'), 2200)
    const t2 = window.setTimeout(() => setPhase('out'), durationMs - 500)
    const t3 = window.setTimeout(() => onDone?.(), durationMs)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [autoFinish, durationMs, onDone])

  return (
    <div
      className={`badge-stage ${variantClass} badge-phase-${phase} ${className}`.trim()}
      style={
        {
          '--cat-black': SPLASH_PALETTE.black,
          '--cat-silver': SPLASH_PALETTE.silver,
          '--cat-silver-hi': SPLASH_PALETTE.silverHi,
          '--cat-blue': SPLASH_PALETTE.blue,
          '--cat-blue-deep': SPLASH_PALETTE.blueDeep,
        } as CSSProperties
      }
      role="status"
      aria-label="CataPriv Platform loading"
    >
      {children}
      <div className="badge-scanlines" aria-hidden />
    </div>
  )
}

/** Tiny end-card caption — keep secondary to the illustration. */
export function BadgeDpp({ className = '' }: { className?: string }) {
  return (
    <p className={`badge-dpp ${className}`.trim()}>CataPriv Platform (DPP)</p>
  )
}

export type BadgeWordmarkKind = 'full' | 'dpp' | 'stacked' | 'habeas-dpp'

type BadgeWordmarkProps = {
  kind?: BadgeWordmarkKind
  className?: string
}

/** Hero typography lockups for Habeas Data Privacy Platform / DPP. */
export function BadgeWordmark({ kind = 'full', className = '' }: BadgeWordmarkProps) {
  const cls = `badge-wordmark badge-wordmark-${kind} ${className}`.trim()

  if (kind === 'dpp') {
    return (
      <p className={cls} aria-label="DPP">
        <span className="badge-wordmark-dpp-hero">DPP</span>
      </p>
    )
  }

  if (kind === 'habeas-dpp') {
    return (
      <div className={cls}>
        <p className="badge-wordmark-line badge-wordmark-brand">Habeas</p>
        <p className="badge-wordmark-line badge-wordmark-dpp-sub">DPP</p>
      </div>
    )
  }

  if (kind === 'stacked') {
    return (
      <div className={cls} aria-label="Habeas Data Privacy Platform">
        <p className="badge-wordmark-line">Habeas</p>
        <p className="badge-wordmark-line">Data Privacy</p>
        <p className="badge-wordmark-line">Platform</p>
      </div>
    )
  }

  return (
    <p className={cls}>Habeas Data Privacy Platform</p>
  )
}
