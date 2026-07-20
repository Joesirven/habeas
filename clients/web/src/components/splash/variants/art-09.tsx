import { useId, type ReactNode } from 'react'

import { BadgeStage } from '../badge-stage'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './art-09.css'

/**
 * TYPE LOCKUP v3 — circular / arced type around a seal badge.
 * Curved Habeas · Data Privacy Platform · DPP. Spelling: Habeas.
 * v17: clockwise arc-draw. v18: counter-clockwise meet-in-middle draw.
 */

const CX = 160
const CY = 150
const R_OUTER = 118
const R_MID = 92
const R_INNER = 58

/** Upper arc L→R (Habeas). */
function topArc(r: number): string {
  return `M ${(CX - r).toFixed(1)} ${CY.toFixed(1)} A ${r} ${r} 0 0 1 ${(CX + r).toFixed(1)} ${CY.toFixed(1)}`
}

/** Lower arc L→R reading (path runs right→left so glyphs sit upright). */
function bottomArc(r: number): string {
  return `M ${(CX + r).toFixed(1)} ${CY.toFixed(1)} A ${r} ${r} 0 0 1 ${(CX - r).toFixed(1)} ${CY.toFixed(1)}`
}

type Mode = 'cw' | 'ccw'

function ArcTypeSeal({ mode }: { mode: Mode }) {
  const uid = useId().replace(/:/g, '')
  const topId = `art09-top-${uid}`
  const midId = `art09-mid-${uid}`
  const root =
    mode === 'cw' ? 'art-09-svg art-09-mode-cw' : 'art-09-svg art-09-mode-ccw'

  return (
    <svg
      className={root}
      viewBox="0 0 320 300"
      width="340"
      height="318"
      aria-hidden
    >
      <defs>
        <path id={topId} d={topArc(R_OUTER)} fill="none" />
        <path id={midId} d={bottomArc(R_MID)} fill="none" />
      </defs>

      <ellipse className="art-09-glow" cx={CX} cy={CY} rx="132" ry="126" />

      {/* Guide rings — stroke-draw is the motion hero */}
      <circle
        className="art-09-ring art-09-ring-outer"
        cx={CX}
        cy={CY}
        r={R_OUTER}
        fill="none"
      />
      <circle
        className="art-09-ring art-09-ring-mid"
        cx={CX}
        cy={CY}
        r={R_MID}
        fill="none"
      />
      <circle
        className="art-09-ring art-09-ring-inner"
        cx={CX}
        cy={CY}
        r={R_INNER}
        fill="none"
      />

      {/* Soft seal plate behind center DPP */}
      <circle className="art-09-plate" cx={CX} cy={CY} r="48" />
      <circle className="art-09-plate-stroke" cx={CX} cy={CY} r="48" fill="none" />
      <circle className="art-09-plate-inner" cx={CX} cy={CY} r="40" fill="none" />

      {/* Arc type — Habeas (outer top) */}
      <text className="art-09-type art-09-type-habeas">
        <textPath href={`#${topId}`} startOffset="50%" textAnchor="middle">
          Habeas
        </textPath>
      </text>

      {/* Arc type — Data Privacy Platform (mid bottom) */}
      <text className="art-09-type art-09-type-platform">
        <textPath href={`#${midId}`} startOffset="50%" textAnchor="middle">
          Data Privacy Platform
        </textPath>
      </text>

      {/* Center monogram */}
      <text
        className="art-09-type art-09-type-dpp"
        x={CX}
        y={CY + 8}
        textAnchor="middle"
      >
        DPP
      </text>

      {/* Tick marks at 12 / 3 / 6 / 9 — seal chrome */}
      <g className="art-09-ticks" strokeLinecap="square">
        <path d={`M ${CX} ${CY - R_INNER + 4} L ${CX} ${CY - R_INNER + 14}`} />
        <path d={`M ${CX + R_INNER - 4} ${CY} L ${CX + R_INNER - 14} ${CY}`} />
        <path d={`M ${CX} ${CY + R_INNER - 4} L ${CX} ${CY + R_INNER - 14}`} />
        <path d={`M ${CX - R_INNER + 4} ${CY} L ${CX - R_INNER + 14} ${CY}`} />
      </g>
    </svg>
  )
}

/** V17 — rings + type draw clockwise from 12 o’clock. */
function V17(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-09-v17" {...props}>
      <div className="art-09-badge badge-bloom" aria-hidden>
        <ArcTypeSeal mode="cw" />
      </div>
    </BadgeStage>
  )
}

/** V18 — outer/mid arcs draw counter-clockwise and meet; DPP punches last. */
function V18(props: SplashStageProps) {
  return (
    <BadgeStage variantClass="art-09-v18" {...props}>
      <div className="art-09-badge badge-bloom" aria-hidden>
        <ArcTypeSeal mode="ccw" />
      </div>
    </BadgeStage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  17: V17,
  18: V18,
}

export const art09: SplashVariantModule = {
  meta: [
    {
      id: 17,
      name: 'ArcSeal CW',
      blurb: 'Curved Habeas / Data Privacy Platform / DPP — clockwise arc-draw.',
    },
    {
      id: 18,
      name: 'ArcSeal CCW',
      blurb: 'Curved type seal — counter-clockwise meet-in-middle arc-draw.',
    },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[17](props),
}
