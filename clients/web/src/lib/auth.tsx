import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'

import { getMe, type MePayload, type UserRole } from '@/lib/api'

export type { MePayload, UserRole }

type AuthContextValue = {
  me: MePayload | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
  /** Effective role (may be simulated). */
  role: UserRole | undefined
  /** Allowlist role before simulate override. */
  realRole: UserRole | undefined
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const query = useQuery({
    queryKey: ['admin-api', 'me'],
    queryFn: getMe,
    staleTime: 60_000,
    retry: 1,
  })

  const value: AuthContextValue = {
    me: query.data,
    isLoading: query.isLoading,
    isError: query.isError,
    error: query.error instanceof Error ? query.error : null,
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

export function RoleGate({ allow, children }: RoleGateProps) {
  const { role, isLoading, isError, error } = useAuth()

  if (isLoading) {
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

  if (isError) {
    return (
      <section className="space-y-4">
        <p className="taste-micro">Access</p>
        <h2 className="font-display text-[2rem] font-medium tracking-tight text-ink">
          Cannot load role
        </h2>
        <p className="max-w-lg text-sm leading-relaxed text-ink-soft">
          The UI called <code className="text-ink">GET /api/me</code> (same-origin proxy to
          admin-api) and failed. On Cloud Run, confirm IAP is only on{' '}
          <code className="text-ink">ops-ia-web-dev</code>, admin-api has{' '}
          <code className="text-ink">--no-iap</code>, and the web runtime SA has{' '}
          <code className="text-ink">roles/run.invoker</code>. Locally use{' '}
          <code className="text-ink">http://127.0.0.1:5174</code> with admin-api on :8000.
        </p>
        {error ? (
          <p className="max-w-lg text-xs text-mute">{error.message}</p>
        ) : null}
      </section>
    )
  }

  if (!role || !allow(role)) {
    return <ForbiddenState />
  }

  return children
}
