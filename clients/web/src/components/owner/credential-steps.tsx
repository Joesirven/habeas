import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import {
  connectTestFailureMessage,
  connectTestSuccessDescription,
  saveOwnerConnectorCredentials,
  testOwnerConnector,
  type OwnerCredentialPreview,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { ownerConnectorDisplayName } from '@/lib/owner-connector-ui'

import { CredentialInput, FieldHelp, WizardStepShell } from './wizard-shared'

export type CredentialStepField = {
  id: string
  label: string
  help?: string | null
  required: boolean
  input_type: string
}

export function CredentialFieldStep({
  system,
  field,
  value,
  onChange,
  onBack,
  onContinue,
}: {
  system: string
  field: CredentialStepField
  value: string
  onChange: (value: string) => void
  onBack: () => void
  onContinue: () => void
}) {
  const displayName = ownerConnectorDisplayName(null, system)
  // Where-to-find help renders at step level via FieldHelp; the input stays quiet.
  const rawInputType = field.input_type
  const inputField: OwnerCredentialPreview['fields'][number] = {
    id: field.id,
    label: field.label,
    required: field.required,
    help: null,
    input_type:
      rawInputType === 'password' || rawInputType === 'url' ? rawInputType : 'text',
  }

  return (
    <WizardStepShell
      title={field.label}
      description={displayName}
      onBack={onBack}
      primary={
        <Button
          type="button"
          size="sm"
          disabled={field.required && !value.trim()}
          onClick={onContinue}
        >
          Continue
        </Button>
      }
    >
      <div className="space-y-4">
        {field.help ? <FieldHelp help={field.help} /> : null}
        <CredentialInput field={inputField} value={value} onChange={onChange} />
      </div>
    </WizardStepShell>
  )
}

type LiveTestState =
  | { phase: 'running' }
  | { phase: 'passed'; detail: string | null }
  | { phase: 'failed'; message: string }

export function LiveTestStep({
  system,
  verticalId,
  credentials,
  trustCopy,
  onBack,
  onPassed,
}: {
  system: string
  verticalId: string
  credentials: Record<string, string>
  trustCopy?: string
  onBack: () => void
  onPassed: () => void
}) {
  const displayName = ownerConnectorDisplayName(null, system)
  const [state, setState] = useState<LiveTestState>({ phase: 'running' })
  const startedRef = useRef(false)
  const savedRef = useRef(false)
  const advancedRef = useRef(false)

  function pass(detail: string | null | undefined) {
    setState({ phase: 'passed', detail: detail ?? null })
  }

  function fail(message: string) {
    setState({ phase: 'failed', message })
  }

  const saveMutation = useMutation({
    mutationFn: () => saveOwnerConnectorCredentials(verticalId, system, credentials),
    onSuccess: (data) => {
      savedRef.current = true
      if (data.ok) pass(data.detail)
      else fail(connectTestFailureMessage(data.detail))
    },
    onError: (error) => {
      fail(
        actionToast.safeErrorMessage(
          error,
          'Could not save credentials. Go back to fix the fields, then try again.',
        ),
      )
    },
  })

  const retestMutation = useMutation({
    mutationFn: () => testOwnerConnector(verticalId, system),
    onSuccess: (data) => {
      if (data.ok) pass(data.detail)
      else fail(connectTestFailureMessage(data.detail))
    },
    onError: (error) => {
      fail(
        actionToast.safeErrorMessage(
          error,
          'Connection test failed. Check the values and try again.',
        ),
      )
    },
  })

  useEffect(() => {
    if (startedRef.current) return
    startedRef.current = true
    saveMutation.mutate()
  }, [saveMutation])

  const onPassedRef = useRef(onPassed)
  onPassedRef.current = onPassed

  function advance() {
    if (advancedRef.current) return
    advancedRef.current = true
    onPassedRef.current()
  }

  useEffect(() => {
    if (state.phase !== 'passed') return
    const timer = window.setTimeout(advance, 1400)
    return () => window.clearTimeout(timer)
    // advance is stable via onPassedRef — don't re-arm on parent re-renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.phase])

  function retry() {
    setState({ phase: 'running' })
    if (savedRef.current) retestMutation.mutate()
    else saveMutation.mutate()
  }

  return (
    <WizardStepShell
      title={`Test your ${displayName} connection`}
      description="We’ll save what you entered in Google’s secure vault, then check that Habeas can authenticate."
      onBack={onBack}
      primary={
        state.phase === 'passed' ? (
          <Button type="button" size="sm" onClick={advance}>
            Continue
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-3">
        {state.phase === 'running' ? (
          <div
            className="flex items-center gap-2 rounded-md border border-line bg-canvas px-3 py-2.5"
            role="status"
            aria-live="polite"
            aria-busy="true"
          >
            <Spinner className="size-4" />
            <p className="text-xs text-ink">Saving securely, then testing the connection…</p>
          </div>
        ) : null}

        {state.phase === 'passed' ? (
          <div
            className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2.5 text-xs text-emerald-900"
            role="status"
          >
            <p className="font-medium">Connection confirmed</p>
            <p className="mt-0.5">{connectTestSuccessDescription(state.detail, displayName)}</p>
          </div>
        ) : null}

        {state.phase === 'failed' ? (
          <div
            className="space-y-2 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-900"
            role="alert"
          >
            <p className="font-medium">Connection test failed</p>
            <p>{state.message}</p>
            <div>
              <Button type="button" size="sm" variant="outline" onClick={retry}>
                Try again
              </Button>
            </div>
          </div>
        ) : null}

        {trustCopy ? <p className="text-[11px] text-mute">{trustCopy}</p> : null}
      </div>
    </WizardStepShell>
  )
}

export function LiveSeedChoiceStep({
  system,
  onChoice,
  onBack,
}: {
  system: string
  onChoice: (uploadNow: boolean) => void
  onBack?: () => void
}) {
  const displayName = ownerConnectorDisplayName(null, system)

  return (
    <WizardStepShell
      title="Send a first file now?"
      description={`${displayName} also delivers data automatically once connected — a first file is optional.`}
      onBack={onBack}
    >
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onChoice(true)}
          className="rounded-md border border-line bg-white px-3 py-3 text-left transition hover:border-habeas-mid hover:bg-canvas"
        >
          <span className="block text-sm font-medium text-ink">Upload a file</span>
          <span className="mt-0.5 block text-xs text-mute">
            Pick a CSV now — you’ll match columns next.
          </span>
        </button>
        <button
          type="button"
          onClick={() => onChoice(false)}
          className="rounded-md border border-line bg-white px-3 py-3 text-left transition hover:border-habeas-mid hover:bg-canvas"
        >
          <span className="block text-sm font-medium text-ink">Skip for now</span>
          <span className="mt-0.5 block text-xs text-mute">
            We’ll wait for the automatic delivery.
          </span>
        </button>
      </div>
    </WizardStepShell>
  )
}
