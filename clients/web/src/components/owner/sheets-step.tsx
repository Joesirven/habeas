/**
 * Sheets connect step for the owner wizard — SheetsConnectPanel moved wholesale
 * from connectors.tsx (Google sign-in OAuth flow, spreadsheet/tab pick, upload
 * fallback, mapping + rejected-row clean-up). Also home to the Sheets OAuth
 * session helpers, exported so the settings page can detect an OAuth return
 * and reopen the wizard at the sheets system.
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
  type OwnerRejectedUploadRow,
  type OwnerSheetsOauthFile,
  type OwnerUploadResult,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  EMAIL_FORMAT_OPTIONS,
  MANUAL_UPLOAD_LABEL,
  MULTI_PII_DELIMITER_OPTIONS,
  PHONE_FORMAT_OPTIONS,
  UPLOAD_IDENTIFIER_FIELDS,
  delimiterValueFromKey,
  ownerConnectorDisplayName,
  parseCsvDocument,
  rejectedRowCodeLabel,
  serializeCsvDocument,
  suggestUploadColumnMapping,
  systemWizardCopy,
  uploadMappingComplete,
  type CsvDocument,
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

function csvTextFromUploadResult(result: OwnerUploadResult): string | null {
  const extra = result as OwnerUploadResult & {
    csv?: unknown
    extracted_csv?: unknown
  }
  if (typeof extra.csv === 'string' && extra.csv.trim()) return extra.csv
  if (typeof extra.extracted_csv === 'string' && extra.extracted_csv.trim()) {
    return extra.extracted_csv
  }
  return null
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
  columnMapping: Record<string, string>
  needsMapping: boolean
  workingDoc: CsvDocument | null
  rejectedRows: OwnerRejectedUploadRow[]
  emailFormat: string
  phoneFormat: string
  uploadOk: boolean
}

export function emptySheetsConnectDraft(): SheetsConnectDraft {
  return {
    method: null,
    oauthRedeemed: false,
    spreadsheetId: '',
    tab: '',
    csvHeaders: [],
    columnMapping: {},
    needsMapping: false,
    workingDoc: null,
    rejectedRows: [],
    emailFormat: 'standard',
    phoneFormat: 'us_10',
    uploadOk: false,
  }
}

function MappingAndRejectedBlock({
  csvHeaders,
  columnMapping,
  onColumnMappingChange,
  needsMapping,
  workingDoc,
  rejectedRows,
  onWorkingDocChange,
  onResubmitCleaned,
  resubmitting,
  fileName,
}: {
  csvHeaders: string[]
  columnMapping: Record<string, string>
  onColumnMappingChange: (next: Record<string, string>) => void
  needsMapping: boolean
  workingDoc: CsvDocument | null
  rejectedRows: OwnerRejectedUploadRow[]
  onWorkingDocChange: (next: CsvDocument) => void
  onResubmitCleaned: (file: File) => void
  resubmitting: boolean
  fileName: string
}) {
  const mappingReady = uploadMappingComplete(columnMapping)

  return (
    <>
      {needsMapping && csvHeaders.length > 0 ? (
        <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2">
          <p className="text-xs font-medium text-ink">Column mapping</p>
          {UPLOAD_IDENTIFIER_FIELDS.map((field) => (
            <label key={field.id} className="block space-y-1 text-xs">
              <span className="text-ink">{field.label}</span>
              <select
                className={FIELD_CLASS}
                value={columnMapping[field.id] ?? ''}
                onChange={(event) =>
                  onColumnMappingChange({ ...columnMapping, [field.id]: event.target.value })
                }
                aria-label={`Map ${field.label} column`}
              >
                <option value="">Select a column…</option>
                {csvHeaders.map((header) => (
                  <option key={`${field.id}:${header}`} value={header}>
                    {header}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {!mappingReady ? (
            <p className="text-[11px] text-mute">
              Map at least one identifier (email, phone, name, date of birth, or ZIP). Extra
              columns are ignored.
            </p>
          ) : null}
        </div>
      ) : null}

      {rejectedRows.length > 0 ? (
        <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2">
          <p className="text-xs font-medium text-ink">Clean rejected rows</p>
          <p className="text-[11px] text-mute">
            {rejectedRows.length} row(s) failed validation.
            {workingDoc
              ? ' Edit the cells, then resubmit. The rest of the file is kept as-is.'
              : ' Fix the flagged rows in the sheet, then extract again.'}
          </p>
          {workingDoc ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr>
                      <th className="border-b border-line px-2 py-1 text-left font-medium text-mute">
                        Row
                      </th>
                      <th className="border-b border-line px-2 py-1 text-left font-medium text-mute">
                        Reason
                      </th>
                      {workingDoc.headers.map((header) => (
                        <th
                          key={header}
                          className="border-b border-line px-2 py-1 text-left font-medium text-mute"
                        >
                          {header}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rejectedRows.map((rejected) => {
                      const rowIndex = rejected.row - 1
                      const cells = workingDoc.rows[rowIndex] ?? []
                      return (
                        <tr key={rejected.row}>
                          <td className="px-2 py-1 align-top text-ink">{rejected.row}</td>
                          <td className="px-2 py-1 align-top">
                            <div className="flex flex-wrap gap-1">
                              {rejected.codes.map((code) => (
                                <Badge key={`${rejected.row}:${code}`} variant="fail">
                                  {rejectedRowCodeLabel(code)}
                                </Badge>
                              ))}
                            </div>
                          </td>
                          {workingDoc.headers.map((header, colIndex) => (
                            <td key={`${rejected.row}:${header}`} className="px-1 py-1">
                              <input
                                className={FIELD_CLASS}
                                value={cells[colIndex] ?? ''}
                                aria-label={`Row ${rejected.row} ${header}`}
                                onChange={(event) => {
                                  const value = event.target.value
                                  const rows = workingDoc.rows.map((row, index) =>
                                    index === rowIndex
                                      ? row.map((cell, cellIndex) =>
                                          cellIndex === colIndex ? value : cell,
                                        )
                                      : row,
                                  )
                                  onWorkingDocChange({ ...workingDoc, rows })
                                }}
                              />
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={resubmitting}
                onClick={() => {
                  const next = new File([serializeCsvDocument(workingDoc)], fileName, {
                    type: 'text/csv',
                  })
                  onResubmitCleaned(next)
                }}
              >
                Resubmit cleaned rows
              </Button>
            </>
          ) : (
            <ul className="space-y-1 text-xs">
              {rejectedRows.map((rejected) => (
                <li key={rejected.row} className="flex flex-wrap items-center gap-1">
                  <span className="text-ink">Row {rejected.row}</span>
                  {rejected.codes.map((code) => (
                    <Badge key={`${rejected.row}:${code}`} variant="fail">
                      {rejectedRowCodeLabel(code)}
                    </Badge>
                  ))}
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </>
  )
}

function applyConnectResultToDraft(
  current: SheetsConnectDraft,
  result: OwnerUploadResult,
): SheetsConnectDraft {
  if (result.ok) {
    return {
      ...current,
      needsMapping: false,
      workingDoc: null,
      rejectedRows: [],
      uploadOk: true,
    }
  }
  if (result.detail === 'upload_needs_mapping') {
    const headers = result.detected_headers?.filter((header) => header.trim()) ?? current.csvHeaders
    return {
      ...current,
      csvHeaders: headers,
      columnMapping: suggestUploadColumnMapping(headers),
      needsMapping: true,
      rejectedRows: [],
      workingDoc: null,
      uploadOk: false,
    }
  }
  if (result.detail === 'upload_rows_rejected') {
    const csvText = csvTextFromUploadResult(result)
    return {
      ...current,
      rejectedRows: result.rejected_rows ?? [],
      workingDoc: csvText ? parseCsvDocument(csvText) : current.workingDoc,
      uploadOk: false,
    }
  }
  return { ...current, uploadOk: false }
}

function toastConnectResult(result: OwnerUploadResult) {
  if (result.ok) {
    actionToast.success({
      title: 'Extract validated',
      description:
        result.upload_row_count != null
          ? `${result.upload_row_count} usable row(s). Continue when ready.`
          : 'Rows accepted. Continue when ready.',
    })
    return
  }
  if (result.detail === 'upload_needs_mapping') {
    actionToast.info({
      title: 'Map your columns',
      description:
        'Match at least one identifier — email, phone, name, date of birth, or ZIP — to a column.',
    })
    return
  }
  if (result.detail === 'upload_rows_rejected') {
    actionToast.warning({
      title: 'Rows need cleaning',
      description: connectTestFailureMessage(result.detail),
    })
    return
  }
  actionToast.error({
    title: 'Extract failed',
    description: connectTestFailureMessage(result.detail),
  })
}

/**
 * CSV upload branch of the sheets connect panel (moved from connectors.tsx —
 * the old UploadConnectPanel, now local to the sheets flow).
 */
function SheetsCsvUploadPanel({
  verticalId,
  connector,
  delimiterKey,
  onDelimiterChange,
  uploadOk,
  onUploadOkChange,
  onBack,
  onContinue,
  invalidate,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  delimiterKey: string
  onDelimiterChange: (key: string) => void
  uploadOk: boolean
  onUploadOkChange: (ok: boolean) => void
  onBack: () => void
  onContinue: () => void
  invalidate: () => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [csvHeaders, setCsvHeaders] = useState<string[]>([])
  const [columnMapping, setColumnMapping] = useState<Record<string, string>>({})
  const [needsMapping, setNeedsMapping] = useState(false)
  const [emailFormat, setEmailFormat] = useState<string>('standard')
  const [phoneFormat, setPhoneFormat] = useState<string>('us_10')
  const [workingDoc, setWorkingDoc] = useState<ReturnType<typeof parseCsvDocument> | null>(null)
  const [rejectedRows, setRejectedRows] = useState<OwnerRejectedUploadRow[]>([])

  const mappingReady = uploadMappingComplete(columnMapping)

  const resetFileLocalState = () => {
    setNeedsMapping(false)
    setCsvHeaders([])
    setColumnMapping({})
    setWorkingDoc(null)
    setRejectedRows([])
    onUploadOkChange(false)
  }

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
    mutationFn: async (overrideFile?: File) => {
      const toUpload = overrideFile ?? file
      if (!toUpload) throw new Error('Choose a CSV file first.')
      return uploadOwnerConnectorCsv(
        verticalId,
        connector.system,
        toUpload,
        delimiterValueFromKey(delimiterKey),
        needsMapping ? columnMapping : null,
        { emailFormat, phoneFormat },
      )
    },
    onSuccess: async (result, overrideFile) => {
      invalidate()
      if (result.ok) {
        setNeedsMapping(false)
        setWorkingDoc(null)
        setRejectedRows([])
        onUploadOkChange(true)
        actionToast.success({
          title: 'Upload validated',
          description:
            result.upload_row_count != null
              ? `${result.upload_row_count} usable row(s). Continue when ready.`
              : 'File accepted. Continue when ready.',
        })
        return
      }
      onUploadOkChange(false)
      if (result.detail === 'upload_needs_mapping') {
        const headers =
          result.detected_headers?.filter((h) => h.trim()) ?? csvHeaders
        setCsvHeaders(headers)
        setColumnMapping(suggestUploadColumnMapping(headers))
        setNeedsMapping(true)
        setRejectedRows([])
        setWorkingDoc(null)
        actionToast.info({
          title: 'Map your columns',
          description:
            'Match at least one identifier — email, phone, name, date of birth, or ZIP — to a column in the file.',
        })
        return
      }
      if (result.detail === 'upload_rows_rejected') {
        const source = overrideFile ?? file
        if (source) {
          const text = await source.text()
          setWorkingDoc(parseCsvDocument(text))
        }
        setRejectedRows(result.rejected_rows ?? [])
        actionToast.warning({
          title: 'Rows need cleaning',
          description: connectTestFailureMessage(result.detail),
        })
        return
      }
      actionToast.error({
        title: 'Upload test failed',
        description: connectTestFailureMessage(result.detail),
      })
    },
    onError: (error) => {
      onUploadOkChange(false)
      actionToast.error({
        title: 'Upload failed',
        description: actionToast.safeErrorMessage(error, 'Check the file and try again.'),
        action: {
          label: 'Retry',
          onClick: () => uploadMutation.mutate(undefined),
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
          'Upload your export as-is. Email alone or phone alone is enough. After upload, map columns if the headers do not match. Rows that fail the selected email or phone format stay in this step so you can clean them and resubmit.'}
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
        <span className="font-medium text-ink">Separator when a cell has more than one value</span>
        <select
          className={FIELD_CLASS}
          value={delimiterKey}
          onChange={(event) => onDelimiterChange(event.target.value)}
          aria-label="Separator when a cell has more than one value"
        >
          {MULTI_PII_DELIMITER_OPTIONS.map((opt) => (
            <option key={opt.key} value={opt.key}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-1 text-xs">
        <span className="font-medium text-ink">Email format</span>
        <select
          className={FIELD_CLASS}
          value={emailFormat}
          onChange={(event) => {
            setEmailFormat(event.target.value)
            onUploadOkChange(false)
          }}
          aria-label="Email format"
        >
          {EMAIL_FORMAT_OPTIONS.map((opt) => (
            <option key={opt.id} value={opt.id}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-1 text-xs">
        <span className="font-medium text-ink">Phone format</span>
        <select
          className={FIELD_CLASS}
          value={phoneFormat}
          onChange={(event) => {
            setPhoneFormat(event.target.value)
            onUploadOkChange(false)
          }}
          aria-label="Phone format"
        >
          {PHONE_FORMAT_OPTIONS.map((opt) => (
            <option key={opt.id} value={opt.id}>
              {opt.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-1 text-xs">
        <span className="font-medium text-ink">CSV file</span>
        <input
          type="file"
          accept=".csv,text/csv"
          className="block w-full text-xs text-ink file:mr-2 file:rounded file:border file:border-line file:bg-white file:px-2 file:py-1"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null)
            resetFileLocalState()
          }}
        />
      </label>

      {needsMapping && csvHeaders.length > 0 ? (
        <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2">
          <p className="text-xs font-medium text-ink">Column mapping</p>
          {UPLOAD_IDENTIFIER_FIELDS.map((field) => (
            <label key={field.id} className="block space-y-1 text-xs">
              <span className="text-ink">{field.label}</span>
              <select
                className={FIELD_CLASS}
                value={columnMapping[field.id] ?? ''}
                onChange={(event) => {
                  const value = event.target.value
                  setColumnMapping((prev) => ({ ...prev, [field.id]: value }))
                  onUploadOkChange(false)
                }}
                aria-label={`Map ${field.label} column`}
              >
                <option value="">Select a column…</option>
                {csvHeaders.map((header) => (
                  <option key={`${field.id}:${header}`} value={header}>
                    {header}
                  </option>
                ))}
              </select>
            </label>
          ))}
          {!mappingReady ? (
            <p className="text-[11px] text-mute">
              Map at least one identifier (email, phone, name, date of birth, or ZIP). Extra
              columns are ignored.
            </p>
          ) : null}
        </div>
      ) : null}

      {workingDoc && rejectedRows.length > 0 ? (
        <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2">
          <p className="text-xs font-medium text-ink">Clean rejected rows</p>
          <p className="text-[11px] text-mute">
            {rejectedRows.length} row(s) failed validation. Edit the cells, then resubmit. The
            rest of the file is kept as-is.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-xs">
              <thead>
                <tr>
                  <th className="border-b border-line px-2 py-1 text-left font-medium text-mute">
                    Row
                  </th>
                  <th className="border-b border-line px-2 py-1 text-left font-medium text-mute">
                    Reason
                  </th>
                  {workingDoc.headers.map((header) => (
                    <th
                      key={header}
                      className="border-b border-line px-2 py-1 text-left font-medium text-mute"
                    >
                      {header}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rejectedRows.map((rejected) => {
                  const rowIndex = rejected.row - 1
                  const cells = workingDoc.rows[rowIndex] ?? []
                  return (
                    <tr key={rejected.row}>
                      <td className="px-2 py-1 align-top text-ink">{rejected.row}</td>
                      <td className="px-2 py-1 align-top">
                        <div className="flex flex-wrap gap-1">
                          {rejected.codes.map((code) => (
                            <Badge key={`${rejected.row}:${code}`} variant="fail">
                              {rejectedRowCodeLabel(code)}
                            </Badge>
                          ))}
                        </div>
                      </td>
                      {workingDoc.headers.map((header, colIndex) => (
                        <td key={`${rejected.row}:${header}`} className="px-1 py-1">
                          <input
                            className={FIELD_CLASS}
                            value={cells[colIndex] ?? ''}
                            aria-label={`Row ${rejected.row} ${header}`}
                            onChange={(event) => {
                              const value = event.target.value
                              setWorkingDoc((prev) => {
                                if (!prev) return prev
                                const rows = prev.rows.map((row, index) =>
                                  index === rowIndex
                                    ? row.map((cell, cellIndex) =>
                                        cellIndex === colIndex ? value : cell,
                                      )
                                    : row,
                                )
                                return { ...prev, rows }
                              })
                            }}
                          />
                        </td>
                      ))}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={uploadMutation.isPending}
            onClick={() => {
              if (!workingDoc) return
              const next = new File(
                [serializeCsvDocument(workingDoc)],
                file?.name ?? 'cleaned.csv',
                { type: 'text/csv' },
              )
              setFile(next)
              uploadMutation.mutate(next)
            }}
          >
            Resubmit cleaned rows
          </Button>
        </div>
      ) : null}

      <div className="flex flex-wrap justify-between gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onBack}>
          Back
        </Button>
        <div className="flex gap-2">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={
              !file ||
              uploadMutation.isPending ||
              (needsMapping && !mappingReady)
            }
            onClick={() => uploadMutation.mutate(undefined)}
          >
            {uploadMutation.isPending
              ? 'Uploading…'
              : needsMapping
                ? 'Apply mapping & test'
                : 'Upload & test'}
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
 * upload a CSV. Owns its own OAuth redirect; the host dialog just renders it.
 * Props unchanged from the original connectors.tsx panel.
 */
export function SheetsConnectPanel({
  verticalId,
  connector,
  delimiterKey,
  onDelimiterChange,
  draft,
  onDraftChange,
  onBack,
  onContinue,
  invalidate,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  delimiterKey: string
  onDelimiterChange: (key: string) => void
  draft: SheetsConnectDraft
  onDraftChange: (next: SheetsConnectDraft) => void
  onBack: () => void
  onContinue: () => void
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
  const mappingReady = uploadMappingComplete(draft.columnMapping)

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
        multi_pii_delimiter: delimiterValueFromKey(delimiterKey),
        column_mapping: draft.needsMapping ? draft.columnMapping : null,
        email_format: draft.emailFormat,
        phone_format: draft.phoneFormat,
      })
    },
    onSuccess: (result) => {
      invalidate()
      onDraftChange(applyConnectResultToDraft(draft, result))
      toastConnectResult(result)
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

  const cleanedUploadMutation = useMutation({
    mutationFn: (file: File) =>
      uploadOwnerConnectorCsv(
        verticalId,
        connector.system,
        file,
        delimiterValueFromKey(delimiterKey),
        draft.needsMapping ? draft.columnMapping : null,
        { emailFormat: draft.emailFormat, phoneFormat: draft.phoneFormat },
      ),
    onSuccess: (result) => {
      invalidate()
      onDraftChange(applyConnectResultToDraft(draft, result))
      toastConnectResult(result)
    },
    onError: (error) => {
      actionToast.error({
        title: 'Upload failed',
        description: actionToast.safeErrorMessage(error, 'Check the file and try again.'),
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
        Sign in with Google to pick a sheet, or upload a CSV. Mapping and rejected-row clean-up are
        the same either way.
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
                              {file.tabs?.length
                                ? `${file.tabs.length} tab(s)`
                                : 'Spreadsheet'}
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

              <label className="block space-y-1 text-xs">
                <span className="font-medium text-ink">Separator when a cell has more than one value</span>
                <select
                  className={FIELD_CLASS}
                  value={delimiterKey}
                  onChange={(event) => onDelimiterChange(event.target.value)}
                  aria-label="Separator when a cell has more than one value"
                >
                  {MULTI_PII_DELIMITER_OPTIONS.map((opt) => (
                    <option key={opt.key} value={opt.key}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block space-y-1 text-xs">
                <span className="font-medium text-ink">Email format</span>
                <select
                  className={FIELD_CLASS}
                  value={draft.emailFormat}
                  onChange={(event) =>
                    onDraftChange({ ...draft, emailFormat: event.target.value, uploadOk: false })
                  }
                  aria-label="Email format"
                >
                  {EMAIL_FORMAT_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              <label className="block space-y-1 text-xs">
                <span className="font-medium text-ink">Phone format</span>
                <select
                  className={FIELD_CLASS}
                  value={draft.phoneFormat}
                  onChange={(event) =>
                    onDraftChange({ ...draft, phoneFormat: event.target.value, uploadOk: false })
                  }
                  aria-label="Phone format"
                >
                  {PHONE_FORMAT_OPTIONS.map((opt) => (
                    <option key={opt.id} value={opt.id}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>

              <MappingAndRejectedBlock
                csvHeaders={draft.csvHeaders}
                columnMapping={draft.columnMapping}
                onColumnMappingChange={(next) =>
                  onDraftChange({ ...draft, columnMapping: next, uploadOk: false })
                }
                needsMapping={draft.needsMapping}
                workingDoc={draft.workingDoc}
                rejectedRows={draft.rejectedRows}
                onWorkingDocChange={(next) => onDraftChange({ ...draft, workingDoc: next })}
                onResubmitCleaned={(file) => cleanedUploadMutation.mutate(file)}
                resubmitting={cleanedUploadMutation.isPending || extractMutation.isPending}
                fileName={`${connector.system}-cleaned.csv`}
              />
            </div>
          )}
        </div>
      ) : null}

      {draft.method === 'upload' ? (
        <SheetsCsvUploadPanel
          verticalId={verticalId}
          connector={connector}
          delimiterKey={delimiterKey}
          onDelimiterChange={onDelimiterChange}
          uploadOk={draft.uploadOk}
          onUploadOkChange={(ok) => onDraftChange({ ...draft, uploadOk: ok })}
          onBack={onBack}
          onContinue={onContinue}
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
                disabled={
                  !draft.spreadsheetId ||
                  !draft.tab ||
                  extractMutation.isPending ||
                  (draft.needsMapping && !mappingReady)
                }
                onClick={() => extractMutation.mutate()}
              >
                {extractMutation.isPending
                  ? 'Extracting…'
                  : draft.needsMapping
                    ? 'Apply mapping & extract'
                    : 'Extract & test'}
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
