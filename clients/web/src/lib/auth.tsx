import { useQuery } from '@tanstack/react-query'
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'

import { Button } from '@/components/ui/button'
import {
  adminApiUserTokenNeedsRefresh,
  getAdminApiUserToken,
  getMe,
  googleIdentityServicesClientId,
  registerAdminApiUserTokenRefresher,
  setAdminApiUserToken,
  subscribeAdminApiUserToken,
  usesDirectAdminApi,
  type MePayload,
  type UserRole,
} from '@/lib/api'

export type { MePayload, UserRole }

export const GIS_SCRIPT_SRC = 'https://accounts.google.com/gsi/client'
export const GIS_LOAD_TIMEOUT_MS = 8_000
const GIS_PROMPT_TIMEOUT_MS = 8_000
/** RoleGate skeleton cap — flip to RoleApiErrorState if /me never arrives. */
export const ROLE_GATE_FAIL_SOFT_MS = 8_000

/** Architecture B (direct admin-api) miss vs same-origin `/api` role load. */
export type IdentityMissKind = 'google_sign_in' | 'role_api'

export const GOOGLE_SIGN_IN_ERROR = {
  title: 'Could not sign in with Google',
  description: 'Sign in with Google did not complete. Retry to continue.',
  retryLabel: 'Retry',
} as const

export function classifyIdentityMiss(input: {
  directAdminApi: boolean
  hasUserToken: boolean
}): IdentityMissKind {
  if (input.directAdminApi && !input.hasUserToken) return 'google_sign_in'
  return 'role_api'
}

type GoogleIdPromptNotification = {
  isNotDisplayed: () => boolean
  isSkippedMoment: () => boolean
  isDismissedMoment: () => boolean
}

type GoogleAccountsId = {
  initialize: (config: {
    client_id: string
    callback: (response: { credential?: string }) => void
    auto_select?: boolean
    cancel_on_tap_outside?: boolean
  }) => void
  prompt: (momentListener?: (notification: GoogleIdPromptNotification) => void) => void
  renderButton: (
    parent: HTMLElement,
    options: {
      type?: 'standard' | 'icon'
      theme?: 'outline' | 'filled_blue' | 'filled_black'
      size?: 'large' | 'medium' | 'small'
      text?: 'signin_with' | 'signup_with' | 'continue_with' | 'signin'
      shape?: 'rectangular' | 'pill' | 'circle' | 'square'
      width?: number
    },
  ) => void
  cancel?: () => void
}

type GisScriptElement = HTMLScriptElement & {
  complete?: boolean
  readyState?: string
}

declare global {
  interface Window {
    google?: { accounts?: { id?: GoogleAccountsId } }
  }
}

function isGoogleIdentityReady(): boolean {
  return Boolean(window.google?.accounts?.id)
}

function gisScriptAlreadySettled(script: GisScriptElement): boolean {
  if (script.complete === true) return true
  return script.readyState === 'complete' || script.readyState === 'loaded'
}

/**
 * Load GIS. Never hang: a completed/failed tag does not fire `load` again.
 * Timeout resolves (fail soft) so AuthProvider can settle a Google sign-in miss.
 */
export function loadGoogleIdentityScript(
  timeoutMs = GIS_LOAD_TIMEOUT_MS,
): Promise<void> {
  if (typeof document === 'undefined') return Promise.resolve()
  if (isGoogleIdentityReady()) return Promise.resolve()

  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      if (error) reject(error)
      else resolve()
    }
    const timer = window.setTimeout(() => finish(), timeoutMs)

    const existing = document.querySelector<GisScriptElement>(
      `script[src="${GIS_SCRIPT_SRC}"]`,
    )
    if (existing) {
      if (isGoogleIdentityReady() || gisScriptAlreadySettled(existing)) {
        finish()
        return
      }
      existing.addEventListener('load', () => finish(), { once: true })
      existing.addEventListener('error', () => finish(new Error('GIS script failed')), {
        once: true,
      })
      return
    }

    const script = document.createElement('script')
    script.src = GIS_SCRIPT_SRC
    script.async = true
    script.onload = () => finish()
    script.onerror = () => finish(new Error('GIS script failed'))
    document.head.appendChild(script)
  })
}

/**
 * Initialize GIS once per client id. One Tap (`prompt`) is best-effort —
 * IAP / FedCM often skip it. The Sign in with Google button stays available.
 */
export async function initializeGoogleIdentity(clientId: string): Promise<boolean> {
  await loadGoogleIdentityScript()
  const api = window.google?.accounts?.id
  if (!api) return false
  api.initialize({
    client_id: clientId,
    auto_select: true,
    cancel_on_tap_outside: false,
    callback: (response) => {
      const token = response.credential?.trim()
      if (token) setAdminApiUserToken(token)
    },
  })
  return true
}

/** One Tap only. Skip / not-displayed / dismiss is a miss, not a fatal error. */
export function promptGoogleOneTap(): Promise<string | null> {
  return new Promise((resolve) => {
    const api = window.google?.accounts?.id
    if (!api) {
      resolve(null)
      return
    }
    let settled = false
    const finish = (token: string | null) => {
      if (settled) return
      settled = true
      resolve(token)
    }
    const onToken = () => {
      const token = getAdminApiUserToken()
      if (token) {
        unsubscribe()
        window.clearTimeout(timer)
        finish(token)
      }
    }
    const unsubscribe = subscribeAdminApiUserToken(onToken)
    const timer = window.setTimeout(() => {
      unsubscribe()
      finish(getAdminApiUserToken())
    }, GIS_PROMPT_TIMEOUT_MS)
    onToken()
    api.prompt((notification) => {
      if (
        notification.isNotDisplayed() ||
        notification.isSkippedMoment() ||
        notification.isDismissedMoment()
      ) {
        window.clearTimeout(timer)
        unsubscribe()
        finish(getAdminApiUserToken())
      }
    })
  })
}

/** Official GIS button — works when One Tap is suppressed behind IAP. */
export async function renderGoogleSignInButton(
  parent: HTMLElement,
  clientId = googleIdentityServicesClientId(),
): Promise<boolean> {
  if (!clientId) return false
  const ready = await initializeGoogleIdentity(clientId)
  const api = window.google?.accounts?.id
  if (!ready || !api) return false
  parent.replaceChildren()
  api.renderButton(parent, {
    type: 'standard',
    theme: 'outline',
    size: 'large',
    text: 'signin_with',
    shape: 'rectangular',
    width: 280,
  })
  return true
}

let mintInflight: Promise<void> | null = null

/**
 * Architecture B: when VITE_ADMIN_API_URL is set, obtain a user ID token
 * before GET /me. Remints when the in-memory JWT is near expiry.
 * Same-origin `/api` skips GIS so local/prod proxy stays intact.
 */
export async function ensureDirectAdminApiUserToken(): Promise<void> {
  if (!usesDirectAdminApi()) return
  if (getAdminApiUserToken() && !adminApiUserTokenNeedsRefresh()) return
  if (mintInflight) return mintInflight
  const clientId = googleIdentityServicesClientId()
  if (!clientId) return
  mintInflight = (async () => {
    try {
      const ready = await initializeGoogleIdentity(clientId)
      if (!ready) return
      const token = await promptGoogleOneTap()
      if (token) setAdminApiUserToken(token)
    } catch {
      // Leave token unset. GET /me still runs via nginx /api (IAP) so the
      // session is not stuck on Retry when One Tap is skipped behind IAP.
    }
  })().finally(() => {
    mintInflight = null
  })
  return mintInflight
}

registerAdminApiUserTokenRefresher(ensureDirectAdminApiUserToken)

type AuthContextValue = {
  me: MePayload | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
  /** Architecture B: GIS user JWT is in memory. */
  hasUserToken: boolean
  /** Architecture B: GET /me failed and One Tap did not mint a token. */
  googleSignInFailed: boolean
  /** Remint GIS (Architecture B) then retry GET /me. */
  retryIdentity: () => void
  /** Effective role (may be simulated). */
  role: UserRole | undefined
  /** Allowlist role before simulate override. */
  realRole: UserRole | undefined
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const needsUserToken = usesDirectAdminApi()
  const [tokenReady, setTokenReady] = useState(!needsUserToken)
  const [hasUserToken, setHasUserToken] = useState(() => Boolean(getAdminApiUserToken()))
  const [googleSignInFailed, setGoogleSignInFailed] = useState(false)

  const settleDirectToken = useCallback((cancelled?: () => boolean) => {
    if (cancelled?.()) return
    setHasUserToken(Boolean(getAdminApiUserToken()))
    // One Tap miss is not fatal: GET /me still runs (nginx /api IAP fallback).
    setGoogleSignInFailed(false)
    setTokenReady(true)
  }, [])

  useEffect(() => {
    return subscribeAdminApiUserToken(() => {
      setHasUserToken(Boolean(getAdminApiUserToken()))
      setGoogleSignInFailed(false)
    })
  }, [])

  useEffect(() => {
    if (!needsUserToken) {
      setTokenReady(true)
      return
    }
    let cancelled = false
    void ensureDirectAdminApiUserToken().finally(() => {
      settleDirectToken(() => cancelled)
    })
    return () => {
      cancelled = true
    }
  }, [needsUserToken, settleDirectToken])

  const queryEnabled = tokenReady
  const query = useQuery({
    queryKey: ['admin-api', 'me'],
    queryFn: getMe,
    staleTime: 60_000,
    retry: false,
    enabled: queryEnabled,
  })

  const hadUserToken = useRef(hasUserToken)
  useEffect(() => {
    if (hasUserToken && !hadUserToken.current) {
      void query.refetch()
    }
    hadUserToken.current = hasUserToken
  }, [hasUserToken, query])

  const retryIdentity = useCallback(() => {
    setGoogleSignInFailed(false)
    if (!needsUserToken) {
      void query.refetch()
      return
    }
    setTokenReady(false)
    void ensureDirectAdminApiUserToken().finally(() => {
      settleDirectToken()
    })
  }, [needsUserToken, query, settleDirectToken])

  const value: AuthContextValue = {
    me: query.data,
    isLoading: !tokenReady || (queryEnabled && query.isLoading),
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
    hasUserToken,
    googleSignInFailed:
      googleSignInFailed ||
      (needsUserToken && !hasUserToken && tokenReady && query.isError),
    retryIdentity,
    role: query.data?.role,
    realRole: query.data?.real_role ?? query.data?.role,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}

/** Role session hook — shared query via AuthProvider. */
export function useMe() {
  const { me, isLoading, isError, role, realRole } = useAuth()

  return {
    me,
    isLoading,
    isError,
    role,
    realRole,
    isSuperAdmin: role === 'super_admin',
    isAdmin: role === 'admin' || role === 'super_admin',
    isLegal: role === 'legal',
  }
}

export function isSuperAdmin(role: UserRole | undefined): boolean {
  return role === 'super_admin'
}

export function isLegal(role: UserRole | undefined): boolean {
  return role === 'legal'
}

export function canAccessLegalSurfaces(role: UserRole | undefined): boolean {
  return role === 'legal' || role === 'super_admin' || role === 'admin'
}

/** Data owner or data user — matching review, fulfill, refresh. */
export function isVerticalOperatorRole(role: UserRole | undefined): boolean {
  return role === 'data_owner' || role === 'data_user'
}

/** ⌘K palette — legal/admin plus data owners (Requests + Actions; People stays legal-only). */
export function canAccessOwnerPalette(role: UserRole | undefined): boolean {
  return canAccessLegalSurfaces(role) || isVerticalOperatorRole(role)
}

/** Legal Home / inbox persona — admin and legal share surfaces (KD1). */
export function isLegalAdminPersona(role: UserRole | undefined): boolean {
  return role === 'legal' || role === 'admin'
}

/** Conditions, SLAs, email templates — admin write only (KD2). */
export function canMutateLegalSettings(role: UserRole | undefined): boolean {
  return role === 'admin' || role === 'super_admin'
}

export function canAccessInsights(role: UserRole | undefined): boolean {
  return role === 'super_admin' || role === 'admin'
}

export function canAccessOpsSurfaces(role: UserRole | undefined): boolean {
  return role === 'super_admin'
}

type RouteShellProps = {
  eyebrow: string
  title: string
  description: string
  note?: string
}

export function RouteShell({ eyebrow, title, description, note }: RouteShellProps) {
  return (
    <section className="space-y-8">
      <header>
        <p className="taste-micro">{eyebrow}</p>
        <h2 className="mt-3 font-display text-xl font-medium tracking-tight text-ink">
          {title}
        </h2>
        <p className="mt-4 max-w-xl text-sm leading-relaxed text-ink-soft">{description}</p>
      </header>
      <div className="taste-panel-soft p-6 sm:p-7">
        <p className="text-sm text-ink-soft">
          {note ?? 'Shell route — full experience ships in a follow-up unit.'}
        </p>
      </div>
    </section>
  )
}

export function ForbiddenState() {
  return (
    <section className="space-y-4">
      <p className="taste-micro">Access</p>
      <h2 className="font-display text-[2rem] font-medium tracking-tight text-ink">Forbidden</h2>
      <p className="max-w-md text-sm leading-relaxed text-ink-soft">
        Your role does not include this surface. If you need access, contact a super admin.
      </p>
    </section>
  )
}

type RoleGateProps = {
  allow: (role: UserRole) => boolean
  children: ReactNode
}

function RoleApiErrorState({ error }: { error: Error | null }) {
  return (
    <section className="space-y-4">
      <p className="taste-micro">Access</p>
      <h2 className="font-display text-[2rem] font-medium tracking-tight text-ink">
        Cannot load role
      </h2>
      <p className="max-w-lg text-sm leading-relaxed text-ink-soft">
        The UI called <code className="text-ink">GET /me</code> and failed.{' '}
        {usesDirectAdminApi() ? (
          <>
            Direct admin-api (<code className="text-ink">VITE_ADMIN_API_URL</code> set) needs{' '}
            <code className="text-ink">Authorization: Bearer</code> with a user Google ID token
            from GIS (<code className="text-ink">VITE_GOOGLE_CLIENT_ID</code> or{' '}
            <code className="text-ink">VITE_GIS_CLIENT_ID</code> — not a hardcoded client id).
          </>
        ) : (
          <>
            Same-origin <code className="text-ink">GET /api/me</code> (nginx/Vite proxy). On Cloud
            Run, confirm IAP is only on <code className="text-ink">admin-web-dev</code> or{' '}
            <code className="text-ink">admin-web-prod</code>, admin-api has{' '}
            <code className="text-ink">--no-iap</code>, and the web runtime SA has{' '}
            <code className="text-ink">roles/run.invoker</code>.
          </>
        )}{' '}
        Locally leave <code className="text-ink">VITE_ADMIN_API_URL</code> empty and use{' '}
        <code className="text-ink">http://127.0.0.1:5174</code> with admin-api on :8000.
      </p>
      {error ? <p className="max-w-lg text-xs text-mute">{error.message}</p> : null}
    </section>
  )
}

function GoogleSignInErrorState({ onRetry }: { onRetry: () => void }) {
  const buttonHostRef = useRef<HTMLDivElement>(null)
  const [buttonKey, setButtonKey] = useState(0)

  useEffect(() => {
    const host = buttonHostRef.current
    if (!host) return
    void renderGoogleSignInButton(host)
  }, [buttonKey])

  return (
    <section className="space-y-4">
      <p className="taste-micro">Access</p>
      <h2 className="font-display text-[2rem] font-medium tracking-tight text-ink">
        {GOOGLE_SIGN_IN_ERROR.title}
      </h2>
      <p className="max-w-lg text-sm leading-relaxed text-ink-soft">
        {GOOGLE_SIGN_IN_ERROR.description}
      </p>
      <div ref={buttonHostRef} className="min-h-10" data-testid="gis-sign-in-button" />
      <Button
        type="button"
        onClick={() => {
          setButtonKey((key) => key + 1)
          onRetry()
        }}
      >
        {GOOGLE_SIGN_IN_ERROR.retryLabel}
      </Button>
    </section>
  )
}

export function RoleGate({ allow, children }: RoleGateProps) {
  const {
    role,
    isLoading,
    me,
    isError,
    error,
    hasUserToken,
    googleSignInFailed,
    retryIdentity,
  } = useAuth()
  const [loadingTimedOut, setLoadingTimedOut] = useState(false)
  const waitingForMe = isLoading && !me
  const showGoogleSignIn =
    usesDirectAdminApi() &&
    !hasUserToken &&
    !me &&
    (googleSignInFailed || isError || loadingTimedOut)

  useEffect(() => {
    if (!waitingForMe) {
      setLoadingTimedOut(false)
      return
    }
    const timer = window.setTimeout(() => {
      setLoadingTimedOut(true)
    }, ROLE_GATE_FAIL_SOFT_MS)
    return () => {
      window.clearTimeout(timer)
    }
  }, [waitingForMe])

  if (waitingForMe && !loadingTimedOut) {
    return (
      <div className="space-y-3" role="status" aria-label="Loading access">
        {Array.from({ length: 4 }, (_, index) => (
          <div
            key={index}
            className={`h-4 animate-pulse rounded-md bg-line/80 ${
              index === 3 ? 'w-2/3' : 'w-full'
            }`}
            aria-hidden="true"
          />
        ))}
      </div>
    )
  }

  if (showGoogleSignIn) {
    return <GoogleSignInErrorState onRetry={retryIdentity} />
  }

  if (isError || loadingTimedOut) {
    return <RoleApiErrorState error={error} />
  }

  if (!role || !allow(role)) {
    return <ForbiddenState />
  }

  return children
}
