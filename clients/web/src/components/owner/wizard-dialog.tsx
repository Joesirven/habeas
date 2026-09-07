/**
 * WizardDialog — the "Configure data system" modal for ONE connection.
 *
 * Opened from a system row on the Data vertical settings page (the page is
 * the any-order picker; there is no in-modal hub). Step model lives in
 * `@/lib/owner-wizard-flow` (pure TS). The dialog is the runner: it owns the
 * history stack plus the *planned* steps for the active system, and all
 * per-system draft state (credentials, column mapping, formats, upload
 * result/headers, sheets draft, cadence).
 *
 * Flow-logic approach for dynamic steps
 * -------------------------------------
 * `startSystem` pushes only the subflow's first step; `planned` holds the full
 * ordered plan for the active system. Because the stack is base + this system's
 * visited steps only, the next step is always `planned[stack.length - 1]`, so
 * Back (`popStep`) never corrupts forward navigation — re-advancing replays the
 * same planned step instead of duplicating it. Back from the first step closes
 * the dialog.
 * - choice resolve: splice `branchSteps(input, mode)` into `planned` after the
 *   choice step, then advance.
 * - mapping confirm (upload and sheets): drop any stale `format` steps from
 *   the unvisited tail of `planned`, insert `formatStepsForMapping(system,
 *   mapping)` ahead of cadence/system-done, then advance. Format and
 *   delimiter never run before a column is mapped.
 * - live-seed-choice "upload now": replace the unvisited tail (cadence /
 *   system-done from the live branch) with `branchSteps(input, 'upload')`.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  completeOwnerConnectorWizard,
  getOwnerConnectorCredentialPreview,
  ownerSheetsOauthExtract,
  setOwnerConnectorCadence,
  setOwnerConnectorMode,
  uploadOwnerConnectorCsv,
  type OwnerConnectorSystem,
  type OwnerCredentialPreview,
  type OwnerUploadResult,
  type RefreshCadence,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  DIRECT_CONNECTION_LABEL,
  MANUAL_UPLOAD_LABEL,
  SHEETS_CADENCE_OPTION_IDS,
  activeModeFromMetadata,
  allowsLive,
  buildModeStepCards,
  cadenceOptionFromMetadata,
  connectionMethodLabel,
  delimiterValueFromKey,
  isOwnerConnectorsHiddenSystem,
  isSheetsOwnerSystem,
  ownerConnectorDisplayName,
  ownerUploadAllowed,
  suggestUploadColumnMapping,
} from '@/lib/owner-connector-ui'
import {
  branchSteps,
  formatStepColumnLabel,
  formatStepsForMapping,
  initialStack,
  popStep,
  pushStep,
  stackTop,
  startSystem,
  systemSubflowSteps,
  type StepStack,
  type SubflowInput,
  type WizardStep,
} from '@/lib/owner-wizard-flow'
import { cn } from '@/lib/utils'

import { CredentialFieldStep, LiveSeedChoiceStep, LiveTestStep } from './credential-steps'
import {
  SheetsConnectPanel,
  emptySheetsConnectDraft,
  readOwnerSheetsOauthSession,
  type SheetsConnectDraft,
} from './sheets-step'
import { FormatStep, MappingStep, UploadFileStep } from './upload-steps'
import {
  CadenceStep,
  SystemDoneStep,
  WizardStepShell,
  ownerConnectorWizardCompleted,
} from './wizard-shared'

/**
 * Per-system upload format drafts. `delimiter` stores the
 * MULTI_PII_DELIMITER_OPTIONS *key* ('none' | ';' | '|' | ',') — convert with
 * `delimiterValueFromKey` before sending to the API.
 */
type UploadFormatDrafts = { email?: string; phone?: string; name?: string; delimiter?: string }

type FlowState = {
  /** True history — index 0 is the (never rendered) base, top is the current step. */
  stack: StepStack
  /** Full ordered plan for the active system subflow (base excluded). */
  planned: WizardStep[]
}

const FORMAT_DEFAULTS: Record<'email' | 'phone' | 'name' | 'delimiter', string> = {
  email: 'standard',
  phone: 'us_10',
  name: 'first_last',
  delimiter: 'none',
}

function mapPreviewFields(preview: OwnerCredentialPreview): SubflowInput['credentialFields'] {
  return preview.fields.map((field) => ({
    id: field.id,
    label: field.label,
    help: field.help ?? undefined,
    required: field.required,
    input_type: field.input_type,
  }))
}

export function WizardDialog({
  open,
  onOpenChange,
  verticalId,
  verticalLabel,
  connectors,
  initialSystem = null,
  onSystemCompleted,
  onAllDone,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  verticalId: string
  verticalLabel: string
  connectors: OwnerConnectorSystem[]
  initialSystem?: string | null
  onSystemCompleted?: (system: string) => void
  onAllDone?: () => void
}) {
  const queryClient = useQueryClient()

  const [flow, setFlow] = useState<FlowState>(() => ({ stack: initialStack(), planned: [] }))
  const [activeInput, setActiveInput] = useState<SubflowInput | null>(null)
  /** System selected but waiting on its credential preview before starting. */
  const [pendingSystem, setPendingSystem] = useState<string | null>(null)
  /** System whose credential preview is being fetched (live-capable systems). */
  const [previewForSystem, setPreviewForSystem] = useState<string | null>(null)
  const [completedThisSession, setCompletedThisSession] = useState<string[]>([])

  const [credentialsBySystem, setCredentialsBySystem] = useState<
    Record<string, Record<string, string>>
  >({})
  const [mappingBySystem, setMappingBySystem] = useState<Record<string, Record<string, string>>>({})
  const [formatsBySystem, setFormatsBySystem] = useState<Record<string, UploadFormatDrafts>>({})
  const [headersBySystem, setHeadersBySystem] = useState<Record<string, string[]>>({})
  const [fileBySystem, setFileBySystem] = useState<Record<string, File | null>>({})
  const [uploadResultBySystem, setUploadResultBySystem] = useState<
    Record<string, OwnerUploadResult | null>
  >({})
  const [cadenceBySystem, setCadenceBySystem] = useState<Record<string, RefreshCadence | null>>({})
  const [sheetsDraftBySystem, setSheetsDraftBySystem] = useState<
    Record<string, SheetsConnectDraft>
  >({})

  const wasOpenRef = useRef(false)
  const autoStartedForRef = useRef<string | null>(null)

  const previewQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'credential-preview', verticalId, previewForSystem],
    queryFn: () => getOwnerConnectorCredentialPreview(verticalId, previewForSystem as string),
    enabled: open && previewForSystem != null,
    staleTime: 60_000,
  })

  const modeMutation = useMutation({
    mutationFn: ({ system, mode }: { system: string; mode: 'live' | 'upload' }) =>
      setOwnerConnectorMode(verticalId, system, { mode }),
    onError: (error) => {
      actionToast.error({
        title: 'Could not save connection method',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
      })
    },
  })

  const cadenceMutation = useMutation({
    mutationFn: async ({ system, cadence }: { system: string; cadence: RefreshCadence }) => {
      await setOwnerConnectorCadence(verticalId, system, { refresh_cadence: cadence })
      return completeOwnerConnectorWizard(verticalId, system, { refresh_cadence: cadence })
    },
    onSuccess: (_data, { system }) => {
      invalidate()
      setCompletedThisSession((current) =>
        current.includes(system) ? current : [...current, system],
      )
      advance()
    },
    onError: (error, { system }) => {
      actionToast.error({
        title: 'Could not save cadence',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => {
            const cadence = cadenceBySystem[system]
            if (cadence) cadenceMutation.mutate({ system, cadence })
          },
        },
      })
    },
  })

  function confirmedFormats(system: string) {
    const mapping = mappingBySystem[system] ?? {}
    const formats = formatsBySystem[system] ?? {}
    const payload = Object.values(mapping).some((value) => value?.trim()) ? mapping : null
    const delimiter = delimiterValueFromKey(formats.delimiter ?? FORMAT_DEFAULTS.delimiter)
    return {
      mapping,
      payload,
      delimiter,
      emailFormat: mapping.email ? (formats.email ?? FORMAT_DEFAULTS.email) : undefined,
      phoneFormat: mapping.phone ? (formats.phone ?? FORMAT_DEFAULTS.phone) : undefined,
      nameFormat: mapping.full_name
        ? ((formats.name ?? FORMAT_DEFAULTS.name) as 'first_last' | 'last_first')
        : undefined,
    }
  }

  // The first upload/extract fires before mapping and formats. This finalize
  // re-runs with the confirmed mapping + chosen formats so persisted
  // column_mapping / name_format / delimiter match what the owner decided.
  const finalizeUploadMutation = useMutation({
    mutationFn: ({ system }: { system: string }) => {
      const file = fileBySystem[system]
      if (!file) return Promise.resolve(null)
      const confirmed = confirmedFormats(system)
      return uploadOwnerConnectorCsv(
        verticalId,
        system,
        file,
        confirmed.delimiter,
        confirmed.payload,
        {
          emailFormat: confirmed.emailFormat,
          phoneFormat: confirmed.phoneFormat,
          nameFormat: confirmed.nameFormat,
        },
      )
    },
    onSuccess: (result, { system }) => {
      if (!result) {
        advance()
        return
      }
      setUploadResultBySystem((current) => ({ ...current, [system]: result }))
      if (!result.ok) {
        actionToast.error({
          title: 'Upload needs attention',
          description:
            result.detail === 'upload_rows_rejected'
              ? 'Some rows were rejected with these choices. Go back to adjust the mapping, or fix the file and pick it again.'
              : 'Check the column mapping, then try again.',
          action: { label: 'Retry', onClick: () => finalizeUploadMutation.mutate({ system }) },
        })
        return
      }
      advance()
    },
    onError: (error, { system }) => {
      actionToast.error({
        title: 'Could not finish the upload',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: { label: 'Retry', onClick: () => finalizeUploadMutation.mutate({ system }) },
      })
    },
  })

  const finalizeExtractMutation = useMutation({
    mutationFn: ({ system }: { system: string }) => {
      const draft = sheetsDraftBySystem[system]
      if (!draft?.spreadsheetId || !draft.tab) return Promise.resolve(null)
      const confirmed = confirmedFormats(system)
      return ownerSheetsOauthExtract(verticalId, system, {
        spreadsheet_id: draft.spreadsheetId,
        tab: draft.tab,
        multi_pii_delimiter: confirmed.delimiter,
        column_mapping: confirmed.payload,
        email_format: confirmed.emailFormat,
        phone_format: confirmed.phoneFormat,
        name_format: confirmed.nameFormat,
      })
    },
    onSuccess: (result, { system }) => {
      if (!result) {
        advance()
        return
      }
      setUploadResultBySystem((current) => ({ ...current, [system]: result }))
      if (!result.ok) {
        actionToast.error({
          title: 'Extract needs attention',
          description:
            result.detail === 'upload_rows_rejected'
              ? 'Some rows were rejected with these choices. Go back to adjust the mapping or formats.'
              : 'Check the column mapping, then try again.',
          action: { label: 'Retry', onClick: () => finalizeExtractMutation.mutate({ system }) },
        })
        return
      }
      advance()
    },
    onError: (error, { system }) => {
      actionToast.error({
        title: 'Could not finish the extract',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: { label: 'Retry', onClick: () => finalizeExtractMutation.mutate({ system }) },
      })
    },
  })

  function finalizeUpload(system: string) {
    if (fileBySystem[system]) {
      finalizeUploadMutation.mutate({ system })
      return
    }
    const draft = sheetsDraftBySystem[system]
    if (draft?.method === 'oauth' && draft.spreadsheetId && draft.tab) {
      finalizeExtractMutation.mutate({ system })
      return
    }
    advance()
  }

  function invalidate() {
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    })
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connector-reminders'],
    })
  }

  function connectorFor(system: string): OwnerConnectorSystem | undefined {
    return connectors.find((connector) => connector.system === system)
  }

  function displayNameFor(system: string): string {
    const connector = connectorFor(system)
    return ownerConnectorDisplayName(verticalId, system, connector?.display_name)
  }

  function ensureMode(connector: OwnerConnectorSystem, mode: 'live' | 'upload') {
    if (activeModeFromMetadata(connector.metadata) === mode) return
    modeMutation.mutate({ system: connector.system, mode })
  }

  function seedMappingFromMetadata(system: string, metadata: Record<string, unknown>) {
    const raw = metadata.column_mapping
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) {
      const mapping: Record<string, string> = {}
      for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
        if (typeof value === 'string' && value.trim()) mapping[key] = value
      }
      if (Object.keys(mapping).length > 0) {
        setMappingBySystem((current) =>
          current[system] && Object.keys(current[system]).length > 0
            ? current
            : { ...current, [system]: mapping },
        )
      }
    }
    const headers = metadata.detected_headers
    if (Array.isArray(headers)) {
      const next = headers.map((item) => String(item).trim()).filter(Boolean)
      if (next.length > 0) {
        setHeadersBySystem((current) =>
          current[system]?.length ? current : { ...current, [system]: next },
        )
      }
    }
  }

  function seedCadence(system: string, metadata: Record<string, unknown>) {
    setCadenceBySystem((current) =>
      system in current ? current : { ...current, [system]: cadenceOptionFromMetadata(metadata) },
    )
  }

  function seedSheetsDraft(connector: OwnerConnectorSystem) {
    const session = readOwnerSheetsOauthSession()
    const redeemed =
      session?.redeemed === true &&
      session.verticalId === verticalId &&
      session.system === connector.system
    setSheetsDraftBySystem((current) => ({
      ...current,
      [connector.system]:
        current[connector.system] ?? {
          ...emptySheetsConnectDraft(),
          method: redeemed ? 'oauth' : null,
          oauthRedeemed: redeemed,
        },
    }))
  }

  function beginSubflow(
    connector: OwnerConnectorSystem,
    credentialFields: SubflowInput['credentialFields'],
  ) {
    const input: SubflowInput = {
      system: connector.system,
      liveAllowed: allowsLive(connector.allowed_approaches),
      uploadAllowed: ownerUploadAllowed(connector.system, connector.upload_allowed),
      isSheets: isSheetsOwnerSystem(connector.system),
      credentialFields,
    }
    const steps = systemSubflowSteps(input)
    if (steps.length === 0) {
      actionToast.error({
        title: 'No setup path',
        description: 'This system has no available connection method.',
      })
      return
    }
    setActiveInput(input)
    setFlow(({ stack }) => ({ stack: startSystem(stack, steps), planned: steps }))
    seedCadence(connector.system, connector.metadata)
    seedMappingFromMetadata(connector.system, connector.metadata)
    if (input.isSheets) {
      seedSheetsDraft(connector)
      return
    }
    // Single-mode systems never show the choice step, so pin the mode here —
    // mirrors the old wizard's ensureMode on the how-to continue.
    if (input.liveAllowed !== input.uploadAllowed) {
      ensureMode(connector, input.liveAllowed ? 'live' : 'upload')
    }
  }

  function selectSystem(system: string) {
    const connector = connectorFor(system)
    if (!connector) return
    if (isSheetsOwnerSystem(connector.system)) {
      beginSubflow(connector, [])
      return
    }
    if (allowsLive(connector.allowed_approaches)) {
      setPreviewForSystem(system)
      const uploadAllowed = ownerUploadAllowed(
        connector.system,
        connector.upload_allowed,
      )
      if (!uploadAllowed) {
        // Live-only: credential field count shapes the subflow — wait for it.
        setPendingSystem(system)
        return
      }
    }
    beginSubflow(connector, [])
  }

  function advance() {
    setFlow(({ stack, planned }) => {
      const next = planned[stack.length - 1]
      if (!next) return { stack, planned }
      return { stack: pushStep(stack, next), planned }
    })
  }

  function goBack() {
    // No hub: Back from the subflow's first step closes the dialog.
    if (flow.stack.length <= 2) {
      onOpenChange(false)
      return
    }
    setFlow(({ stack, planned }) => ({ stack: popStep(stack), planned }))
  }

  function handleChoice(system: string, mode: 'live' | 'upload') {
    if (!activeInput || activeInput.system !== system) return
    let resolved = activeInput
    if (mode === 'live' && previewForSystem === system && previewQuery.data) {
      resolved = { ...activeInput, credentialFields: mapPreviewFields(previewQuery.data) }
      setActiveInput(resolved)
    }
    const branch = branchSteps(resolved, mode)
    if (branch.length === 0) return
    const connector = connectorFor(system)
    if (connector) ensureMode(connector, mode)
    setFlow(({ stack, planned }) => {
      const insertAt = stack.length - 1
      // Drop the tail: anything after the choice step is a previously chosen
      // branch (re-choosing a mode must not accumulate abandoned steps).
      const nextPlanned = [...planned.slice(0, insertAt), ...branch]
      return { stack: pushStep(stack, nextPlanned[insertAt]), planned: nextPlanned }
    })
  }

  function handleMappingContinue(system: string) {
    const mapping = mappingBySystem[system] ?? {}
    const formatSteps = formatStepsForMapping(system, mapping)
    setFlow(({ stack, planned }) => {
      const insertAt = stack.length - 1
      const tail = planned.slice(insertAt).filter((step) => step.kind !== 'format')
      const nextPlanned = [...planned.slice(0, insertAt), ...formatSteps, ...tail]
      if (formatSteps.length === 0) return { stack, planned: nextPlanned }
      const next = nextPlanned[insertAt]
      if (!next) return { stack, planned }
      return { stack: pushStep(stack, next), planned: nextPlanned }
    })
    // No format decisions needed — mapping was the last upload decision.
    if (formatSteps.length === 0) finalizeUpload(system)
  }

  function handleSeedChoice(system: string, uploadNow: boolean) {
    if (!uploadNow || !activeInput || activeInput.system !== system) {
      advance()
      return
    }
    const branch = branchSteps(activeInput, 'upload')
    const connector = connectorFor(system)
    if (connector) ensureMode(connector, 'upload')
    setFlow(({ stack, planned }) => {
      const insertAt = stack.length - 1
      const nextPlanned = [...planned.slice(0, insertAt), ...branch]
      return { stack: pushStep(stack, nextPlanned[insertAt]), planned: nextPlanned }
    })
  }

  function handleUploaded(system: string, result: OwnerUploadResult, headers: string[]) {
    setUploadResultBySystem((current) => ({ ...current, [system]: result }))
    setHeadersBySystem((current) => ({ ...current, [system]: headers }))
    setMappingBySystem((current) => {
      const existing = current[system] ?? {}
      return { ...current, [system]: { ...suggestUploadColumnMapping(headers), ...existing } }
    })
    advance()
  }

  function handleSystemDoneContinue(system: string) {
    onSystemCompleted?.(system)
    const done = new Set(completedThisSession)
    done.add(system)
    const visible = connectors.filter(
      (connector) => !isOwnerConnectorsHiddenSystem(connector.system),
    )
    // Per-connection wizard: finishing closes the dialog (the settings page
    // is the picker). Still fire onAllDone when every system is configured.
    onOpenChange(false)
    if (
      visible.length > 0 &&
      visible.every(
        (connector) => done.has(connector.system) || ownerConnectorWizardCompleted(connector),
      )
    ) {
      onAllDone?.()
    }
  }

  // Fresh run each time the dialog opens.
  useEffect(() => {
    if (open && !wasOpenRef.current) {
      setFlow({ stack: initialStack(), planned: [] })
      setActiveInput(null)
      setPendingSystem(null)
      setPreviewForSystem(null)
      setCompletedThisSession([])
      setCredentialsBySystem({})
      setMappingBySystem({})
      setFormatsBySystem({})
      setHeadersBySystem({})
      setFileBySystem({})
      setUploadResultBySystem({})
      setCadenceBySystem({})
      setSheetsDraftBySystem({})
    }
    wasOpenRef.current = open
    if (!open) autoStartedForRef.current = null
  }, [open])

  // OAuth resume / per-row Set up: open straight into a system's subflow, once.
  useEffect(() => {
    if (!open || !initialSystem) return
    if (autoStartedForRef.current === initialSystem) return
    if (stackTop(flow.stack).kind !== 'hub' || pendingSystem) return
    autoStartedForRef.current = initialSystem
    selectSystem(initialSystem)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, initialSystem, flow.stack, pendingSystem])

  // Live-only systems start once their credential preview lands.
  useEffect(() => {
    if (!open || !pendingSystem || previewForSystem !== pendingSystem) return
    const preview = previewQuery.data
    if (!preview) return
    const connector = connectorFor(pendingSystem)
    if (!connector) return
    beginSubflow(connector, mapPreviewFields(preview))
    setPendingSystem(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, pendingSystem, previewForSystem, previewQuery.data])

  // Preview failure for a live-only system: toast once; the body shows an
  // inline Retry while pendingSystem stays set (no hub to fall back to).
  useEffect(() => {
    if (!pendingSystem || !previewQuery.isError) return
    actionToast.error({
      title: 'Could not load credential fields',
      description: actionToast.safeErrorMessage(previewQuery.error, 'Try again.'),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingSystem, previewQuery.isError])

  const top = stackTop(flow.stack)
  // Progress within the active system's plan. The stack holds hub + visited
  // steps, so visited-subflow-count = stack.length - 1; the total is the full
  // known plan (which grows when mapping inserts format steps).
  const progressIndex = flow.stack.length - 1
  const progressTotal = flow.planned.length
  const activeConnector = 'system' in top ? connectorFor(top.system) : undefined

  function renderChoiceStep(system: string) {
    const connector = connectorFor(system)
    if (!connector) return null
    const displayName = displayNameFor(system)
    const methodLabel =
      connectionMethodLabel(
        system,
        connector.connection_method_label ?? connector.connection_method,
      ) ?? DIRECT_CONNECTION_LABEL
    const modeCards = buildModeStepCards({
      systemId: system,
      displayName,
      allowedApproaches: connector.allowed_approaches,
      connectionMethod: connector.connection_method_label ?? connector.connection_method,
      uploadAllowed: connector.upload_allowed,
    })
    const cards = modeCards.filter((card) => card.allowed)
    const previewLoading = previewForSystem === system && previewQuery.isPending
    const previewReady = previewForSystem === system && previewQuery.data != null
    const previewFailed = previewForSystem === system && previewQuery.isError

    return (
      <WizardStepShell
        title={`${displayName} · Connection type`}
        description={`Choose how Habeas receives ${displayName} data.`}
        onBack={goBack}
      >
        <div className="grid gap-2 sm:grid-cols-2">
          {cards.map((card) => {
            const isLive = card.mode === 'live'
            const disabled = isLive && !previewReady
            return (
              <button
                key={card.mode}
                type="button"
                disabled={disabled}
                onClick={() => handleChoice(system, card.mode)}
                className={cn(
                  'rounded-md border p-3 text-left transition-colors',
                  'border-line hover:border-slate-300',
                  disabled ? 'cursor-not-allowed opacity-60' : '',
                )}
              >
                <p className="text-sm font-medium text-ink">
                  {isLive ? methodLabel : MANUAL_UPLOAD_LABEL}
                </p>
                <p className="mt-1 text-xs text-ink-soft">{card.hint ?? card.definition}</p>
                {isLive && previewLoading ? (
                  <p className="mt-1 text-[11px] text-mute">Loading connection details…</p>
                ) : null}
              </button>
            )
          })}
        </div>
        {previewFailed ? (
          <p className="text-xs text-red-800">
            Could not load {methodLabel} credential fields.{' '}
            <button
              type="button"
              className="font-medium text-habeas-navy underline-offset-2 hover:underline"
              onClick={() => void previewQuery.refetch()}
            >
              Retry
            </button>
          </p>
        ) : null}
      </WizardStepShell>
    )
  }

  function renderStep(step: WizardStep) {
    switch (step.kind) {
      case 'hub':
        // Transient base frame — the auto-start effect immediately enters the
        // target system's subflow. Never a rendered destination.
        return <SkeletonLines lines={3} />

      case 'choice':
        return renderChoiceStep(step.system)

      case 'cred': {
        // Fields come from the active subflow input (already mapped from the
        // credential preview with `help` normalized to string | undefined).
        const field =
          activeInput && activeInput.system === step.system
            ? activeInput.credentialFields[step.fieldIndex]
            : undefined
        if (!field) {
          return (
            <WizardStepShell title={displayNameFor(step.system)} onBack={goBack}>
              <SkeletonLines lines={3} />
            </WizardStepShell>
          )
        }
        return (
          <CredentialFieldStep
            system={step.system}
            field={field}
            value={credentialsBySystem[step.system]?.[field.id] ?? ''}
            onChange={(value) =>
              setCredentialsBySystem((current) => ({
                ...current,
                [step.system]: { ...current[step.system], [field.id]: value },
              }))
            }
            onBack={goBack}
            onContinue={advance}
          />
        )
      }

      case 'live-test':
        return (
          <LiveTestStep
            verticalId={verticalId}
            system={step.system}
            credentials={credentialsBySystem[step.system] ?? {}}
            trustCopy={
              previewForSystem === step.system
                ? (previewQuery.data?.trust_copy ?? undefined)
                : undefined
            }
            onBack={goBack}
            onPassed={advance}
          />
        )

      case 'live-seed-choice':
        return (
          <LiveSeedChoiceStep
            system={step.system}
            onChoice={(uploadNow) => handleSeedChoice(step.system, uploadNow)}
            onBack={goBack}
          />
        )

      case 'upload': {
        if (!activeConnector) return null
        return (
          <UploadFileStep
            system={step.system}
            verticalId={verticalId}
            columnMapping={mappingBySystem[step.system] ?? {}}
            formats={formatsBySystem[step.system] ?? {}}
            initialFile={fileBySystem[step.system] ?? null}
            initialHeaders={headersBySystem[step.system] ?? []}
            onBack={goBack}
            onUploaded={(result, headers) => handleUploaded(step.system, result, headers)}
            onFileSelected={(file) =>
              setFileBySystem((current) => ({ ...current, [step.system]: file }))
            }
          />
        )
      }

      case 'mapping': {
        const headers =
          headersBySystem[step.system] ??
          uploadResultBySystem[step.system]?.detected_headers?.filter((header) =>
            header.trim(),
          ) ??
          []
        return (
          <MappingStep
            headers={headers}
            mapping={mappingBySystem[step.system] ?? {}}
            onChange={(next) =>
              setMappingBySystem((current) => ({ ...current, [step.system]: next }))
            }
            onBack={goBack}
            onContinue={() => handleMappingContinue(step.system)}
          />
        )
      }

      case 'format':
        return (
          <FormatStep
            formatId={step.formatId}
            columnLabel={formatStepColumnLabel(
              step.formatId,
              mappingBySystem[step.system] ?? {},
            )}
            value={
              formatsBySystem[step.system]?.[step.formatId] ?? FORMAT_DEFAULTS[step.formatId]
            }
            onChange={(value) =>
              setFormatsBySystem((current) => ({
                ...current,
                [step.system]: { ...current[step.system], [step.formatId]: value },
              }))
            }
            onBack={goBack}
            onContinue={() => {
              // Last format step before cadence → persist mapping + formats.
              const next = flow.planned[flow.stack.length - 1]
              if (next?.kind === 'cadence') {
                finalizeUpload(step.system)
              } else {
                advance()
              }
            }}
          />
        )

      case 'sheets': {
        if (!activeConnector) return null
        return (
          <SheetsConnectPanel
            verticalId={verticalId}
            connector={activeConnector}
            draft={sheetsDraftBySystem[step.system] ?? emptySheetsConnectDraft()}
            onDraftChange={(next) =>
              setSheetsDraftBySystem((current) => ({ ...current, [step.system]: next }))
            }
            onBack={goBack}
            onContinue={advance}
            onHeadersReady={(result, headers) => handleUploaded(step.system, result, headers)}
            onFileSelected={(file) =>
              setFileBySystem((current) => ({ ...current, [step.system]: file }))
            }
            invalidate={invalidate}
          />
        )
      }

      case 'cadence': {
        const value = cadenceBySystem[step.system] ?? null
        return (
          <WizardStepShell
            title="Refresh cadence"
            description={`How often should ${displayNameFor(step.system)} data stay current?`}
            onBack={goBack}
            primary={
              <Button
                type="button"
                size="sm"
                disabled={!value || cadenceMutation.isPending}
                onClick={() => {
                  if (value) cadenceMutation.mutate({ system: step.system, cadence: value })
                }}
              >
                {cadenceMutation.isPending ? 'Saving…' : 'Continue'}
              </Button>
            }
          >
            <CadenceStep
              value={value}
              onChange={(next) =>
                setCadenceBySystem((current) => ({ ...current, [step.system]: next }))
              }
              optionIds={
                isSheetsOwnerSystem(step.system) ? SHEETS_CADENCE_OPTION_IDS : undefined
              }
            />
          </WizardStepShell>
        )
      }

      case 'system-done':
        return (
          <SystemDoneStep
            displayName={displayNameFor(step.system)}
            primary={
              <Button
                type="button"
                size="sm"
                onClick={() => handleSystemDoneContinue(step.system)}
              >
                Done
              </Button>
            }
          />
        )

      default:
        return null
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          'flex h-[96vh] max-h-[96vh] w-[96vw] max-w-[96vw] flex-col gap-0 overflow-hidden p-0',
          'translate-x-[-50%] translate-y-[-50%]',
        )}
      >
        <DialogHeader className="shrink-0 space-y-1 border-b border-line px-4 py-2.5 pr-12">
          <DialogTitle className="text-base">Configure data system</DialogTitle>
          <DialogDescription className="sr-only">
            Configure one {verticalLabel} connection, step by step.
          </DialogDescription>
          {top.kind === 'hub' ? (
            <p className="text-xs text-mute">{verticalLabel}</p>
          ) : (
            <p className="text-xs text-mute">
              {displayNameFor(top.system)} — step {progressIndex} of {progressTotal}
            </p>
          )}
        </DialogHeader>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
          <div className="mx-auto w-full max-w-2xl">
            {pendingSystem ? (
              previewQuery.isError ? (
                <div className="space-y-3">
                  <p className="text-xs text-red-800">
                    Could not load {displayNameFor(pendingSystem)} setup.
                  </p>
                  <div className="flex gap-2">
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => void previewQuery.refetch()}
                    >
                      Retry
                    </Button>
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => onOpenChange(false)}
                    >
                      Close
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <p className="text-xs text-mute">
                    Loading {displayNameFor(pendingSystem)} setup…
                  </p>
                  <SkeletonLines lines={3} />
                </div>
              )
            ) : (
              renderStep(top)
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
