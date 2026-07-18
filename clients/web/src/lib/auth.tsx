import { useQuery } from '@tanstack/react-query'
import { createContext, useContext, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { getMe, type MePayload, type UserRole } from '@/lib/api'

export type { MePayload, UserRole }

type AuthContextValue = {
  me: MePayload | undefined
  isLoading: boolean
  isError: boolean
  error: Error | null
  role: UserRole | undefined
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
  const { me, isLoading, isError, role } = useAuth()

  return {
    me,
    isLoading,
    isError,
    isSuperAdmin: role === 'super_admin',
    isAdmin: role === 'admin' || role === 'super_admin',
  }
}

export function isSuperAdmin(role: UserRole | undefined): boolean {
  return role === 'super_admin'
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
        <h2 className="mt-3 font-display text-[2.25rem] font-medium tracking-tight text-ink">
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
      <div role="status" aria-label="Loading access">
        <SkeletonLines lines={4} />
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
