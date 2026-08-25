import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import {
  completeOwnerConnectorWizard,
  connectTestFailureMessage,
  connectTestSuccessDescription,
  downloadOwnerUploadTemplate,
  getOwnerConnectorCredentialPreview,
  listOwnerConnectorReminders,
  listOwnerConnectors,
  listVerticalMembers,
  mintVerticalMemberInvite,
  ownerSheetsOauthExtract,
  ownerSheetsOauthFiles,
  ownerSheetsOauthRedeem,
  ownerSheetsOauthStart,
  saveOwnerConnectorCredentials,
  setOwnerConnectorCadence,
  setOwnerConnectorMode,
  testOwnerConnector,
  uploadOwnerConnectorCsv,
  type ConnectorReminder,
  type OwnerConnectorList,
  type OwnerConnectorSystem,
  type OwnerCredentialPreview,
  type OwnerRejectedUploadRow,
  type OwnerSheetsOauthFile,
  type OwnerUploadResult,
  type UserRole,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, useAuth } from '@/lib/auth'
import {
  CADENCE_OPTION_IDS,
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WEEKLY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
  MULTI_PII_DELIMITER_OPTIONS,
  SYSTEM_COPY,
  activeModeFromMetadata,
  allowsLive,
  allowsOauth,
  allowsUpload,
  buildReminderBannerItems,
  buildVerticalWizardSteps,
  parseVerticalWizardStepId,
  cadenceDaysFromMetadata,
  cadenceOptionFromMetadata,
  delimiterValueFromKey,
  displayStatusChip,
  filterOwnerWizardConnectors,
  filterRemindersForOwnerConnectorsPage,
  isOwnerConnectorsHiddenSystem,
  isOwnerConnectorsHiddenVertical,
  isSheetsOwnerSystem,
  ownerConnectorDisplayName,
  liveConnectReady,
  modeStepSystemHint,
  refreshCadenceFromCadenceOption,
  suggestUploadColumnMapping,
  uploadMappingComplete,
  UPLOAD_IDENTIFIER_FIELDS,
  UPLOAD_SAMPLE_CSV,
  EMAIL_FORMAT_OPTIONS,
  PHONE_FORMAT_OPTIONS,
  parseCsvDocument,
  serializeCsvDocument,
  rejectedRowCodeLabel,
  verticalWizardStepIndex,
  visibleReminderBanners,
  wizardProgressPercent,
  type CadenceOptionId,
  type CsvDocument,
  type SheetsConnectMethod,
} from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

const CADENCE_OPTION_COPY: Record<
  CadenceOptionId,
  { label: string; description: string }
> = {
  [CADENCE_OPTION_RARELY]: {
    label: 'This list rarely changes',
    description:
      'One good extract or upload is enough until you choose otherwise. Matching stays ready.',
  },
  [CADENCE_OPTION_WITH_NEW_BATCHES]: {
    label: 'Keep current with new request batches',
    description:
      'When Habeas promotes a new DROP intake batch, refresh this source if the last successful refresh was at least 12 hours ago. Same-day extra batches do not force another refresh. Login is never blocked; matching waits until refresh.',
  },
  [CADENCE_OPTION_WEEKLY]: {
    label: 'Weekly',
    description:
      'Matching needs a successful upload or refresh within the last 7 days.',
  },
}

function canAccessOwnerConnectors(role: UserRole) {
  return (
    role === 'data_owner' ||
    role === 'data_user' ||
    role === 'super_admin' ||
    role === 'admin'
  )
}

function canConfigureOwnerConnectors(role: UserRole | undefined) {
  return role === 'data_owner' || role === 'super_admin' || role === 'admin'
}

function canInviteVerticalMembers(role: UserRole | undefined) {
  return role === 'data_owner' || role === 'super_admin' || role === 'admin'
}

function connectorTitle(
  verticalId: string,
  connector: Pick<OwnerConnectorSystem, 'system' | 'display_name'>,
) {
  return ownerConnectorDisplayName(verticalId, connector.system, connector.display_name)
}

function systemsNeedingCadence(connectors: readonly OwnerConnectorSystem[]) {
  return connectors.filter(
    (connector) =>
      isSheetsOwnerSystem(connector.system) ||
      allowsUpload(connector.allowed_approaches) ||
      connector.system === 'google_sheets' ||
      connector.system === 'alumni_google_sheet' ||
      connector.system === 'contact_us_google_sheet',
  )
}

function wizardableConnectors(connectors: readonly OwnerConnectorSystem[]) {
  return filterOwnerWizardConnectors(connectors).filter(
    (connector) =>
      isSheetsOwnerSystem(connector.system) ||
      allowsUpload(connector.allowed_approaches) ||
      allowsLive(connector.allowed_approaches) ||
      allowsOauth(connector.allowed_approaches),
  )
}

function cadenceSystemsUseSheetsCards(connectors: readonly OwnerConnectorSystem[]) {
  return systemsNeedingCadence(connectors).some((connector) =>
    isSheetsOwnerSystem(connector.system),
  )
}

const OWNER_SHEETS_OAUTH_SESSION_KEY = 'habeas-cli.owner.sheets-oauth.session'
const OWNER_SHEETS_OAUTH_REDIRECT_PATH = '/owner/connectors'

type StoredOwnerSheetsOauthSession = {
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

function readOwnerSheetsOauthSession(): StoredOwnerSheetsOauthSession | null {
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

function writeOwnerSheetsOauthSession(session: StoredOwnerSheetsOauthSession | null) {
  if (session == null) {
    sessionStorage.removeItem(OWNER_SHEETS_OAUTH_SESSION_KEY)
    return
  }
  sessionStorage.setItem(OWNER_SHEETS_OAUTH_SESSION_KEY, JSON.stringify(session))
}

function readSheetsOauthReturnParams(search?: OwnerConnectorsSearch) {
  const fromSearch = {
    code: search?.code?.trim() || undefined,
    state: search?.state?.trim() || undefined,
    error: search?.error?.trim() || undefined,
  }
  if (fromSearch.code || fromSearch.state || fromSearch.error) return fromSearch
  if (typeof window === 'undefined') return fromSearch
  const params = new URLSearchParams(window.location.search)
  return {
    code: params.get('code')?.trim() || undefined,
    state: params.get('state')?.trim() || undefined,
    error: params.get('error')?.trim() || undefined,
  }
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

function initialCadenceOption(connectors: readonly OwnerConnectorSystem[]): CadenceOptionId | null {
  for (const connector of systemsNeedingCadence(connectors)) {
    const fromPolicy = cadenceOptionFromMetadata(connector.metadata)
    if (fromPolicy) return fromPolicy
    if (cadenceDaysFromMetadata(connector.metadata) === 7) return CADENCE_OPTION_WEEKLY
  }
  return null
}

function cadenceLabel(option: CadenceOptionId | null): string {
  if (!option) return '—'
  return CADENCE_OPTION_COPY[option].label
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

type CredentialField = OwnerCredentialPreview['fields'][number]

const OWNER_CREDENTIAL_ERROR_FALLBACK =
  'Could not save credentials. Check the fields and try again.'

function ownerCredentialErrorMessage(error: unknown, fallback = OWNER_CREDENTIAL_ERROR_FALLBACK): string {
  if (!(error instanceof Error)) return fallback
  const match = error.message.match(/Admin API \d+: (.+)/)
  if (match) {
    try {
      const parsed = JSON.parse(match[1]) as { detail?: unknown }
      if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
        const normalized = parsed.detail.trim().toLowerCase()
        if (
          normalized.startsWith('missing required credential field:') ||
          normalized.startsWith('unknown credential fields for') ||
          normalized.startsWith('credential field ')
        ) {
          return OWNER_CREDENTIAL_ERROR_FALLBACK
        }
        return parsed.detail
      }
    } catch {
      // fall through
    }
  }
  return fallback
}

function FieldHelp({ help }: { help: string }) {
  const lines = help
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const steps = lines.filter((line) => /^\d+\.\s/.test(line))
  const notes = lines.filter((line) => !/^\d+\.\s/.test(line))

  return (
    <div className="space-y-2 text-xs leading-relaxed text-ink-soft">
      {steps.length > 0 ? (
        <ol className="list-decimal space-y-1 pl-4 text-ink">
          {steps.map((step) => (
            <li key={step}>{step.replace(/^\d+\.\s*/, '')}</li>
          ))}
        </ol>
      ) : null}
      {notes.map((note) => (
        <p key={note}>{note}</p>
      ))}
    </div>
  )
}

function CredentialInput({
  field,
  value,
  onChange,
  disabled,
}: {
  field: CredentialField
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const inputType =
    field.input_type === 'password' ? 'password' : field.input_type === 'url' ? 'url' : 'text'

  return (
    <div className="space-y-2">
      <label htmlFor={`owner-cred-${field.id}`} className="block text-xs font-medium text-ink">
        {field.label}
        {field.required ? <span className="font-normal text-mute"> · required</span> : null}
      </label>
      {field.help ? <FieldHelp help={field.help} /> : null}
      <input
        id={`owner-cred-${field.id}`}
        name={field.id}
        type={inputType}
        autoComplete="off"
        required={field.required}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD_CLASS}
      />
    </div>
  )
}

function WizardProgressBar({
  currentIndex,
  totalSteps,
}: {
  currentIndex: number
  totalSteps: number
}) {
  const percent = wizardProgressPercent(currentIndex, totalSteps)
  const valueNow = totalSteps > 0 ? Math.min(currentIndex + 1, totalSteps) : 0

  return (
    <div className="mb-4">
      <div
        role="progressbar"
        aria-valuenow={valueNow}
        aria-valuemin={1}
        aria-valuemax={Math.max(totalSteps, 1)}
        aria-label="Connector setup progress"
        className="h-1.5 overflow-hidden rounded-full bg-line"
      >
        <div
          className="h-full rounded-full bg-habeas-navy transition-all duration-300"
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  )
}

function LiveTestOverlay({ systemLabel }: { systemLabel: string }) {
  const [phase, setPhase] = useState<'saving' | 'testing'>('saving')

  useEffect(() => {
    const timer = window.setTimeout(() => setPhase('testing'), 1200)
    return () => window.clearTimeout(timer)
  }, [])

  const title = phase === 'saving' ? 'Saving credentials…' : `Testing ${systemLabel}…`
  const detail =
    phase === 'saving'
      ? 'Writing your keys to Google’s secure vault.'
      : `Checking that Habeas can authenticate with ${systemLabel}.`

  return (
    <div
      className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-md bg-white/95 px-4 text-center backdrop-blur-[2px]"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={title}
    >
      <div className="w-full max-w-sm rounded-md border border-line bg-white p-4 shadow-sm">
        <div className="mx-auto mb-3 flex size-9 items-center justify-center rounded-full bg-habeas-navy/10">
          <Spinner className="size-4" />
        </div>
        <p className="text-sm font-medium text-ink">{title}</p>
        <p className="mt-1 text-xs text-ink-soft">{detail}</p>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-line">
          <div
            className={`h-full rounded-full bg-habeas-navy transition-all duration-700 ${
              phase === 'saving' ? 'w-1/2' : 'w-full'
            }`}
          />
        </div>
      </div>
    </div>
  )
}

function UploadHowToPanel({
  verticalId,
  connector,
  onContinue,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onContinue: () => void
}) {
  const copy =
    SYSTEM_COPY[connector.system]?.uploadHowto ??
    modeStepSystemHint(connector.system, 'upload')

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">
          {connectorTitle(verticalId, connector)} · Upload how-to
        </h4>
        {copy ? <p className="mt-1 text-xs leading-relaxed text-ink-soft">{copy}</p> : null}
      </div>

      <div className="rounded-md border border-line bg-white px-3 py-2.5 text-xs text-ink-soft">
        <p className="font-medium text-ink">What to upload</p>
        <p className="mt-1">
          Use your existing export. After you upload, map your columns to Habeas fields. You do
          not need to reshape the file to a template first.
        </p>
        <p className="mt-2 font-medium text-ink">Need at least one identifier</p>
        <p className="mt-1 text-ink-soft">
          Email alone is enough. Phone alone is enough. Name, date of birth, or ZIP also count.
          Map extra columns after upload if the headers do not match.
        </p>
      </div>

      <div className="flex justify-end">
        <Button type="button" size="sm" onClick={onContinue}>
          Continue
        </Button>
      </div>
    </div>
  )
}

function SheetsHowToPanel({
  verticalId,
  connector,
  onContinue,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onContinue: () => void
}) {
  const copy =
    SYSTEM_COPY[connector.system]?.howto ??
    SYSTEM_COPY[connector.system]?.oauthHowto ??
    SYSTEM_COPY[connector.system]?.uploadHowto

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">
          {connectorTitle(verticalId, connector)} · Connect Google or upload
        </h4>
        {copy ? <p className="mt-1 text-xs leading-relaxed text-ink-soft">{copy}</p> : null}
      </div>
      <div className="rounded-md border border-line bg-white px-3 py-2.5 text-xs text-ink-soft">
        <p className="font-medium text-ink">Connect Google</p>
        <p className="mt-1">
          Sign in with your Habeas Google account. After Google returns, pick one or more
          spreadsheets and a tab, then extract. No service-account share.
        </p>
        <p className="mt-2 font-medium text-ink">Or upload a CSV</p>
        <p className="mt-1">
          Same mapping and rejected-row clean-up as any other upload. Email or phone alone is
          enough.
        </p>
      </div>
      <div className="flex justify-end">
        <Button type="button" size="sm" onClick={onContinue}>
          Continue
        </Button>
      </div>
    </div>
  )
}

type SheetsConnectDraft = {
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

function emptySheetsConnectDraft(): SheetsConnectDraft {
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
  sourceFile?: File | null,
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

void applyConnectResultToDraft
void sourceFilePlaceholder

function LiveHowToPanel({
  verticalId,
  connector,
  onContinue,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onContinue: () => void
}) {
  const copy =
    SYSTEM_COPY[connector.system]?.liveHowto ?? modeStepSystemHint(connector.system, 'live')

  const previewQuery = useQuery({
    queryKey: [
      'admin-api',
      'owner',
      'credential-preview',
      verticalId,
      connector.system,
      'howto',
    ],
    queryFn: () => getOwnerConnectorCredentialPreview(verticalId, connector.system),
    staleTime: 60_000,
  })

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">
          {connectorTitle(verticalId, connector)} · Live how-to
        </h4>
        {copy ? <p className="mt-1 text-xs leading-relaxed text-ink-soft">{copy}</p> : null}
      </div>

      {previewQuery.isPending ? <SkeletonLines lines={3} /> : null}

      {previewQuery.isError ? (
        <p className="text-xs text-red-800">
          Could not load Live credential instructions for {connectorTitle(verticalId, connector)}.
        </p>
      ) : null}

      {previewQuery.data?.trust_copy ? (
        <p className="rounded border border-line bg-white px-3 py-2 text-xs leading-relaxed text-ink-soft">
          {previewQuery.data.trust_copy}
        </p>
      ) : null}

      {previewQuery.data?.fields.length ? (
        <div className="space-y-3 rounded-md border border-line bg-white px-3 py-2.5">
          {previewQuery.data.fields.map((field) => (
            <div key={field.id} className="space-y-1">
              <p className="text-xs font-medium text-ink">{field.label}</p>
              {field.help ? <FieldHelp help={field.help} /> : null}
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex justify-end">
        <Button type="button" size="sm" onClick={onContinue}>
          Continue
        </Button>
      </div>
    </div>
  )
}

function LiveConnectPanel({
  verticalId,
  connector,
  onBack,
  onContinue,
  onUseUpload,
  invalidate,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onBack: () => void
  onContinue: () => void
  onUseUpload?: () => void
  invalidate: () => void
}) {
  const previewQuery = useQuery({
    queryKey: [
      'admin-api',
      'owner',
      'credential-preview',
      verticalId,
      connector.system,
    ],
    queryFn: () => getOwnerConnectorCredentialPreview(verticalId, connector.system),
    staleTime: 60_000,
  })

  const preview = previewQuery.data
  const systemLabel = connectorTitle(verticalId, connector)

  const [credentials, setCredentials] = useState<Record<string, string>>({})
  const [clientError, setClientError] = useState<string | null>(null)
  const [confirmTestOpen, setConfirmTestOpen] = useState(false)
  const [liveTestOk, setLiveTestOk] = useState(connector.last_test_ok === true)
  const [fieldsDirty, setFieldsDirty] = useState(false)
  const [credentialsSaved, setCredentialsSaved] = useState(liveConnectReady(connector))

  useEffect(() => {
    if (connector.last_test_ok === true) setLiveTestOk(true)
  }, [connector.last_test_ok])

  useEffect(() => {
    if (liveConnectReady(connector)) setCredentialsSaved(true)
  }, [connector.last_test_ok, connector.status, connector.metadata])

  useEffect(() => {
    if (!preview?.fields.length) return
    setCredentials((current) => {
      const next = { ...current }
      for (const field of preview.fields) {
        if (next[field.id] === undefined) next[field.id] = ''
      }
      return next
    })
  }, [preview])

  const credentialsMutation = useMutation({
    mutationFn: (payload: Record<string, string>) =>
      saveOwnerConnectorCredentials(verticalId, connector.system, payload),
    onMutate: () => setClientError(null),
    onSuccess: (data) => {
      setConfirmTestOpen(false)
      setCredentialsSaved(true)
      setFieldsDirty(false)
      invalidate()
      if (data.ok) {
        setLiveTestOk(true)
        actionToast.success({
          title: 'Connection confirmed',
          description: connectTestSuccessDescription(data.detail, systemLabel),
        })
        return
      }
      actionToast.error({
        title: 'Connection test failed',
        description: connectTestFailureMessage(data.detail),
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
      })
    },
    onError: (error) => {
      setConfirmTestOpen(false)
      actionToast.error({
        title: 'Could not connect',
        description: ownerCredentialErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
      })
    },
  })

  const retestMutation = useMutation({
    mutationFn: () => testOwnerConnector(verticalId, connector.system),
    onMutate: () => setClientError(null),
    onSuccess: (data) => {
      setConfirmTestOpen(false)
      invalidate()
      if (data.ok) {
        setLiveTestOk(true)
        actionToast.success({
          title: 'Connection confirmed',
          description: connectTestSuccessDescription(data.detail, systemLabel),
        })
        return
      }
      actionToast.error({
        title: 'Connection test failed',
        description: connectTestFailureMessage(data.detail),
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
      })
    },
    onError: (error) => {
      setConfirmTestOpen(false)
      actionToast.error({
        title: 'Could not connect',
        description: ownerCredentialErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
      })
    },
  })

  const testing = credentialsMutation.isPending || retestMutation.isPending
  const useStoredRetest = credentialsSaved && !fieldsDirty
  const latestTest = retestMutation.isSuccess ? retestMutation.data : credentialsMutation.data
  const testFailed = Boolean(latestTest && !latestTest.ok)
  const testPassed = liveTestOk || latestTest?.ok === true
  const testFailureMessage = testFailed ? connectTestFailureMessage(latestTest?.detail) : null
  const submitError =
    clientError ??
    (credentialsMutation.isError
      ? ownerCredentialErrorMessage(credentialsMutation.error)
      : retestMutation.isError
        ? ownerCredentialErrorMessage(retestMutation.error)
        : null)

  const filledSummary = (preview?.fields ?? [])
    .filter((field) => credentials[field.id]?.trim())
    .map((field) => field.label)

  function updateField(fieldId: string, value: string) {
    setCredentials((current) => ({ ...current, [fieldId]: value }))
    setFieldsDirty(true)
    if (liveTestOk) setLiveTestOk(false)
    credentialsMutation.reset()
    retestMutation.reset()
  }

  function validateCredentials(): boolean {
    if (!preview) return false
    for (const field of preview.fields) {
      if (field.required && !credentials[field.id]?.trim()) {
        setClientError(`Enter ${field.label.toLowerCase()}.`)
        return false
      }
    }
    setClientError(null)
    return true
  }

  function runCredentialTest() {
    if (useStoredRetest) {
      setClientError(null)
      retestMutation.mutate()
      return
    }
    if (!validateCredentials()) return
    credentialsMutation.mutate(credentials)
  }

  if (previewQuery.isPending) {
    return (
      <div className="space-y-3">
        <SkeletonLines lines={4} />
      </div>
    )
  }

  if (previewQuery.isError) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-red-800">
          Could not load credential fields for {systemLabel}.
        </p>
        <div className="flex gap-2">
          <Button type="button" size="sm" variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => void previewQuery.refetch()}
          >
            Retry
          </Button>
        </div>
      </div>
    )
  }

  if (!preview) return null

  const canSubmitFields = preview.fields.length > 0
  const canStartTest = !testing && (useStoredRetest || canSubmitFields)

  return (
    <div className="relative space-y-3">
      {testing ? <LiveTestOverlay systemLabel={systemLabel} /> : null}

      <h4 className="text-sm font-medium text-ink">{systemLabel} · Live credentials</h4>
      <p className="text-xs text-mute">
        Paste Live credentials below, then test the connection before continuing.
      </p>

      {preview.fields.length === 0 ? (
        <p className="text-xs text-mute">
          No Live credentials are collected for this system in the wizard. Contact Habeas if you
          expected a form.
        </p>
      ) : (
        <div className="space-y-4">
          {preview.fields.map((field) => (
            <CredentialInput
              key={field.id}
              field={field}
              value={credentials[field.id] ?? ''}
              onChange={(value) => updateField(field.id, value)}
              disabled={testing}
            />
          ))}
        </div>
      )}

      <div className="space-y-2 rounded-md border border-line bg-white px-3 py-2.5 text-sm">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium text-ink">{systemLabel}</span>
          <Badge
            variant={testing ? 'run' : testPassed ? 'ok' : testFailed ? 'fail' : 'wait'}
          >
            {testing ? 'Testing…' : testPassed ? 'Passed' : testFailed ? 'Failed' : 'Ready to test'}
          </Badge>
        </div>
        <p className="text-xs text-mute">
          Fields provided: {filledSummary.length > 0 ? filledSummary.join(', ') : 'none yet'}
        </p>
      </div>

      {testPassed && !testing ? (
        <div
          className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs text-emerald-900"
          role="status"
        >
          <p className="font-medium">Connection confirmed</p>
          <p className="mt-0.5">
            {connectTestSuccessDescription(latestTest?.detail, systemLabel)}
          </p>
        </div>
      ) : null}

      {testFailed ? (
        <div
          className="space-y-1 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-900"
          role="alert"
        >
          <p className="font-medium">Connection test failed</p>
          <p>{testFailureMessage}</p>
          <p className="text-red-800/80">Fix the values above and test again.</p>
        </div>
      ) : null}

      {submitError && !testPassed ? (
        <p className="text-xs text-red-700" role="alert">
          {submitError}
        </p>
      ) : null}

      {!testPassed ? (
        <p className="text-xs text-mute">
          Continue stays disabled until the connection test passes.
        </p>
      ) : null}

      <div className="flex flex-wrap justify-between gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onBack}>
          Back
        </Button>
        <div className="flex gap-2">
          {!testPassed ? (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={!canStartTest}
              onClick={() => setConfirmTestOpen(true)}
            >
              {useStoredRetest
                ? testFailed
                  ? 'Retest stored credentials'
                  : 'Test stored credentials'
                : testFailed
                  ? 'Test again'
                  : 'Test connection'}
            </Button>
          ) : null}
          <Button type="button" size="sm" disabled={!testPassed} onClick={onContinue}>
            Continue
          </Button>
        </div>
      </div>
      {onUseUpload ? (
        <p className="text-xs text-mute">
          Live test failed or the vendor is unavailable?{' '}
          <button
            type="button"
            className="font-medium text-habeas-navy underline-offset-2 hover:underline"
            onClick={onUseUpload}
          >
            Set up a CSV upload instead
          </button>
        </p>
      ) : null}

      <ConfirmActionDialog
        open={confirmTestOpen}
        onOpenChange={(open) => {
          if (testing) return
          setConfirmTestOpen(open)
        }}
        title={`Test ${systemLabel} connection?`}
        description={
          useStoredRetest
            ? 'We’ll verify the credentials already stored in Google’s secure vault. Values are never shown back in this app.'
            : 'We’ll save your keys in Google’s secure vault, then verify Habeas can authenticate. Values are never shown back in this app.'
        }
        confirmLabel="Yes, test now"
        cancelLabel="Cancel"
        confirming={testing}
        confirmingTitle="Testing connection…"
        confirmingDescription={
          useStoredRetest
            ? 'Verifying stored credentials with the provider. Keep this tab open.'
            : 'Saving keys securely, then verifying with the provider. Keep this tab open.'
        }
        onConfirm={runCredentialTest}
      />
    </div>
  )
}

function downloadUploadSample(kind: keyof typeof UPLOAD_SAMPLE_CSV) {
  const sample = UPLOAD_SAMPLE_CSV[kind]
  const blob = new Blob([sample.body], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = sample.filename
  anchor.click()
  URL.revokeObjectURL(url)
}

function UploadConnectPanel({
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
        Upload your export as-is. Email alone or phone alone is enough. After upload, map columns
        if the headers do not match. Rows that fail the selected email or phone format stay in this
        step so you can clean them and resubmit.
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
        {(Object.keys(UPLOAD_SAMPLE_CSV) as Array<keyof typeof UPLOAD_SAMPLE_CSV>).map((kind) => (
          <Button
            key={kind}
            type="button"
            size="sm"
            variant="outline"
            onClick={() => {
              downloadUploadSample(kind)
              actionToast.success({
                title: 'Sample downloaded',
                description: `${UPLOAD_SAMPLE_CSV[kind].filename} is ready to upload.`,
              })
            }}
          >
            {UPLOAD_SAMPLE_CSV[kind].label}
          </Button>
        ))}
      </div>

      <label className="block space-y-1 text-xs">
        <span className="font-medium text-ink">Multi-PII delimiter</span>
        <select
          className={FIELD_CLASS}
          value={delimiterKey}
          onChange={(event) => onDelimiterChange(event.target.value)}
          aria-label="Multi-PII delimiter"
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

function CadenceStepPanel({
  verticalId,
  connectors,
  cadenceOption,
  onCadenceChange,
  onBack,
  onContinue,
  saving,
}: {
  verticalId: string
  connectors: readonly OwnerConnectorSystem[]
  cadenceOption: CadenceOptionId | null
  onCadenceChange: (option: CadenceOptionId) => void
  onBack: () => void
  onContinue: () => void
  saving: boolean
}) {
  const cadenceSystems = systemsNeedingCadence(connectors)

  if (!cadenceSystems.length) {
    return (
      <div className="space-y-3">
        <p className="text-xs text-mute">
          This vertical only has Live systems. Refresh cadence applies to file, upload, and sheet
          sources — continue to confirm.
        </p>
        <div className="flex justify-between gap-2">
          <Button type="button" size="sm" variant="ghost" onClick={onBack}>
            Back
          </Button>
          <Button type="button" size="sm" onClick={onContinue}>
            Continue
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">Refresh cadence</h4>
        <p className="mt-1 text-xs text-mute">
          Applies to upload and sheet sources in this vertical:{' '}
          {cadenceSystems.map((connector) => connectorTitle(verticalId, connector)).join(', ')}.
        </p>
      </div>

      <div className="space-y-2">
        {CADENCE_OPTION_IDS.map((optionId) => {
          const copy = CADENCE_OPTION_COPY[optionId]
          const selected = cadenceOption === optionId
          return (
            <button
              key={optionId}
              type="button"
              aria-pressed={selected}
              onClick={() => onCadenceChange(optionId)}
              className={cn(
                'w-full rounded-md border p-3 text-left transition-colors',
                selected
                  ? 'border-habeas-navy bg-canvas ring-1 ring-habeas-navy'
                  : 'border-line hover:border-slate-300',
              )}
            >
              <p className="text-sm font-medium text-ink">{copy.label}</p>
              <p className="mt-1 text-xs leading-relaxed text-mute">{copy.description}</p>
            </button>
          )
        })}
      </div>

      <div className="flex flex-wrap justify-between gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button type="button" size="sm" disabled={saving} onClick={onContinue}>
          {saving ? 'Saving…' : 'Continue'}
        </Button>
      </div>
    </div>
  )
}

function ConfirmStepPanel({
  verticalId,
  connectors,
  cadenceOption,
  delimiterKeys,
  onBack,
  onComplete,
  completing,
}: {
  verticalId: string
  connectors: readonly OwnerConnectorSystem[]
  cadenceOption: CadenceOptionId | null
  delimiterKeys: Record<string, string>
  onBack: () => void
  onComplete: () => void
  completing: boolean
}) {
  const cadenceSystems = systemsNeedingCadence(connectors)
  const liveSystems = connectors.filter((connector) => allowsLive(connector.allowed_approaches))

  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">Confirm setup</h4>
        <p className="mt-1 text-xs text-mute">
          Review this vertical before completing the wizard.
        </p>
      </div>

      <ul className="space-y-2 text-xs">
        {connectors.map((connector) => (
          <li
            key={connector.system}
            className="rounded-md border border-line bg-white px-3 py-2 text-ink-soft"
          >
            <span className="font-medium text-ink">{connectorTitle(verticalId, connector)}</span>
            {allowsUpload(connector.allowed_approaches) ? (
              <span>
                {' '}
                · Upload delimiter:{' '}
                <span className="font-medium text-ink">
                  {delimiterValueFromKey(delimiterKeys[connector.system] ?? 'none') ?? 'None'}
                </span>
              </span>
            ) : null}
          </li>
        ))}
      </ul>

      {cadenceSystems.length ? (
        <p className="text-xs text-mute">
          Refresh cadence:{' '}
          <span className="font-medium text-ink">{cadenceLabel(cadenceOption)}</span>
        </p>
      ) : null}

      {liveSystems.length ? (
        <p className="rounded-md border border-line bg-white px-3 py-2 text-xs text-ink-soft">
          Live credentials must be rotated at least every <strong>180 days</strong> for:{' '}
          {liveSystems.map((connector) => connectorTitle(verticalId, connector)).join(', ')}. Matching may gate
          when rotation is overdue.
        </p>
      ) : null}

      <div className="flex flex-wrap justify-between gap-2">
        <Button type="button" size="sm" variant="ghost" onClick={onBack}>
          Back
        </Button>
        <Button type="button" size="sm" disabled={completing} onClick={onComplete}>
          {completing ? 'Completing…' : 'Complete wizard'}
        </Button>
      </div>
    </div>
  )
}

function VerticalWizard({
  verticalId,
  list,
  onDone,
}: {
  verticalId: string
  list: OwnerConnectorList
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const connectors = wizardableConnectors(list.connectors)
  const connectorBySystem = useMemo(
    () => Object.fromEntries(list.connectors.map((connector) => [connector.system, connector])),
    [list.connectors],
  )

  const steps = useMemo(
    () =>
      buildVerticalWizardSteps({
        systems: list.connectors.map((connector) => ({
          system: connector.system,
          allowedApproaches: connector.allowed_approaches,
          displayLabel: connectorTitle(verticalId, connector),
        })),
        viewOnly: list.view_only,
      }),
    [list.connectors, list.view_only],
  )

  const [currentStepId, setCurrentStepId] = useState(() => steps[0]?.id ?? '')
  const [delimiterKeys, setDelimiterKeys] = useState<Record<string, string>>(() =>
    Object.fromEntries(connectors.map((connector) => [connector.system, 'none'])),
  )
  const [uploadOkBySystem, setUploadOkBySystem] = useState<Record<string, boolean>>({})
  const [cadenceOption, setCadenceOption] = useState<CadenceOptionId | null>(() =>
    initialCadenceOption(connectors),
  )

  const stepIndex = verticalWizardStepIndex(steps, currentStepId)
  const parsedStep = parseVerticalWizardStepId(currentStepId)

  useEffect(() => {
    if (!steps.length) return
    if (verticalWizardStepIndex(steps, currentStepId) < 0) {
      setCurrentStepId(steps[0].id)
    }
  }, [steps, currentStepId])

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    })
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connector-reminders'],
    })
  }

  const modeMutation = useMutation({
    mutationFn: ({
      system,
      mode,
    }: {
      system: string
      mode: 'live' | 'upload'
    }) => setOwnerConnectorMode(verticalId, system, { mode }),
  })

  const cadenceMutation = useMutation({
    mutationFn: async (option: CadenceOptionId) => {
      const refreshCadence = refreshCadenceFromCadenceOption(option)
      if (!refreshCadence) {
        throw new Error('Invalid cadence option')
      }
      const body = { refresh_cadence: refreshCadence }
      const targets = systemsNeedingCadence(connectors)
      for (const connector of targets) {
        await setOwnerConnectorCadence(verticalId, connector.system, body)
      }
    },
    onSuccess: (_data, option) => {
      invalidate()
      actionToast.success({
        title: 'Cadence saved',
        description: CADENCE_OPTION_COPY[option].label,
      })
      setCurrentStepId((currentId) => {
        const idx = verticalWizardStepIndex(steps, currentId)
        if (idx >= 0 && idx < steps.length - 1) return steps[idx + 1].id
        return currentId
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not save cadence',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => {
            if (cadenceOption) cadenceMutation.mutate(cadenceOption)
          },
        },
      })
    },
  })

  const completeMutation = useMutation({
    mutationFn: async () => {
      const refreshCadence = refreshCadenceFromCadenceOption(cadenceOption)
      const body = refreshCadence ? { refresh_cadence: refreshCadence } : undefined
      for (const connector of connectors) {
        await completeOwnerConnectorWizard(verticalId, connector.system, body)
      }
    },
    onSuccess: () => {
      invalidate()
      actionToast.success({
        title: 'Wizard complete',
        description: `${list.display_label} setup finished.`,
      })
      onDone()
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not complete wizard',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => completeMutation.mutate(),
        },
      })
    },
  })

  function goBack() {
    if (stepIndex > 0) setCurrentStepId(steps[stepIndex - 1].id)
  }

  function goNext() {
    if (stepIndex >= 0 && stepIndex < steps.length - 1) {
      setCurrentStepId(steps[stepIndex + 1].id)
    }
  }

  async function ensureMode(system: string, mode: 'live' | 'upload') {
    const connector = connectorBySystem[system]
    if (!connector) return
    const current = activeModeFromMetadata(connector.metadata)
    if (current === mode) return
    await modeMutation.mutateAsync({ system, mode })
    invalidate()
  }

  async function handleContinueFromHowTo(system: string, mode: 'live' | 'upload') {
    try {
      await ensureMode(system, mode)
      goNext()
    } catch (error) {
      actionToast.error({
        title: 'Could not save mode',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
      })
    }
  }

  function handleCadenceContinue() {
    const targets = systemsNeedingCadence(connectors)
    if (!targets.length) {
      goNext()
      return
    }
    if (!cadenceOption) {
      actionToast.warning({
        title: 'Choose a refresh cadence',
        description: 'Pick how often upload or sheet data should stay current.',
      })
      return
    }
    cadenceMutation.mutate(cadenceOption)
  }

  if (!steps.length) {
    return (
      <p className="mt-3 text-xs text-mute">No owner wizard steps are configured for this vertical.</p>
    )
  }

  if (stepIndex < 0 || !parsedStep) {
    return (
      <div className="mt-3 rounded-md border border-line bg-canvas p-3 sm:p-4">
        <WizardProgressBar currentIndex={0} totalSteps={steps.length} />
        <p className="text-xs text-mute">Could not load this wizard step.</p>
        <Button type="button" size="sm" className="mt-2" onClick={() => setCurrentStepId(steps[0].id)}>
          Restart wizard
        </Button>
      </div>
    )
  }

  const connector =
    'system' in parsedStep ? connectorBySystem[parsedStep.system] : undefined

  return (
    <div className="mt-3 rounded-md border border-line bg-canvas p-3 sm:p-4">
      <WizardProgressBar currentIndex={stepIndex} totalSteps={steps.length} />

      {parsedStep.kind === 'howto-upload' && connector ? (
        <UploadHowToPanel
          verticalId={verticalId}
          connector={connector}
          onContinue={() => void handleContinueFromHowTo(parsedStep.system, 'upload')}
        />
      ) : null}

      {parsedStep.kind === 'howto-live' && connector ? (
        <LiveHowToPanel
          verticalId={verticalId}
          connector={connector}
          onContinue={() => void handleContinueFromHowTo(parsedStep.system, 'live')}
        />
      ) : null}

      {parsedStep.kind === 'upload' && connector ? (
        <UploadConnectPanel
          verticalId={verticalId}
          connector={connector}
          delimiterKey={delimiterKeys[connector.system] ?? 'none'}
          onDelimiterChange={(key) =>
            setDelimiterKeys((current) => ({ ...current, [connector.system]: key }))
          }
          uploadOk={uploadOkBySystem[connector.system] === true}
          onUploadOkChange={(ok) =>
            setUploadOkBySystem((current) => ({ ...current, [connector.system]: ok }))
          }
          onBack={goBack}
          onContinue={goNext}
          invalidate={invalidate}
        />
      ) : null}

      {parsedStep.kind === 'live-creds' && connector ? (
        <LiveConnectPanel
          verticalId={verticalId}
          connector={connector}
          invalidate={invalidate}
          onBack={goBack}
          onContinue={goNext}
          onUseUpload={
            allowsUpload(connector.allowed_approaches)
              ? () => setCurrentStepId(`${connector.system}-howto-upload`)
              : undefined
          }
        />
      ) : null}

      {parsedStep.kind === 'cadence' ? (
        <CadenceStepPanel
          verticalId={verticalId}
          connectors={connectors}
          cadenceOption={cadenceOption}
          onCadenceChange={setCadenceOption}
          onBack={goBack}
          onContinue={handleCadenceContinue}
          saving={cadenceMutation.isPending}
        />
      ) : null}

      {parsedStep.kind === 'confirm' ? (
        <ConfirmStepPanel
          verticalId={verticalId}
          connectors={connectors}
          cadenceOption={cadenceOption}
          delimiterKeys={delimiterKeys}
          onBack={goBack}
          onComplete={() => completeMutation.mutate()}
          completing={completeMutation.isPending}
        />
      ) : null}
    </div>
  )
}

function DisplayStatusBadge({
  displayStatus,
  gateAllowed,
}: {
  displayStatus: string
  gateAllowed: boolean
}) {
  const chip = displayStatusChip(displayStatus, { gateAllowed })
  return <Badge variant={chip.variant}>{chip.label}</Badge>
}

function ReminderBanners({
  reminders,
  dismissedIds,
  onDismiss,
}: {
  reminders: ConnectorReminder[]
  dismissedIds: ReadonlySet<string>
  onDismiss: (id: string) => void
}) {
  const items = visibleReminderBanners(buildReminderBannerItems(reminders), dismissedIds)
  if (!items.length) return null

  return (
    <div className="space-y-2" role="region" aria-label="Connector reminders">
      {items.map((item) => (
        <div
          key={item.id}
          className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2.5 text-sm ${
            item.severity === 'overdue'
              ? 'border-red-200 bg-red-50 text-red-900'
              : 'border-amber-200 bg-amber-50 text-amber-950'
          }`}
        >
          <div className="min-w-0 space-y-0.5">
            <p className="font-medium">{item.title}</p>
            <p className="text-xs opacity-90">{item.description}</p>
            <p className="text-[11px] opacity-70">
              {ownerConnectorDisplayName(item.verticalId, item.system)} ·{' '}
              {item.verticalId.replaceAll('_', '/')}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="shrink-0"
            onClick={() => onDismiss(item.id)}
          >
            Dismiss
          </Button>
        </div>
      ))}
    </div>
  )
}

function ViewOnlyCard({ list }: { list: OwnerConnectorList }) {
  return (
    <div className="rounded-md border border-line bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-ink">{list.display_label}</h3>
          <p className="mt-0.5 text-xs text-mute">
            Already connected — view only. No owner upload or credential wizard.
          </p>
        </div>
        <Badge variant="default">View only</Badge>
      </div>
      <ul className="mt-3 space-y-2">
        {filterOwnerWizardConnectors(list.connectors).map((connector) => (
          <li
            key={connector.system}
            className="flex flex-wrap items-center justify-between gap-2 rounded border border-line bg-canvas px-3 py-2 text-sm"
          >
            <span className="font-medium text-ink">
              {connectorTitle(list.vertical_id, connector)}
            </span>
            <DisplayStatusBadge
              displayStatus={connector.display_status}
              gateAllowed={connector.gate_allowed}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function ConnectorStatusRow({
  verticalId,
  connector,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
}) {
  const metaMode = activeModeFromMetadata(connector.metadata)

  return (
    <div className="rounded-md border border-line bg-white px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h4 className="text-sm font-medium text-ink">{connectorTitle(verticalId, connector)}</h4>
          <p className="text-[11px] text-mute">
            {connector.system.replaceAll('_', ' ')}
            {metaMode ? ` · ${metaMode}` : ''}
            {connector.connection_id
              ? ` · ${connector.connection_id.slice(0, 8)}…`
              : ' · not linked'}
          </p>
        </div>
        <DisplayStatusBadge
          displayStatus={connector.display_status}
          gateAllowed={connector.gate_allowed}
        />
      </div>
    </div>
  )
}

function VerticalConnectorsSection({
  verticalId,
  selected,
  onSelect,
}: {
  verticalId: string
  selected: boolean
  onSelect: () => void
}) {
  const { role } = useAuth()
  const listQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    queryFn: () => listOwnerConnectors(verticalId),
    staleTime: 15_000,
  })

  const list = listQuery.data
  const needsSetup = useMemo(
    () =>
      list?.connectors.some(
        (connector) =>
          !isOwnerConnectorsHiddenSystem(connector.system) &&
          (connector.display_status === 'needs_setup' ||
            connector.display_status === 'action_required'),
      ) ?? false,
    [list],
  )
  const [wizardOpen, setWizardOpen] = useState(false)

  useEffect(() => {
    if (needsSetup) setWizardOpen(true)
  }, [needsSetup])

  if (listQuery.isPending) {
    return (
      <div className="rounded-md border border-line bg-white p-4">
        <SkeletonLines lines={3} />
      </div>
    )
  }

  if (listQuery.isError) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">
        <p className="font-medium">Could not load connectors for {verticalId}</p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-2"
          onClick={() => void listQuery.refetch()}
        >
          Retry
        </Button>
      </div>
    )
  }

  if (!list) return null

  const connectors = filterOwnerWizardConnectors(list.connectors)
  if (connectors.length === 0) return null

  if (list.view_only) {
    return <ViewOnlyCard list={{ ...list, connectors }} />
  }

  const canWizard =
    canConfigureOwnerConnectors(role) && wizardableConnectors(connectors).length > 0

  return (
    <section
      className={`space-y-3 rounded-md border p-3 sm:p-4 ${
        selected ? 'border-habeas-navy/40 bg-habeas-navy/[0.03]' : 'border-line bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="text-left" onClick={onSelect}>
          <h3 className="text-sm font-medium text-ink">{list.display_label}</h3>
          <p className="text-[11px] text-mute">{connectors.length} system(s)</p>
        </button>
        {canWizard ? (
          <Button
            type="button"
            size="sm"
            variant={wizardOpen ? 'outline' : 'default'}
            onClick={() => setWizardOpen((open) => !open)}
          >
            {wizardOpen ? 'Hide wizard' : 'Open setup wizard'}
          </Button>
        ) : null}
      </div>

      <div className="space-y-2">
        {connectors.map((connector) => (
          <ConnectorStatusRow
            key={connector.system}
            verticalId={verticalId}
            connector={connector}
          />
        ))}
      </div>

      {wizardOpen && canWizard ? (
        <VerticalWizard
          verticalId={verticalId}
          list={{ ...list, connectors }}
          onDone={() => setWizardOpen(false)}
        />
      ) : null}
    </section>
  )
}

function TeamMembersSection({
  verticalId,
  canInvite,
}: {
  verticalId: string
  canInvite: boolean
}) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const membersQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'vertical-members', verticalId],
    queryFn: () => listVerticalMembers(verticalId),
    enabled: canInvite,
  })
  const inviteMutation = useMutation({
    mutationFn: (inviteEmail: string) => mintVerticalMemberInvite(verticalId, inviteEmail),
    onSuccess: (invite) => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'owner', 'vertical-members', verticalId],
      })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
      setEmail('')
      void navigator.clipboard.writeText(invite.invite_url).catch(() => undefined)
      actionToast.success({
        title: 'Invite created',
        description: 'Link copied. Share it with your teammate.',
        action: {
          label: 'Copy again',
          onClick: () => {
            void navigator.clipboard.writeText(invite.invite_url)
          },
        },
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not create invite',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => inviteMutation.mutate(email.trim()),
        },
      })
    },
  })
  if (!canInvite) return null
  const members = membersQuery.data ?? []
  return (
    <section
      id="team"
      className="space-y-3 rounded-md border border-line bg-white px-4 py-3"
    >
      <header>
        <h3 className="text-sm font-medium text-ink">Team members</h3>
        <p className="mt-1 text-xs text-ink-soft">
          Invite data users to this vertical. They can review matches, fulfill, and
          refresh systems — not connector credentials or catalog settings.
        </p>
      </header>
      {members.length > 0 ? (
        <ul className="space-y-1 text-xs text-ink-soft">
          {members.map((member) => (
            <li key={`${member.email}:${member.assignment_role}`}>
              <span className="text-ink">{member.email}</span>
              {' · '}
              {member.assignment_role === 'data_user' ? 'Data user' : 'Data owner'}
              {member.active ? '' : ' · inactive'}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-mute">No additional team members yet.</p>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          const next = email.trim()
          if (!next) return
          inviteMutation.mutate(next)
        }}
      >
        <label className="min-w-[12rem] flex-1 text-[0.65rem] text-mute">
          Teammate email
          <input
            className={FIELD_CLASS}
            type="email"
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <Button type="submit" size="sm" disabled={inviteMutation.isPending}>
          {inviteMutation.isPending ? 'Sending…' : 'Send invite'}
        </Button>
      </form>
    </section>
  )
}

function OwnerConnectorsBody({ verticalFilter }: { verticalFilter?: string }) {
  const { me, role } = useAuth()
  const navigate = useNavigate()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set())

  const verticals = me?.verticals ?? []
  const visibleVerticals = useMemo(() => {
    const assigned = verticals.filter((id) => !isOwnerConnectorsHiddenVertical(id))
    if (!verticalFilter) return assigned
    return assigned.filter((id) => id === verticalFilter)
  }, [verticals, verticalFilter])

  const remindersFromMe = me?.connector_reminders
  const remindersQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connector-reminders'],
    queryFn: async () => {
      try {
        const payload = await listOwnerConnectorReminders()
        return payload.reminders
      } catch {
        return remindersFromMe ?? []
      }
    },
    staleTime: 30_000,
    enabled: role === 'data_owner' || role === 'data_user' || role === 'super_admin' || role === 'admin',
  })

  const reminders: ConnectorReminder[] = filterRemindersForOwnerConnectorsPage(
    remindersQuery.data ?? remindersFromMe ?? [],
  )

  if (!verticals.length) {
    return (
      <section className="space-y-6">
        <header>
          <Micro>{role === 'data_user' ? 'Data user' : 'Data owner'}</Micro>
          <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink">
            Connectors
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            No verticals are assigned to your account yet. Ask a Habeas admin to assign you to a
            vertical catalog entry.
          </p>
        </header>
        <div className="rounded-md border border-dashed border-line bg-canvas px-4 py-8 text-center text-sm text-mute">
          Empty — no assigned verticals.
        </div>
        <Button asChild size="sm" variant="outline">
          <Link to="/" search={{ tab: 'pipeline' }}>
            Back to Home
          </Link>
        </Button>
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Micro>{role === 'data_user' ? 'Data user' : 'Data owner'}</Micro>
          <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink">
            Connectors
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Complete one setup wizard per vertical. Systems are sequential sections inside that
            wizard. Soft reminders never block login.
          </p>
        </div>
        {verticalFilter ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              void navigate({
                to: '/owner/connectors',
                search: {},
              })
            }
          >
            Show all verticals
          </Button>
        ) : null}
      </header>

      <ReminderBanners
        reminders={reminders}
        dismissedIds={dismissedIds}
        onDismiss={(id) =>
          setDismissedIds((prev) => {
            const next = new Set(prev)
            next.add(id)
            return next
          })
        }
      />

      {verticalFilter && !verticals.includes(verticalFilter) ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          Vertical <code className="text-ink">{verticalFilter}</code> is not assigned to you.
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {verticals
          .filter((id) => !isOwnerConnectorsHiddenVertical(id))
          .map((id) => (
          <Button
            key={id}
            type="button"
            size="sm"
            variant={verticalFilter === id ? 'default' : 'outline'}
            onClick={() =>
              void navigate({
                to: '/owner/connectors',
                search: { vertical: id },
              })
            }
          >
            {id.replaceAll('_', '/')}
          </Button>
        ))}
      </div>

      <div className="space-y-4">
        {visibleVerticals.map((verticalId) => (
          <VerticalConnectorsSection
            key={verticalId}
            verticalId={verticalId}
            selected={verticalFilter === verticalId}
            onSelect={() =>
              void navigate({
                to: '/owner/connectors',
                search: { vertical: verticalId },
              })
            }
          />
        ))}
      </div>

      {canInviteVerticalMembers(role)
        ? (verticalFilter ? [verticalFilter] : visibleVerticals)
            .filter((id) => !isOwnerConnectorsHiddenVertical(id))
            .map((verticalId) => (
              <TeamMembersSection
                key={`team-${verticalId}`}
                verticalId={verticalId}
                canInvite
              />
            ))
        : null}
    </section>
  )
}

export type OwnerConnectorsSearch = {
  vertical?: string
}

export function OwnerConnectorsPage({ search }: { search?: OwnerConnectorsSearch }) {
  return (
    <RoleGate allow={canAccessOwnerConnectors}>
      <OwnerConnectorsBody verticalFilter={search?.vertical} />
    </RoleGate>
  )
}
