/**
 * Sheets connect step for the owner wizard — Google sign-in, spreadsheet/tab
 * pick, or CSV fallback. Mapping and format/delimiter steps run after this
 * panel (same runner path as upload). OAuth session helpers live here so the
 * settings page can detect an OAuth return and reopen the wizard.
 */
import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  connectTestFailureMessage,
  downloadOwnerUploadTemplate,
  ownerSheetsOauthExtract,
  ownerSheetsOauthFiles,
  ownerSheetsOauthStart,
  setOwnerConnectorMode,
  uploadOwnerConnectorCsv,
  type OwnerConnectorSystem,
  type OwnerSheetsOauthFile,
  type OwnerUploadResult,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  MANUAL_UPLOAD_LABEL,
  ownerConnectorDisplayName,
  systemWizardCopy,
  type SheetsConnectMethod,
} from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

import { OWNER_FIELD_CLASS } from './wizard-shared'

const FIELD_CLASS = OWNER_FIELD_CLASS

const OWNER_SHEETS_OAUTH_SESSION_KEY = 'habeas-cli.owner.sheets-oauth.session'

/** OAuth allowlist pins the return to the settings page route. */
export const OWNER_SHEETS_OAUTH_REDIRECT_PATH = '/owner/connectors'

export type StoredOwnerSheetsOauthSession = {
  verticalId: string
  system: string
  state: string
  session_id: string
  redeemed?: boolean
}

function ownerSheetsOauthRedirectUri() {
  if (typeof window === 'undefined') {
    return `http://127.0.0.1:5173${OWNER_SHEETS_OAUTH_REDIRECT_PATH}`
  }
  return `${window.location.origin}${OWNER_SHEETS_OAUTH_REDIRECT_PATH}`
}

export function readOwnerSheetsOauthSession(): StoredOwnerSheetsOauthSession | null {
  try {
    const raw = sessionStorage.getItem(OWNER_SHEETS_OAUTH_SESSION_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as StoredOwnerSheetsOauthSession
    if (!parsed.verticalId || !parsed.system || !parsed.state || !parsed.session_id) {
      return null
    }
    return parsed
  } catch {
    return null
  }
}

export function writeOwnerSheetsOauthSession(session: StoredOwnerSheetsOauthSession | null) {
  if (session == null) {
    sessionStorage.removeItem(OWNER_SHEETS_OAUTH_SESSION_KEY)
    return
  }
  const persisted: StoredOwnerSheetsOauthSession = {
    verticalId: session.verticalId,
    system: session.system,
    state: session.state,
    session_id: session.session_id,
  }
  if (session.redeemed) persisted.redeemed = true
  sessionStorage.setItem(OWNER_SHEETS_OAUTH_SESSION_KEY, JSON.stringify(persisted))
}

function connectorTitle(
  verticalId: string,
  connector: Pick<OwnerConnectorSystem, 'system' | 'display_name'>,
) {
  return ownerConnectorDisplayName(verticalId, connector.system, connector.display_name)
}

function tabKey(tab: { title: string; sheet_id?: number | null }) {
  return tab.sheet_id != null ? `${tab.sheet_id}:${tab.title}` : tab.title
}

export type SheetsConnectDraft = {
  method: SheetsConnectMethod | null
  oauthRedeemed: boolean
  spreadsheetId: string
  tab: string
  csvHeaders: string[]
  uploadOk: boolean
}

export function emptySheetsConnectDraft(): SheetsConnectDraft {
  return {
    method: null,
    oauthRedeemed: false,
    spreadsheetId: '',
    tab: '',
    csvHeaders: [],
    uploadOk: false,
  }
}

function headersFromResult(result: OwnerUploadResult, fallback: string[] = []): string[] {
  const detected = result.detected_headers?.filter((header) => header.trim()) ?? []
  return detected.length > 0 ? detected : fallback
}

function headersReady(result: OwnerUploadResult): boolean {
  return result.ok || result.detail === 'upload_needs_mapping'
}

function toastHeadersResult(result: OwnerUploadResult, kind: 'extract' | 'upload') {
  if (headersReady(result)) {
    const count = result.detected_headers?.filter((header) => header.trim()).length
    actionToast.success({
      title: kind === 'extract' ? 'Columns found' : 'File accepted',
      description:
        count != null && count > 0
          ? `${count} column${count === 1 ? '' : 's'} found. Map them next.`
          : 'Map your columns next.',
    })
    return
  }
  actionToast.error({
    title: kind === 'extract' ? 'Extract failed' : 'Upload failed',
    description: connectTestFailureMessage(result.detail),
  })
}

/**
 * CSV fallback on the sheets connect step. Headers only — mapping and
 * format/delimiter run as later wizard steps.
 */
function SheetsCsvUploadPanel({
  verticalId,
  connector,
  uploadOk,
  onUploadOkChange,
  onBack,
  onContinue,
  onFileSelected,
  onHeadersReady,
  invalidate,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  uploadOk: boolean
  onUploadOkChange: (ok: boolean) => void
  onBack: () => void
  onContinue: () => void
  onFileSelected?: (file: File | null) => void
  onHeadersReady: (result: OwnerUploadResult, headers: string[]) => void
  invalidate: () => void
}) {
  const [file, setFile] = useState<File | null>(null)

  const templateMutation = useMutation({
    mutationFn: () => downloadOwnerUploadTemplate(verticalId, connector.system),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${connector.system}-upload-template.csv`
      anchor.click()
      URL.revokeObjectURL(url)
      actionToast.success({
        title: 'Template downloaded',
        description: 'Optional Habeas headers. You can still upload an existing export and map columns.',
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not download template',
        description: actionToast.safeErrorMessage(
          error,
          'Template may not be ready yet. Try again shortly.',
        ),
        action: {
          label: 'Retry',
          onClick: () => templateMutation.mutate(),
        },
      })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV file first.')
      return uploadOwnerConnectorCsv(verticalId, connector.system, file, null, null, {})
    },
    onSuccess: (result) => {
      invalidate()
      toastHeadersResult(result, 'upload')
      if (!headersReady(result)) {
        onUploadOkChange(false)
        return
      }
      const headers = headersFromResult(result)
      onUploadOkChange(true)
      onHeadersReady(result, headers)
    },
    onError: (error) => {
      onUploadOkChange(false)
      actionToast.error({
        title: 'Upload failed',
        description: actionToast.safeErrorMessage(error, 'Check the file and try again.'),
        action: {
          label: 'Retry',
          onClick: () => uploadMutation.mutate(),
        },
      })
    },
  })

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-ink">
        {connectorTitle(verticalId, connector)} · Upload CSV
      </h4>
      <p className="text-xs text-mute">
        {systemWizardCopy(connector.system)?.uploadHowto ??
          'Upload your export as-is. You will map columns and choose formats next.'}
      </p>
      <div className="flex flex-wrap gap-1.5">
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={templateMutation.isPending}
          onClick={() => templateMutation.mutate()}
        >
          {templateMutation.isPending ? 'Downloading…' : 'Download template'}
        </Button>
      </div>

      <label className="block space-y-1 text-xs">
        <span className="font-medium text-ink">CSV file</span>
        <input
          type="file"
          accept=".csv,text/csv"
          className="block w-full text-xs text-ink file:mr-2 file:rounded file:border file:border-line file:bg-white file:px-2 file:py-1"
          onChange={(event) => {
            const next = event.target.files?.[0] ?? null
            setFile(next)
            onFileSelected?.(next)
            onUploadOkChange(false)
          }}
        />
      </label>

      <div className="flex flex-wrap justify-between gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onBack}>
          Back
        </Button>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={!file || uploadMutation.isPending}
            onClick={() => uploadMutation.mutate()}
          >
            {uploadMutation.isPending ? 'Uploading…' : 'Read columns'}
          </Button>
          <Button type="button" size="sm" disabled={!uploadOk} onClick={onContinue}>
            Continue
          </Button>
        </div>
      </div>
    </div>
  )
}

/**
 * Sheets connect panel — sign in with Google and pick a spreadsheet/tab, or
 * upload a CSV. Mapping and format/delimiter are later wizard steps.
 */
export function SheetsConnectPanel({
  verticalId,
  connector,
  draft,
  onDraftChange,
  onBack,
  onContinue,
  onHeadersReady,
  onFileSelected,
  invalidate,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  draft: SheetsConnectDraft
  onDraftChange: (next: SheetsConnectDraft) => void
  onBack: () => void
  onContinue: () => void
  onHeadersReady: (result: OwnerUploadResult, headers: string[]) => void
  onFileSelected?: (file: File | null) => void
  invalidate: () => void
}) {
  const systemLabel = connectorTitle(verticalId, connector)
  const storedOauth = readOwnerSheetsOauthSession()
  const oauthReady =
    draft.oauthRedeemed ||
    (storedOauth?.redeemed === true &&
      storedOauth.verticalId === verticalId &&
      storedOauth.system === connector.system)

  const filesQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'sheets-oauth', 'files', verticalId, connector.system],
    queryFn: () => ownerSheetsOauthFiles(verticalId, connector.system),
    enabled: draft.method === 'oauth' && oauthReady,
    staleTime: 15_000,
  })

  const files: OwnerSheetsOauthFile[] = filesQuery.data?.files ?? []
  const selectedFile = files.find((file) => file.spreadsheet_id === draft.spreadsheetId)
  const tabs = selectedFile?.tabs ?? []

  const startMutation = useMutation({
    mutationFn: async () => {
      await setOwnerConnectorMode(verticalId, connector.system, { mode: 'live' })
      return ownerSheetsOauthStart(verticalId, connector.system, {
        redirect_uri: ownerSheetsOauthRedirectUri(),
      })
    },
    onSuccess: (data) => {
      writeOwnerSheetsOauthSession({
        verticalId,
        system: connector.system,
        state: data.state,
        session_id: data.session_id,
      })
      window.location.assign(data.authorize_url)
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not start Google sign-in',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => startMutation.mutate(),
        },
      })
    },
  })

  const extractMutation = useMutation({
    mutationFn: async () => {
      if (!draft.spreadsheetId || !draft.tab) {
        throw new Error('Choose a spreadsheet and tab first.')
      }
      return ownerSheetsOauthExtract(verticalId, connector.system, {
        spreadsheet_id: draft.spreadsheetId,
        tab: draft.tab,
      })
    },
    onSuccess: (result) => {
      invalidate()
      toastHeadersResult(result, 'extract')
      if (!headersReady(result)) {
        onDraftChange({ ...draft, uploadOk: false })
        return
      }
      const headers = headersFromResult(result, draft.csvHeaders)
      onDraftChange({ ...draft, csvHeaders: headers, uploadOk: true })
      onHeadersReady(result, headers)
    },
    onError: (error) => {
      onDraftChange({ ...draft, uploadOk: false })
      actionToast.error({
        title: 'Extract failed',
        description: actionToast.safeErrorMessage(error, 'Check the sheet and try again.'),
        action: {
          label: 'Retry',
          onClick: () => extractMutation.mutate(),
        },
      })
    },
  })

  function selectMethod(method: SheetsConnectMethod) {
    onDraftChange({
      ...emptySheetsConnectDraft(),
      method,
      oauthRedeemed: method === 'oauth' ? oauthReady : false,
    })
  }

  return (
    <div className="space-y-3">
      <h4 className="text-sm font-medium text-ink">{systemLabel} · Connect</h4>
      <p className="text-xs text-mute">
        Sign in with Google to pick a sheet, or upload a CSV. You will map columns and choose
        formats next.
      </p>

      <div className="grid gap-2 sm:grid-cols-2">
        <button
          type="button"
          aria-pressed={draft.method === 'oauth'}
          onClick={() => selectMethod('oauth')}
          className={cn(
            'rounded-md border p-3 text-left transition-colors',
            draft.method === 'oauth'
              ? 'border-habeas-navy bg-canvas ring-1 ring-habeas-navy'
              : 'border-line hover:border-slate-300',
          )}
        >
          <p className="text-sm font-medium text-ink">Sign in with Google</p>
          <p className="mt-1 text-xs text-ink-soft">Choose one spreadsheet and a tab to use.</p>
        </button>
        <button
          type="button"
          aria-pressed={draft.method === 'upload'}
          onClick={() => selectMethod('upload')}
          className={cn(
            'rounded-md border p-3 text-left transition-colors',
            draft.method === 'upload'
              ? 'border-habeas-navy bg-canvas ring-1 ring-habeas-navy'
              : 'border-line hover:border-slate-300',
          )}
        >
          <p className="text-sm font-medium text-ink">{MANUAL_UPLOAD_LABEL}</p>
          <p className="mt-1 text-xs text-ink-soft">
            Use an existing export if you cannot grant sheet access.
          </p>
        </button>
      </div>

      {draft.method === 'oauth' ? (
        <div className="space-y-3">
          {!oauthReady ? (
            <div className="space-y-2">
              <p className="text-xs text-ink-soft">
                Sign in with Google and choose the spreadsheet and tab. Habeas can only read
                that sheet — its contents never appear in this app.
              </p>
              <Button
                type="button"
                size="sm"
                disabled={startMutation.isPending}
                onClick={() => startMutation.mutate()}
              >
                {startMutation.isPending ? 'Starting…' : 'Sign in with Google'}
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="ok">Google connected</Badge>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    writeOwnerSheetsOauthSession(null)
                    onDraftChange({ ...draft, oauthRedeemed: false, uploadOk: false })
                  }}
                >
                  Connect a different account
                </Button>
              </div>

              {filesQuery.isPending ? <SkeletonLines lines={3} /> : null}
              {filesQuery.isError ? (
                <p className="text-xs text-red-800">
                  Could not list spreadsheets.{' '}
                  <button
                    type="button"
                    className="font-medium text-habeas-navy underline-offset-2 hover:underline"
                    onClick={() => void filesQuery.refetch()}
                  >
                    Retry
                  </button>
                </p>
              ) : null}

              {filesQuery.isSuccess && files.length === 0 ? (
                <p className="rounded-md border border-dashed border-line bg-canvas px-3 py-3 text-xs text-mute">
                  No Drive spreadsheets found. Connect a different account or upload a CSV.
                </p>
              ) : null}

              {files.length > 0 ? (
                <fieldset className="space-y-2">
                  <legend className="text-xs font-medium text-ink">Spreadsheets</legend>
                  <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-line bg-white p-2">
                    {files.map((file) => {
                      const selected = draft.spreadsheetId === file.spreadsheet_id
                      return (
                        <label
                          key={file.spreadsheet_id}
                          className={cn(
                            'flex cursor-pointer items-start gap-2 rounded px-2 py-1.5 text-xs',
                            selected ? 'bg-habeas-navy/5 text-ink' : 'text-ink-soft hover:bg-canvas',
                          )}
                        >
                          <input
                            type="radio"
                            name={`sheets-file-${connector.system}`}
                            className="mt-0.5"
                            checked={selected}
                            onChange={() =>
                              onDraftChange({
                                ...draft,
                                spreadsheetId: file.spreadsheet_id,
                                tab: file.tabs?.[0]?.title ?? '',
                                uploadOk: false,
                              })
                            }
                          />
                          <span className="min-w-0">
                            <span className="block font-medium text-ink">{file.name}</span>
                            <span className="block text-[11px] text-mute">
                              {file.tabs?.length ? `${file.tabs.length} tab(s)` : 'Spreadsheet'}
                            </span>
                          </span>
                        </label>
                      )
                    })}
                  </div>
                </fieldset>
              ) : null}

              {draft.spreadsheetId ? (
                <label className="block space-y-1 text-xs">
                  <span className="font-medium text-ink">Tab</span>
                  {tabs.length > 0 ? (
                    <select
                      className={FIELD_CLASS}
                      value={draft.tab}
                      onChange={(event) =>
                        onDraftChange({ ...draft, tab: event.target.value, uploadOk: false })
                      }
                      aria-label="Sheet tab"
                    >
                      <option value="">Select a tab…</option>
                      {tabs.map((tab) => (
                        <option key={tabKey(tab)} value={tab.title}>
                          {tab.title}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      className={FIELD_CLASS}
                      value={draft.tab}
                      onChange={(event) =>
                        onDraftChange({ ...draft, tab: event.target.value, uploadOk: false })
                      }
                      aria-label="Sheet tab"
                      placeholder="Tab name"
                    />
                  )}
                </label>
              ) : null}
            </div>
          )}
        </div>
      ) : null}

      {draft.method === 'upload' ? (
        <SheetsCsvUploadPanel
          verticalId={verticalId}
          connector={connector}
          uploadOk={draft.uploadOk}
          onUploadOkChange={(ok) => onDraftChange({ ...draft, uploadOk: ok })}
          onBack={onBack}
          onContinue={onContinue}
          onFileSelected={onFileSelected}
          onHeadersReady={onHeadersReady}
          invalidate={invalidate}
        />
      ) : (
        <div className="flex flex-wrap justify-between gap-2">
          <Button type="button" size="sm" variant="ghost" onClick={onBack}>
            Back
          </Button>
          <div className="flex gap-2">
            {draft.method === 'oauth' && oauthReady ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!draft.spreadsheetId || !draft.tab || extractMutation.isPending}
                onClick={() => extractMutation.mutate()}
              >
                {extractMutation.isPending ? 'Reading…' : 'Read columns'}
              </Button>
            ) : null}
            <Button
              type="button"
              size="sm"
              disabled={!draft.uploadOk || (filesQuery.isSuccess && files.length === 0)}
              onClick={onContinue}
            >
              Continue
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
