import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Dev / Vite labs (`/dev/*`, matching-results-lab, lab chrome).
 * On unless this is a production build (`import.meta.env.PROD`).
 * Bake `VITE_ENABLE_LABS=true` to keep labs on Cloud Run admin-web-dev.
 */
export function labsEnabled(): boolean {
  return (
    import.meta.env.VITE_ENABLE_LABS === 'true' || !import.meta.env.PROD
  )
}

/** Matches admin-api `UUID(request_id)` validation for journey/detail routes. */
const REQUEST_UUID_RE =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i

export function isRequestUuid(value: string | null | undefined): boolean {
  if (value == null) return false
  const trimmed = value.trim()
  if (!trimmed || trimmed === 'undefined' || trimmed === 'null') return false
  return REQUEST_UUID_RE.test(trimmed)
}

/** Deduped request ids that pass `isRequestUuid` — stable sort for apply payloads. */
export function filterRequestUuids(ids: Iterable<string>): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const id of ids) {
    const trimmed = id.trim()
    if (!isRequestUuid(trimmed) || seen.has(trimmed)) continue
    seen.add(trimmed)
    out.push(trimmed)
  }
  return out.sort()
}

/**
 * Resolve connection invite URLs for copy/mailto.
 * Admin-api may return a path (`/connect/...`) when `public_web_base_url` is unset;
 * owners need an absolute link.
 */
export function absoluteInviteUrl(inviteUrl: string): string {
  const trimmed = inviteUrl.trim()
  if (!trimmed) return trimmed
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) return trimmed
  if (typeof window === 'undefined') return trimmed
  const path = trimmed.startsWith('/') ? trimmed : `/${trimmed}`
  return `${window.location.origin}${path}`
}

/** Best-effort first name from an IAP / Google account email local-part. */
export function firstNameFromEmail(email: string | null | undefined): string {
  const local = email?.split('@')[0]?.trim() ?? ''
  if (!local) return 'there'
  const token = local.split(/[._+-]/)[0] ?? local
  if (!token) return 'there'
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()
}

/** Client-side pagination slice — shared math for Inbox / All requests row lists. */
export function paginate<T>(items: T[], page: number, pageSize: number) {
  const total = items.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const currentPage = Math.min(Math.max(1, page), totalPages)
  const start = total === 0 ? 0 : (currentPage - 1) * pageSize
  const end = Math.min(start + pageSize, total)
  return {
    items: items.slice(start, end),
    total,
    totalPages,
    currentPage,
    start,
    end,
  }
}
