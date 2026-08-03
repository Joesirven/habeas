import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  createConnectionInvite,
  revokeConnectionInvite,
  type ConnectionInviteCreateResponse,
  type IntegrationSystemId,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { absoluteInviteUrl } from '@/lib/utils'

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

export type ConnectionInvitePanelProps = {
  connectionId: string
  system?: IntegrationSystemId
  ownerEmail?: string
  onDone?: () => void
}

function buildInviteMailto(
  inviteUrl: string,
  ownerEmail: string | undefined,
): string {
  const subject = encodeURIComponent('Habeas connection setup')
  const body = encodeURIComponent(
    [
      'Hi,',
      '',
      'Please use this secure link to submit integration credentials for Habeas privacy automation:',
      '',
      inviteUrl,
      '',
      'This link expires in 72 hours and works only once.',
      'Do not share credentials by email or chat — use the link only.',
      '',
      'Thank you',
    ].join('\n'),
  )
  const to = ownerEmail?.trim() ? encodeURIComponent(ownerEmail.trim()) : ''
  return `mailto:${to}?subject=${subject}&body=${body}`
}

export function ConnectionInvitePanel({
  connectionId,
  system,
  ownerEmail,
  onDone,
}: ConnectionInvitePanelProps) {
  const inviteAllowed = system !== 'cassandra'
  const [invite, setInvite] = useState<ConnectionInviteCreateResponse | null>(null)
  const [minting, setMinting] = useState(false)
  const [revoking, setRevoking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copyNote, setCopyNote] = useState<string | null>(null)

  async function handleMint() {
    setMinting(true)
    setError(null)
    try {
      const trimmedOwner = ownerEmail?.trim()
      const response = await createConnectionInvite(
        connectionId,
        trimmedOwner ? { owner_email: trimmedOwner } : {},
      )
      setInvite(response)
    } catch (err) {
      setError(actionToast.safeErrorMessage(err, 'Could not create invite'))
    } finally {
      setMinting(false)
    }
  }

  async function handleRevoke() {
    if (!invite) return
    setRevoking(true)
    setError(null)
    try {
      await revokeConnectionInvite(connectionId, invite.invite_id)
      setInvite(null)
    } catch (err) {
      setError(actionToast.safeErrorMessage(err, 'Could not revoke invite'))
    } finally {
      setRevoking(false)
    }
  }

  function copyInviteUrl() {
    if (!invite?.invite_url) return
    void navigator.clipboard.writeText(absoluteInviteUrl(invite.invite_url)).then(() => {
      setCopyNote('Copied link')
      window.setTimeout(() => setCopyNote(null), 2000)
    })
  }

  const shareUrl = invite?.invite_url ? absoluteInviteUrl(invite.invite_url) : null

  const mailtoHref =
    shareUrl != null
      ? buildInviteMailto(shareUrl, invite?.owner_email ?? ownerEmail)
      : null

  if (!inviteAllowed) {
    return (
      <div className="space-y-3 text-sm">
        <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
          Cassandra connectivity is handled by Habeas Infrastructure (INF). No owner invite is
          sent — ops marks the connection{' '}
          <span className="font-medium text-ink">infra_pending</span> until INF confirms TLS,
          service accounts, and egress are live. Credentials are stored only in Google Cloud Secret
          Manager once setup completes.
        </div>
        {onDone ? (
          <div className="flex justify-end pt-1">
            <Button type="button" size="sm" variant="outline" onClick={onDone}>
              Done
            </Button>
          </div>
        ) : null}
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-ink-soft">
        Owner invite links expire in 72 hours, work once, and send credentials directly to Google
        Cloud Secret Manager — never through email or chat.
      </p>

      {error ? (
        <p className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800">
          {error}
        </p>
      ) : null}

      {invite ? (
        <div className="space-y-2 rounded-md border border-line bg-canvas p-3">
          <p className="text-xs text-ink-soft">
            Send this link to{' '}
            <span className="font-mono text-ink">{invite.owner_email}</span>. It is shown only
            once.
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
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={revoking}
              onClick={() => void handleRevoke()}
            >
              {revoking ? 'Revoking…' : 'Revoke invite'}
            </Button>
          </div>
          {copyNote ? <p className="text-xs text-mute">{copyNote}</p> : null}
        </div>
      ) : (
        <Button type="button" size="sm" disabled={minting} onClick={() => void handleMint()}>
          {minting ? 'Creating link…' : 'Create invite link'}
        </Button>
      )}

      {onDone ? (
        <div className="flex justify-end pt-1">
          <Button type="button" size="sm" variant="outline" onClick={onDone}>
            Done
          </Button>
        </div>
      ) : null}
    </div>
  )
}
