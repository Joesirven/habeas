import type { CSSProperties, ReactNode } from 'react'

export type SplashVariantMeta = {
  id: number
  name: string
  blurb: string
}

export type SplashStageProps = {
  /** Lab mode loops; production passes autoFinish. */
  autoFinish?: boolean
  durationMs?: number
  onDone?: () => void
  className?: string
  style?: CSSProperties
}

export type SplashVariantModule = {
  meta: SplashVariantMeta[]
  /** Render one variant by id (must be in this module’s meta). */
  render: (id: number, props: SplashStageProps) => ReactNode
}
