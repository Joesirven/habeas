import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  completeOwnerConnectorWizard,
  downloadOwnerUploadTemplate,
  listOwnerConnectorReminders,
  listOwnerConnectors,
  setOwnerConnectorCadence,
  setOwnerConnectorMode,
  uploadOwnerConnectorCsv,
  type ConnectorReminder,
  type OwnerConnectorList,
  type OwnerConnectorSystem,
  type UserRole,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, useAuth } from '@/lib/auth'
import {
  MULTI_PII_DELIMITER_OPTIONS,
  OWNER_WIZARD_STEPS,
  activeModeFromMetadata,
  allowsLive,
  allowsUpload,
  buildReminderBannerItems,
  cadenceDaysFromMetadata,
  delimiterValueFromKey,
  displayStatusChip,
  liveConnectReady,
  ownerWizardStepIndex,
  visibleReminderBanners,
  type OwnerWizardStep,
} from '@/lib/owner-connector-ui'

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

function canAccessOwnerConnectors(role: UserRole) {
  return role === 'data_owner' || role === 'super_admin' || role === 'admin'
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

function WizardProgress({ step }: { step: OwnerWizardStep }) {
  const activeIndex = ownerWizardStepIndex(step)
  return (
    <ol className="mb-4 flex gap-2" aria-label="Connector setup steps">
      {OWNER_WIZARD_STEPS.map((entry, index) => {
        const active = index === activeIndex
        const done = index < activeIndex
        return (
          <li
            key={entry.id}
            className={`flex-1 rounded-md border px-2 py-1.5 text-center text-[11px] font-medium ${
              active
                ? 'border-habeas-navy bg-habeas-navy text-white'
                : done
                  ? 'border-habeas-navy/30 bg-habeas-navy/5 text-habeas-navy'
                  : 'border-line bg-canvas text-mute'
            }`}
          >
            {index + 1}. {entry.label}
          </li>
        )
      })}
    </ol>
  )
}

function DisplayStatusBadge({
  displayStatus,
  gateAllowed,
}: {
  displayStatus: string
  gateAllowed: boolean
}) {
  const chip = displayStatusChip(displayStatus, { gateAllowed })
  return <Badge variant={chip.variant}>{chip.label}</Badge>
}

function ReminderBanners({
  reminders,
  dismissedIds,
  onDismiss,
}: {
  reminders: ConnectorReminder[]
  dismissedIds: ReadonlySet<string>
  onDismiss: (id: string) => void
}) {
  const items = visibleReminderBanners(
    buildReminderBannerItems(reminders),
    dismissedIds,
  )
  if (!items.length) return null

  return (
    <div className="space-y-2" role="region" aria-label="Connector reminders">
      {items.map((item) => (
        <div
          key={item.id}
          className={`flex items-start justify-between gap-3 rounded-md border px-3 py-2.5 text-sm ${
            item.severity === 'overdue'
              ? 'border-red-200 bg-red-50 text-red-900'
              : 'border-amber-200 bg-amber-50 text-amber-950'
          }`}
        >
          <div className="min-w-0 space-y-0.5">
            <p className="font-medium">{item.title}</p>
            <p className="text-xs opacity-90">{item.description}</p>
            <p className="text-[11px] opacity-70">
              {item.system.replaceAll('_', ' ')} · {item.verticalId.replaceAll('_', '/')}
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="shrink-0"
            onClick={() => onDismiss(item.id)}
          >
            Dismiss
          </Button>
        </div>
      ))}
    </div>
  )
}

function ViewOnlyCard({ list }: { list: OwnerConnectorList }) {
  return (
    <div className="rounded-md border border-line bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-ink">{list.display_label}</h3>
          <p className="mt-0.5 text-xs text-mute">
            Already connected — view only. No owner upload or credential wizard.
          </p>
        </div>
        <Badge variant="default">View only</Badge>
      </div>
      <ul className="mt-3 space-y-2">
        {list.connectors.map((connector) => (
          <li
            key={connector.system}
            className="flex flex-wrap items-center justify-between gap-2 rounded border border-line bg-canvas px-3 py-2 text-sm"
          >
            <span className="font-medium text-ink">{connector.display_name}</span>
            <DisplayStatusBadge
              displayStatus={connector.display_status}
              gateAllowed={connector.gate_allowed}
            />
          </li>
        ))}
      </ul>
    </div>
  )
}

function ConnectorWizard({
  verticalId,
  connector,
  onDone,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  onDone: () => void
}) {
  const queryClient = useQueryClient()
  const metaMode = activeModeFromMetadata(connector.metadata)
  const canUpload = allowsUpload(connector.allowed_approaches)
  const canLive = allowsLive(connector.allowed_approaches)

  const initialMode: 'live' | 'upload' | null =
    metaMode ?? (canUpload ? 'upload' : canLive ? 'live' : null)

  const [step, setStep] = useState<OwnerWizardStep>('mode')
  const [mode, setMode] = useState<'live' | 'upload' | null>(initialMode)
  const [delimiterKey, setDelimiterKey] = useState('none')
  const [cadenceDays, setCadenceDays] = useState(
    String(cadenceDaysFromMetadata(connector.metadata)),
  )
  const [file, setFile] = useState<File | null>(null)
  const [uploadOk, setUploadOk] = useState(false)

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    })
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connector-reminders'],
    })
  }

  const modeMutation = useMutation({
    mutationFn: (next: 'live' | 'upload') =>
      setOwnerConnectorMode(verticalId, connector.system, { mode: next }),
    onSuccess: (_data, next) => {
      invalidate()
      actionToast.success({
        title: 'Mode saved',
        description: `Using ${next === 'upload' ? 'Upload' : 'Live'} for ${connector.display_name}.`,
      })
      setStep('connect')
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not save mode',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => {
            if (mode) modeMutation.mutate(mode)
          },
        },
      })
    },
  })

  const cadenceMutation = useMutation({
    mutationFn: (days: number) =>
      setOwnerConnectorCadence(verticalId, connector.system, {
        cadence_days: days,
      }),
    onSuccess: () => {
      invalidate()
      actionToast.success({
        title: 'Cadence saved',
        description: `Refresh every ${cadenceDays} days.`,
      })
      setStep('confirm')
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not save cadence',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => {
            const days = Number.parseInt(cadenceDays, 10)
            if (Number.isFinite(days) && days >= 1) cadenceMutation.mutate(days)
          },
        },
      })
    },
  })

  const completeMutation = useMutation({
    mutationFn: () => completeOwnerConnectorWizard(verticalId, connector.system),
    onSuccess: () => {
      invalidate()
      actionToast.success({
        title: 'Wizard complete',
        description: `${connector.display_name} setup finished.`,
      })
      onDone()
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not complete wizard',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => completeMutation.mutate(),
        },
      })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: async () => {
      if (!file) throw new Error('Choose a CSV file first.')
      return uploadOwnerConnectorCsv(
        verticalId,
        connector.system,
        file,
        delimiterValueFromKey(delimiterKey),
      )
    },
    onSuccess: (result) => {
      invalidate()
      if (result.ok) {
        setUploadOk(true)
        actionToast.success({
          title: 'Upload validated',
          description:
            result.upload_row_count != null
              ? `${result.upload_row_count} usable row(s). Continue to cadence.`
              : 'File accepted. Continue to cadence.',
        })
      } else {
        actionToast.error({
          title: 'Upload test failed',
          description: actionToast.safeErrorMessage(
            new Error(result.detail || 'upload failed'),
            'Check headers and delimiter, then try again.',
          ),
        })
      }
    },
    onError: (error) => {
      actionToast.error({
        title: 'Upload failed',
        description: actionToast.safeErrorMessage(
          error,
          'Check the file and try again.',
        ),
        action: {
          label: 'Retry',
          onClick: () => uploadMutation.mutate(),
        },
      })
    },
  })

  const templateMutation = useMutation({
    mutationFn: () => downloadOwnerUploadTemplate(verticalId, connector.system),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${connector.system}-upload-template.csv`
      anchor.click()
      URL.revokeObjectURL(url)
      actionToast.success({
        title: 'Template downloaded',
        description: 'Fill required headers, then upload your CSV.',
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not download template',
        description: actionToast.safeErrorMessage(
          error,
          'Template may not be ready yet. Try again shortly.',
        ),
        action: {
          label: 'Retry',
          onClick: () => templateMutation.mutate(),
        },
      })
    },
  })

  return (
    <div className="mt-3 rounded-md border border-line bg-canvas p-3 sm:p-4">
      <WizardProgress step={step} />

      {step === 'mode' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            Choose how Habeas receives data for {connector.display_name}. Only
            approaches allowed for this system are shown.
          </p>
          <div className="flex flex-wrap gap-2">
            {canUpload ? (
              <Button
                type="button"
                size="sm"
                variant={mode === 'upload' ? 'default' : 'outline'}
                onClick={() => setMode('upload')}
              >
                Upload
              </Button>
            ) : null}
            {canLive ? (
              <Button
                type="button"
                size="sm"
                variant={mode === 'live' ? 'default' : 'outline'}
                onClick={() => setMode('live')}
              >
                Live
              </Button>
            ) : null}
          </div>
          {!canUpload && !canLive ? (
            <p className="text-xs text-mute">
              No owner approaches are configured for this system.
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              size="sm"
              disabled={!mode || modeMutation.isPending}
              onClick={() => {
                if (mode) modeMutation.mutate(mode)
              }}
            >
              {modeMutation.isPending ? 'Saving…' : 'Continue'}
            </Button>
          </div>
        </div>
      ) : null}

      {step === 'connect' && mode === 'upload' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            Download the frozen template, pick a multi-PII delimiter, then upload a
            CSV. The connection test checks headers and usable rows.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={templateMutation.isPending}
              onClick={() => templateMutation.mutate()}
            >
              {templateMutation.isPending ? 'Downloading…' : 'Download template'}
            </Button>
          </div>
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-ink">Multi-PII delimiter</span>
            <select
              className={FIELD_CLASS}
              value={delimiterKey}
              onChange={(event) => setDelimiterKey(event.target.value)}
              aria-label="Multi-PII delimiter"
            >
              {MULTI_PII_DELIMITER_OPTIONS.map((opt) => (
                <option key={opt.key} value={opt.key}>
                  {opt.label}
                </option>
              ))}
            </select>
          </label>
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-ink">CSV file</span>
            <input
              type="file"
              accept=".csv,text/csv"
              className="block w-full text-xs text-ink file:mr-2 file:rounded file:border file:border-line file:bg-white file:px-2 file:py-1"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null)
                setUploadOk(false)
              }}
            />
          </label>
          <div className="flex flex-wrap justify-between gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => setStep('mode')}>
              Back
            </Button>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={!file || uploadMutation.isPending}
                onClick={() => uploadMutation.mutate()}
              >
                {uploadMutation.isPending ? 'Uploading…' : 'Upload & test'}
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!uploadOk}
                onClick={() => setStep('cadence')}
              >
                Continue
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {step === 'connect' && mode === 'live' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            Live credentials are completed through a Habeas invite link (
            <code className="text-ink">/connect/…</code>). Ask Ops for an invite if
            you do not have one. After redeem succeeds, return here and refresh
            status before continuing.
          </p>
          <p className="rounded border border-line bg-white px-3 py-2 text-xs text-ink-soft">
            Connecting credentials is separate from enabling matching. Matching stays
            gated until freshness and rotation rules pass.
          </p>
          {liveConnectReady(connector) ? (
            <p className="text-xs text-ink">
              Live credentials are recorded. Continue to set cadence.
            </p>
          ) : (
            <p className="text-xs text-mute">
              Continue stays disabled until this connection shows a successful
              redeem (connected status or rotation timestamp).
            </p>
          )}
          <div className="flex flex-wrap justify-between gap-2">
            <Button type="button" size="sm" variant="ghost" onClick={() => setStep('mode')}>
              Back
            </Button>
            <div className="flex gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => invalidate()}
              >
                Refresh status
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={!liveConnectReady(connector)}
                onClick={() => setStep('cadence')}
              >
                Continue
              </Button>
            </div>
          </div>
        </div>
      ) : null}

      {step === 'cadence' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            How often should Habeas expect a refresh for this system? Soft reminders
            appear when approaching or past this window; matching hard-gates when stale.
          </p>
          <label className="block space-y-1 text-xs">
            <span className="font-medium text-ink">Cadence (days)</span>
            <input
              type="number"
              min={1}
              max={3650}
              className={FIELD_CLASS}
              value={cadenceDays}
              onChange={(event) => setCadenceDays(event.target.value)}
            />
          </label>
          <div className="flex flex-wrap justify-between gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setStep('connect')}
            >
              Back
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={cadenceMutation.isPending}
              onClick={() => {
                const days = Number.parseInt(cadenceDays, 10)
                if (!Number.isFinite(days) || days < 1) {
                  actionToast.warning({
                    title: 'Enter a valid cadence',
                    description: 'Use a whole number of days (1 or more).',
                  })
                  return
                }
                cadenceMutation.mutate(days)
              }}
            >
              {cadenceMutation.isPending ? 'Saving…' : 'Continue'}
            </Button>
          </div>
        </div>
      ) : null}

      {step === 'confirm' ? (
        <div className="space-y-3">
          <p className="text-xs text-mute">
            Confirm setup for {connector.display_name}. Mode:{' '}
            <span className="font-medium text-ink">{mode ?? '—'}</span>
            {mode === 'upload' ? (
              <>
                {' '}
                · Delimiter:{' '}
                <span className="font-medium text-ink">
                  {delimiterValueFromKey(delimiterKey) ?? 'None'}
                </span>
              </>
            ) : null}
            {' '}
            · Cadence:{' '}
            <span className="font-medium text-ink">{cadenceDays} days</span>
          </p>
          <div className="flex flex-wrap justify-between gap-2">
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => setStep('cadence')}
            >
              Back
            </Button>
            <Button
              type="button"
              size="sm"
              disabled={completeMutation.isPending}
              onClick={() => completeMutation.mutate()}
            >
              {completeMutation.isPending ? 'Completing…' : 'Complete wizard'}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function ConnectorCard({
  verticalId,
  connector,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
}) {
  const [wizardOpen, setWizardOpen] = useState(
    connector.display_status === 'needs_setup' ||
      connector.display_status === 'action_required',
  )
  const metaMode = activeModeFromMetadata(connector.metadata)
  const canWizard =
    allowsUpload(connector.allowed_approaches) ||
    allowsLive(connector.allowed_approaches)

  return (
    <div className="rounded-md border border-line bg-white p-3 sm:p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h4 className="text-sm font-medium text-ink">{connector.display_name}</h4>
          <p className="text-[11px] text-mute">
            {connector.system.replaceAll('_', ' ')}
            {metaMode ? ` · ${metaMode}` : ''}
            {connector.connection_id
              ? ` · ${connector.connection_id.slice(0, 8)}…`
              : ' · not linked'}
          </p>
        </div>
        <DisplayStatusBadge
          displayStatus={connector.display_status}
          gateAllowed={connector.gate_allowed}
        />
      </div>
      {canWizard ? (
        <div className="mt-3">
          <Button
            type="button"
            size="sm"
            variant={wizardOpen ? 'outline' : 'default'}
            onClick={() => setWizardOpen((open) => !open)}
          >
            {wizardOpen ? 'Hide wizard' : 'Open setup wizard'}
          </Button>
          {wizardOpen ? (
            <ConnectorWizard
              verticalId={verticalId}
              connector={connector}
              onDone={() => setWizardOpen(false)}
            />
          ) : null}
        </div>
      ) : (
        <p className="mt-2 text-xs text-mute">No owner wizard for this system.</p>
      )}
    </div>
  )
}

function VerticalConnectorsSection({
  verticalId,
  selected,
  onSelect,
}: {
  verticalId: string
  selected: boolean
  onSelect: () => void
}) {
  const listQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    queryFn: () => listOwnerConnectors(verticalId),
    staleTime: 15_000,
  })

  if (listQuery.isPending) {
    return (
      <div className="rounded-md border border-line bg-white p-4">
        <SkeletonLines lines={3} />
      </div>
    )
  }

  if (listQuery.isError) {
    return (
      <div className="rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">
        <p className="font-medium">Could not load connectors for {verticalId}</p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          className="mt-2"
          onClick={() => void listQuery.refetch()}
        >
          Retry
        </Button>
      </div>
    )
  }

  const list = listQuery.data
  if (!list) return null

  if (list.view_only) {
    return <ViewOnlyCard list={list} />
  }

  return (
    <section
      className={`space-y-3 rounded-md border p-3 sm:p-4 ${
        selected ? 'border-habeas-navy/40 bg-habeas-navy/[0.03]' : 'border-line bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button
          type="button"
          className="text-left"
          onClick={onSelect}
        >
          <h3 className="text-sm font-medium text-ink">{list.display_label}</h3>
          <p className="text-[11px] text-mute">{list.connectors.length} system(s)</p>
        </button>
      </div>
      <div className="space-y-2">
        {list.connectors.map((connector) => (
          <ConnectorCard
            key={connector.system}
            verticalId={verticalId}
            connector={connector}
          />
        ))}
      </div>
    </section>
  )
}

function OwnerConnectorsBody({
  verticalFilter,
}: {
  verticalFilter?: string
}) {
  const { me, role } = useAuth()
  const navigate = useNavigate()
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set())

  const verticals = me?.verticals ?? []
  const visibleVerticals = useMemo(() => {
    if (!verticalFilter) return verticals
    return verticals.filter((id) => id === verticalFilter)
  }, [verticals, verticalFilter])

  const remindersFromMe = me?.connector_reminders
  const remindersQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connector-reminders'],
    queryFn: async () => {
      try {
        const payload = await listOwnerConnectorReminders()
        return payload.reminders
      } catch {
        // U10 may land later — fall back to /me reminders without crashing.
        return remindersFromMe ?? []
      }
    },
    staleTime: 30_000,
    enabled: role === 'data_owner' || role === 'super_admin' || role === 'admin',
  })

  const reminders: ConnectorReminder[] =
    remindersQuery.data ?? remindersFromMe ?? []

  if (!verticals.length) {
    return (
      <section className="space-y-6">
        <header>
          <Micro>Data owner</Micro>
          <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink">
            Connectors
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            No verticals are assigned to your account yet. Ask a Habeas admin to
            assign you to a vertical catalog entry.
          </p>
        </header>
        <div className="rounded-md border border-dashed border-line bg-canvas px-4 py-8 text-center text-sm text-mute">
          Empty — no assigned verticals.
        </div>
        <Button asChild size="sm" variant="outline">
          <Link to="/" search={{ tab: 'pipeline' }}>
            Back to My work
          </Link>
        </Button>
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Micro>Data owner</Micro>
          <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink">
            Connectors
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Set Live or Upload mode, cadence, and complete setup for your assigned
            verticals. Soft reminders never block login.
          </p>
        </div>
        {verticalFilter ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() =>
              void navigate({
                to: '/owner/connectors',
                search: {},
              })
            }
          >
            Show all verticals
          </Button>
        ) : null}
      </header>

      <ReminderBanners
        reminders={reminders}
        dismissedIds={dismissedIds}
        onDismiss={(id) =>
          setDismissedIds((prev) => {
            const next = new Set(prev)
            next.add(id)
            return next
          })
        }
      />

      {verticalFilter && !verticals.includes(verticalFilter) ? (
        <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-950">
          Vertical <code className="text-ink">{verticalFilter}</code> is not assigned
          to you.
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {verticals.map((id) => (
          <Button
            key={id}
            type="button"
            size="sm"
            variant={verticalFilter === id ? 'default' : 'outline'}
            onClick={() =>
              void navigate({
                to: '/owner/connectors',
                search: { vertical: id },
              })
            }
          >
            {id.replaceAll('_', '/')}
          </Button>
        ))}
      </div>

      <div className="space-y-4">
        {visibleVerticals.map((verticalId) => (
          <VerticalConnectorsSection
            key={verticalId}
            verticalId={verticalId}
            selected={verticalFilter === verticalId}
            onSelect={() =>
              void navigate({
                to: '/owner/connectors',
                search: { vertical: verticalId },
              })
            }
          />
        ))}
      </div>
    </section>
  )
}

export type OwnerConnectorsSearch = {
  vertical?: string
}

export function OwnerConnectorsPage({
  search,
}: {
  search?: OwnerConnectorsSearch
}) {
  return (
    <RoleGate allow={canAccessOwnerConnectors}>
      <OwnerConnectorsBody verticalFilter={search?.vertical} />
    </RoleGate>
  )
}
