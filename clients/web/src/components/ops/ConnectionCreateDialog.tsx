import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  ConfirmActionDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  createConnection,
  getConnectionSystems,
  type ConnectionRecord,
  type ConnectionSystemsPayload,
  type IntegrationSystemId,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { isCreatableConnectionSystem, isUploadOnlySystem } from '@/lib/connection-display'

type ConnectionSystemOption = ConnectionSystemsPayload['systems'][number]

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

const FALLBACK_SYSTEMS: ConnectionSystemOption[] = [
  { system_id: 'axios_hq', display_label: 'Axios HQ', invite_allowed: false, credential_fields: [], trust_copy: '' },
  { system_id: 'paylocity', display_label: 'Paylocity', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'lever', display_label: 'Lever', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'auth0', display_label: 'Auth0', invite_allowed: true, credential_fields: [], trust_copy: '' },
  {
    system_id: 'bizdev_contacts',
    display_label: 'BizDev Contacts',
    invite_allowed: true,
    credential_fields: [],
    trust_copy: '',
  },
  {
    system_id: 'hr_alumni',
    display_label: 'HR Alumni List',
    invite_allowed: true,
    credential_fields: [],
    trust_copy: '',
  },
]

function creatableSystems(systems: ConnectionSystemOption[]): ConnectionSystemOption[] {
  return systems.filter((entry) =>
    isCreatableConnectionSystem({
      system_id: entry.system_id,
      invite_allowed: entry.invite_allowed,
    }),
  )
}

export type ConnectionCreateDialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreated?: (connection: ConnectionRecord) => void
}

type DialogPhase = 'form' | 'success'

function verticalAssignmentCopy(system: IntegrationSystemId): string {
  if (isUploadOnlySystem(system)) {
    return 'Assign the owner on the Verticals tab. They refresh data via the vertical connector upload wizard.'
  }
  return 'Assign the owner on the Verticals tab. After login, they complete credentials and testing in the connector wizard — no invite link is minted here.'
}

export function ConnectionCreateDialog({
  open,
  onOpenChange,
  onCreated,
}: ConnectionCreateDialogProps) {
  const [systems, setSystems] = useState<ConnectionSystemOption[]>(
    creatableSystems(FALLBACK_SYSTEMS),
  )
  const [system, setSystem] = useState<IntegrationSystemId>('axios_hq')
  const [displayName, setDisplayName] = useState('')
  const [phase, setPhase] = useState<DialogPhase>('form')
  const [submitting, setSubmitting] = useState(false)
  const [confirmSheetsOpen, setConfirmSheetsOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdConnection, setCreatedConnection] = useState<ConnectionRecord | null>(null)

  const isGoogleSheets = system === 'google_sheets'
  const uploadOnly = isUploadOnlySystem(system)

  function resetForm() {
    setSystem('axios_hq')
    setDisplayName('')
    setPhase('form')
    setSubmitting(false)
    setConfirmSheetsOpen(false)
    setError(null)
    setCreatedConnection(null)
  }

  useEffect(() => {
    if (!open) {
      resetForm()
      return
    }

    let cancelled = false
    void getConnectionSystems()
      .then((payload) => {
        if (cancelled) return
        const next =
          payload.systems.length > 0
            ? creatableSystems(payload.systems)
            : creatableSystems(FALLBACK_SYSTEMS)
        setSystems(next)
        setSystem((current) =>
          next.some((entry) => entry.system_id === current)
            ? current
            : (next[0]?.system_id ?? 'axios_hq'),
        )
      })
      .catch(() => {
        if (!cancelled) setSystems(creatableSystems(FALLBACK_SYSTEMS))
      })

    return () => {
      cancelled = true
    }
  }, [open])

  function handleOpenChange(next: boolean) {
    if (!next && submitting) return
    onOpenChange(next)
  }

  function validateForm(): string | null {
    const trimmedName = displayName.trim()
    if (!trimmedName) {
      setError('Display name is required.')
      return null
    }
    setError(null)
    return trimmedName
  }

  async function runCreate(trimmedName: string) {
    setSubmitting(true)
    setError(null)
    try {
      if (isGoogleSheets) {
        actionToast.info({
          title: 'Creating Sheets service account',
          description: 'Provisioning a dedicated Google identity for this connection…',
        })
      }

      const connection = await createConnection({
        system,
        display_name: trimmedName,
        owner_email: null,
      })
      setCreatedConnection(connection)

      if (isGoogleSheets) {
        const sa =
          typeof connection.metadata?.service_account_email === 'string'
            ? connection.metadata.service_account_email
            : null
        actionToast.success({
          title: 'Sheets service account ready',
          description: sa
            ? `Share target: ${sa}`
            : 'Dedicated service account created for this connection.',
        })
      }

      setConfirmSheetsOpen(false)
      setPhase('success')
      onCreated?.(connection)
    } catch (err) {
      setConfirmSheetsOpen(false)
      const message = actionToast.safeErrorMessage(err, 'Could not create connection')
      setError(message)
      actionToast.error({
        title: isGoogleSheets ? 'Could not create Sheets connection' : 'Could not create connection',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            if (isGoogleSheets) setConfirmSheetsOpen(true)
            else void runCreate(trimmedName)
          },
        },
      })
    } finally {
      setSubmitting(false)
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmedName = validateForm()
    if (!trimmedName) return
    if (isGoogleSheets) {
      setConfirmSheetsOpen(true)
      return
    }
    void runCreate(trimmedName)
  }

  function handleDone() {
    if (createdConnection) onCreated?.(createdConnection)
    handleOpenChange(false)
  }

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-lg" onOpenAutoFocus={(event) => event.preventDefault()}>
          {phase === 'form' ? (
            <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
              <DialogHeader>
                <DialogTitle>New connection</DialogTitle>
                <DialogDescription>
                  Register an integration connection. Owner access comes from vertical assignment on
                  the Verticals tab — not invite links.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-3">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-ink-soft">System</span>
                  <select
                    className={`${fieldClass} text-xs`}
                    value={system}
                    onChange={(event) => setSystem(event.target.value as IntegrationSystemId)}
                  >
                    {systems.map((entry) => (
                      <option key={entry.system_id} value={entry.system_id}>
                        {entry.display_label}
                        {isUploadOnlySystem(entry.system_id) ? ' (upload only)' : ''}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-ink-soft">Display name</span>
                  <input
                    type="text"
                    className={fieldClass}
                    placeholder="Production Axios HQ"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    autoComplete="off"
                  />
                </label>

                {uploadOnly ? (
                  <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                    Upload-only — registers the connection without owner credentials. After create,
                    assign the owner on the Verticals tab.
                  </div>
                ) : (
                  <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                    After create, open the <span className="font-medium text-ink">Verticals</span>{' '}
                    tab and assign an owner to the vertical that includes this system. They complete
                    setup from Connectors after login.
                  </div>
                )}

                {isGoogleSheets ? (
                  <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                    Creating this connection provisions a{' '}
                    <span className="font-medium text-ink">dedicated Google service account</span>{' '}
                    for sheet sharing. You’ll confirm before anything is created.
                  </div>
                ) : null}
              </div>

              {submitting && !isGoogleSheets ? (
                <div
                  className="flex items-center gap-3 rounded-md border border-line bg-canvas px-3 py-3"
                  role="status"
                  aria-live="polite"
                >
                  <span
                    className="inline-block size-5 shrink-0 animate-spin rounded-full border-2 border-habeas-navy/20 border-t-habeas-navy"
                    aria-hidden
                  />
                  <div className="min-w-0 text-xs">
                    <p className="font-medium text-ink">Creating connection…</p>
                    <p className="text-ink-soft">Keep this tab open.</p>
                  </div>
                </div>
              ) : null}

              {error ? (
                <p className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800">
                  {error}
                </p>
              ) : null}

              <DialogFooter>
                <Button
                  type="button"
                  variant="outline"
                  disabled={submitting}
                  onClick={() => handleOpenChange(false)}
                >
                  Cancel
                </Button>
                <Button type="submit" disabled={submitting}>
                  {submitting ? 'Creating…' : 'Create connection'}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="space-y-4">
              <DialogHeader>
                <DialogTitle>Connection created</DialogTitle>
                <DialogDescription>
                  {uploadOnly
                    ? 'Upload-only connection registered.'
                    : isGoogleSheets
                      ? 'Dedicated service account is ready.'
                      : 'Next step: assign an owner on the Verticals tab.'}
                </DialogDescription>
              </DialogHeader>

              {isGoogleSheets &&
              typeof createdConnection?.metadata?.service_account_email === 'string' ? (
                <div className="space-y-1 rounded-md border border-line bg-canvas p-3 text-xs text-ink-soft">
                  <p className="font-medium text-ink">Share this service account as Editor</p>
                  <p className="break-all font-mono text-ink">
                    {createdConnection.metadata.service_account_email}
                  </p>
                  <p>The assigned owner will see this address in the connector wizard.</p>
                </div>
              ) : null}

              <div className="space-y-2 rounded-md border border-line bg-canvas p-3 text-xs text-ink-soft">
                <p>
                  <span className="font-medium text-ink">{createdConnection?.display_name}</span>{' '}
                  is registered and waiting for owner setup.
                </p>
                <p>{verticalAssignmentCopy(system)}</p>
              </div>

              <DialogFooter>
                <Button type="button" onClick={handleDone}>
                  Done
                </Button>
              </DialogFooter>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmActionDialog
        open={confirmSheetsOpen}
        onOpenChange={(next) => {
          if (submitting) return
          setConfirmSheetsOpen(next)
        }}
        title="Create Google Sheets connection?"
        description="We’ll create a dedicated Google service account for this connection. After create, assign the owner on the Verticals tab — they share the spreadsheet with that account as Editor in the connector wizard."
        confirmLabel="Yes, create connection"
        cancelLabel="Cancel"
        confirming={submitting}
        confirmingTitle="Creating dedicated service account…"
        confirmingDescription="Provisioning Google identity and saving the connection. Keep this tab open."
        onConfirm={() => {
          const trimmedName = validateForm()
          if (!trimmedName) {
            setConfirmSheetsOpen(false)
            return
          }
          void runCreate(trimmedName)
        }}
      />
    </>
  )
}
