import { KEYHOLE_SLOT_SLIDE_IN_ID } from './splash/variants/keyhole-offset'
import { renderSplashVariant, SPLASH_VARIANT_COUNT, SPLASH_VARIANTS } from './splash/registry'

export { SPLASH_VARIANT_COUNT, SPLASH_VARIANTS, KEYHOLE_SLOT_SLIDE_IN_ID }

type PostAuthSplashProps = {
  variant?: number
  autoFinish?: boolean
  durationMs?: number
  onDone?: () => void
  className?: string
}

/** Post-IAP bumper — pick a variant from /dev/splash-lab. Default: CRT Snow Lock (1). */
export function PostAuthSplash({
  variant = 1,
  autoFinish = false,
  durationMs = 3400,
  onDone,
  className = '',
}: PostAuthSplashProps) {
  const id = Math.min(SPLASH_VARIANT_COUNT, Math.max(1, variant))
  return renderSplashVariant(id, { autoFinish, durationMs, onDone, className })
}

const SPLASH_SEEN_KEY = 'catapriv.splash.seen'

export function shouldPlayPostAuthSplash() {
  try {
    return sessionStorage.getItem(SPLASH_SEEN_KEY) !== '1'
  } catch {
    return true
  }
}

export function markPostAuthSplashSeen() {
  try {
    sessionStorage.setItem(SPLASH_SEEN_KEY, '1')
  } catch {
    /* ignore */
  }
}
