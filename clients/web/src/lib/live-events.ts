import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

// Empty string must fall back to /api (same as api.ts) — ?? keeps "".
const LIVE_EVENTS_PATH = `${import.meta.env.VITE_ADMIN_API_URL || '/api'}/live/events`

export function useLiveEvents() {
  const queryClient = useQueryClient()

  useEffect(() => {
    const source = new EventSource(LIVE_EVENTS_PATH)

    source.addEventListener('ready', () => {
      // Placeholder until Postgres LISTEN bridge emits resource-specific events.
    })

    source.onmessage = () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'drop-matching-progress'],
      })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-pipeline'] })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops', 'drop-processes'] })
    }

    source.onerror = () => {
      source.close()
    }

    return () => source.close()
  }, [queryClient])
}
