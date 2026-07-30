import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
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
