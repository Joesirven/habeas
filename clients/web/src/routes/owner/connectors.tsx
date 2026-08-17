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
  downloadOwnerUploadTemplate,
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
  MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE,
  MULTI_PII_DELIMITER_OPTIONS,
  OWNER_WIZARD_STEPS,
  activeModeFromMetadata,
  allowsLive,
  allowsUpload,
  buildModeStepCards,
  buildReminderBannerItems,
  cadenceDaysFromMetadata,
  delimiterValueFromKey,
  displayStatusChip,
  filterRemindersForOwnerConnectorsPage,
  liveConnectReady,
  modeStepIntroCopy,
  ownerWizardStepIndex,
  visibleReminderBanners,
  type ModeStepCardState,
  type OwnerWizardStep,
} from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

function canAccessOwnerConnectors(role: UserRole) {
  return role === 'data_owner' || role === 'super_admin' || role === 'admin'
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

function LiveConnectPanel({
  verticalId,
  connector,
  onBack,
  onContinue,
  invalidate,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onBack: () => void
  onContinue: () => void
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
  const [credentialsSaved, setCredentialsSaved] = useState(
    liveConnectReady(connector),
  )

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
  const latestTest = retestMutation.isSuccess
    ? retestMutation.data
    : credentialsMutation.data
  const testFailed = Boolean(latestTest && !latestTest.ok)
  const testPassed = liveTestOk || latestTest?.ok === true
  const testFailureMessage = testFailed
    ? connectTestFailureMessage(latestTest?.detail)
    : null
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

      <p className="text-xs text-mute">
        Paste Live credentials for {connector.display_name}. Follow the how-to steps below each
        field, then test the connection before continuing.
      </p>

      {preview.trust_copy ? (
        <p className="rounded border border-line bg-white px-3 py-2 text-xs leading-relaxed text-ink-soft">
          {preview.trust_copy}
        </p>
      ) : null}

      <p className="rounded border border-line bg-white px-3 py-2 text-xs text-ink-soft">
        Connecting credentials is separate from enabling matching. Matching stays gated until
        freshness and rotation rules pass.
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

      {testing ? (
        <div
          className="flex items-start gap-3 rounded-md border border-sky-200 bg-sky-50 px-3 py-2.5"
          role="status"
          aria-live="polite"
        >
          <Spinner className="mt-0.5 size-4 text-sky-700" />
          <div className="min-w-0 text-xs">
            <p className="font-medium text-sky-950">Testing your connection</p>
            <p className="mt-0.5 text-sky-900/80">
              {useStoredRetest
                ? `Verifying stored credentials with ${systemLabel}. This usually takes a few seconds.`
                : `Saving keys, then verifying with ${systemLabel}. This usually takes a few seconds.`}
            </p>
          </div>
        </div>
      ) : null}

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
        <p className="text-xs text-red-700" role="alert">{submitError}</p>
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

function ModeExplainerCards({
  cards,
  selected,
  onSelect,
}: {
  cards: ModeStepCardState[]
  selected: 'live' | 'upload' | null
  onSelect: (mode: 'live' | 'upload') => void
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {cards.map((card) => {
        const isSelected = selected === card.mode
        return (
          <button
            key={card.mode}
            type="button"
            disabled={!card.allowed}
            aria-pressed={isSelected}
            onClick={() => {
              if (card.allowed) onSelect(card.mode)
            }}
            className={cn(
              'rounded-md border px-3 py-3 text-left transition',
              card.allowed
                ? isSelected
                  ? 'border-habeas-navy bg-habeas-navy/5 ring-2 ring-habeas-navy/20'
                  : 'border-line bg-white hover:border-habeas-mid'
                : 'cursor-not-allowed border-line bg-canvas opacity-60',
            )}
          >
            <p className="text-sm font-medium text-ink">{card.title}</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-soft">{card.definition}</p>
            {card.allowed && card.hint ? (
              <p className="mt-2 text-xs text-mute">{card.hint}</p>
            ) : null}
            {!card.allowed && card.disabledReason ? (
              <p className="mt-2 text-xs text-mute">{card.disabledReason}</p>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

function WizardProgress({ step }: { step: OwnerWizardStep }) {
  const activeIndex = ownerWizardStepIndex(step)
  return (
    <ol className="mb-4 flex gap-2" aria-label="Connector setup steps">
      {OWNER_WIZARD_STEPS.map((entry, index) => {
        const active = index === activeIndex
        const done = index < activeIndex
        return (
          <li
            key={entry.id}
            className={`flex-1 rounded-md border px-2 py-1.5 text-center text-[11px] font-medium ${
              active
                ? 'border-habeas-navy bg-habeas-navy text-white'
                : done
                  ? 'border-habeas-navy/30 bg-habeas-navy/5 text-habeas-navy'
                  : 'border-line bg-canvas text-mute'
            }`}
          >
            {index + 1}. {entry.label}
          </li>
        )
      })}
    </ol>
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
  const items = visibleReminderBanners(
    buildReminderBannerItems(reminders),
    dismissedIds,
  )
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

function ConnectorWizard({
  verticalId,
  connector,
  onDone,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const metaMode = activeModeFromMetadata(connector.metadata)
  const canUpload = allowsUpload(connector.allowed_approaches)
  const canLive = allowsLive(connector.allowed_approaches)

  const initialMode: 'live' | 'upload' | null =
    metaMode ?? (canUpload ? 'upload' : canLive ? 'live' : null)

  const [step, setStep] = useState<OwnerWizardStep>('mode')
  const [mode, setMode] = useState<'live' | 'upload' | null>(initialMode)
  const [delimiterKey, setDelimiterKey] = useState('none')
  const [cadenceDays, setCadenceDays] = useState(
    String(cadenceDaysFromMetadata(connector.metadata)),
  )
  const [file, setFile] = useState<File | null>(null)
  const [uploadOk, setUploadOk] = useState(false)

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
    mutationFn: (next: 'live' | 'upload') =>
      setOwnerConnectorMode(verticalId, connector.system, { mode: next }),
    onSuccess: (_data, next) => {
      invalidate()
      actionToast.success({
        title: 'Mode saved',
        description: `Using ${next === 'upload' ? 'Upload' : 'Live'} for ${connector.display_name}.`,
      })
      setStep('connect')
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not save mode',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => {
            if (mode) modeMutation.mutate(mode)
          },
        },
      })
    },
  })

  const cadenceMutation = useMutation({
    mutationFn: (days: number) =>
      setOwnerConnectorCadence(verticalId, connector.system, {
        cadence_days: days,
      }),
    onSuccess: () => {
      invalidate()
      actionToast.success({
        title: 'Cadence saved',
        description: `Refresh every ${cadenceDays} days.`,
      })
      setStep('confirm')
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not save cadence',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => {
            const days = Number.parseInt(cadenceDays, 10)
            if (Number.isFinite(days) && days >= 1) cadenceMutation.mutate(days)
          },
        },
      })
    },
  })

  const completeMutation = useMutation({
    mutationFn: () => completeOwnerConnectorWizard(verticalId, connector.system),
    onSuccess: () => {
      invalidate()
      actionToast.success({
        title: 'Wizard complete',
        description: `${connector.display_name} setup finished.`,
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

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV file first.')
      return uploadOwnerConnectorCsv(
        verticalId,
        connector.system,
        file,
        delimiterValueFromKey(delimiterKey),
      )
    },
    onSuccess: (result) => {
      invalidate()
      if (result.ok) {
        setUploadOk(true)
        actionToast.success({
          title: 'Upload validated',
          description:
            result.upload_row_count != null
              ? `${result.upload_row_count} usable row(s). Continue to cadence.`
              : 'File accepted. Continue to cadence.',
        })
      } else {
        actionToast.error({
          title: 'Upload test failed',
          description: actionToast.safeErrorMessage(
            new Error(result.detail || 'upload failed'),
            'Check headers and delimiter, then try again.',
          ),
        })
      }
    },
    onError: (error) => {
      actionToast.error({
        title: 'Upload failed',
        description: actionToast.safeErrorMessage(
          error,
          'Check the file and try again.',
        ),
        action: {
          label: 'Retry',
          onClick: () => uploadMutation.mutate(),
        },
      })
    },
  })

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
        description: 'Fill required headers, then upload your CSV.',
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

  return (
    <div className="mt-3 rounded-md border border-line bg-canvas p-3 sm:p-4">
      <WizardProgress step={step} />

      {step === 'mode' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">{modeStepIntroCopy(connector.display_name)}</p>
          <ModeExplainerCards
            cards={buildModeStepCards({
              systemId: connector.system,
              displayName: connector.display_name,
              allowedApproaches: connector.allowed_approaches,
            })}
            selected={mode}
            onSelect={setMode}
          />
          <p className="text-xs text-mute">{MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE}</p>
          {!canUpload && !canLive ? (
            <p className="text-xs text-mute">
              No owner approaches are configured for this system.
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              disabled={
                !mode ||
                modeMutation.isPending ||
                (mode === 'upload' && !canUpload) ||
                (mode === 'live' && !canLive)
              }
              onClick={() => {
                if (mode) modeMutation.mutate(mode)
              }}
            >
              {modeMutation.isPending ? 'Saving…' : 'Continue'}
            </Button>
          </div>
        </div>
      ) : null}

      {step === 'connect' && mode === 'upload' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            Download the frozen template, pick a multi-PII delimiter, then upload a
            CSV. The connection test checks headers and usable rows.
          </p>
          <div className="flex flex-wrap gap-2">
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
            <span className="font-medium text-ink">Multi-PII delimiter</span>
            <select
              className={FIELD_CLASS}
              value={delimiterKey}
              onChange={(event) => setDelimiterKey(event.target.value)}
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
                setUploadOk(false)
              }}
            />
          </label>
          <div className="flex flex-wrap justify-between gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => setStep('mode')}>
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
                {uploadMutation.isPending ? 'Uploading…' : 'Upload & test'}
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!uploadOk}
                onClick={() => setStep('cadence')}
              >
                Continue
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {step === 'connect' && mode === 'live' ? (
        <LiveConnectPanel
          verticalId={verticalId}
          connector={connector}
          invalidate={invalidate}
          onBack={() => setStep('mode')}
          onContinue={() => setStep('cadence')}
        />
      ) : null}

      {step === 'cadence' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            How often should Habeas expect a refresh for this system? Soft reminders
            appear when approaching or past this window; matching hard-gates when stale.
          </p>
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-ink">Cadence (days)</span>
            <input
              type="number"
              min={1}
              max={3650}
              className={FIELD_CLASS}
              value={cadenceDays}
              onChange={(event) => setCadenceDays(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap justify-between gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setStep('connect')}
            >
              Back
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={cadenceMutation.isPending}
              onClick={() => {
                const days = Number.parseInt(cadenceDays, 10)
                if (!Number.isFinite(days) || days < 1) {
                  actionToast.warning({
                    title: 'Enter a valid cadence',
                    description: 'Use a whole number of days (1 or more).',
                  })
                  return
                }
                cadenceMutation.mutate(days)
              }}
            >
              {cadenceMutation.isPending ? 'Saving…' : 'Continue'}
            </Button>
          </div>
        </div>
      ) : null}

      {step === 'confirm' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            Confirm setup for {connector.display_name}. Mode:{' '}
            <span className="font-medium text-ink">{mode ?? '—'}</span>
            {mode === 'upload' ? (
              <>
                {' '}
                · Delimiter:{' '}
                <span className="font-medium text-ink">
                  {delimiterValueFromKey(delimiterKey) ?? 'None'}
                </span>
              </>
            ) : null}
            {' '}
            · Cadence:{' '}
            <span className="font-medium text-ink">{cadenceDays} days</span>
          </p>
          <div className="flex flex-wrap justify-between gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setStep('cadence')}
            >
              Back
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={completeMutation.isPending}
              onClick={() => completeMutation.mutate()}
            >
              {completeMutation.isPending ? 'Completing…' : 'Complete wizard'}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function ConnectorCard({
  verticalId,
  connector,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
}) {
  const [wizardOpen, setWizardOpen] = useState(
    connector.display_status === 'needs_setup' ||
      connector.display_status === 'action_required',
  )
  const metaMode = activeModeFromMetadata(connector.metadata)
  const canWizard =
    allowsUpload(connector.allowed_approaches) ||
    allowsLive(connector.allowed_approaches)

  return (
    <div className="rounded-md border border-line bg-white p-3 sm:p-4">
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
      {canWizard ? (
        <div className="mt-3">
          <Button
            type="button"
            size="sm"
            variant={wizardOpen ? 'outline' : 'default'}
            onClick={() => setWizardOpen((open) => !open)}
          >
            {wizardOpen ? 'Hide wizard' : 'Open setup wizard'}
          </Button>
          {wizardOpen ? (
            <ConnectorWizard
              verticalId={verticalId}
              connector={connector}
              onDone={() => setWizardOpen(false)}
            />
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-xs text-mute">No owner wizard for this system.</p>
      )}
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
  const listQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    queryFn: () => listOwnerConnectors(verticalId),
    staleTime: 15_000,
  })

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

  const list = listQuery.data
  if (!list) return null

  if (list.view_only) {
    return <ViewOnlyCard list={list} />
  }

  return (
    <section
      className={`space-y-3 rounded-md border p-3 sm:p-4 ${
        selected ? 'border-habeas-navy/40 bg-habeas-navy/[0.03]' : 'border-line bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          className="text-left"
          onClick={onSelect}
        >
          <h3 className="text-sm font-medium text-ink">{list.display_label}</h3>
          <p className="text-[11px] text-mute">{list.connectors.length} system(s)</p>
        </button>
      </div>
      <div className="space-y-2">
        {list.connectors.map((connector) => (
          <ConnectorCard
            key={connector.system}
            verticalId={verticalId}
            connector={connector}
          />
        ))}
      </div>
    </section>
  )
}

function OwnerConnectorsBody({
  verticalFilter,
}: {
  verticalFilter?: string
}) {
  const { me, role } = useAuth()
  const navigate = useNavigate()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set())

  const verticals = me?.verticals ?? []
  const visibleVerticals = useMemo(() => {
    if (!verticalFilter) return verticals
    return verticals.filter((id) => id === verticalFilter)
  }, [verticals, verticalFilter])

  const remindersFromMe = me?.connector_reminders
  const remindersQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connector-reminders'],
    queryFn: async () => {
      try {
        const payload = await listOwnerConnectorReminders()
        return payload.reminders
      } catch {
        // U10 may land later — fall back to /me reminders without crashing.
        return remindersFromMe ?? []
      }
    },
    staleTime: 30_000,
    enabled: role === 'data_owner' || role === 'super_admin' || role === 'admin',
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
            No verticals are assigned to your account yet. Ask a Habeas admin to
            assign you to a vertical catalog entry.
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
            Set Live or Upload mode, cadence, and complete setup for your assigned
            verticals. Soft reminders never block login.
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
          Vertical <code className="text-ink">{verticalFilter}</code> is not assigned
          to you.
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {verticals.map((id) => (
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

export function OwnerConnectorsPage({
  search,
}: {
  search?: OwnerConnectorsSearch
}) {
  return (
    <RoleGate allow={canAccessOwnerConnectors}>
      <OwnerConnectorsBody verticalFilter={search?.vertical} />
    </RoleGate>
  )
}
