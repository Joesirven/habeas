import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { WizardDialog } from '@/components/owner/wizard-dialog'
import {
  readOwnerSheetsOauthSession,
  writeOwnerSheetsOauthSession,
  type StoredOwnerSheetsOauthSession,
} from '@/components/owner/sheets-step'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  getOwnerVerticalSettings,
  listOwnerConnectorReminders,
  listOwnerConnectors,
  listOwnerVisibleVerticals,
  listVerticalMembers,
  mintVerticalMemberInvite,
  ownerSheetsOauthRedeem,
  patchOwnerVerticalSettings,
  setOwnerConnectorCadence,
  type ConnectorReminder,
  type OwnerConnectorList,
  type OwnerConnectorSystem,
  type OwnerVerticalSettings,
  type UserRole,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { RoleGate, useAuth } from '@/lib/auth'
import {
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WEEKLY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
  activeModeFromMetadata,
  allowsLive,
  allowsOauth,
  allowsUpload,
  buildReminderBannerItems,
  cadenceDaysFromMetadata,
  cadenceOptionFromMetadata,
  cadenceOptionIdsForSystems,
  connectionMethodLabel,
  DIRECT_CONNECTION_LABEL,
  displayStatusChip,
  filterOwnerWizardConnectors,
  filterRemindersForOwnerConnectorsPage,
  isOwnerConnectorsHiddenSystem,
  isOwnerConnectorsHiddenVertical,
  isSheetsOwnerSystem,
  livePingIsNotMatchingExtract,
  MANUAL_UPLOAD_LABEL,
  ownerConnectorsVerticalIds,
  ownerConnectorDisplayName,
  ownerUploadAllowed,
  refreshCadenceFromCadenceOption,
  visibleReminderBanners,
  type CadenceOptionId,
} from '@/lib/owner-connector-ui'
import { wizardCompletedAt } from '@/lib/quick-start-tour'
import { verticalLabel } from '@/lib/legalJourneyLabels'
import { cn } from '@/lib/utils'

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

const CADENCE_OPTION_COPY: Record<
  CadenceOptionId,
  { label: string; description: string }
> = {
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
    description:
      'Matching needs a successful upload or refresh within the last 7 days.',
  },
}

function canAccessOwnerConnectors(role: UserRole) {
  return (
    role === 'data_owner' ||
    role === 'data_user' ||
    role === 'super_admin' ||
    role === 'admin'
  )
}

function canConfigureOwnerConnectors(role: UserRole | undefined) {
  return role === 'data_owner' || role === 'super_admin' || role === 'admin'
}

function canInviteVerticalMembers(role: UserRole | undefined) {
  return role === 'data_owner' || role === 'super_admin' || role === 'admin'
}

function connectorTitle(
  verticalId: string,
  connector: Pick<OwnerConnectorSystem, 'system' | 'display_name'>,
) {
  return ownerConnectorDisplayName(verticalId, connector.system, connector.display_name)
}

/** Prefer API `connection_method_label`, then `connection_method`. Never "Live". */
function ownerMethodLabel(
  connector: Pick<
    OwnerConnectorSystem,
    'system' | 'connection_method' | 'connection_method_label'
  >,
): string {
  const preferred =
    connector.connection_method_label?.trim() || connector.connection_method
  return connectionMethodLabel(connector.system, preferred) ?? DIRECT_CONNECTION_LABEL
}

function systemsNeedingCadence(connectors: readonly OwnerConnectorSystem[]) {
  return connectors.filter(
    (connector) =>
      isSheetsOwnerSystem(connector.system) ||
      ownerUploadAllowed(connector.system, connector.upload_allowed) ||
      livePingIsNotMatchingExtract(connector.system) ||
      // Auth0 live asks cadence in the wizard (matching extract), so the
      // inline select must offer it too.
      connector.system === 'auth0' ||
      connector.system === 'google_sheets' ||
      connector.system === 'alumni_google_sheet' ||
      connector.system === 'contact_us_google_sheet',
  )
}

function wizardableConnectors(connectors: readonly OwnerConnectorSystem[]) {
  return filterOwnerWizardConnectors(connectors).filter(
    (connector) =>
      isSheetsOwnerSystem(connector.system) ||
      allowsUpload(connector.allowed_approaches) ||
      allowsLive(connector.allowed_approaches) ||
      allowsOauth(connector.allowed_approaches),
  )
}

function readSheetsOauthReturnParams(search?: OwnerConnectorsSearch) {
  const fromSearch = {
    code: search?.code?.trim() || undefined,
    state: search?.state?.trim() || undefined,
    error: search?.error?.trim() || undefined,
  }
  if (fromSearch.code || fromSearch.state || fromSearch.error) return fromSearch
  if (typeof window === 'undefined') return fromSearch
  const params = new URLSearchParams(window.location.search)
  return {
    code: params.get('code')?.trim() || undefined,
    state: params.get('state')?.trim() || undefined,
    error: params.get('error')?.trim() || undefined,
  }
}

function Micro({ children }: { children: ReactNode }) {
  return <p className="taste-micro">{children}</p>
}

type NotifyMode = 'off' | 'email' | 'slack' | 'both'

const NOTIFY_MODE_OPTIONS: ReadonlyArray<{ id: NotifyMode; label: string }> = [
  { id: 'off', label: 'Off' },
  { id: 'email', label: 'Email' },
  { id: 'slack', label: 'Slack' },
  { id: 'both', label: 'Both' },
]

function notifyModeFromSettings(settings: OwnerVerticalSettings | undefined): NotifyMode {
  if (!settings) return 'off'
  if (settings.notify_email && settings.notify_slack) return 'both'
  if (settings.notify_email) return 'email'
  if (settings.notify_slack) return 'slack'
  return 'off'
}

function VerticalNotificationsControl({ verticalId }: { verticalId: string }) {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'vertical-settings', verticalId],
    queryFn: () => getOwnerVerticalSettings(verticalId),
    staleTime: 30_000,
  })
  const mode = notifyModeFromSettings(settingsQuery.data)

  const mutation = useMutation({
    mutationFn: (next: NotifyMode) =>
      patchOwnerVerticalSettings(verticalId, {
        notify_email: next === 'email' || next === 'both',
        notify_slack: next === 'slack' || next === 'both',
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'owner', 'vertical-settings', verticalId],
      })
      actionToast.success({
        title: 'Notification preference saved',
        description: 'Delivery starts when notifications ship.',
      })
    },
    onError: (error, next) => {
      actionToast.error({
        title: 'Could not save notifications',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => mutation.mutate(next),
        },
      })
    },
  })

  const disabled = settingsQuery.isPending || settingsQuery.isError || mutation.isPending

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-[11px] text-mute">Notifications</span>
      <div
        className="inline-flex overflow-hidden rounded-md border border-line bg-white"
        role="group"
        aria-label="Notification channels"
      >
        {NOTIFY_MODE_OPTIONS.map((option) => {
          const active = mode === option.id
          return (
            <button
              key={option.id}
              type="button"
              aria-pressed={active}
              disabled={disabled}
              onClick={() => {
                if (option.id !== mode) mutation.mutate(option.id)
              }}
              className={cn(
                'px-2.5 py-1 text-xs transition-colors disabled:opacity-60',
                active ? 'bg-habeas-navy text-white' : 'text-ink-soft hover:bg-canvas',
              )}
            >
              {option.label}
            </button>
          )
        })}
      </div>
      <Badge variant="wait">Coming soon</Badge>
      {settingsQuery.isError ? (
        <button
          type="button"
          className="text-[11px] font-medium text-habeas-navy underline-offset-2 hover:underline"
          onClick={() => void settingsQuery.refetch()}
        >
          Retry load
        </button>
      ) : null}
    </div>
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
  const items = visibleReminderBanners(buildReminderBannerItems(reminders), dismissedIds)
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
              {ownerConnectorDisplayName(item.verticalId, item.system)} ·{' '}
              {verticalLabel(item.verticalId)}
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
        {filterOwnerWizardConnectors(list.connectors).map((connector) => (
          <li
            key={connector.system}
            className="flex flex-wrap items-center justify-between gap-2 rounded border border-line bg-canvas px-3 py-2 text-sm"
          >
            <span className="font-medium text-ink">
              {connectorTitle(list.vertical_id, connector)}
            </span>
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

function ConnectorCadenceSelect({
  verticalId,
  connector,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
}) {
  const queryClient = useQueryClient()
  const cadenceOption =
    cadenceOptionFromMetadata(connector.metadata) ??
    (cadenceDaysFromMetadata(connector.metadata) === 7 ? CADENCE_OPTION_WEEKLY : null)

  const cadenceMutation = useMutation({
    mutationFn: (option: CadenceOptionId) => {
      const refreshCadence = refreshCadenceFromCadenceOption(option)
      if (!refreshCadence) throw new Error('Invalid cadence option')
      return setOwnerConnectorCadence(verticalId, connector.system, {
        refresh_cadence: refreshCadence,
      })
    },
    onSuccess: (_data, option) => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'owner', 'connectors', verticalId],
      })
      actionToast.success({
        title: 'Cadence saved',
        description: CADENCE_OPTION_COPY[option].label,
      })
    },
    onError: (error, option) => {
      actionToast.error({
        title: 'Could not save cadence',
        description: actionToast.safeErrorMessage(error, 'Try again.'),
        action: {
          label: 'Retry',
          onClick: () => cadenceMutation.mutate(option),
        },
      })
    },
  })

  return (
    <label className="flex items-center gap-1.5 text-[11px] text-mute">
      Refresh
      <select
        className="rounded-md border border-line bg-white px-1.5 py-1 text-xs text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20 disabled:opacity-60"
        value={cadenceOption ?? ''}
        disabled={cadenceMutation.isPending}
        onChange={(event) => {
          const next = event.target.value as CadenceOptionId
          if (next && next !== cadenceOption) cadenceMutation.mutate(next)
        }}
        aria-label={`Refresh cadence for ${connectorTitle(verticalId, connector)}`}
      >
        {cadenceOption == null ? (
          <option value="" disabled>
            Choose…
          </option>
        ) : null}
        {cadenceOptionIdsForSystems([connector.system]).map((optionId) => (
          <option key={optionId} value={optionId}>
            {CADENCE_OPTION_COPY[optionId].label}
          </option>
        ))}
      </select>
    </label>
  )
}

function ConnectorStatusRow({
  verticalId,
  connector,
  canConfigure,
  onOpenWizard,
}: {
  verticalId: string
  connector: OwnerConnectorSystem
  canConfigure: boolean
  onOpenWizard: (system: string) => void
}) {
  const metaMode = activeModeFromMetadata(connector.metadata)
  const modeLabel =
    metaMode === 'live'
      ? ownerMethodLabel(connector)
      : metaMode === 'upload'
        ? MANUAL_UPLOAD_LABEL
        : null
  const completed = wizardCompletedAt(connector.metadata) != null
  const showCadence =
    canConfigure && completed && systemsNeedingCadence([connector]).length > 0

  return (
    <div className="rounded-md border border-line bg-white px-3 py-2.5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 space-y-1">
          <h4 className="text-sm font-medium text-ink">{connectorTitle(verticalId, connector)}</h4>
          <p className="text-[11px] text-mute">
            {modeLabel ? `${modeLabel} · ` : ''}
            {connector.connection_id
              ? `${connector.connection_id.slice(0, 8)}…`
              : 'not linked'}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {showCadence ? (
            <ConnectorCadenceSelect verticalId={verticalId} connector={connector} />
          ) : null}
          <DisplayStatusBadge
            displayStatus={connector.display_status}
            gateAllowed={connector.gate_allowed}
          />
          {canConfigure ? (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onOpenWizard(connector.system)}
            >
              {completed ? 'Review' : 'Set up'}
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  )
}

function VerticalConnectorsSection({
  verticalId,
  selected,
  onSelect,
  initialWizardSystem,
  wizardAutoOpen,
  onWizardClosed,
}: {
  verticalId: string
  selected: boolean
  onSelect: () => void
  initialWizardSystem?: string
  wizardAutoOpen?: boolean
  onWizardClosed?: () => void
}) {
  const { role } = useAuth()
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    queryFn: () => listOwnerConnectors(verticalId),
    staleTime: 15_000,
  })

  const list = listQuery.data
  const needsSetup = useMemo(
    () =>
      list?.connectors.some(
        (connector) =>
          !isOwnerConnectorsHiddenSystem(connector.system) &&
          (connector.display_status === 'needs_setup' ||
            connector.display_status === 'action_required'),
      ) ?? false,
    [list],
  )
  const [wizardOpen, setWizardOpen] = useState(false)
  const [wizardSystem, setWizardSystem] = useState<string | undefined>(initialWizardSystem)

  // Auto-open on Sheets OAuth resume, or on needs_setup/action_required when this
  // section is the only/selected one (stacked modals across sections are never OK).
  // initialWizardSystem can arrive AFTER mount (redeem mutation resolves async),
  // so re-sync the target system, not just the open flag.
  useEffect(() => {
    if (initialWizardSystem) {
      setWizardSystem(initialWizardSystem)
      setWizardOpen(true)
      return
    }
    if (wizardAutoOpen && needsSetup) setWizardOpen(true)
  }, [initialWizardSystem, wizardAutoOpen, needsSetup])

  const invalidate = () => {
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connectors', verticalId],
    })
    void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
    void queryClient.invalidateQueries({
      queryKey: ['admin-api', 'owner', 'connector-reminders'],
    })
  }

  function openWizard(system?: string) {
    setWizardSystem(system)
    setWizardOpen(true)
  }

  function handleWizardOpenChange(open: boolean) {
    setWizardOpen(open)
    if (!open) {
      setWizardSystem(undefined)
      // Consume a Sheets OAuth resume so later UI state flips (vertical filter,
      // needsSetup changes) do not force-reopen the wizard unprompted.
      onWizardClosed?.()
    }
  }

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

  if (!list) return null

  const connectors = filterOwnerWizardConnectors(list.connectors)
  if (connectors.length === 0) return null

  if (list.view_only) {
    return <ViewOnlyCard list={{ ...list, connectors }} />
  }

  const canConfigure = canConfigureOwnerConnectors(role)
  const canWizard = canConfigure && wizardableConnectors(connectors).length > 0

  return (
    <section
      className={`space-y-3 rounded-md border p-3 sm:p-4 ${
        selected ? 'border-habeas-navy/40 bg-habeas-navy/[0.03]' : 'border-line bg-white'
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <button type="button" className="text-left" onClick={onSelect}>
          <h3 className="text-sm font-medium text-ink">{list.display_label}</h3>
          <p className="text-[11px] text-mute">{connectors.length} system(s)</p>
        </button>
        {canWizard ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => openWizard()}
          >
            Start wizard
          </Button>
        ) : null}
      </div>

      {canConfigure ? <VerticalNotificationsControl verticalId={verticalId} /> : null}

      <div className="space-y-2">
        {connectors.map((connector) => (
          <ConnectorStatusRow
            key={connector.system}
            verticalId={verticalId}
            connector={connector}
            canConfigure={canConfigure}
            onOpenWizard={openWizard}
          />
        ))}
      </div>

      {canWizard ? (
        <WizardDialog
          key={wizardSystem ?? 'hub'}
          open={wizardOpen}
          onOpenChange={handleWizardOpenChange}
          verticalId={verticalId}
          verticalLabel={list.display_label}
          connectors={connectors}
          initialSystem={wizardSystem}
          onSystemCompleted={(system: string) => {
            invalidate()
            const connector = connectors.find((row) => row.system === system)
            actionToast.success({
              title: `${connector ? connectorTitle(verticalId, connector) : system} configured`,
              description: `${list.display_label} · system setup saved.`,
            })
          }}
          onAllDone={() => {
            invalidate()
            actionToast.success({
              title: 'All systems configured',
              description: `${list.display_label} setup finished.`,
            })
          }}
        />
      ) : null}
    </section>
  )
}

function TeamMembersSection({
  verticalId,
  canInvite,
}: {
  verticalId: string
  canInvite: boolean
}) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const membersQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'vertical-members', verticalId],
    queryFn: () => listVerticalMembers(verticalId),
    enabled: canInvite,
  })
  const inviteMutation = useMutation({
    mutationFn: (inviteEmail: string) => mintVerticalMemberInvite(verticalId, inviteEmail),
    onSuccess: (invite) => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'owner', 'vertical-members', verticalId],
      })
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'me'] })
      setEmail('')
      void navigator.clipboard.writeText(invite.invite_url).catch(() => undefined)
      actionToast.success({
        title: 'Invite created',
        description: 'Link copied. Share it with your teammate.',
        action: {
          label: 'Copy again',
          onClick: () => {
            void navigator.clipboard.writeText(invite.invite_url)
          },
        },
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not create invite',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => inviteMutation.mutate(email.trim()),
        },
      })
    },
  })
  if (!canInvite) return null
  const members = membersQuery.data ?? []
  return (
    <section className="space-y-3 rounded-md border border-line bg-white px-4 py-3">
      <header>
        <h3 className="text-sm font-medium text-ink">Team members</h3>
        <p className="mt-1 text-xs text-ink-soft">
          Invite data users to this vertical. They can review matches, fulfill, and
          refresh systems — not connector credentials or catalog settings.
        </p>
      </header>
      {members.length > 0 ? (
        <ul className="space-y-1 text-xs text-ink-soft">
          {members.map((member) => (
            <li key={`${member.email}:${member.assignment_role}`}>
              <span className="text-ink">{member.email}</span>
              {' · '}
              {member.assignment_role === 'data_user' ? 'Data user' : 'Data owner'}
              {member.active ? '' : ' · inactive'}
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-mute">No additional team members yet.</p>
      )}
      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(event) => {
          event.preventDefault()
          const next = email.trim()
          if (!next) return
          inviteMutation.mutate(next)
        }}
      >
        <label className="min-w-[12rem] flex-1 text-[0.65rem] text-mute">
          Teammate email
          <input
            className={FIELD_CLASS}
            type="email"
            autoComplete="off"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
          />
        </label>
        <Button type="submit" size="sm" disabled={inviteMutation.isPending}>
          {inviteMutation.isPending ? 'Copying…' : 'Copy invite link'}
        </Button>
      </form>
    </section>
  )
}

function OwnerConnectorsBody({ search }: { search?: OwnerConnectorsSearch }) {
  const { me, role, realRole } = useAuth()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const verticalFilter = search?.vertical
  const [dismissedIds, setDismissedIds] = useState<Set<string>>(() => new Set())
  const [oauthResume, setOauthResume] = useState<{
    verticalId: string
    system: string
  } | null>(() => {
    const stored = readOwnerSheetsOauthSession()
    if (stored?.redeemed) return { verticalId: stored.verticalId, system: stored.system }
    return null
  })
  const [oauthReturn] = useState(() => readSheetsOauthReturnParams(search))

  const redeemMutation = useMutation({
    mutationFn: (input: StoredOwnerSheetsOauthSession & { code: string }) =>
      ownerSheetsOauthRedeem(input.verticalId, input.system, {
        session_id: input.session_id,
        code: input.code,
        state: input.state,
      }),
    onSuccess: (_data, input) => {
      writeOwnerSheetsOauthSession({
        verticalId: input.verticalId,
        system: input.system,
        state: input.state,
        session_id: input.session_id,
        redeemed: true,
      })
      setOauthResume({ verticalId: input.verticalId, system: input.system })
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'owner', 'connectors', input.verticalId],
      })
      actionToast.success({
        title: 'Google connected',
        description: 'Choose a spreadsheet and tab to use.',
      })
      void navigate({
        to: '/owner/connectors',
        search: { vertical: input.verticalId },
        replace: true,
      })
    },
    onError: (error, input) => {
      actionToast.error({
        title: 'Google sign-in failed',
        description: actionToast.safeErrorMessage(error, 'Start Google sign-in again.'),
        action: {
          label: 'Dismiss',
          onClick: () => undefined,
        },
      })
      void navigate({
        to: '/owner/connectors',
        search: { vertical: input.verticalId },
        replace: true,
      })
    },
  })

  useEffect(() => {
    const returned = oauthReturn
    if (returned.error) {
      actionToast.error({
        title: 'Google sign-in cancelled',
        description: 'Start Google sign-in again if you still want to link a sheet.',
      })
      void navigate({
        to: '/owner/connectors',
        search: verticalFilter ? { vertical: verticalFilter } : {},
        replace: true,
      })
      return
    }
    if (!returned.code || !returned.state) return
    const stored = readOwnerSheetsOauthSession()
    if (!stored) {
      actionToast.error({
        title: 'Google sign-in expired',
        description: 'Start Google sign-in again from the wizard.',
      })
      void navigate({
        to: '/owner/connectors',
        search: verticalFilter ? { vertical: verticalFilter } : {},
        replace: true,
      })
      return
    }
    if (stored.state !== returned.state) {
      actionToast.error({
        title: 'Google sign-in check failed',
        description: 'Start Google sign-in again from the wizard.',
      })
      void navigate({
        to: '/owner/connectors',
        search: { vertical: stored.verticalId },
        replace: true,
      })
      return
    }
    if (redeemMutation.isPending || redeemMutation.isSuccess) return
    redeemMutation.mutate({ ...stored, code: returned.code })
    // Redeem once from the first-paint callback capture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (typeof window === 'undefined') return
    if (window.location.hash !== '#team') return
    document.getElementById('team')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [role])

  const catalogQuery = useQuery({
    queryKey: ['admin-api', 'owner', 'verticals'],
    queryFn: listOwnerVisibleVerticals,
    staleTime: 30_000,
    enabled:
      role === 'data_owner' ||
      role === 'data_user' ||
      role === 'super_admin' ||
      role === 'admin',
  })
  const verticals = useMemo(
    () =>
      ownerConnectorsVerticalIds({
        role,
        realRole,
        meVerticals: me?.verticals,
        catalogVerticalIds: catalogQuery.isSuccess
          ? catalogQuery.data.map((row) => row.id)
          : undefined,
      }),
    [role, realRole, me?.verticals, catalogQuery.isSuccess, catalogQuery.data],
  )
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
        return remindersFromMe ?? []
      }
    },
    staleTime: 30_000,
    enabled: role === 'data_owner' || role === 'data_user' || role === 'super_admin' || role === 'admin',
  })

  const reminders: ConnectorReminder[] = filterRemindersForOwnerConnectorsPage(
    remindersQuery.data ?? remindersFromMe ?? [],
  )

  if (!verticals.length) {
    return (
      <section className="space-y-6">
        <header>
          <Micro>{role === 'data_user' ? 'Data user' : 'Data owner'}</Micro>
          <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink">
            Data vertical settings
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            No verticals are assigned to your account yet. Ask a Habeas admin to assign you to a
            vertical catalog entry.
          </p>
        </header>
        <div className="rounded-md border border-dashed border-line bg-canvas px-4 py-8 text-center text-sm text-mute">
          Empty — no assigned verticals.
        </div>
        <Button asChild size="sm" variant="outline">
          <Link to="/" search={{ tab: 'pipeline' }}>
            Back to Home
          </Link>
        </Button>
      </section>
    )
  }

  return (
    <section className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Micro>{role === 'data_user' ? 'Data user' : 'Settings'}</Micro>
          <h2 className="mt-2 font-display text-xl font-medium tracking-tight text-ink">
            Data vertical settings
          </h2>
          <p className="mt-2 max-w-xl text-sm text-ink-soft">
            Set up each system in any order — open the wizard from a vertical below. Soft
            reminders never block login. Team invite stays on this page
            {' '}
            <a href="#team" className="font-medium text-habeas-navy underline-offset-2 hover:underline">
              #team
            </a>
            — not a first-login gate.
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
          Vertical <code className="text-ink">{verticalFilter}</code> is not assigned to you.
        </div>
      ) : null}

      <div className="flex flex-wrap gap-2">
        {verticals
          .filter((id) => !isOwnerConnectorsHiddenVertical(id))
          .map((id) => (
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
            {verticalLabel(id)}
          </Button>
        ))}
      </div>

      <div className="space-y-4">
        {visibleVerticals.map((verticalId) => (
          <VerticalConnectorsSection
            key={verticalId}
            verticalId={verticalId}
            selected={verticalFilter === verticalId}
            initialWizardSystem={
              oauthResume?.verticalId === verticalId ? oauthResume.system : undefined
            }
            wizardAutoOpen={
              verticalFilter === verticalId || visibleVerticals.length === 1
            }
            onWizardClosed={() => setOauthResume(null)}
            onSelect={() =>
              void navigate({
                to: '/owner/connectors',
                search: { vertical: verticalId },
              })
            }
          />
        ))}
      </div>

      {role === 'data_owner' || canInviteVerticalMembers(role) ? (
        <div id="team" className="space-y-4">
          {(verticalFilter ? [verticalFilter] : visibleVerticals)
            .filter((id) => !isOwnerConnectorsHiddenVertical(id) && verticals.includes(id))
            .map((verticalId) => (
              <TeamMembersSection
                key={`team-${verticalId}`}
                verticalId={verticalId}
                canInvite
              />
            ))}
        </div>
      ) : null}
    </section>
  )
}

export type OwnerConnectorsSearch = {
  vertical?: string
  code?: string
  state?: string
  error?: string
}

export function OwnerConnectorsPage({ search }: { search?: OwnerConnectorsSearch }) {
  return (
    <RoleGate allow={canAccessOwnerConnectors}>
      <OwnerConnectorsBody search={search} />
    </RoleGate>
  )
}
