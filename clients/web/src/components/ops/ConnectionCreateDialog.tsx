import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
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
import { absoluteInviteUrl, firstNameFromEmail } from '@/lib/utils'

type ConnectionSystemOption = ConnectionSystemsPayload['systems'][number]

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

const FALLBACK_SYSTEMS: ConnectionSystemOption[] = [
  { system_id: 'mailchimp', display_label: 'Mailchimp', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'paylocity', display_label: 'Paylocity', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'lever', display_label: 'Lever', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'auth0', display_label: 'Auth0', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'google_sheets', display_label: 'Google Sheets', invite_allowed: true, credential_fields: [], trust_copy: '' },
  { system_id: 'cassandra', display_label: 'Cassandra', invite_allowed: false, credential_fields: [], trust_copy: '' },
]

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
  const [systems, setSystems] = useState<ConnectionSystemOption[]>(FALLBACK_SYSTEMS)
  const [owners, setOwners] = useState<ConnectionOwnerCandidate[]>([])
  const [ownersError, setOwnersError] = useState<string | null>(null)
  const [system, setSystem] = useState<IntegrationSystemId>('mailchimp')
  const [displayName, setDisplayName] = useState('')
  const [ownerEmail, setOwnerEmail] = useState('')
  const [phase, setPhase] = useState<DialogPhase>('form')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [createdConnection, setCreatedConnection] = useState<ConnectionRecord | null>(null)
  const [invite, setInvite] = useState<ConnectionInviteCreateResponse | null>(null)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  const selectedSystem = systems.find((entry) => entry.system_id === system)
  const isCassandra = system === 'cassandra'
  const inviteAllowed = selectedSystem?.invite_allowed ?? !isCassandra

  function resetForm() {
    setSystem('mailchimp')
    setDisplayName('')
    setOwnerEmail('')
    setPhase('form')
    setSubmitting(false)
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
        if (!cancelled && payload.systems.length > 0) {
          setSystems(payload.systems)
        }
      })
      .catch(() => {
        if (!cancelled) setSystems(FALLBACK_SYSTEMS)
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

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault()
    const trimmedName = displayName.trim()
    if (!trimmedName) {
      setError('Display name is required.')
      return
    }

    const trimmedOwner = ownerEmail.trim()
    if (inviteAllowed && !trimmedOwner) {
      setError('Owner email is required for invite-based systems.')
      return
    }

    setSubmitting(true)
    setError(null)

    try {
      const connection = await createConnection({
        system,
        display_name: trimmedName,
        owner_email: inviteAllowed ? trimmedOwner : null,
      })
      setCreatedConnection(connection)

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
      // Cassandra / infra: dialog success phase is the sole outcome UI (no toast).

      setPhase('success')
      onCreated?.(connection)
    } catch (err) {
      setError(actionToast.safeErrorMessage(err, 'Could not create connection'))
    } finally {
      setSubmitting(false)
    }
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
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-lg" onOpenAutoFocus={(event) => event.preventDefault()}>
        {phase === 'form' ? (
          <form className="space-y-4" onSubmit={(event) => void handleSubmit(event)}>
            <DialogHeader>
              <DialogTitle>New connection</DialogTitle>
              <DialogDescription>
                Register an integration connection. SaaS systems use a one-time owner invite;
                Cassandra is provisioned by Infrastructure.
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
                    if (next === 'cassandra') setOwnerEmail('')
                  }}
                >
                  {systems.map((entry) => (
                    <option key={entry.system_id} value={entry.system_id}>
                      {entry.display_label}
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
              ) : (
                <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
                  Cassandra connectivity is handled by Habeas Infrastructure (INF). No owner
                  invite is sent — ops marks the connection{' '}
                  <span className="font-medium text-ink">infra_pending</span> until INF confirms
                  TLS, service accounts, and egress are live. Credentials are stored only in
                  Google Cloud Secret Manager once setup completes.
                </div>
              )}
            </div>

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
                {submitting ? 'Creating…' : isCassandra ? 'Create connection' : 'Create & invite'}
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
                  : 'Share the invite link with the owner. It is shown only once.'}
              </DialogDescription>
            </DialogHeader>

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
  )
}
