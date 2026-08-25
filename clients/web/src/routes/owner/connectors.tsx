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
  connectRedeemSystemLabel,
  connectTestFailureMessage,
  connectTestSuccessDescription,
  getOwnerConnectorCredentialPreview,
  listOwnerConnectorReminders,
  listOwnerConnectors,
  saveOwnerConnectorCredentials,
  setOwnerConnectorCadence,
  setOwnerConnectorMode,
  testOwnerConnector,
  uploadOwnerConnectorCsv,
  type ConnectorReminder,
  type IntegrationSystemId,
  type OwnerConnectorList,
  type OwnerConnectorSystem,
  type OwnerCredentialPreview,
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
  allowsUpload,
  buildReminderBannerItems,
  buildVerticalWizardSteps,
  parseVerticalWizardStepId,
  cadenceDaysFromMetadata,
  cadenceOptionFromMetadata,
  delimiterValueFromKey,
  displayStatusChip,
  filterRemindersForOwnerConnectorsPage,
  isOwnerConnectorsHiddenSystem,
  isOwnerConnectorsHiddenVertical,
  liveConnectReady,
  modeStepSystemHint,
  refreshCadenceFromCadenceOption,
  suggestUploadColumnMapping,
  uploadMappingComplete,
  UPLOAD_IDENTIFIER_FIELDS,
  UPLOAD_SAMPLE_CSV,
  verticalWizardStepIndex,
  visibleReminderBanners,
  wizardProgressPercent,
  type CadenceOptionId,
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

function systemsNeedingCadence(connectors: readonly OwnerConnectorSystem[]) {
  return connectors.filter(
    (connector) =>
      allowsUpload(connector.allowed_approaches) ||
      connector.system === 'google_sheets' ||
      connector.system === 'alumni_google_sheet' ||
      connector.system === 'contact_us_google_sheet',
  )
}

function wizardableConnectors(connectors: readonly OwnerConnectorSystem[]) {
  return connectors.filter(
    (connector) =>
      !isOwnerConnectorsHiddenSystem(connector.system) &&
      (allowsUpload(connector.allowed_approaches) || allowsLive(connector.allowed_approaches)),
  )
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
        <h4 className="text-sm font-medium text-ink">{connector.display_name} · Upload how-to</h4>
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
        <h4 className="text-sm font-medium text-ink">{connector.display_name} · Live how-to</h4>
        {copy ? <p className="mt-1 text-xs leading-relaxed text-ink-soft">{copy}</p> : null}
      </div>

      {previewQuery.isPending ? <SkeletonLines lines={3} /> : null}

      {previewQuery.isError ? (
        <p className="text-xs text-red-800">
          Could not load Live credential instructions for {connector.display_name}.
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
  const systemLabel = connectRedeemSystemLabel({
    system: connector.system as IntegrationSystemId,
    display_name: connector.display_name,
  })

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
          description: connectTestSuccessDescription(data.detail, connector.display_name),
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
          description: connectTestSuccessDescription(data.detail, connector.display_name),
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
          Could not load credential fields for {connector.display_name}.
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

      <h4 className="text-sm font-medium text-ink">{connector.display_name} · Live credentials</h4>
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
          <span className="font-medium text-ink">{connector.display_name}</span>
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
            {connectTestSuccessDescription(latestTest?.detail, connector.display_name)}
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

  const mappingReady = uploadMappingComplete(columnMapping)

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV file first.')
      return uploadOwnerConnectorCsv(
        verticalId,
        connector.system,
        file,
        delimiterValueFromKey(delimiterKey),
        needsMapping ? columnMapping : null,
      )
    },
    onSuccess: (result) => {
      invalidate()
      if (result.ok) {
        setNeedsMapping(false)
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
        actionToast.info({
          title: 'Map your columns',
          description:
            'Match at least one identifier — email, phone, name, date of birth, or ZIP — to a column in the file.',
        })
        return
      }
      actionToast.error({
        title: 'Upload test failed',
        description: actionToast.safeErrorMessage(
          new Error(result.detail || 'upload failed'),
          'Check headers and delimiter, then try again.',
        ),
      })
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
      <h4 className="text-sm font-medium text-ink">{connector.display_name} · Upload CSV</h4>
      <p className="text-xs text-mute">
        Upload your export as-is. Email alone or phone alone is enough. After upload, map columns
        if the headers do not match.
      </p>
      <div className="flex flex-wrap gap-1.5">
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
        <span className="font-medium text-ink">CSV file</span>
        <input
          type="file"
          accept=".csv,text/csv"
          className="block w-full text-xs text-ink file:mr-2 file:rounded file:border file:border-line file:bg-white file:px-2 file:py-1"
          onChange={(event) => {
            setFile(event.target.files?.[0] ?? null)
            setNeedsMapping(false)
            setCsvHeaders([])
            setColumnMapping({})
            onUploadOkChange(false)
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
            onClick={() => uploadMutation.mutate()}
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
  connectors,
  cadenceOption,
  onCadenceChange,
  onBack,
  onContinue,
  saving,
}: {
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
          {cadenceSystems.map((connector) => connector.display_name).join(', ')}.
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
  connectors,
  cadenceOption,
  delimiterKeys,
  onBack,
  onComplete,
  completing,
}: {
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
            <span className="font-medium text-ink">{connector.display_name}</span>
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
          {liveSystems.map((connector) => connector.display_name).join(', ')}. Matching may gate
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
          displayLabel: connector.display_name,
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
              {item.system.replaceAll('_', ' ')} · {item.verticalId.replaceAll('_', '/')}
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
        {list.connectors.map((connector) => (
          <li
            key={connector.system}
            className="flex flex-wrap items-center justify-between gap-2 rounded border border-line bg-canvas px-3 py-2 text-sm"
          >
            <span className="font-medium text-ink">{connector.display_name}</span>
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

function ConnectorStatusRow({ connector }: { connector: OwnerConnectorSystem }) {
  const metaMode = activeModeFromMetadata(connector.metadata)

  return (
    <div className="rounded-md border border-line bg-white px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h4 className="text-sm font-medium text-ink">{connector.display_name}</h4>
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

  const connectors = list.connectors.filter(
    (connector) => !isOwnerConnectorsHiddenSystem(connector.system),
  )
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
          <ConnectorStatusRow key={connector.system} connector={connector} />
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
          <Micro>Data owner</Micro>
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
          <Micro>Data owner</Micro>
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
