import type { ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import type { OwnerCredentialPreview, RefreshCadence } from '@/lib/api'
import {
  CADENCE_OPTION_IDS,
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WEEKLY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
  type CadenceOptionId,
} from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

/** Shared quiet field styling for owner wizard inputs and selects. */
export const OWNER_FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

export type CredentialField = OwnerCredentialPreview['fields'][number]

/** Numbered where-to-find-this steps plus free-text notes (moved from connectors.tsx). */
export function FieldHelp({ help }: { help: string }) {
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

/** Single credential input with label + where-to-find help (moved from connectors.tsx). */
export function CredentialInput({
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
        className={OWNER_FIELD_CLASS}
      />
    </div>
  )
}

/**
 * Presentational step frame for the owner wizard: quiet title, optional
 * description, content, and a footer with a ghost Back plus a primary action
 * slot. Back is omitted entirely when `onBack` is not provided; at a subflow's
 * first step the host wires Back to pop onto the hub (true history).
 */
export function WizardStepShell({
  title,
  description,
  children,
  onBack,
  backDisabled = false,
  primary,
}: {
  title: string
  description?: string
  children: ReactNode
  onBack?: () => void
  backDisabled?: boolean
  primary?: ReactNode
}) {
  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">{title}</h4>
        {description ? <p className="mt-1 text-xs leading-relaxed text-mute">{description}</p> : null}
      </div>
      {children}
      {onBack || primary ? (
        <div className="flex flex-wrap justify-between gap-2">
          {onBack ? (
            <Button type="button" size="sm" variant="ghost" disabled={backDisabled} onClick={onBack}>
              Back
            </Button>
          ) : (
            <span />
          )}
          {primary ? <div className="flex gap-2">{primary}</div> : null}
        </div>
      ) : null}
    </div>
  )
}

const CADENCE_OPTION_COPY: Record<CadenceOptionId, { label: string; description: string }> = {
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
    description: 'Matching needs a successful upload or refresh within the last 7 days.',
  },
}

/**
 * Refresh-cadence picker (moved from the connectors.tsx cadence step). Pure
 * presentational — the host owns the save mutation. `optionIds` lets the host
 * narrow the choices (sheets systems omit weekly).
 */
export function CadenceStep({
  value,
  onChange,
  optionIds = CADENCE_OPTION_IDS,
}: {
  value: RefreshCadence | null
  onChange: (value: RefreshCadence) => void
  optionIds?: readonly CadenceOptionId[]
}) {
  return (
    <div className="space-y-2">
      {optionIds.map((optionId) => {
        const copy = CADENCE_OPTION_COPY[optionId]
        const selected = value === optionId
        return (
          <button
            key={optionId}
            type="button"
            aria-pressed={selected}
            onClick={() => onChange(optionId)}
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
  )
}

/** Quiet per-system success step shown after cadence save + wizard completion. */
export function SystemDoneStep({
  displayName,
  nextLine,
  primary,
}: {
  displayName: string
  nextLine?: string
  primary?: ReactNode
}) {
  return (
    <div className="space-y-3">
      <div>
        <h4 className="text-sm font-medium text-ink">You’re all set with {displayName}</h4>
        <p className="mt-1 text-xs leading-relaxed text-mute">
          {nextLine ??
            'Habeas matches this system against new request batches from here. You can review or change it anytime from Data vertical settings.'}
        </p>
      </div>
      {primary ? <div className="flex justify-end">{primary}</div> : null}
    </div>
  )
}
