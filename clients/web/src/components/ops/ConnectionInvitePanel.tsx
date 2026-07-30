import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  createConnectionInvite,
  revokeConnectionInvite,
  type ConnectionInviteCreateResponse,
  type IntegrationSystemId,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'

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

  async function handleMint() {
    setMinting(true)
    try {
      const response = await createConnectionInvite(connectionId)
      setInvite(response)
      actionToast.success({
        title: 'Invite link created',
        description: 'Share it with the connection owner.',
      })
    } catch (err) {
      actionToast.error({
        title: 'Could not create invite',
        description: actionToast.safeErrorMessage(err),
        action: {
          label: 'Retry',
          onClick: () => void handleMint(),
        },
      })
    } finally {
      setMinting(false)
    }
  }

  async function handleRevoke() {
    if (!invite) return
    const inviteId = invite.invite_id
    setRevoking(true)
    try {
      await revokeConnectionInvite(connectionId, inviteId)
      setInvite(null)
      actionToast.success({
        title: 'Invite revoked',
        description: 'The link can no longer be used.',
      })
    } catch (err) {
      actionToast.error({
        title: 'Could not revoke invite',
        description: actionToast.safeErrorMessage(err),
        action: {
          label: 'Retry',
          onClick: () => void handleRevoke(),
        },
      })
    } finally {
      setRevoking(false)
    }
  }

  function copyInviteUrl() {
    if (!invite?.invite_url) return
    const url = invite.invite_url
    void navigator.clipboard.writeText(url).then(() => {
      actionToast.copied('Copied invite link', () => navigator.clipboard.writeText(url))
    })
  }

  const mailtoHref =
    invite?.invite_url != null
      ? buildInviteMailto(invite.invite_url, invite.owner_email ?? ownerEmail)
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
            value={invite.invite_url}
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
