import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import {
  connectTestFailureMessage,
  connectTestSuccessDescription,
  connectTestTriageSummary,
  createConnectionInvite,
  deleteConnection,
  revokeConnectionInvite,
  testConnection,
  type ConnectionInviteCreateResponse,
  type ConnectionRecord,
  type IntegrationSystemId,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { useAuth } from '@/lib/auth'
import { absoluteInviteUrl, firstNameFromEmail } from '@/lib/utils'

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

export type ConnectionInvitePanelProps = {
  connectionId: string
  system?: IntegrationSystemId
  displayName?: string
  ownerEmail?: string
  status?: ConnectionRecord['status']
  lastTestOk?: boolean | null
  lastTestDetail?: string | null
  lastTestedAt?: string | null
  metadata?: Record<string, unknown> | null
  onDone?: () => void
  onUpdated?: () => void
  onDeleted?: () => void
}

function buildInviteMailto(
  inviteUrl: string,
  ownerEmail: string | undefined,
  fromFirstName: string,
): string {
  const ownerFirst = firstNameFromEmail(ownerEmail)
  const subject = encodeURIComponent('Habeas connection setup')
  const body = encodeURIComponent(
    [
      `Hi, ${ownerFirst},`,
      '',
      'Please use this secure link to submit integration credentials for Habeas privacy automation:',
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
  const to = ownerEmail?.trim() ? encodeURIComponent(ownerEmail.trim()) : ''
  return `mailto:${to}?subject=${subject}&body=${body}`
}

function formatLastTestLine(
  lastTestedAt: string | null | undefined,
  lastTestOk: boolean | null | undefined,
  lastTestDetail: string | null | undefined,
  metadata?: Record<string, unknown> | null,
): string {
  if (!lastTestedAt) return 'Not tested yet'
  const when = new Date(lastTestedAt).toLocaleString()
  if (lastTestOk === true) return `Last test ${when} · passed`
  if (lastTestOk === false) {
    return `Last test ${when} · failed — ${connectTestTriageSummary(lastTestDetail, metadata)}`
  }
  return `Last test ${when}`
}

export function ConnectionInvitePanel({
  connectionId,
  system,
  displayName,
  ownerEmail,
  status,
  lastTestOk,
  lastTestDetail,
  lastTestedAt,
  metadata,
  onDone,
  onUpdated,
  onDeleted,
}: ConnectionInvitePanelProps) {
  const { me } = useAuth()
  const inviteAllowed = system !== 'cassandra'
  const canRetest = system != null && system !== 'cassandra'
  const [invite, setInvite] = useState<ConnectionInviteCreateResponse | null>(null)
  const [minting, setMinting] = useState(false)
  const [revoking, setRevoking] = useState(false)
  const [testing, setTesting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmTestOpen, setConfirmTestOpen] = useState(false)
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [localLastTestOk, setLocalLastTestOk] = useState(lastTestOk)
  const [localLastTestDetail, setLocalLastTestDetail] = useState(lastTestDetail)
  const [localLastTestedAt, setLocalLastTestedAt] = useState(lastTestedAt)

  useEffect(() => {
    setLocalLastTestOk(lastTestOk)
    setLocalLastTestDetail(lastTestDetail)
    setLocalLastTestedAt(lastTestedAt)
  }, [lastTestOk, lastTestDetail, lastTestedAt])

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
      actionToast.success({
        title: 'Invite link ready',
        description: 'Copy it once — it is not shown again after you close this dialog.',
      })
      onUpdated?.()
    } catch (err) {
      const message = actionToast.safeErrorMessage(err, 'Could not create invite')
      setError(message)
      actionToast.error({
        title: 'Could not create invite',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            void handleMint()
          },
        },
      })
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
      actionToast.success({ title: 'Invite revoked' })
      onUpdated?.()
    } catch (err) {
      const message = actionToast.safeErrorMessage(err, 'Could not revoke invite')
      setError(message)
      actionToast.error({
        title: 'Could not revoke invite',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            void handleRevoke()
          },
        },
      })
    } finally {
      setRevoking(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    try {
      await deleteConnection(connectionId)
      setConfirmDeleteOpen(false)
      actionToast.success({
        title: 'Connection deleted',
        description: 'Active invites for this connection are no longer valid.',
      })
      onDeleted?.()
    } catch (err) {
      const message = actionToast.safeErrorMessage(err, 'Could not delete connection')
      setError(message)
      actionToast.error({
        title: 'Could not delete connection',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            void handleDelete()
          },
        },
      })
    } finally {
      setDeleting(false)
    }
  }

  async function runRetest() {
    setTesting(true)
    setError(null)
    try {
      const result = await testConnection(connectionId)
      const testedAt = new Date().toISOString()
      setLocalLastTestOk(result.ok)
      setLocalLastTestDetail(result.detail)
      setLocalLastTestedAt(testedAt)
      setConfirmTestOpen(false)
      if (result.ok) {
        actionToast.success({
          title: 'Connection test passed',
          description: connectTestSuccessDescription(
            result.detail,
            displayName ?? system ?? 'connection',
          ),
        })
      } else {
        actionToast.error({
          title: 'Connection test failed',
          description: connectTestFailureMessage(result.detail),
          action: {
            label: 'Retry',
            onClick: () => setConfirmTestOpen(true),
          },
        })
      }
      onUpdated?.()
    } catch (err) {
      setConfirmTestOpen(false)
      const message = actionToast.safeErrorMessage(err, 'Could not run connection test')
      setError(message)
      actionToast.error({
        title: 'Could not run connection test',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
      })
    } finally {
      setTesting(false)
    }
  }

  function copyInviteUrl() {
    if (!invite?.invite_url) return
    const url = absoluteInviteUrl(invite.invite_url)
    void navigator.clipboard.writeText(url).then(() => {
      actionToast.copied('Copied invite link', copyInviteUrl)
    })
  }

  const shareUrl = invite?.invite_url ? absoluteInviteUrl(invite.invite_url) : null

  const mailtoHref =
    shareUrl != null
      ? buildInviteMailto(
          shareUrl,
          invite?.owner_email ?? ownerEmail,
          firstNameFromEmail(me?.email),
        )
      : null

  const busy = minting || revoking || testing || deleting

  const deleteConfirmDialog = (
    <ConfirmActionDialog
      open={confirmDeleteOpen}
      onOpenChange={(open) => {
        if (deleting) return
        setConfirmDeleteOpen(open)
      }}
      title="Delete this connection?"
      description="This permanently removes the connection. Active invite links become invalid immediately. Stored credentials in Secret Manager are not deleted in this version."
      confirmLabel="Delete connection"
      cancelLabel="Cancel"
      tone="destructive"
      confirming={deleting}
      confirmingTitle="Deleting…"
      confirmingDescription="Removing the connection."
      onConfirm={() => {
        void handleDelete()
      }}
    />
  )

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
        {error ? (
          <p
            className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800"
            role="alert"
          >
            {error}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-1">
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={busy}
            onClick={() => setConfirmDeleteOpen(true)}
          >
            Delete connection
          </Button>
          {onDone ? (
            <Button type="button" size="sm" variant="outline" onClick={onDone}>
              Done
            </Button>
          ) : null}
        </div>
        {deleteConfirmDialog}
      </div>
    )
  }

  return (
    <div className="space-y-3 text-sm">
      <p className="text-xs text-ink-soft">
        Owner invite links expire in 72 hours, work once, and send credentials directly to Google
        Cloud Secret Manager — never through email or chat.
      </p>

      {(status != null || localLastTestedAt != null) && (
        <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            {status ? (
              <Badge
                variant={
                  status === 'connected'
                    ? 'ok'
                    : status === 'failed' || status === 'revoked'
                      ? 'fail'
                      : status === 'invited'
                        ? 'run'
                        : 'wait'
                }
              >
                {status.replaceAll('_', ' ')}
              </Badge>
            ) : null}
            {localLastTestOk === true ? (
              <Badge variant="ok">Last test ok</Badge>
            ) : localLastTestOk === false ? (
              <Badge variant="fail">Last test failed</Badge>
            ) : null}
          </div>
          <p className="text-xs text-ink-soft">
            {formatLastTestLine(
              localLastTestedAt,
              localLastTestOk,
              localLastTestDetail,
              metadata,
            )}
          </p>
          {localLastTestOk === false ? (
            <div
              className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-900"
              role="alert"
            >
              <p className="font-medium">Triage</p>
              <p className="mt-0.5">
                {connectTestTriageSummary(localLastTestDetail, metadata)}
              </p>
              <p className="mt-1 text-red-800/80">
                Owner invite stays usable after a failed test — ask them to correct credentials and
                retry, or run Test connection here after they update the secret.
              </p>
            </div>
          ) : null}
        </div>
      )}

      {error ? (
        <p
          className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800"
          role="alert"
        >
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
              disabled={busy}
              onClick={() => void handleRevoke()}
            >
              {revoking ? 'Revoking…' : 'Revoke invite'}
            </Button>
          </div>
        </div>
      ) : (
        <Button type="button" size="sm" disabled={busy} onClick={() => void handleMint()}>
          {minting ? 'Creating link…' : 'Create invite link'}
        </Button>
      )}

      {canRetest ? (
        <div className="flex flex-wrap gap-2 border-t border-line pt-3">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={() => setConfirmTestOpen(true)}
          >
            {testing ? 'Testing…' : 'Test connection'}
          </Button>
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
        <Button
          type="button"
          size="sm"
          variant="destructive"
          disabled={busy}
          onClick={() => setConfirmDeleteOpen(true)}
        >
          Delete connection
        </Button>
        {onDone ? (
          <Button type="button" size="sm" variant="outline" onClick={onDone}>
            Done
          </Button>
        ) : null}
      </div>

      <ConfirmActionDialog
        open={confirmTestOpen}
        onOpenChange={(open) => {
          if (testing) return
          setConfirmTestOpen(open)
        }}
        title="Test this connection?"
        description="Habeas will read the stored secret and verify authentication with the provider. Secret values are never shown here."
        confirmLabel="Yes, test now"
        cancelLabel="Cancel"
        confirming={testing}
        onConfirm={() => {
          void runRetest()
        }}
      />
      {deleteConfirmDialog}
    </div>
  )
}
