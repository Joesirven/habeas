import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { actionToast } from '@/lib/action-toast'
import {
  canAccessOpsSurfaces,
  ForbiddenState,
  useMe,
} from '@/lib/auth'
import {
  getSheetsOauthLabStatus,
  sheetsOauthLabRedeem,
  sheetsOauthLabStart,
  sheetsOauthLabTest,
} from '@/lib/api'

const DEFAULT_SHEET_URL =
  'https://docs.google.com/spreadsheets/d/1UfivETx7dY4O6gkoc13mVypuW2wb4xVWUNoJN02mgrs/edit?gid=886346040#gid=886346040'

const SESSION_KEY = 'habeas-cli.lab.sheets-oauth.session'

type StoredLabSession = {
  lab_session_id: string
  state: string
  spreadsheet_url: string
}

function readStoredSession(): StoredLabSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredLabSession
    if (!parsed.lab_session_id || !parsed.state) return null
    return parsed
  } catch {
    return null
  }
}

function writeStoredSession(session: StoredLabSession | null) {
  if (session == null) {
    sessionStorage.removeItem(SESSION_KEY)
    return
  }
  sessionStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export type SheetsOauthLabSearch = {
  code?: string
  state?: string
  error?: string
}

function searchWithoutOauthCallback(search: SheetsOauthLabSearch): SheetsOauthLabSearch {
  return search.error ? { error: search.error } : {}
}

/** Owner-style Sheets OAuth lab — not production connections wiring. */
export function SheetsOauthLabPage() {
  const me = useMe()
  const navigate = useNavigate({ from: '/dev/sheets-oauth' })
  const search = useSearch({ from: '/dev/sheets-oauth' })
  const queryClient = useQueryClient()

  const [spreadsheetUrl, setSpreadsheetUrl] = useState(DEFAULT_SHEET_URL)
  const [labSessionId, setLabSessionId] = useState<string | null>(
    () => readStoredSession()?.lab_session_id ?? null,
  )
  const [stepNote, setStepNote] = useState<string | null>(null)

  const statusQuery = useQuery({
    queryKey: ['lab', 'sheets-oauth', 'status'],
    queryFn: getSheetsOauthLabStatus,
    enabled: canAccessOpsSurfaces(me.role),
  })

  const redirectUri = useMemo(() => {
    if (typeof window === 'undefined') return 'http://127.0.0.1:5173/dev/sheets-oauth'
    return `${window.location.origin}/dev/sheets-oauth`
  }, [])

  const startMutation = useMutation({
    mutationFn: () =>
      sheetsOauthLabStart({
        spreadsheet_url: spreadsheetUrl.trim(),
        redirect_uri: redirectUri,
      }),
    onSuccess: (data) => {
      writeStoredSession({
        lab_session_id: data.lab_session_id,
        state: data.state,
        spreadsheet_url: spreadsheetUrl.trim(),
      })
      setLabSessionId(data.lab_session_id)
      window.location.assign(data.authorize_url)
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not start Google connect',
        description: actionToast.safeErrorMessage(error),
      })
    },
  })

  const redeemMutation = useMutation({
    mutationFn: (input: { lab_session_id: string; code: string; state: string }) =>
      sheetsOauthLabRedeem(input),
    onSuccess: (data) => {
      setStepNote(
        `Refresh token stored in admin-api memory · domain ${data.google_email_domain ?? 'unknown'}`,
      )
      actionToast.success({
        title: 'Google connected',
        description: 'Owner-style refresh token captured (lab memory only).',
      })
      void queryClient.invalidateQueries({ queryKey: ['lab', 'sheets-oauth'] })
      void navigate({
        to: '/dev/sheets-oauth',
        search: {},
        replace: true,
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Redeem failed',
        description: actionToast.safeErrorMessage(error),
      })
      void navigate({
        to: '/dev/sheets-oauth',
        search: searchWithoutOauthCallback(search),
        replace: true,
      })
    },
  })

  const testMutation = useMutation({
    mutationFn: () => {
      if (!labSessionId) throw new Error('missing lab session')
      return sheetsOauthLabTest({ lab_session_id: labSessionId })
    },
    onSuccess: (data) => {
      if (data.ok) {
        actionToast.success({
          title: 'Connection test passed',
          description: `detail=${data.detail} sheets=${data.sheet_count ?? 'n/a'}`,
        })
      } else {
        actionToast.error({
          title: 'Connection test failed',
          description: data.detail,
        })
      }
    },
    onError: (error) => {
      actionToast.error({
        title: 'Test failed',
        description: actionToast.safeErrorMessage(error),
      })
    },
  })

  useEffect(() => {
    if (search.error) {
      setStepNote(`Google returned error=${search.error}`)
      return
    }
    if (!search.code || !search.state) return
    const stored = readStoredSession()
    if (!stored) {
      setStepNote('OAuth returned a code but no lab session was found in this browser.')
      void navigate({
        to: '/dev/sheets-oauth',
        search: searchWithoutOauthCallback(search),
        replace: true,
      })
      return
    }
    if (stored.state !== search.state) {
      setStepNote('OAuth state mismatch — start Connect again.')
      void navigate({
        to: '/dev/sheets-oauth',
        search: searchWithoutOauthCallback(search),
        replace: true,
      })
      return
    }
    if (redeemMutation.isPending || redeemMutation.isSuccess) return
    redeemMutation.mutate({
      lab_session_id: stored.lab_session_id,
      code: search.code,
      state: search.state,
    })
    // Intentionally once per code/state pair.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [search.code, search.state, search.error])

  if (me.isLoading) {
    return <p className="text-sm text-slate-500">Loading identity…</p>
  }
  if (!canAccessOpsSurfaces(me.role)) {
    return <ForbiddenState />
  }

  const configured = statusQuery.data?.configured === true

  return (
    <section className="mx-auto max-w-2xl space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
          Dev lab · not production
        </p>
        <h1 className="text-xl font-semibold text-slate-900">Sheets owner OAuth</h1>
        <p className="text-sm leading-relaxed text-slate-600">
          Experiment for the data-owner path: sign in with Google, store a refresh token
          server-side, then run the same metadata connection test workers would use. No
          domain-wide delegation and no share-to-service-account step.
        </p>
      </header>

      <div className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-slate-500">OAuth client</span>
          {statusQuery.isLoading ? (
            <Badge variant="wait">Checking…</Badge>
          ) : configured ? (
            <Badge variant="ok">Configured</Badge>
          ) : (
            <Badge variant="fail">Not configured</Badge>
          )}
          <span className="text-xs text-slate-500">Secret store</span>
          <Badge variant="wait">{statusQuery.data?.secret_store ?? 'process_memory'}</Badge>
        </div>
        <p className="text-xs leading-relaxed text-slate-600">
          {statusQuery.data?.note ??
            'Admin-api must expose SHEETS_LAB_OAUTH_CLIENT_ID / SECRET for a Workspace-internal OAuth client.'}
        </p>
        <p className="font-mono text-[11px] text-slate-500 break-all">
          redirect_uri={redirectUri}
        </p>
        <p className="font-mono text-[11px] text-slate-500">
          actor={statusQuery.data?.actor_email ?? me.me?.email ?? '—'}
        </p>
      </div>

      <ol className="space-y-4">
        <li className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
          <p className="text-sm font-medium text-slate-900">1 · Spreadsheet URL</p>
          <p className="text-xs text-slate-600">
            Paste a sheet you can already open as your @habeas.us user (owner already has
            access — no external share).
          </p>
          <input
            value={spreadsheetUrl}
            onChange={(event) => setSpreadsheetUrl(event.target.value)}
            aria-label="Spreadsheet URL"
            className="w-full rounded-md border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-900 outline-none focus:border-habeas-mid focus:ring-1 focus:ring-habeas-mid"
          />
        </li>

        <li className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
          <p className="text-sm font-medium text-slate-900">2 · Connect Google</p>
          <p className="text-xs text-slate-600">
            Offline access + spreadsheets.readonly + drive.readonly + openid + email.
            Consent as the owner account. Refresh token is redeemed by admin-api (client
            secret never in the browser).
          </p>
          <Button
            type="button"
            disabled={startMutation.isPending || !spreadsheetUrl.trim()}
            onClick={() => {
              if (!configured) {
                actionToast.warning({
                  title: 'OAuth client not configured',
                  description:
                    'Set SHEETS_LAB_OAUTH_CLIENT_ID and SHEETS_LAB_OAUTH_CLIENT_SECRET on admin-api, then restart it.',
                })
                return
              }
              startMutation.mutate()
            }}
          >
            {startMutation.isPending ? 'Starting…' : 'Connect Google Sheets'}
          </Button>
          {!configured ? (
            <p className="text-xs text-amber-800">
              Button is ready, but Connect will not start until the badge above is{' '}
              <span className="font-medium">Configured</span> (OAuth client env on
              admin-api).
            </p>
          ) : null}
        </li>

        <li className="rounded-md border border-slate-200 bg-white p-4 space-y-3">
          <p className="text-sm font-medium text-slate-900">3 · Connection test</p>
          <p className="text-xs text-slate-600">
            Calls spreadsheets.get for spreadsheet id + sheet count only — no cell values.
          </p>
          <Button
            type="button"
            variant="outline"
            disabled={!labSessionId || testMutation.isPending || redeemMutation.isPending}
            onClick={() => testMutation.mutate()}
          >
            {testMutation.isPending ? 'Testing…' : 'Run connection test'}
          </Button>
          {labSessionId ? (
            <p className="font-mono text-[11px] text-slate-500">
              lab_session={labSessionId.slice(0, 10)}…
            </p>
          ) : null}
          {stepNote ? <p className="text-xs text-slate-700">{stepNote}</p> : null}
          {testMutation.data ? (
            <p className="font-mono text-[11px] text-slate-700">
              ok={String(testMutation.data.ok)} detail={testMutation.data.detail}{' '}
              sheet_count={testMutation.data.sheet_count ?? 'n/a'}
            </p>
          ) : null}
        </li>
      </ol>

      <div className="rounded-md border border-dashed border-slate-300 bg-slate-50 p-4 text-xs text-slate-600 space-y-2">
        <p className="font-medium text-slate-800">Setup (once)</p>
        <ol className="list-decimal pl-4 space-y-1">
          <li>
            In Google Cloud Console (example-gcp-project), create an <strong>OAuth client</strong> type
            Web application, internal/Workspace users.
          </li>
          <li>Add authorized redirect URI: {redirectUri}</li>
          <li>
            Enable Sheets API. Put client id/secret on local admin-api as{' '}
            <code className="font-mono">SHEETS_LAB_OAUTH_CLIENT_ID</code> /{' '}
            <code className="font-mono">SHEETS_LAB_OAUTH_CLIENT_SECRET</code>.
          </li>
          <li>Restart admin-api, then use Connect on this page as dev-owner-1@example.com.</li>
        </ol>
      </div>
    </section>
  )
}
