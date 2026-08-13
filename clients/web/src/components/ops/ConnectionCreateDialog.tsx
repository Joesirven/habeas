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
  createConnectionInvite,
  getConnectionSystems,
  listConnectionOwnerCandidates,
  type ConnectionInviteCreateResponse,
  type ConnectionOwnerCandidate,
  type ConnectionRecord,
  type ConnectionSystemsPayload,
  type IntegrationSystemId,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { useAuth } from '@/lib/auth'
import {
  connectionInviteAllowed,
  isCreatableConnectionSystem,
  isUploadOnlySystem,
} from '@/lib/connection-display'
import { absoluteInviteUrl, firstNameFromEmail } from '@/lib/utils'

type ConnectionSystemOption = ConnectionSystemsPayload['systems'][number]

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

const FALLBACK_SYSTEMS: ConnectionSystemOption[] = [
  { system_id: 'mailchimp', display_label: 'Mailchimp', invite_allowed: true, credential_fields: [], trust_copy: '' },
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
  { system_id: 'cassandra', display_label: 'Cassandra', invite_allowed: false, credential_fields: [], trust_copy: '' },
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

function buildInviteMailto(
  inviteUrl: string,
  displayName: string,
  ownerEmail: string,
  fromFirstName: string,
): string {
  const ownerFirst = firstNameFromEmail(ownerEmail)
  const subject = encodeURIComponent(`Habeas connection setup — ${displayName}`)
  const body = encodeURIComponent(
    [
      `Hi, ${ownerFirst},`,
      '',
      `Please use this secure link to submit integration credentials for "${displayName}":`,
      '',
      inviteUrl,
      '',
      'This link expires in 72 hours and works only once.',
      'Do not share credentials by email or chat — use the link only.',
      '',
      'Thank you,',
      fromFirstName,
    ].join('\n'),
  )
  return `mailto:${encodeURIComponent(ownerEmail)}?subject=${subject}&body=${body}`
}

export function ConnectionCreateDialog({
  open,
  onOpenChange,
  onCreated,
}: ConnectionCreateDialogProps) {
  const { me } = useAuth()
  const [systems, setSystems] = useState<ConnectionSystemOption[]>(
    creatableSystems(FALLBACK_SYSTEMS),
  )
  const [owners, setOwners] = useState<ConnectionOwnerCandidate[]>([])
  const [ownersError, setOwnersError] = useState<string | null>(null)
  const [system, setSystem] = useState<IntegrationSystemId>('mailchimp')
  const [displayName, setDisplayName] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [phase, setPhase] = useState<DialogPhase>('form')
  const [submitting, setSubmitting] = useState(false)
  const [confirmSheetsOpen, setConfirmSheetsOpen] = useState(false)
  const [provisionPhase, setProvisionPhase] = useState<'idle' | 'account' | 'connection' | 'invite'>(
    'idle',
  )
  const [error, setError] = useState<string | null>(null)
  const [createdConnection, setCreatedConnection] = useState<ConnectionRecord | null>(null)
  const [invite, setInvite] = useState<ConnectionInviteCreateResponse | null>(null)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  const selectedSystem = systems.find((entry) => entry.system_id === system)
  const isCassandra = system === 'cassandra'
  const isGoogleSheets = system === 'google_sheets'
  const uploadOnly = isUploadOnlySystem(system)
  // Omit empty credential_fields from fallbacks — upload-only / invite_allowed cover gating.
  const inviteAllowed = connectionInviteAllowed({
    system,
    inviteAllowed: selectedSystem?.invite_allowed,
    credentialFieldCount:
      selectedSystem != null && selectedSystem.credential_fields.length > 0
        ? selectedSystem.credential_fields.length
        : null,
  })

  function resetForm() {
    setSystem('mailchimp')
    setDisplayName('')
    setOwnerEmail('')
    setPhase('form')
    setSubmitting(false)
    setConfirmSheetsOpen(false)
    setProvisionPhase('idle')
    setError(null)
    setCreatedConnection(null)
    setInvite(null)
    setCopyNote(null)
    setOwnersError(null)
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
            : (next[0]?.system_id ?? 'mailchimp'),
        )
      })
      .catch(() => {
        if (!cancelled) setSystems(creatableSystems(FALLBACK_SYSTEMS))
      })

    void listConnectionOwnerCandidates()
      .then((payload) => {
        if (!cancelled) {
          setOwners(payload.owners)
          setOwnersError(null)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setOwners([])
          setOwnersError('Could not load allowlisted owners.')
        }
      })

    return () => {
      cancelled = true
    }
  }, [open])

  function handleOpenChange(next: boolean) {
    if (!next && submitting) return
    onOpenChange(next)
  }

  async function mintInvite(connectionId: string, owner?: string) {
    const trimmed = (owner ?? ownerEmail).trim()
    const inviteResponse = await createConnectionInvite(
      connectionId,
      trimmed ? { owner_email: trimmed } : {},
    )
    setInvite(inviteResponse)
    // Success UI is the dialog success phase (invite URL) — no toast (avoids dual chrome).
  }

  function validateForm(): { name: string; owner: string } | null {
    const trimmedName = displayName.trim()
    if (!trimmedName) {
      setError('Display name is required.')
      return null
    }
    const trimmedOwner = ownerEmail.trim()
    if (inviteAllowed && !trimmedOwner) {
      setError('Owner email is required for invite-based systems.')
      return null
    }
    setError(null)
    return { name: trimmedName, owner: trimmedOwner }
  }

  async function runCreate(trimmedName: string, trimmedOwner: string) {
    setSubmitting(true)
    setError(null)
    try {
      if (isGoogleSheets) {
        setProvisionPhase('account')
        actionToast.info({
          title: 'Creating Sheets service account',
          description: 'Provisioning a dedicated Google identity for this connection…',
        })
      } else {
        setProvisionPhase('connection')
      }

      const connection = await createConnection({
        system,
        display_name: trimmedName,
        owner_email: inviteAllowed ? trimmedOwner : null,
      })
      setCreatedConnection(connection)
      setProvisionPhase(inviteAllowed && trimmedOwner ? 'invite' : 'idle')

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

      if (inviteAllowed && trimmedOwner) {
        try {
          await mintInvite(connection.id, trimmedOwner)
        } catch (inviteErr) {
          actionToast.error({
            title: 'Could not create invite',
            description: actionToast.safeErrorMessage(
              inviteErr,
              'Connection was saved, but the invite link could not be created.',
            ),
            action: {
              label: 'Retry',
              onClick: () => {
                void mintInvite(connection.id, trimmedOwner)
                  .then(() => {
                    actionToast.success({
                      title: 'Invite link ready',
                      description: 'Copy it from the connection dialog.',
                    })
                  })
                  .catch((retryErr) => {
                    actionToast.error({
                      title: 'Could not create invite',
                      description: actionToast.safeErrorMessage(
                        retryErr,
                        'Invite link could not be created. Open the connection row and try again.',
                      ),
                    })
                  })
              },
            },
          })
        }
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
            else void runCreate(trimmedName, trimmedOwner)
          },
        },
      })
    } finally {
      setSubmitting(false)
      setProvisionPhase('idle')
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const valid = validateForm()
    if (!valid) return
    if (isGoogleSheets) {
      setConfirmSheetsOpen(true)
      return
    }
    void runCreate(valid.name, valid.owner)
  }

  function copyInviteUrl() {
    if (!invite?.invite_url) return
    void navigator.clipboard.writeText(absoluteInviteUrl(invite.invite_url)).then(() => {
      setCopyNote('Copied link')
      window.setTimeout(() => setCopyNote(null), 2000)
    })
  }

  function handleDone() {
    if (createdConnection) onCreated?.(createdConnection)
    handleOpenChange(false)
  }

  const shareUrl = invite?.invite_url ? absoluteInviteUrl(invite.invite_url) : null

  const mailtoHref =
    shareUrl && invite?.owner_email
      ? buildInviteMailto(
          shareUrl,
          createdConnection?.display_name ?? displayName,
          invite.owner_email,
          firstNameFromEmail(me?.email),
        )
      : null

  return (
    <>
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent className="max-w-lg" onOpenAutoFocus={(event) => event.preventDefault()}>
          {phase === 'form' ? (
            <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
              <DialogHeader>
                <DialogTitle>New connection</DialogTitle>
                <DialogDescription>
                  Register an integration connection. SaaS systems use a one-time owner invite;
                  upload-only systems create without an invite; Cassandra is provisioned by
                  Infrastructure.
                </DialogDescription>
              </DialogHeader>

              <div className="space-y-3">
                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-ink-soft">System</span>
                  <select
                    className={`${fieldClass} text-xs`}
                    value={system}
                    onChange={(event) => {
                      const next = event.target.value as IntegrationSystemId
                      setSystem(next)
                      if (next === 'cassandra' || isUploadOnlySystem(next)) setOwnerEmail('')
                    }}
                  >
                    {systems.map((entry) => (
                      <option key={entry.system_id} value={entry.system_id}>
                        {entry.display_label}
                        {isUploadOnlySystem(entry.system_id) ? ' (upload only)' : ''}
                        {entry.system_id === 'cassandra' ? ' (infra)' : ''}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="flex flex-col gap-1">
                  <span className="text-xs font-medium text-ink-soft">Display name</span>
                  <input
                    type="text"
                    className={fieldClass}
                    placeholder="Production Mailchimp"
                    value={displayName}
                    onChange={(event) => setDisplayName(event.target.value)}
                    autoComplete="off"
                  />
                </label>

                {inviteAllowed ? (
                  <label className="flex flex-col gap-1">
                    <span className="text-xs font-medium text-ink-soft">Owner email</span>
                    <select
                      className={`${fieldClass} text-xs`}
                      value={ownerEmail}
                      onChange={(event) => setOwnerEmail(event.target.value)}
                      disabled={owners.length === 0}
                    >
                      <option value="">
                        {owners.length === 0 ? 'No allowlisted owners' : 'Select an owner…'}
                      </option>
                      {owners.map((owner) => (
                        <option key={owner.email} value={owner.email}>
                          {owner.email} ({owner.role.replaceAll('_', ' ')})
                        </option>
                      ))}
                    </select>
                    <span className="text-xs text-mute">
                      Only Habeas operators already on a role allowlist (super admin, admin, legal,
                      or data owner).
                    </span>
                    {ownersError ? (
                      <span className="text-xs text-red-700">{ownersError}</span>
                    ) : null}
                  </label>
                ) : uploadOnly ? (
                  <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                    Upload-only — creates the connection without minting an invite. Owners refresh
                    data via the vertical connector upload wizard.
                  </div>
                ) : (
                  <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                    Cassandra connectivity is handled by Habeas Infrastructure (INF). No owner
                    invite is sent — ops marks the connection{' '}
                    <span className="font-medium text-ink">infra_pending</span> until INF confirms
                    TLS, service accounts, and egress are live. Credentials are stored only in
                    Google Cloud Secret Manager once setup completes.
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
                    <p className="font-medium text-ink">
                      {provisionPhase === 'invite'
                        ? 'Creating invite link…'
                        : 'Creating connection…'}
                    </p>
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
                  {submitting
                    ? 'Creating…'
                    : isCassandra || uploadOnly || isGoogleSheets
                      ? 'Create connection'
                      : 'Create & invite'}
                </Button>
              </DialogFooter>
            </form>
          ) : (
            <div className="space-y-4">
              <DialogHeader>
                <DialogTitle>Connection created</DialogTitle>
                <DialogDescription>
                  {isCassandra
                    ? 'Infrastructure handoff — no owner invite.'
                    : uploadOnly
                      ? 'Upload-only connection registered — no invite minted.'
                      : isGoogleSheets
                        ? 'Dedicated service account is ready. Share the invite link with the owner.'
                        : 'Share the invite link with the owner. It is shown only once.'}
                </DialogDescription>
              </DialogHeader>

              {isGoogleSheets &&
              typeof createdConnection?.metadata?.service_account_email === 'string' ? (
                <div className="space-y-1 rounded-md border border-line bg-canvas p-3 text-xs text-ink-soft">
                  <p className="font-medium text-ink">Share this service account as Editor</p>
                  <p className="break-all font-mono text-ink">
                    {createdConnection.metadata.service_account_email}
                  </p>
                  <p>The owner will see this same address in the invite steps.</p>
                </div>
              ) : null}

              {isCassandra ? (
                <div className="space-y-2 rounded-md border border-line bg-canvas p-3 text-xs text-ink-soft">
                  <p>
                    <span className="font-medium text-ink">{createdConnection?.display_name}</span>{' '}
                    is registered as Cassandra with status{' '}
                    <span className="font-medium text-ink">infra_pending</span>.
                  </p>
                  <p>
                    Open an INF ticket for TLS certificates, service account credentials, and egress
                    allowlisting. Habeas does not collect secrets on this path.
                  </p>
                </div>
              ) : uploadOnly ? (
                <div className="space-y-2 rounded-md border border-line bg-canvas p-3 text-xs text-ink-soft">
                  <p>
                    <span className="font-medium text-ink">{createdConnection?.display_name}</span>{' '}
                    is ready for owner upload refresh via the vertical connector wizard.
                  </p>
                  <p>Assign the owner on the Verticals tab if they are not already mapped.</p>
                </div>
              ) : invite ? (
                <div className="space-y-2 rounded-md border border-line bg-canvas p-3">
                  <p className="text-xs text-ink-soft">
                    Send to <span className="font-mono text-ink">{invite.owner_email}</span>. Link
                    expires in 72 hours, works once, and stores credentials in Secret Manager only.
                  </p>
                  <input
                    type="text"
                    readOnly
                    className={`${fieldClass} font-mono text-xs`}
                    value={shareUrl ?? ''}
                    aria-label="Invite URL"
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" size="sm" onClick={copyInviteUrl}>
                      Copy link
                    </Button>
                    {mailtoHref ? (
                      <Button type="button" size="sm" variant="outline" asChild>
                        <a href={mailtoHref}>Email owner</a>
                      </Button>
                    ) : null}
                  </div>
                  {copyNote ? <p className="text-xs text-mute">{copyNote}</p> : null}
                </div>
              ) : (
                <p className="text-xs text-ink-soft">
                  Connection saved. Use the invite panel on the connection row to mint a link later.
                </p>
              )}

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
        description="We’ll create a dedicated Google service account for this connection, then mint the owner invite. The owner must share the spreadsheet with that account as Editor."
        confirmLabel="Yes, create connection"
        cancelLabel="Cancel"
        confirming={submitting}
        confirmingTitle={
          provisionPhase === 'invite'
            ? 'Creating invite link…'
            : 'Creating dedicated service account…'
        }
        confirmingDescription="Provisioning Google identity and saving the connection. Keep this tab open."
        onConfirm={() => {
          const valid = validateForm()
          if (!valid) {
            setConfirmSheetsOpen(false)
            return
          }
          void runCreate(valid.name, valid.owner)
        }}
      />
    </>
  )
}
