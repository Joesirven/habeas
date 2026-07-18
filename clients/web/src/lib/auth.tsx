import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { getMe, type OpsRole } from '@/lib/api'

export const ME_QUERY_KEY = ['admin-api', 'me'] as const

export function useMeQuery(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ME_QUERY_KEY,
    queryFn: getMe,
    retry: false,
    staleTime: 60_000,
    enabled: options?.enabled ?? true,
  })
}

export function useOpsRole(): OpsRole | null {
  const me = useMeQuery()
  return me.data?.role ?? null
}

/** Power console + Runs / Jobs / ops Dashboard / Incidents / ops Configuration. */
export function isSuperAdmin(role: OpsRole | null | undefined): boolean {
  return role === 'super_admin'
}

/** Matching review / needs-attention — any resolved ops role. */
export function canAccessNeedsAttention(role: OpsRole | null | undefined): boolean {
  return role === 'super_admin' || role === 'admin' || role === 'data_owner'
}

export function ForbiddenEmptyState({
  eyebrow = 'ACCESS',
  title = 'Not available for this role',
  detail = 'This route is gated by DROP ops role. Your session does not include access.',
}: {
  eyebrow?: string
  title?: string
  detail?: string
}) {
  return (
    <section className="space-y-4">
      <header>
        <p className="taste-micro">{eyebrow}</p>
        <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink sm:text-2xl">
          {title}
        </h2>
      </header>
      <div className="taste-panel p-5">
        <p className="text-sm text-ink-soft">{detail}</p>
      </div>
    </section>
  )
}

type RequireRoleProps = {
  allow: readonly OpsRole[]
  children: ReactNode
  /** Shown while GET /me is in flight. */
  loading?: ReactNode
}

/** Client-side deep-link gate. API 403 remains authoritative (U5/U8). */
export function RequireRole({ allow, children, loading }: RequireRoleProps) {
  const me = useMeQuery()

  if (me.isPending) {
    return (
      loading ?? (
        <div className="taste-panel space-y-3 p-5" role="status" aria-label="Loading session">
          <div className="h-4 w-full animate-pulse rounded-md bg-line/80" aria-hidden />
          <div className="h-4 w-full animate-pulse rounded-md bg-line/80" aria-hidden />
          <div className="h-4 w-2/3 animate-pulse rounded-md bg-line/80" aria-hidden />
        </div>
      )
    )
  }

  const role = me.data?.role ?? null
  if (!role || !allow.includes(role)) {
    return <ForbiddenEmptyState />
  }

  return children
}

export function OpsPageChrome({
  eyebrow,
  title,
  support,
  children,
}: {
  eyebrow: string
  title: string
  support?: string
  children?: ReactNode
}) {
  return (
    <section className="space-y-6">
      <header className="max-w-2xl">
        <p className="taste-micro">{eyebrow}</p>
        <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink sm:text-2xl">
          {title}
        </h2>
        {support ? <p className="mt-2 text-sm leading-relaxed text-ink-soft">{support}</p> : null}
      </header>
      {children}
    </section>
  )
}
