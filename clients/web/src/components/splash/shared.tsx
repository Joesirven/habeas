import { SPLASH_PALETTE } from './palette'
import { PLATFORM_NAME } from '@/lib/brand'

/** Pixel cat licking its paw — optional accent for character-led bumpers. */
export function PixelCat({ size = 140 }: { size?: number }) {
  return (
    <svg
      className="splash-shared-cat"
      viewBox="0 0 64 48"
      width={size}
      height={(size * 48) / 64}
      aria-hidden
      shapeRendering="crispEdges"
    >
      <rect x="16" y="14" width="28" height="20" fill={SPLASH_PALETTE.silver} />
      <rect x="14" y="10" width="8" height="8" fill={SPLASH_PALETTE.silver} />
      <rect x="38" y="10" width="8" height="8" fill={SPLASH_PALETTE.silver} />
      <rect x="16" y="8" width="4" height="4" fill={SPLASH_PALETTE.blue} />
      <rect x="40" y="8" width="4" height="4" fill={SPLASH_PALETTE.blue} />
      <rect x="22" y="20" width="3" height="3" fill={SPLASH_PALETTE.black} />
      <rect x="34" y="20" width="3" height="3" fill={SPLASH_PALETTE.black} />
      <rect x="28" y="26" width="4" height="2" fill={SPLASH_PALETTE.black} />
      <g className="splash-shared-paw">
        <rect x="40" y="28" width="10" height="6" fill={SPLASH_PALETTE.silver} />
        <rect x="48" y="24" width="6" height="6" fill={SPLASH_PALETTE.silver} />
        <rect x="50" y="20" width="4" height="4" fill={SPLASH_PALETTE.blue} />
      </g>
      <rect x="18" y="34" width="6" height="8" fill={SPLASH_PALETTE.silver} />
      <rect x="36" y="34" width="6" height="8" fill={SPLASH_PALETTE.silver} />
    </svg>
  )
}

/** Glossy orb + dashed arrow motif from Habeas wordmark, flattened for 1985. */
export function HabeasOrbArrow({ size = 96 }: { size?: number }) {
  return (
    <svg
      className="splash-shared-orb"
      viewBox="0 0 120 100"
      width={size}
      height={(size * 100) / 120}
      aria-hidden
    >
      <circle cx="48" cy="42" r="28" fill={SPLASH_PALETTE.blue} opacity="0.85" />
      <circle cx="38" cy="32" r="8" fill={SPLASH_PALETTE.silverHi} opacity="0.55" />
      <g stroke={SPLASH_PALETTE.blue} strokeWidth="3" fill="none" strokeLinecap="square">
        <path d="M28 78 H78" strokeDasharray="6 5" />
        <path d="M78 78 L92 78 L86 72 M92 78 L86 84" strokeDasharray="0" />
      </g>
    </svg>
  )
}

/** Raster Habeas logo (source of truth for wordmark). */
export function HabeasLogoImg({ className = '' }: { className?: string }) {
  return (
    <img
      className={`splash-shared-logo ${className}`.trim()}
      src="/habeas-logo.png"
      alt="Habeas"
      width={223}
      height={96}
      draggable={false}
    />
  )
}

export function DppTitle({ className = '' }: { className?: string }) {
  return (
    <p className={`splash-shared-dpp ${className}`.trim()}>{PLATFORM_NAME}</p>
  )
}

export function PresentationLine({ className = '' }: { className?: string }) {
  return (
    <p className={`splash-shared-tag ${className}`.trim()}>A Habeas presentation</p>
  )
}
