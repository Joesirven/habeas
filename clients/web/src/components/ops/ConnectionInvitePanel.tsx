import { useEffect, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmActionDialog } from '@/components/ui/dialog'
import {
  connectTestFailureMessage,
  connectTestSuccessDescription,
  deleteConnection,
  forceConnectionMode,
  overrideConnectionCadence,
  resetConnectionWizard,
  testConnection,
  type ConnectionRecord,
  type IntegrationSystemId,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { clearOwnerQuickStartTourState, tourUserIdFromEmail } from '@/lib/quick-start-tour'
import {
  connectionDisplayStatusLabel,
  connectionDisplayStatusVariant,
  isUploadOnlySystem,
  leverTriageCopy,
  resolveConnectionChipStatus,
} from '@/lib/connection-display'

const fieldClass =
  'w-full rounded-md border border-line bg-paper px-2.5 py-1.5 text-sm text-ink'

export type ConnectionInvitePanelProps = {
  connectionId: string
  system?: IntegrationSystemId
  displayName?: string
  ownerEmail?: string
  status?: ConnectionRecord['status']
  displayStatus?: ConnectionRecord['display_status']
  gateCode?: string | null
  gateAllowed?: boolean | null
  metadata?: Record<string, unknown>
  lastTestOk?: boolean | null
  lastTestDetail?: string | null
  lastTestedAt?: string | null
  onDone?: () => void
  onUpdated?: () => void
  onDeleted?: () => void
}

function formatLastTestLine(
  lastTestedAt: string | null | undefined,
  lastTestOk: boolean | null | undefined,
  lastTestDetail: string | null | undefined,
): string {
  if (!lastTestedAt) return 'Not tested yet'
  const when = new Date(lastTestedAt).toLocaleString()
  if (lastTestOk === true) return `Last test ${when} · passed`
  if (lastTestOk === false) {
    return `Last test ${when} · failed — ${connectTestFailureMessage(lastTestDetail)}`
  }
  return `Last test ${when}`
}

function readActiveMode(metadata: Record<string, unknown> | undefined): 'live' | 'upload' | null {
  const raw = metadata?.active_mode
  if (raw === 'live' || raw === 'upload') return raw
  return null
}

function readCadenceOverride(metadata: Record<string, unknown> | undefined): number | null {
  const raw = metadata?.cadence_days_override
  if (typeof raw === 'number' && Number.isFinite(raw) && raw > 0) return Math.floor(raw)
  if (typeof raw === 'string' && raw.trim()) {
    const parsed = Number.parseInt(raw, 10)
    if (Number.isFinite(parsed) && parsed > 0) return parsed
  }
  return null
}

export function ConnectionInvitePanel({
  connectionId,
  system,
  displayName,
  ownerEmail,
  status,
  displayStatus,
  gateCode,
  gateAllowed,
  metadata,
  lastTestOk,
  lastTestDetail,
  lastTestedAt,
  onDone,
  onUpdated,
  onDeleted,
}: ConnectionInvitePanelProps) {
  const uploadOnly = isUploadOnlySystem(system)
  const canRetest = system != null && system !== 'cassandra' && !uploadOnly
  const isCassandra = system === 'cassandra'
  const [testing, setTesting] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [forcingMode, setForcingMode] = useState(false)
  const [savingCadence, setSavingCadence] = useState(false)
  const [resettingWizard, setResettingWizard] = useState(false)
  const [confirmTestOpen, setConfirmTestOpen] = useState(false)
  const [confirmDeleteOpen, setConfirmDeleteOpen] = useState(false)
  const [confirmResetOpen, setConfirmResetOpen] = useState(false)
  const [cadenceInput, setCadenceInput] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [localLastTestOk, setLocalLastTestOk] = useState(lastTestOk)
  const [localLastTestDetail, setLocalLastTestDetail] = useState(lastTestDetail)
  const [localLastTestedAt, setLocalLastTestedAt] = useState(lastTestedAt)

  const chipStatus = resolveConnectionChipStatus({
    status: status ?? 'pending',
    display_status: displayStatus,
  })
  const activeMode = readActiveMode(metadata)
  const cadenceOverride = readCadenceOverride(metadata)
  const triageCopy = leverTriageCopy(localLastTestDetail)

  useEffect(() => {
    setLocalLastTestOk(lastTestOk)
    setLocalLastTestDetail(lastTestDetail)
    setLocalLastTestedAt(lastTestedAt)
  }, [lastTestOk, lastTestDetail, lastTestedAt])

  useEffect(() => {
    setCadenceInput(cadenceOverride != null ? String(cadenceOverride) : '')
  }, [cadenceOverride, connectionId])

  async function handleDelete() {
    setDeleting(true)
    setError(null)
    try {
      await deleteConnection(connectionId)
      setConfirmDeleteOpen(false)
      actionToast.success({
        title: 'Connection deleted',
        description: 'The connection record was removed.',
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

  async function handleForceMode(mode: 'live' | 'upload') {
    setForcingMode(true)
    setError(null)
    try {
      await forceConnectionMode(connectionId, { mode })
      actionToast.success({
        title: mode === 'live' ? 'Forced Live mode' : 'Forced Upload mode',
        description: 'Active mode updated for this connection.',
      })
      onUpdated?.()
    } catch (err) {
      const message = actionToast.safeErrorMessage(err, 'Could not force mode')
      setError(message)
      actionToast.error({
        title: 'Could not force mode',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            void handleForceMode(mode)
          },
        },
      })
    } finally {
      setForcingMode(false)
    }
  }

  async function handleSaveCadence(days: number | null) {
    setSavingCadence(true)
    setError(null)
    try {
      await overrideConnectionCadence(connectionId, { cadence_days_override: days })
      actionToast.success({
        title: days == null ? 'Cadence override cleared' : 'Cadence override saved',
        description:
          days == null
            ? 'Owner cadence will apply again.'
            : `Upload freshness now uses ${days} day${days === 1 ? '' : 's'}.`,
      })
      onUpdated?.()
    } catch (err) {
      const message = actionToast.safeErrorMessage(err, 'Could not update cadence')
      setError(message)
      actionToast.error({
        title: 'Could not update cadence',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            void handleSaveCadence(days)
          },
        },
      })
    } finally {
      setSavingCadence(false)
    }
  }

  async function handleResetWizard() {
    setResettingWizard(true)
    setError(null)
    try {
      await resetConnectionWizard(connectionId)
      const ownerUserId = tourUserIdFromEmail(ownerEmail)
      if (ownerUserId) {
        clearOwnerQuickStartTourState(ownerUserId)
      }
      setConfirmResetOpen(false)
      actionToast.success({
        title: 'Wizard reset',
        description: 'The owner must complete setup again before matching is eligible.',
      })
      onUpdated?.()
    } catch (err) {
      const message = actionToast.safeErrorMessage(err, 'Could not reset wizard')
      setError(message)
      actionToast.error({
        title: 'Could not reset wizard',
        description: message,
        action: {
          label: 'Retry',
          onClick: () => {
            void handleResetWizard()
          },
        },
      })
    } finally {
      setResettingWizard(false)
    }
  }

  const busy = testing || deleting || forcingMode || savingCadence || resettingWizard

  const statusBlock = (
    <div className="space-y-2 rounded-md border border-line bg-canvas px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={connectionDisplayStatusVariant(chipStatus)}>
          {connectionDisplayStatusLabel(chipStatus)}
        </Badge>
        {gateAllowed === false ? (
          <Badge variant="fail">Matching gated</Badge>
        ) : null}
        {gateCode ? (
          <span className="font-mono text-[0.65rem] text-mute">{gateCode}</span>
        ) : null}
        {localLastTestOk === true ? (
          <Badge variant="ok">Last test ok</Badge>
        ) : localLastTestOk === false ? (
          <Badge variant="fail">Last test failed</Badge>
        ) : null}
      </div>
      <p className="text-xs text-ink-soft">
        {formatLastTestLine(localLastTestedAt, localLastTestOk, localLastTestDetail)}
      </p>
      {triageCopy ? (
        <p className="rounded-md border border-amber-200 bg-amber-50 px-2.5 py-2 text-xs text-amber-950">
          {triageCopy}
        </p>
      ) : null}
    </div>
  )

  const adminControls = !isCassandra ? (
    <div className="space-y-3 border-t border-line pt-3">
      <p className="text-xs font-medium text-ink">Super admin controls</p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-ink-soft">
          Mode{activeMode ? `: ${activeMode}` : ' (unset)'}
        </span>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || uploadOnly}
          onClick={() => void handleForceMode('live')}
        >
          Force Live
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => void handleForceMode('upload')}
        >
          Force Upload
        </Button>
      </div>
      {uploadOnly ? (
        <p className="text-xs text-mute">Live mode is not available for upload-only systems.</p>
      ) : null}
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-[8rem] flex-col gap-1">
          <span className="text-xs text-ink-soft">Cadence override (days)</span>
          <input
            type="number"
            min={1}
            className={`${fieldClass} text-xs`}
            value={cadenceInput}
            onChange={(event) => setCadenceInput(event.target.value)}
            placeholder="e.g. 30"
            disabled={busy}
          />
        </label>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy}
          onClick={() => {
            const trimmed = cadenceInput.trim()
            if (!trimmed) {
              setError('Enter a positive day count, or Clear override.')
              return
            }
            const days = Number.parseInt(trimmed, 10)
            if (!Number.isFinite(days) || days < 1) {
              setError('Cadence override must be a positive number of days.')
              return
            }
            void handleSaveCadence(days)
          }}
        >
          Save override
        </Button>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={busy || cadenceOverride == null}
          onClick={() => void handleSaveCadence(null)}
        >
          Clear override
        </Button>
      </div>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={busy}
        onClick={() => setConfirmResetOpen(true)}
      >
        Reset owner wizard
      </Button>
    </div>
  ) : null

  const deleteConfirmDialog = (
    <ConfirmActionDialog
      open={confirmDeleteOpen}
      onOpenChange={(open) => {
        if (deleting) return
        setConfirmDeleteOpen(open)
      }}
      title="Delete this connection?"
      description="This permanently removes the connection. Stored credentials in Secret Manager are not deleted in this version."
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

  const resetConfirmDialog = (
    <ConfirmActionDialog
      open={confirmResetOpen}
      onOpenChange={(open) => {
        if (resettingWizard) return
        setConfirmResetOpen(open)
      }}
      title="Reset owner wizard?"
      description="The owner must complete setup again before matching is eligible, even if credentials still authenticate."
      confirmLabel="Reset wizard"
      cancelLabel="Cancel"
      tone="destructive"
      confirming={resettingWizard}
      confirmingTitle="Resetting…"
      confirmingDescription="Clearing wizard completion."
      onConfirm={() => {
        void handleResetWizard()
      }}
    />
  )

  if (isCassandra) {
    return (
      <div className="space-y-3 text-sm">
        {statusBlock}
        <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
          Cassandra connectivity is handled by Habeas Infrastructure (INF). No owner onboarding
          flow — ops marks the connection{' '}
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
      {uploadOnly ? (
        <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
          Upload-only system — owners refresh via the vertical connector upload wizard after a super
          admin assigns them a vertical.
        </div>
      ) : (
        <div className="rounded-md border border-line bg-canvas px-3 py-2 text-xs text-ink-soft">
          Owners complete Live credential setup from <span className="font-medium text-ink">Connectors</span>{' '}
          after a super admin assigns them a vertical. Use the Verticals tab to manage assignments —
          one-off invite links are no longer used.
        </div>
      )}

      {(status != null || displayStatus != null || localLastTestedAt != null) && statusBlock}

      {error ? (
        <p
          className="rounded-md border border-red-200 bg-red-50 px-2.5 py-2 text-xs text-red-800"
          role="alert"
        >
          {error}
        </p>
      ) : null}

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

      {adminControls}

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
      {resetConfirmDialog}
    </div>
  )
}
