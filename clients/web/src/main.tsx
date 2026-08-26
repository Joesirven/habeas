import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from '@tanstack/react-router'
import { Component, StrictMode, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

import { router } from '@/router'
import './index.css'

const queryFetchStarts = new Map<string, number>()

function redactQueryKey(queryKey: readonly unknown[]): string {
  const safe = queryKey.map((part) =>
    typeof part === 'string' && part.includes('@') ? '[redacted]' : part,
  )
  return JSON.stringify(safe)
}

function isAbortLike(error: unknown): boolean {
  const name =
    error && typeof error === 'object' && 'name' in error
      ? String((error as { name?: unknown }).name)
      : ''
  return name === 'AbortError' || name === 'TimeoutError'
}

function logQueryTiming(fields: {
  queryKey: string
  start: number
  duration_ms: number
  status: 'pending' | 'success' | 'error'
  abort: boolean
}): void {
  console.info({
    prefix: 'dpra-timing',
    kind: 'query',
    route: globalThis.location?.pathname ?? '',
    url: '',
    ...fields,
  })
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
    },
  },
})

queryClient.getQueryCache().subscribe((event) => {
  if (event.type !== 'updated') return
  const { query, action } = event
  const queryKey = redactQueryKey(query.queryKey)
  const hash = query.queryHash

  if (action.type === 'fetch') {
    const start = Date.now()
    queryFetchStarts.set(hash, start)
    logQueryTiming({
      queryKey,
      start,
      duration_ms: 0,
      status: 'pending',
      abort: false,
    })
    return
  }

  if (action.type !== 'success' && action.type !== 'error') return

  const start = queryFetchStarts.get(hash) ?? 0
  queryFetchStarts.delete(hash)
  const duration_ms = start > 0 ? Date.now() - start : 0
  const abort = action.type === 'error' && isAbortLike(action.error)
  logQueryTiming({
    queryKey,
    start,
    duration_ms,
    status: action.type,
    abort,
  })
})

type ErrorBoundaryProps = {
  children: ReactNode
}

type ErrorBoundaryState = {
  error: Error | null
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div className="min-h-screen bg-paper px-4 py-8 text-ink">
          <p className="text-xs text-ink">Something went wrong loading this page.</p>
          <p className="mt-2 text-xs text-mute">{this.state.error.message}</p>
          <button
            type="button"
            className="mt-3 rounded border border-line px-2 py-1 text-xs"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ErrorBoundary>
        <RouterProvider router={router} />
      </ErrorBoundary>
    </QueryClientProvider>
  </StrictMode>,
)
