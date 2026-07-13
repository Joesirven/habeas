const API_BASE = import.meta.env.VITE_ADMIN_API_URL ?? '/api'

export async function fetchAdminApi<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...init?.headers,
    },
  })

  if (!response.ok) {
    throw new Error(`Admin API ${response.status}: ${response.statusText}`)
  }

  return response.json() as Promise<T>
}

export type HealthPayload = {
  status: string
  service?: string
}

export function getHealth() {
  return fetchAdminApi<HealthPayload>('/healthz')
}
