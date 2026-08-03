import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
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
