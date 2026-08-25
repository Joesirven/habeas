import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useRouterState } from '@tanstack/react-router'
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
  type RefObject,
} from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { AccessDeliveryEmailCard } from '@/components/fulfillment/AccessDeliveryEmail'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  ConfirmActionDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { isLegalAdminPersona, isVerticalOperatorRole, useMe } from '@/lib/auth'
import {
  NOTICE_APPROVAL,
  WORKBENCH_STAGE_ORDER,
  actionReasonLabel,
  deriveWorkbenchChromeFromOpsJourney,
  isWorkbenchStageKey,
  opsStageToWorkbench,
  workbenchStageLabel,
  workbenchStatusLabel,
  type DerivedWorkbenchSubstep,
  type WorkbenchStageKey,
} from '@/lib/legalJourneyLabels'
import { actionToast } from '@/lib/action-toast'
import { matchingReviewPromoteToast } from '@/lib/inbox-status-lab'
import {
  matchingConnectorGateChip,
  ownerConnectorsSearch,
  resolveOverlayConnectorCallout,
  type OverlayConnectorCallout,
} from '@/lib/connection-display'
import {
  deleteRequestDocument,
  downloadRequestDocument,
  dropResponseStatusLabel,
  getFulfillmentArtifact,
  getLatestIdentityVerification,
  getRequest,
  getRequestComments,
  getRequestJourney,
  getRequestJourneyWorkbench,
  getRequestTimeline,
  getAuth0MatchCandidates,
  getNeedsAttention,
  getOwnerMatchingNeedsAttention,
  listRequestDocuments,
  patchAccessDeliveryStatus,
  postFulfillmentKickoff,
  postIdentityVerification,
  postNoticeApprove,
  postRequestClose,
  postRequestComment,
  postDropMatchingResultDecline,
  postDropMatchingResultPromote,
  postTriageBulkReject,
  postTriageSendToMatching,
  uploadRequestDocument,
  DROP_RESPONSE_STATUS_OPTIONS,
  type DropResponseStatusCode,
  type JourneyStageStatus,
  type MatchedPersonContact,
  type MatchingResultDetail,
  type NeedsAttentionItem,
  type RequestComment,
  type RequestDocumentRecord,
  type RequestJourneyResponse,
  type RequestRecord,
  type RequesterContact,
  type TimelineEntry,
  type WorkbenchVerticalRow,
  fetchOwnerVerticalMatchingDetailOptional,
} from '@/lib/api'
import { cn, isRequestUuid } from '@/lib/utils'

import {
  AccessHandoffPanel,
  AttemptRow,
  MatchedContactsPanel,
  MatchedContactsUnavailableCallout,
  MatchingReviewPanel,
  OwnerFulfillmentStatusPanel,
  fetchMatchingDetailOptional,
  formatMatchedContactsSummary,
  ownerDropStatusLabel,
  redactHashHex,
} from '@/components/requests/RequestTriageDialog'

const SOURCE_LABELS: Record<string, string> = {
  webform: 'Gravity Forms',
  drop: 'CA DROP',
  csv: 'Authorized Agent',
  manual: 'Manual',
}

export type RequestDetailTab =
  | 'details'
  | 'ingest'
  | 'matching'
  | 'fulfillment'
  | 'notice'

export const REQUEST_DETAIL_TAB_TRIGGER =
  'h-7 rounded-md border border-transparent px-2.5 text-[0.7rem] data-[state=active]:border-habeas-navy/25 data-[state=active]:bg-white data-[state=active]:text-habeas-navy data-[state=active]:shadow-sm'

type JourneyRailStage = {
  stage: string
  label: string
  status: JourneyStageStatus
  blocker: string | null
}

type JourneySubstepItem = {
  key: string
  label: string
  status: JourneyStageStatus
  blocker?: string | null
  muted?: boolean
  statusLabel?: string
}

function journeyItemsForStage(opts: {
  stageKey: string
  substeps?: DerivedWorkbenchSubstep[]
  matchingCluster?: PipelineClusterRow[]
  fulfillmentCluster?: PipelineClusterRow[]
}): JourneySubstepItem[] {
  const { stageKey, substeps, matchingCluster, fulfillmentCluster } = opts
  if (stageKey === 'matching' && matchingCluster && matchingCluster.length > 0) {
    return matchingCluster.map((row) => ({
      key: `m-${row.vertical}`,
      label: row.label,
      status: row.matching_status,
      blocker: row.blocker,
      muted: !row.live,
      statusLabel: row.live ? workbenchStatusLabel(row.matching_status) : 'Soon',
    }))
  }
  if (stageKey === 'fulfillment' && fulfillmentCluster && fulfillmentCluster.length > 0) {
    return fulfillmentCluster.map((row) => {
      const status = row.fulfillment_status ?? ('not_started' as JourneyStageStatus)
      return {
        key: `f-${row.vertical}`,
        label: row.label,
        status,
        blocker: row.blocker,
        muted: !row.live,
        statusLabel: row.live ? workbenchStatusLabel(status) : 'Soon',
      }
    })
  }
  return (substeps?.filter((step) => step.parent === stageKey) ?? []).map((step) => ({
    key: step.key,
    label: step.label,
    status: step.status,
    blocker: step.blocker,
    statusLabel: step.statusLabel,
  }))
}

export type RequestDetailOverlayProps = {
  requestId: string | null
  open: boolean
  onOpenChange: (open: boolean) => void
  /** Element to restore focus on close (KD36). */
  returnFocusRef?: RefObject<HTMLElement | null>
  /** Optional list-row context — avoids refetch for display label. */
  seedRequest?: RequestRecord | null
  /** Owner vertical-item review — required for the vertical matching-results path. */
  vertical?: string | null
  /** Catalog system on the opened inbox item / `?system=` — owner matching-results query. */
  system?: string | null
}

function trimScopeId(value: string | null | undefined): string | null {
  const trimmed = value?.trim()
  return trimmed ? trimmed : null
}

export function isAuth0MatchingScope(
  vertical?: string | null,
  system?: string | null,
): boolean {
  const verticalId = trimScopeId(vertical)?.toLowerCase()
  const systemId = trimScopeId(system)?.toLowerCase()
  return verticalId === 'auth0' || systemId === 'auth0'
}

/** Compact Auth0 vendor-record list on the existing matching pane — no new route. */
export function Auth0MatchCandidatesList({ requestId }: { requestId: string }) {
  const ready = isRequestUuid(requestId)
  const query = useQuery({
    queryKey: [
      'admin-api',
      'requests',
      requestId,
      'verticals',
      'auth0',
      'match-candidates',
    ],
    queryFn: () => getAuth0MatchCandidates(requestId),
    enabled: ready,
  })
  const candidates = query.data?.candidates ?? []
  const matchCount = query.data?.match_count ?? candidates.length

  return (
    <div className="space-y-1.5 rounded-md border border-line bg-paper px-2.5 py-2">
      <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
        Auth0 candidates
        {query.isSuccess ? (
          <span className="ml-1.5 font-normal tabular-nums normal-case tracking-normal">
            {matchCount}
          </span>
        ) : null}
      </p>
      {query.isPending ? (
        <p className="text-[0.7rem] text-mute">Loading candidates…</p>
      ) : query.isError ? (
        <p className="text-[0.7rem] text-ink-soft">Could not load Auth0 candidates.</p>
      ) : candidates.length === 0 ? (
        <p className="text-[0.7rem] text-mute">No Auth0 vendor records matched.</p>
      ) : (
        <ul className="space-y-1">
          {candidates.map((candidate) => (
            <li
              key={candidate.vendor_record_id}
              className="truncate font-mono text-[0.7rem] text-ink"
            >
              {candidate.vendor_record_id}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function systemFromAttentionItem(item: NeedsAttentionItem | null | undefined): string | null {
  return trimScopeId(item?.system) ?? trimScopeId(item?.system_id)
}

/** Raw `?system=` even when a route's validateSearch omits the key. */
function useLocationSystemParam(): string | null {
  const href = useRouterState({ select: (state) => state.location.href })
  try {
    const queryIndex = href.indexOf('?')
    if (queryIndex < 0) return null
    return trimScopeId(new URLSearchParams(href.slice(queryIndex)).get('system'))
  } catch {
    return null
  }
}

export function useRequestDetailOverlay() {
  const [open, setOpen] = useState(false)
  const [requestId, setRequestId] = useState<string | null>(null)
  const [seedRequest, setSeedRequest] = useState<RequestRecord | null>(null)
  const [vertical, setVertical] = useState<string | null>(null)
  const [system, setSystem] = useState<string | null>(null)
  const returnFocusRef = useRef<HTMLElement | null>(null)

  const openOverlay = useCallback(
    (
      id: string,
      trigger?: HTMLElement | null,
      seed?: RequestRecord | null,
      nextVertical?: string | null,
      nextSystem?: string | null,
    ) => {
      if (!isRequestUuid(id)) return
      returnFocusRef.current =
        trigger ?? (document.activeElement instanceof HTMLElement ? document.activeElement : null)
      setRequestId(id)
      setSeedRequest(seed ?? null)
      setVertical(trimScopeId(nextVertical))
      setSystem(trimScopeId(nextSystem))
      setOpen(true)
    },
    [],
  )

  const onOpenChange = useCallback((next: boolean) => {
    setOpen(next)
    if (!next) {
      setRequestId(null)
      setSeedRequest(null)
      setVertical(null)
      setSystem(null)
    }
  }, [])

  return {
    open,
    requestId,
    seedRequest,
    vertical,
    system,
    openOverlay,
    onOpenChange,
    returnFocusRef,
  }
}

function findOverlayAttentionItem(
  items: NeedsAttentionItem[],
  requestId: string,
  vertical?: string | null,
  system?: string | null,
): NeedsAttentionItem | undefined {
  const verticalNorm = trimScopeId(vertical)
  const systemNorm = trimScopeId(system)?.toLowerCase() || null
  const matchesSystem = (item: NeedsAttentionItem) => {
    if (!systemNorm) return true
    const itemSystem = systemFromAttentionItem(item)?.toLowerCase() || null
    return itemSystem === systemNorm
  }
  const sameRequest = items.filter((item) => item.request_id === requestId)
  if (verticalNorm) {
    return (
      sameRequest.find(
        (item) => item.vertical === verticalNorm && matchesSystem(item),
      ) ??
      sameRequest.find((item) => item.vertical === verticalNorm) ??
      sameRequest.find((item) => !item.vertical && matchesSystem(item))
    )
  }
  return sameRequest.find((item) => matchesSystem(item)) ?? sameRequest[0]
}

async function fetchOverlayAttentionItem(
  requestId: string,
  options: { vertical?: string | null; system?: string | null; ownerPersona: boolean },
): Promise<NeedsAttentionItem | undefined> {
  const response = options.ownerPersona
    ? await getOwnerMatchingNeedsAttention({
        limit: 200,
        ...(trimScopeId(options.vertical) ? { vertical: options.vertical!.trim() } : {}),
        ...(trimScopeId(options.system) ? { system: options.system!.trim() } : {}),
      })
    : await getNeedsAttention({ limit: 200 })
  return findOverlayAttentionItem(
    response.items,
    requestId,
    options.vertical,
    options.system,
  )
}

export function requestDetailHeaderLabel(
  requestId: string,
  intakeSource: string,
  displayLabel?: string | null,
): string {
  const channel = SOURCE_LABELS[intakeSource] ?? intakeSource
  if (intakeSource === 'drop') {
    return `${requestId} · ${channel}`
  }
  return displayLabel?.trim() || requestId
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return '—'
  return new Date(value).toLocaleString()
}

function journeyResponseStatus(
  journey: RequestJourneyResponse | null | undefined,
): number | null {
  const value = journey?.response_status
  return typeof value === 'number' ? value : null
}

function resolveDropStatusCode(opts: {
  journey?: RequestJourneyResponse | null
  matching?: MatchingResultDetail | null
  attentionItem?: NeedsAttentionItem | null
}): { code: number | null; isRecommended: boolean } {
  const fromJourney = journeyResponseStatus(opts.journey)
  if (fromJourney != null) return { code: fromJourney, isRecommended: false }
  // Fulfilled notice/delivery rows carry response_status on needs-attention.
  const fromAttention = opts.attentionItem?.response_status
  if (typeof fromAttention === 'number') {
    return { code: fromAttention, isRecommended: false }
  }
  const recommended =
    opts.matching?.recommended_response_status ??
    opts.attentionItem?.recommended_response_status
  if (typeof recommended === 'number') {
    return { code: recommended, isRecommended: true }
  }
  return { code: null, isRecommended: false }
}

function matchingResultsLabel(matching: MatchingResultDetail): string {
  const type = String(
    matching?.match_type ?? (matching?.matched ? 'matched' : 'not matched'),
  ).replaceAll('_', ' ')
  const count = typeof matching?.match_count === 'number' ? matching.match_count : 0
  return `${type} · ${count}`
}

function matchingStatusLabel(reviewStatus: string | null | undefined): string {
  const normalized = (reviewStatus ?? '').trim().toLowerCase()
  if (normalized === 'pending') return 'Pending review'
  if (normalized === 'approved') return 'Approved'
  if (normalized === 'declined' || normalized === 'rejected') return 'Declined'
  if (normalized === 'none' || normalized === '') return 'None'
  return (reviewStatus ?? '').replaceAll('_', ' ')
}

function substepDotClass(status: JourneyStageStatus): string {
  switch (status) {
    case 'complete':
      return 'bg-habeas-mid'
    case 'failed':
      return 'bg-red-700/70'
    case 'in_progress':
      return 'bg-habeas-light animate-pulse'
    case 'waiting':
      return 'border border-habeas-mid bg-paper'
    case 'skipped':
      return 'bg-line-strong'
    default:
      return 'border border-line bg-paper'
  }
}

/**
 * Minimal vertical row for pipeline chrome — request or batch aggregate.
 * Full WorkbenchVerticalRow satisfies this; batch helpers may pass a subset.
 */
export type PipelineClusterRow = {
  vertical: string
  label: string
  live: boolean
  matching_status: JourneyStageStatus
  fulfillment_status: JourneyStageStatus | null
  blocker: string | null
}

function stagePanelClass(status: JourneyStageStatus): string {
  switch (status) {
    case 'in_progress':
    case 'waiting':
      return 'border-amber-300 bg-amber-50'
    case 'complete':
      return 'border-emerald-200/80 bg-emerald-50/50'
    case 'failed':
      return 'border-red-300 bg-red-50'
    default:
      return 'border-line bg-canvas'
  }
}

function stageLabelClass(status: JourneyStageStatus): string {
  switch (status) {
    case 'in_progress':
    case 'waiting':
      return 'font-medium text-amber-950'
    case 'complete':
      return 'text-emerald-800'
    case 'failed':
      return 'text-red-800'
    default:
      return 'text-mute'
  }
}

function stageIsActive(status: JourneyStageStatus): boolean {
  return status === 'in_progress' || status === 'waiting' || status === 'failed'
}

function JourneySubstepList({
  items,
  compact,
}: {
  items: Array<{
    key: string
    label: string
    status: JourneyStageStatus
    blocker?: string | null
    muted?: boolean
    statusLabel?: string
  }>
  compact: boolean
}) {
  if (items.length === 0) return null
  return (
    <ul className={cn('space-y-0.5', compact ? 'mt-1' : 'mt-1.5')}>
      {items.map((item) => (
        <li
          key={item.key}
          className={cn(
            'flex items-center gap-1 truncate text-ink',
            compact ? 'text-[0.55rem]' : 'text-[0.65rem]',
            item.muted && 'opacity-50',
          )}
          title={
            item.blocker
              ? `${item.label}: ${workbenchStatusLabel(item.status)} — ${item.blocker}`
              : `${item.label}: ${workbenchStatusLabel(item.status)}`
          }
        >
          <span
            className={cn('h-1.5 w-1.5 shrink-0 rounded-full', substepDotClass(item.status))}
            aria-hidden="true"
          />
          <span className="min-w-0 flex-1 truncate">{item.label}</span>
          {item.statusLabel ? (
            <span className="shrink-0 text-mute">{item.statusLabel}</span>
          ) : null}
        </li>
      ))}
    </ul>
  )
}

export function journeyRailStages(
  stages: JourneyRailStage[],
): JourneyRailStage[] {
  if (stages.length > 0) return stages
  return WORKBENCH_STAGE_ORDER.map((key) => ({
    stage: key,
    label: workbenchStageLabel(key),
    status: 'not_started' as JourneyStageStatus,
    blocker: null,
  }))
}

/** Substeps / vertical cluster for one high-level stage — lives inside that stage's tab. */
export function JourneyStageSubsteps({
  stages,
  stageKey,
  substeps,
  matchingCluster,
  fulfillmentCluster,
  density = 'compact',
}: {
  stages: JourneyRailStage[]
  stageKey: string
  substeps?: DerivedWorkbenchSubstep[]
  matchingCluster?: PipelineClusterRow[]
  fulfillmentCluster?: PipelineClusterRow[]
  density?: 'compact' | 'comfortable'
}) {
  const compact = density === 'compact'
  const rail = journeyRailStages(stages)
  const stage = rail.find((item) => item.stage === stageKey)
  const items = journeyItemsForStage({
    stageKey,
    substeps,
    matchingCluster,
    fulfillmentCluster,
  })
  if (!stage && items.length === 0) {
    return (
      <p className={cn('text-mute', compact ? 'text-[0.65rem]' : 'text-[0.7rem]')}>
        No substeps for this stage.
      </p>
    )
  }
  return (
    <div
      id={`journey-substeps-${stageKey}`}
      className={cn(
        'rounded-md border px-2 py-1.5 text-left',
        stage ? stagePanelClass(stage.status) : 'border-line bg-canvas',
      )}
    >
      {stage ? (
        <>
          <p
            className={cn(
              'truncate leading-tight',
              compact ? 'text-[0.55rem]' : 'text-[0.65rem]',
              stageLabelClass(stage.status),
            )}
          >
            {stage.label}
            <span className="ml-1.5 font-normal text-mute">
              · {workbenchStatusLabel(stage.status)}
            </span>
          </p>
          {stage.blocker ? (
            <p className={cn('mt-0.5 text-mute', compact ? 'text-[0.5rem]' : 'text-[0.6rem]')}>
              {stage.blocker}
            </p>
          ) : null}
        </>
      ) : null}
      {items.length > 0 ? (
        <JourneySubstepList items={items} compact={compact} />
      ) : (
        <p className={cn('mt-1 text-mute', compact ? 'text-[0.5rem]' : 'text-[0.6rem]')}>
          No nested steps yet.
        </p>
      )}
    </div>
  )
}

/**
 * Four-panel journey chrome (Ingest → Matching → Fulfillment → Notice).
 * Always-visible rail. Click a stage to open that stage's tab (selectMode)
 * or expand substeps underneath (legacy).
 */
export function ThinJourneyPipeline({
  stages,
  substeps,
  matchingCluster,
  fulfillmentCluster,
  splitPosture,
  density = 'comfortable',
  expandedStage: expandedStageControlled,
  onExpandedStageChange,
  showSubsteps = true,
  onStageActivate,
}: {
  stages: JourneyRailStage[]
  substeps?: DerivedWorkbenchSubstep[]
  matchingCluster?: PipelineClusterRow[]
  fulfillmentCluster?: PipelineClusterRow[]
  splitPosture?: boolean
  density?: 'compact' | 'comfortable'
  /** When provided (including `null`), expansion/selection is controlled by the parent. */
  expandedStage?: string | null
  onExpandedStageChange?: (stage: string | null) => void
  /** Hide the inline substep panel — stage tabs own those details. */
  showSubsteps?: boolean
  /** Click always activates the stage (opens its tab) instead of toggling expand. */
  onStageActivate?: (stage: string) => void
}) {
  const rail = journeyRailStages(stages)
  const compact = density === 'compact'

  const defaultExpanded =
    rail.find((stage) => stageIsActive(stage.status))?.stage ??
    rail.find((stage) => stage.status === 'complete')?.stage ??
    null

  const isControlled = expandedStageControlled !== undefined
  const [expandedStageUncontrolled, setExpandedStageUncontrolled] = useState<string | null>(
    defaultExpanded,
  )
  const expandedStage = isControlled ? expandedStageControlled : expandedStageUncontrolled

  const setExpandedStage = (next: string | null | ((prev: string | null) => string | null)) => {
    const resolved = typeof next === 'function' ? next(expandedStage) : next
    if (isControlled) {
      onExpandedStageChange?.(resolved)
    } else {
      setExpandedStageUncontrolled(resolved)
    }
  }

  const railKey = rail.map((stage) => `${stage.stage}:${stage.status}`).join('|')
  useEffect(() => {
    if (isControlled || onStageActivate) return
    setExpandedStageUncontrolled(defaultExpanded)
    // Re-sync when stage statuses change for this request (not on every parent render).
    // eslint-disable-next-line react-hooks/exhaustive-deps -- railKey captures status shifts
  }, [railKey, isControlled, onStageActivate])

  const expanded = expandedStage != null ? rail.find((stage) => stage.stage === expandedStage) : null
  const expandedItems =
    showSubsteps && expandedStage != null
      ? journeyItemsForStage({
          stageKey: expandedStage,
          substeps,
          matchingCluster,
          fulfillmentCluster,
        })
      : []

  return (
    <div
      className={cn('space-y-1.5', compact ? 'py-0' : 'py-0.5')}
      role="group"
      aria-label="Request journey pipeline"
    >
      <div className="flex items-stretch gap-1" role="list" aria-label="High-level journey">
        {rail.map((stage, index) => {
          const isSelected = expandedStage === stage.stage
          return (
            <div
              key={stage.stage}
              className="flex min-w-0 flex-1 items-stretch gap-1"
              role="listitem"
            >
              <button
                type="button"
                className={cn(
                  'min-w-0 flex-1 rounded-md border text-center transition-colors',
                  compact ? 'px-1 py-1' : 'px-1.5 py-1.5',
                  stagePanelClass(stage.status),
                  isSelected && 'ring-1 ring-habeas-navy/40',
                )}
                aria-pressed={isSelected}
                aria-controls={`journey-substeps-${stage.stage}`}
                title={`${stage.label}: ${workbenchStatusLabel(stage.status)}${
                  stage.blocker ? ` — ${stage.blocker}` : ''
                }. Click to open ${stage.label}.`}
                onClick={() => {
                  if (onStageActivate) {
                    onStageActivate(stage.stage)
                    return
                  }
                  setExpandedStage((current) =>
                    current === stage.stage ? null : stage.stage,
                  )
                }}
              >
                <div className="mx-auto mb-1 flex justify-center">
                  <span
                    className={cn(
                      'shrink-0 rounded-full ring-1 ring-inset ring-black/10',
                      compact ? 'size-1.5' : 'size-2',
                      substepDotClass(stage.status),
                    )}
                    aria-hidden="true"
                  />
                </div>
                <p
                  className={cn(
                    'truncate leading-tight',
                    compact ? 'text-[0.55rem]' : 'text-[0.6rem]',
                    stageLabelClass(stage.status),
                  )}
                >
                  {stage.label}
                </p>
              </button>
              {index < rail.length - 1 ? (
                <span
                  className={cn(
                    'flex shrink-0 items-center text-mute',
                    compact ? 'text-[0.55rem]' : 'text-[0.6rem]',
                  )}
                  aria-hidden="true"
                >
                  →
                </span>
              ) : null}
            </div>
          )
        })}
      </div>

      {splitPosture ? (
        <p
          className={cn(
            'text-center text-mute',
            compact ? 'text-[0.5rem]' : 'text-[0.6rem]',
          )}
        >
          Matching + Fulfillment in progress
        </p>
      ) : null}

      {showSubsteps && expanded != null && expandedItems.length > 0 ? (
        <JourneyStageSubsteps
          stages={rail}
          stageKey={expanded.stage}
          substeps={substeps}
          matchingCluster={matchingCluster}
          fulfillmentCluster={fulfillmentCluster}
          density={density}
        />
      ) : null}
    </div>
  )
}

/** Shared Inbox / lab / full-page card: left workbench + full-height activity column. */
export function RequestDetailWorkbenchShell({
  header,
  rail,
  children,
  side,
}: {
  header?: ReactNode
  rail?: ReactNode
  children: ReactNode
  side?: ReactNode
}) {
  return (
    <div className="flex h-full min-h-0 min-w-0 flex-1 overflow-hidden">
      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
        {header}
        {rail != null ? (
          <div className="shrink-0 border-b border-line px-3 py-1.5">{rail}</div>
        ) : null}
        {children}
      </div>
      {side ? (
        <aside
          className="flex h-full min-h-0 w-full shrink-0 flex-col overflow-hidden border-line max-md:max-h-[42%] max-md:border-t md:w-[17.5rem] md:border-l lg:w-[19rem]"
          aria-label="Activity and comments"
        >
          {side}
        </aside>
      ) : null}
    </div>
  )
}

export function RequestDetailSideColumn({
  activity,
  comments,
}: {
  activity: ReactNode
  comments: ReactNode
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <section className="min-h-0 flex-1 overflow-y-auto px-2.5 py-2" aria-label="Activity">
        {activity}
      </section>
      <section
        className="min-h-0 flex-1 overflow-y-auto border-t border-line px-2.5 py-2"
        aria-label="Comments"
      >
        {comments}
      </section>
    </div>
  )
}


/** U19 / AE32 — compact Live-down callout. Fail-tone; no frost. */
function OverlayConnectorFreshnessCallout({
  callout,
}: {
  callout: OverlayConnectorCallout
}) {
  const chip = matchingConnectorGateChip({
    blocked: true,
    displayStatus: callout.displayStatus,
    source: 'reminder',
  })
  return (
    <div
      className="rounded-md border border-red-300/80 bg-red-50 px-2.5 py-1.5"
      role="status"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Badge variant={chip.variant} className="normal-case tracking-normal">
          {callout.title}
        </Badge>
        <p className="min-w-0 flex-1 text-[0.65rem] leading-snug text-red-900/90">
          {callout.description}
        </p>
        {callout.showCta ? (
          <Link
            to="/owner/connectors"
            search={ownerConnectorsSearch(callout.verticalId)}
            className="shrink-0 text-[0.65rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
          >
            Open Connectors
          </Link>
        ) : null}
      </div>
    </div>
  )
}

function isTriageContext(item: NeedsAttentionItem | undefined, journeyStage: string): boolean {
  if (!item) return journeyStage === 'triage'
  return (
    item.kind === 'triage' ||
    item.assignment?.kind === 'triage' ||
    item.current_stage === 'triage'
  )
}

function isNoticeContext(item: NeedsAttentionItem | undefined, journeyStage: string): boolean {
  if (item?.kind === 'notice' || item?.reason === 'notice.review') return true
  return journeyStage === 'notice'
}

function isDeliveryContext(item: NeedsAttentionItem | undefined, journeyStage: string): boolean {
  if (
    item?.kind === 'delivery' ||
    item?.reason === 'access.delivery' ||
    item?.reason === 'delivery.confirm'
  ) {
    return true
  }
  return journeyStage === 'delivery' || journeyStage === 'fulfill'
}

function isAssignmentToLegalContext(item: NeedsAttentionItem | undefined): boolean {
  if (!item) return false
  return (
    item.kind === 'escalations' ||
    item.assignment?.kind === 'escalate' ||
    item.assignment?.target_role === 'legal'
  )
}

type StageAction = {
  id: string
  label: string
  hint?: string
  primary?: boolean
  destructive?: boolean
  softWarning?: string
  /** When set, show confirm dialog before running (title/description override softWarning path). */
  confirm?: { title: string; description: string }
  run: () => Promise<void>
}

function buildStageActions(opts: {
  requestId: string
  journeyStage: string
  attentionItem?: NeedsAttentionItem
  artifactPending?: boolean
  accessDelivered?: boolean
}): StageAction[] {
  const { requestId, journeyStage, attentionItem, artifactPending, accessDelivered } = opts
  const actions: StageAction[] = []

  if (isTriageContext(attentionItem, journeyStage)) {
    actions.push(
      {
        id: 'triage_reject',
        label: 'Reject as Exempted',
        hint: 'DROP response_status 2 — release pre-matching hold',
        run: async () => {
          await postTriageBulkReject({ request_ids: [requestId], response_status: 2 })
        },
      },
      {
        id: 'triage_match',
        label: 'Send to matching',
        primary: true,
        hint: 'Release hold and enqueue matching',
        run: async () => {
          await postTriageSendToMatching({ request_ids: [requestId] })
        },
      },
    )
  }

  if (isNoticeContext(attentionItem, journeyStage)) {
    actions.push({
      id: 'notice_approve',
      label: NOTICE_APPROVAL.action,
      primary: true,
      hint: NOTICE_APPROVAL.hint,
      confirm: {
        title: NOTICE_APPROVAL.confirmTitle,
        description: NOTICE_APPROVAL.hint,
      },
      run: async () => {
        await postNoticeApprove({ request_ids: [requestId] })
      },
    })
  }

  const noticeContext = isNoticeContext(attentionItem, journeyStage)
  // Fulfill stage historically matched delivery context — skip when the work is fulfillment notice.
  if (!noticeContext && isDeliveryContext(attentionItem, journeyStage)) {
    actions.push(
      {
        id: 'delivery_delivered',
        label: 'Confirm delivered',
        primary: true,
        run: async () => {
          await patchAccessDeliveryStatus(requestId, { status: 'delivered' })
        },
      },
      {
        id: 'delivery_failed',
        label: 'Mark delivery failed',
        destructive: true,
        run: async () => {
          await patchAccessDeliveryStatus(requestId, { status: 'failed' })
        },
      },
    )
  }

  const incompleteWarning =
    artifactPending && !accessDelivered
      ? 'Access delivery may still be in progress.'
      : undefined

  actions.push({
    id: 'close',
    label: 'Close request',
    softWarning: incompleteWarning,
    hint: 'Unrestricted close (KD40) — records operator note',
    run: async () => {
      await postRequestClose(requestId, {
        note: 'Operator closed request from detail overlay.',
      })
    },
  })

  return actions
}

function stageActionSuccessTitle(action: StageAction): string {
  switch (action.id) {
    case 'triage_reject':
      return 'Rejected as exempted'
    case 'triage_match':
      return 'Sent to matching'
    case 'notice_approve':
      return 'Fulfillment notice approved'
    case 'delivery_delivered':
      return 'Delivery confirmed'
    case 'delivery_failed':
      return 'Delivery marked failed'
    case 'idv_verified':
      return 'Identity verified'
    case 'close':
      return 'Request closed'
    default:
      return 'Action complete'
  }
}

function stageActionErrorTitle(action: StageAction): string {
  switch (action.id) {
    case 'triage_reject':
      return "Couldn't reject as exempted"
    case 'triage_match':
      return "Couldn't send to matching"
    case 'notice_approve':
      return "Couldn't approve fulfillment notice"
    case 'delivery_delivered':
      return "Couldn't confirm delivery"
    case 'delivery_failed':
      return "Couldn't mark delivery failed"
    case 'idv_verified':
      return "Couldn't record identity verification"
    case 'close':
      return "Couldn't close request"
    default:
      return "Couldn't complete action"
  }
}

function deliverySuccessTitle(status: 'delivered' | 'failed' | 'recalled'): string {
  switch (status) {
    case 'delivered':
      return 'Delivery confirmed'
    case 'failed':
      return 'Delivery marked failed'
    case 'recalled':
      return 'Delivery recalled'
  }
}

function deliveryErrorTitle(status: 'delivered' | 'failed' | 'recalled'): string {
  switch (status) {
    case 'delivered':
      return "Couldn't confirm delivery"
    case 'failed':
      return "Couldn't mark delivery failed"
    case 'recalled':
      return "Couldn't recall delivery"
  }
}

function RequestStageActionBar({
  actions,
  onInvalidate,
}: {
  actions: StageAction[]
  onInvalidate: () => Promise<void>
}) {
  const [pendingId, setPendingId] = useState<string | null>(null)
  const [confirmAction, setConfirmAction] = useState<StageAction | null>(null)

  const runAction = useMutation({
    mutationFn: async (action: StageAction) => {
      setPendingId(action.id)
      await action.run()
    },
    onSuccess: async (_data, action) => {
      setConfirmAction(null)
      setPendingId(null)
      actionToast.success({
        title: stageActionSuccessTitle(action),
        id: `request-stage-action-${action.id}`,
      })
      await onInvalidate()
    },
    onError: (mutationError, action) => {
      setPendingId(null)
      actionToast.error({
        title: stageActionErrorTitle(action),
        description: actionToast.safeErrorMessage(mutationError),
        id: `request-stage-action-${action.id}`,
        action: {
          label: 'Retry',
          onClick: () => {
            runAction.mutate(action)
          },
        },
      })
    },
  })

  if (actions.length === 0) return null

  return (
    <div className="shrink-0 border-b border-line bg-panel/30 px-4 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <p className="taste-micro shrink-0">Next</p>
        {actions.map((action) => (
          <Button
            key={action.id}
            size="sm"
            variant={action.destructive ? 'outline' : action.primary ? 'default' : 'outline'}
            disabled={pendingId != null}
            className={cn(action.destructive && 'border-red-300 text-red-800 hover:bg-red-50')}
            onClick={() => {
              if (action.softWarning || action.confirm) {
                setConfirmAction(action)
                return
              }
              runAction.mutate(action)
            }}
          >
            {pendingId === action.id ? 'Working…' : action.label}
          </Button>
        ))}
      </div>
      <ConfirmActionDialog
        open={confirmAction != null}
        onOpenChange={(next) => {
          if (!next && !runAction.isPending) setConfirmAction(null)
        }}
        title={confirmAction?.confirm?.title ?? confirmAction?.label ?? 'Confirm'}
        description={
          confirmAction?.confirm?.description ??
          (confirmAction?.softWarning
            ? `${confirmAction.softWarning} This does not block close.`
            : (confirmAction?.hint ?? 'Confirm this action.'))
        }
        confirmLabel={confirmAction?.label ?? 'Confirm'}
        confirming={runAction.isPending}
        onConfirm={() => {
          if (confirmAction) runAction.mutate(confirmAction)
        }}
      />
    </div>
  )
}

function phoneSummaryFromMatched(contact: MatchedPersonContact): string | null {
  const phones = Array.isArray(contact.phones) ? contact.phones : []
  if (phones.length === 0) return null
  return phones
    .map((phone) => {
      const type = typeof phone?.type === 'string' ? phone.type : 'phone'
      const number = typeof phone?.number === 'string' ? redactHashHex(phone.number) : '—'
      return `${type}: ${number}`
    })
    .join(' · ')
}

/** Requester contact for Details / Inbox Overview — DROP after match, else intake contact. */
export function RequesterContactSection({
  intakeSource,
  displayLabel,
  requestContact,
  matching,
  dropPreMatch = false,
  compact = false,
}: {
  intakeSource: string
  displayLabel?: string | null
  requestContact?: RequesterContact | null
  matching?: MatchingResultDetail | null
  dropPreMatch?: boolean
  compact?: boolean
}) {
  const isDrop = intakeSource === 'drop'
  const matched = matching?.matched_contacts ?? []
  const matchStatus = matching?.matched_contacts_status
  const primaryMatched = matched[0] ?? null

  const rows: { label: string; value: string }[] = []

  if (isDrop) {
    if (dropPreMatch || matching == null) {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">
            Available after a person match (DROP does not include requester contact at
            intake).
          </p>
        </div>
      )
    }
    if (matchStatus === 'unavailable') {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <MatchedContactsUnavailableCallout matching={matching ?? undefined} />
        </div>
      )
    }
    const effectiveMatchCount =
      typeof matching.match_count === 'number' ? matching.match_count : matched.length
    if (matched.length === 0 || effectiveMatchCount <= 0) {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">No matched person contact on file yet.</p>
        </div>
      )
    }
    const personSummary = formatMatchedContactsSummary(matched)
    if (personSummary && personSummary !== '—') {
      rows.push({ label: 'Matched', value: personSummary })
    }
    if (primaryMatched?.email) {
      rows.push({ label: 'Email', value: redactHashHex(primaryMatched.email) })
    }
    const phones = primaryMatched ? phoneSummaryFromMatched(primaryMatched) : null
    if (phones) rows.push({ label: 'Phone', value: phones })
  } else {
    const name = requestContact?.name?.trim() || displayLabel?.trim() || null
    const email = requestContact?.email?.trim() || null
    const phone = requestContact?.phone?.trim() || null
    if (name) rows.push({ label: 'Name', value: name })
    if (email) rows.push({ label: 'Email', value: redactHashHex(email) })
    if (phone) rows.push({ label: 'Phone', value: redactHashHex(phone) })
    if (rows.length === 0) {
      return (
        <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
          <p className="taste-micro">Requester contact</p>
          <p className="text-mute">No contact on file for this intake.</p>
        </div>
      )
    }
  }

  return (
    <div className={cn('space-y-1.5', compact ? 'text-[0.7rem]' : 'text-xs')}>
      <p className="taste-micro">Requester contact</p>
      <dl
        className={cn(
          'grid gap-x-4 gap-y-2',
          compact ? 'grid-cols-2 sm:grid-cols-3' : 'grid-cols-1 sm:grid-cols-2',
        )}
      >
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className="text-[0.6rem] text-mute">{row.label}</dt>
            <dd
              className={cn(
                'mt-0.5 text-ink',
                row.label === 'Email' || row.label === 'Phone' || row.label === 'Matched'
                  ? 'break-all'
                  : 'truncate',
              )}
              title={row.value}
            >
              {row.value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

/** Request / requester facts — shown as the Details tab (not a side rail). */
function RequestDetailsPanel({
  requestId,
  intakeSource,
  displayLabel,
  requestContact,
  requestorState,
  identityStatus,
  matching,
  dropStatusCode = null,
  dropStatusIsRecommended = false,
  dropPreMatch = false,
  ownerLanguage = false,
}: {
  requestId: string
  intakeSource: string
  displayLabel?: string | null
  requestContact?: RequesterContact | null
  requestorState?: string | null
  identityStatus?: string | null
  matching?: MatchingResultDetail | null
  dropStatusCode?: number | null
  dropStatusIsRecommended?: boolean
  dropPreMatch?: boolean
  ownerLanguage?: boolean
}) {
  const channel = SOURCE_LABELS[intakeSource] ?? intakeSource
  const isDrop = intakeSource === 'drop'

  const rows: { label: string; value: string }[] = []
  rows.push({
    label: 'Display',
    value: requestDetailHeaderLabel(requestId, intakeSource, displayLabel),
  })
  rows.push({ label: 'Request id', value: requestId })
  rows.push({ label: 'Channel', value: channel })
  if (isDrop) {
    const ownerLabel = ownerDropStatusLabel(dropStatusCode)
    rows.push({
      label: ownerLanguage ? 'Match result' : 'CA DROP status',
      value:
        dropStatusCode != null
          ? `${ownerLanguage ? (ownerLabel ?? String(dropStatusCode)) : dropResponseStatusLabel(dropStatusCode)}${
              dropStatusIsRecommended ? ' (recommended)' : ''
            }`
          : 'Pending',
    })
  }
  if (!(isDrop && dropPreMatch)) {
    rows.push({
      label: 'State',
      value: requestorState ?? matching?.requestor_state ?? '—',
    })
    rows.push({
      label: 'Identity verification',
      value: identityStatus ?? 'none recorded',
    })
    if (matching) {
      rows.push({ label: 'Matching results', value: matchingResultsLabel(matching) })
      rows.push({
        label: 'Matching status',
        value: matchingStatusLabel(matching.review_status),
      })
    }
  }

  return (
    <div className="space-y-5 text-xs">
      {ownerLanguage && matching ? (
        <MatchedContactsPanel matching={matching} />
      ) : (
        <RequesterContactSection
          intakeSource={intakeSource}
          displayLabel={displayLabel}
          requestContact={requestContact}
          matching={matching}
          dropPreMatch={dropPreMatch}
        />
      )}
      <div className="space-y-3">
        <p className="taste-micro">Request details</p>
        <dl className="grid grid-cols-1 gap-x-6 gap-y-2.5 sm:grid-cols-2">
          {rows.map((row) => (
            <div key={row.label} className="min-w-0">
              <dt className="text-[0.65rem] text-mute">{row.label}</dt>
              <dd
                className={cn(
                  'mt-0.5 text-ink',
                  row.label === 'Request id' || row.label === 'Display' || row.label === 'State'
                    ? 'font-mono text-[0.7rem]'
                    : null,
                  row.label === 'Identity verification' ? 'capitalize' : null,
                )}
              >
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}

type ActivityFilter = 'all' | 'notes' | 'system'

const HUMAN_ACTIVITY_KINDS = new Set(['comment', 'assignment', 'escalation'])

function isHumanActivityKind(kind: string): boolean {
  return HUMAN_ACTIVITY_KINDS.has(kind.trim().toLowerCase())
}

function activityKindLabel(kind: string): string | null {
  switch (kind.trim().toLowerCase()) {
    case 'comment':
      return 'Note'
    case 'assignment':
      return 'Assignment'
    case 'escalation':
      return 'Assignment to legal'
    case 'approval':
      return 'Approval'
    case 'stage':
      return 'Stage'
    case 'audit':
      return null
    default:
      return null
  }
}

/** Humanize dotted reason keys that may appear in timeline summaries. */
function humanizeActivitySummary(summary: string): string {
  return summary.replace(
    /\b[\w]+(?:\.[\w]+)+\b/g,
    (match) => actionReasonLabel(match),
  )
}

/** Prefer stable meta ids so All ↔ Notes filter changes do not remap selection. */
function timelineEntryKey(entry: TimelineEntry, index: number): string {
  const meta = entry.meta ?? {}
  if (meta.comment_id != null) return `comment:${String(meta.comment_id)}`
  if (meta.approval_id != null) return `approval:${String(meta.approval_id)}`
  if (entry.kind === 'stage' && typeof meta.stage === 'string') {
    return `stage:${meta.stage}:${entry.at}`
  }
  if (typeof meta.command === 'string') {
    return `audit:${meta.command}:${entry.at}`
  }
  return `${entry.at}-${entry.kind}-${index}`
}

/** Only `kind === 'stage'` entries carry `meta.stage` (ops fine-stage key). */
function timelineEntryOpsStage(entry: TimelineEntry): string | null {
  const raw = entry.meta?.stage
  return typeof raw === 'string' && raw.trim() ? raw.trim().toLowerCase() : null
}

function timelineEntryWorkbenchStage(entry: TimelineEntry): WorkbenchStageKey | null {
  const ops = timelineEntryOpsStage(entry)
  return ops ? opsStageToWorkbench(ops) : null
}

function ActivityPanel({
  requestId,
  entries,
  isPending,
  selectable = false,
  selectedKey = null,
  onSelectEntry,
  compact = false,
}: {
  requestId: string
  entries: TimelineEntry[]
  isPending: boolean
  /** Page rail: clickable rows that link to the pipeline detail underneath. */
  selectable?: boolean
  selectedKey?: string | null
  onSelectEntry?: (entry: TimelineEntry, key: string) => void
  compact?: boolean
}) {
  const queryClient = useQueryClient()
  const [filter, setFilter] = useState<ActivityFilter>('all')
  const [comment, setComment] = useState('')

  const commentMutation = useMutation({
    mutationFn: () => postRequestComment(requestId, comment.trim()),
    onSuccess: async () => {
      setComment('')
      actionToast.success({
        title: 'Note posted',
        id: `request-comment-${requestId}`,
      })
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
      })
    },
    onError: (err) => {
      actionToast.error({
        title: "Couldn't post note",
        description: actionToast.safeErrorMessage(err),
        id: `request-comment-${requestId}`,
        action: {
          label: 'Retry',
          onClick: () => {
            commentMutation.mutate()
          },
        },
      })
    },
  })

  const filtered = entries
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => {
      const human = isHumanActivityKind(entry.kind)
      if (filter === 'notes') return human
      if (filter === 'system') return !human
      return true
    })

  const filters: { id: ActivityFilter; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'notes', label: 'Notes & assignment' },
    { id: 'system', label: 'System' },
  ]

  return (
    <div className={cn(compact ? 'space-y-2 p-0' : 'space-y-3 p-4')}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="taste-micro">Activity</p>
        <div className="flex flex-wrap gap-1" role="group" aria-label="Activity filter">
          {filters.map((item) => (
            <button
              key={item.id}
              type="button"
              className={cn(
                'rounded border px-2 py-0.5 text-[0.65rem] transition-colors',
                filter === item.id
                  ? 'border-habeas-navy bg-habeas-navy text-white'
                  : 'border-line bg-paper text-ink-soft hover:border-ink/30',
              )}
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      {isPending ? <SkeletonLines lines={4} /> : null}
      {!isPending && filtered.length === 0 ? (
        <p className="text-xs text-ink-soft">
          {entries.length === 0 ? 'No activity yet.' : 'No matching activity for this filter.'}
        </p>
      ) : null}

      <ol className="space-y-1.5">
        {filtered.map(({ entry, index }) => {
          const human = isHumanActivityKind(entry.kind)
          const kindLabel = activityKindLabel(entry.kind)
          const summary = humanizeActivitySummary(entry.summary)
          const key = timelineEntryKey(entry, index)
          const selected = selectable && selectedKey === key

          if (!human) {
            const rowContent = (
              <>
                <time className="shrink-0 tabular-nums text-[0.65rem]">
                  {formatTimestamp(entry.at)}
                </time>
                <span className="min-w-0 text-ink-soft">{summary}</span>
              </>
            )
            if (selectable) {
              return (
                <li key={key}>
                  <button
                    type="button"
                    className={cn(
                      'flex w-full flex-wrap items-baseline gap-x-2 gap-y-0.5 rounded-md px-1.5 py-1 text-left text-xs text-mute transition-colors hover:bg-panel/40',
                      selected && 'bg-habeas-navy/5 ring-1 ring-habeas-navy/40',
                    )}
                    aria-pressed={selected}
                    aria-controls="pipeline-activity-detail"
                    onClick={() => onSelectEntry?.(entry, key)}
                  >
                    {rowContent}
                  </button>
                </li>
              )
            }
            return (
              <li
                key={key}
                className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 py-1 text-xs text-mute"
              >
                {rowContent}
              </li>
            )
          }

          const cardContent = (
            <>
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="flex min-w-0 flex-wrap items-center gap-1.5">
                  {kindLabel ? (
                    <Badge variant="wait" className="normal-case tracking-normal">
                      {kindLabel}
                    </Badge>
                  ) : null}
                  <span className="font-medium text-ink">
                    {entry.actor?.trim() || 'Operator'}
                  </span>
                </div>
                <time className="shrink-0 tabular-nums text-[0.65rem] text-mute">
                  {formatTimestamp(entry.at)}
                </time>
              </div>
              <p className="mt-1.5 whitespace-pre-wrap text-ink">{summary}</p>
            </>
          )

          if (selectable) {
            return (
              <li key={key}>
                <button
                  type="button"
                  className={cn(
                    'w-full rounded-lg border border-line/80 bg-paper/70 px-3 py-2 text-left text-xs transition-colors hover:border-ink/30',
                    selected && 'border-habeas-navy/50 bg-habeas-navy/5 ring-1 ring-habeas-navy/40',
                  )}
                  aria-pressed={selected}
                  aria-controls="pipeline-activity-detail"
                  onClick={() => onSelectEntry?.(entry, key)}
                >
                  {cardContent}
                </button>
              </li>
            )
          }

          return (
            <li
              key={key}
              className="rounded-lg border border-line/80 bg-paper/70 px-3 py-2 text-xs"
            >
              {cardContent}
            </li>
          )
        })}
      </ol>

      <div className="space-y-2 border-t border-line pt-3">
        <p className="taste-micro">Add a note</p>
        <textarea
          className="min-h-[4.5rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-xs text-ink"
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          maxLength={2000}
          placeholder="Add a note…"
          aria-label="Add a note"
        />
        <Button
          type="button"
          size="sm"
          disabled={comment.trim().length === 0 || commentMutation.isPending}
          onClick={() => commentMutation.mutate()}
        >
          {commentMutation.isPending ? 'Posting…' : 'Post note'}
        </Button>
      </div>
    </div>
  )
}

function MatchingAttemptsUnderPipeline({
  matching,
  pending,
  error = false,
}: {
  matching?: MatchingResultDetail | null
  pending: boolean
  error?: boolean
}) {
  if (pending && !matching) {
    return <SkeletonLines lines={2} />
  }
  if (error && !matching) {
    return (
      <p className="text-[0.7rem] text-red-700">
        Could not load matching attempts for this request.
      </p>
    )
  }
  const attempts = [...(Array.isArray(matching?.attempts) ? matching.attempts : [])].sort(
    (a, b) => b.attempt_number - a.attempt_number,
  )
  return (
    <div className="max-h-64 space-y-1.5 overflow-y-auto">
      <p className="sticky top-0 z-[1] bg-canvas/95 text-[0.65rem] text-mute">
        Pipeline · Matching attempts
      </p>
      {attempts.length === 0 ? (
        <p className="text-[0.7rem] text-mute">No matching attempts recorded.</p>
      ) : (
        <div className="space-y-1.5">
          {attempts.map((attempt) => (
            <AttemptRow key={attempt.id} attempt={attempt} />
          ))}
        </div>
      )}
    </div>
  )
}

function ActivityNoteDetail({ entry }: { entry: TimelineEntry }) {
  const kindLabel = activityKindLabel(entry.kind)
  return (
    <div className="rounded-md border border-line/70 bg-paper/70 px-2.5 py-2 text-[0.7rem]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {kindLabel ? (
            <Badge variant="wait" className="normal-case tracking-normal">
              {kindLabel}
            </Badge>
          ) : null}
          <span className="font-medium text-ink">{entry.actor?.trim() || 'Operator'}</span>
        </div>
        <time className="shrink-0 tabular-nums text-mute">{formatTimestamp(entry.at)}</time>
      </div>
      <p className="mt-1 whitespace-pre-wrap text-ink">{humanizeActivitySummary(entry.summary)}</p>
    </div>
  )
}

function StageActivityDetail({
  entry,
  expandedStage,
}: {
  entry: TimelineEntry
  expandedStage: string | null
}) {
  const opsStage = timelineEntryOpsStage(entry)
  return (
    <div className="rounded-md border border-line/70 bg-canvas/40 px-2.5 py-2 text-[0.7rem]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          <Badge variant="wait" className="normal-case tracking-normal">
            Stage
          </Badge>
          {opsStage ? <span className="font-medium capitalize text-ink">{opsStage}</span> : null}
        </div>
        <time className="shrink-0 tabular-nums text-mute">{formatTimestamp(entry.at)}</time>
      </div>
      <p className="mt-1 text-ink-soft">{humanizeActivitySummary(entry.summary)}</p>
      {expandedStage === 'fulfillment' ? (
        <p className="mt-1 text-habeas-navy">
          Fulfillment tab shows kickoff / delivery detail.
        </p>
      ) : expandedStage === 'notice' ? (
        <p className="mt-1 text-habeas-navy">
          Notice tab shows approval / weekly-batch detail.
        </p>
      ) : null}
    </div>
  )
}

function ActivitySummaryDetail({ entry }: { entry: TimelineEntry }) {
  const kindLabel = activityKindLabel(entry.kind)
  return (
    <div className="rounded-md border border-line/70 bg-canvas/40 px-2.5 py-2 text-[0.7rem]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex min-w-0 flex-wrap items-center gap-1.5">
          {kindLabel ? (
            <Badge variant="wait" className="normal-case tracking-normal">
              {kindLabel}
            </Badge>
          ) : null}
          <span className="font-medium text-ink">{entry.actor?.trim() || 'System'}</span>
        </div>
        <time className="shrink-0 tabular-nums text-mute">{formatTimestamp(entry.at)}</time>
      </div>
      <p className="mt-1 text-ink-soft">{humanizeActivitySummary(entry.summary)}</p>
    </div>
  )
}

/**
 * Detail region rendered under the pipeline on the page layout — reflects the selected
 * Activity row (attempts / note / stage summary) without duplicating tab content.
 */
function PipelineActivityDetail({
  entry,
  expandedStage,
  matching,
  matchingPending,
  matchingError = false,
}: {
  entry: TimelineEntry | null
  expandedStage: string | null
  matching?: MatchingResultDetail | null
  matchingPending: boolean
  matchingError?: boolean
}) {
  if (entry == null) {
    if (expandedStage === 'matching') {
      return (
        <MatchingAttemptsUnderPipeline
          matching={matching}
          pending={matchingPending}
          error={matchingError}
        />
      )
    }
    return <p className="text-[0.65rem] text-mute">Select an activity to inspect details.</p>
  }

  // Notes / assignments always win over ambient Matching expansion.
  if (isHumanActivityKind(entry.kind)) {
    return <ActivityNoteDetail entry={entry} />
  }

  const workbenchStage = timelineEntryWorkbenchStage(entry)
  const opsStage = timelineEntryOpsStage(entry)
  const isMatchingContext =
    workbenchStage === 'matching' ||
    (entry.kind === 'stage' && (opsStage === 'match' || opsStage === 'review'))

  if (isMatchingContext) {
    return (
      <MatchingAttemptsUnderPipeline
        matching={matching}
        pending={matchingPending}
        error={matchingError}
      />
    )
  }

  if (entry.kind === 'stage') {
    return <StageActivityDetail entry={entry} expandedStage={expandedStage} />
  }

  return <ActivitySummaryDetail entry={entry} />
}

/** Legal kickoff (R11/KD6) + Access identity-comment gate (R13/KTD6). */
export function FulfillmentGateControls({
  requestId,
  rows,
  onInvalidate,
}: {
  requestId: string
  rows: WorkbenchVerticalRow[]
  onInvalidate: () => Promise<void>
}) {
  const [notes, setNotes] = useState('')
  const [error, setError] = useState<string | null>(null)
  /** Optional Legal early-advance status at kickoff (R10 / KD6); null keeps disposition. */
  const [statusOverride, setStatusOverride] = useState<DropResponseStatusCode | null>(null)

  const needsIdentity = rows.some(
    (row) => row.identity_required && row.identity_verified !== true,
  )
  const kickoffCandidates = rows.filter(
    (row) => row.actionable && !row.kicked_off && row.disposition_status != null,
  )

  const identityMutation = useMutation({
    mutationFn: () =>
      postIdentityVerification(requestId, { status: 'verified', method: 'manual', notes }),
    onSuccess: async () => {
      setError(null)
      setNotes('')
      await onInvalidate()
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'Identity verification failed'),
  })

  const kickoffMutation = useMutation({
    mutationFn: (vertical: string) =>
      postFulfillmentKickoff(requestId, {
        vertical,
        ...(statusOverride != null ? { status: statusOverride } : {}),
      }),
    onSuccess: async () => {
      setError(null)
      setStatusOverride(null)
      await onInvalidate()
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'Kickoff failed'),
  })

  if (!needsIdentity && kickoffCandidates.length === 0) return null

  return (
    <div className="space-y-3 rounded-lg border border-line/80 bg-panel/30 p-3">
      <p className="taste-micro">Fulfillment gate</p>
      {needsIdentity ? (
        <div className="space-y-1.5">
          <p className="text-[0.7rem] text-ink-soft">
            Access pack/notice requires identity verification with a required comment (KTD6).
          </p>
          <textarea
            className="min-h-[3rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-xs text-ink"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
            maxLength={2000}
            placeholder="Verification method / comment (required)…"
            aria-label="Identity verification comment"
          />
          <Button
            type="button"
            size="sm"
            disabled={notes.trim().length === 0 || identityMutation.isPending}
            onClick={() => identityMutation.mutate()}
          >
            {identityMutation.isPending ? 'Verifying…' : 'Mark identity verified'}
          </Button>
        </div>
      ) : null}
      {kickoffCandidates.length > 0 ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="taste-micro shrink-0" htmlFor="kickoff-status-override">
              Status at kickoff
            </label>
            <select
              id="kickoff-status-override"
              className="rounded-md border border-line bg-paper-raised px-2 py-1 text-xs text-ink"
              value={statusOverride ?? ''}
              onChange={(event) => {
                const raw = event.target.value
                setStatusOverride(
                  raw === '' ? null : (Number(raw) as DropResponseStatusCode),
                )
              }}
              aria-label="Optional status override at kickoff"
            >
              <option value="">Keep current disposition</option>
              {DROP_RESPONSE_STATUS_OPTIONS.map((option) => (
                <option key={option.code} value={option.code}>
                  {option.code} {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <p className="taste-micro shrink-0">Kickoff</p>
            {kickoffCandidates.map((row) => (
              <Button
                key={row.vertical}
                type="button"
                size="sm"
                variant="outline"
                disabled={
                  (row.identity_required && row.identity_verified !== true) ||
                  kickoffMutation.isPending
                }
                title={row.blocker ?? undefined}
                onClick={() => kickoffMutation.mutate(row.vertical)}
              >
                {kickoffMutation.isPending && kickoffMutation.variables === row.vertical
                  ? 'Starting…'
                  : `Start fulfillment — ${row.label}`}
              </Button>
            ))}
          </div>
        </div>
      ) : null}
      {error ? <p className="text-xs text-red-700">{error}</p> : null}
    </div>
  )
}

/** U7 attachments — list/upload/download/delete request documents (R20/KD12/KTD9). */
function AttachmentsPanel({ requestId }: { requestId: string }) {
  const queryClient = useQueryClient()
  const { me, isAdmin, isSuperAdmin } = useMe()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)

  const documentsQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId, 'documents'],
    queryFn: () => listRequestDocuments(requestId),
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadRequestDocument(requestId, file),
    onSuccess: async () => {
      setError(null)
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'requests', requestId, 'documents'],
      })
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'Upload failed'),
  })

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => deleteRequestDocument(requestId, documentId),
    onSuccess: async () => {
      setError(null)
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'requests', requestId, 'documents'],
      })
    },
    onError: (err) => setError(err instanceof Error ? err.message : 'Delete failed'),
  })

  const handleDownload = async (doc: RequestDocumentRecord) => {
    setDownloadingId(doc.id)
    setError(null)
    try {
      const blob = await downloadRequestDocument(requestId, doc.id)
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = doc.filename
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Download failed')
    } finally {
      setDownloadingId(null)
    }
  }

  const canDeleteDoc = (doc: RequestDocumentRecord) => {
    if (isAdmin || isSuperAdmin) return true
    const actor = me?.email?.trim().toLowerCase()
    const owner = doc.uploaded_by?.trim().toLowerCase()
    return Boolean(actor && owner && actor === owner)
  }

  const documents = documentsQuery.data ?? []

  return (
    <div className="space-y-3 border-t border-line pt-4 text-xs">
      <div className="flex items-center justify-between gap-2">
        <p className="taste-micro">Attachments</p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={uploadMutation.isPending}
          onClick={() => fileInputRef.current?.click()}
        >
          {uploadMutation.isPending ? 'Uploading…' : 'Upload file'}
        </Button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0]
            event.target.value = ''
            if (file) uploadMutation.mutate(file)
          }}
        />
      </div>
      {documentsQuery.isPending ? <SkeletonLines lines={2} /> : null}
      {!documentsQuery.isPending && documents.length === 0 ? (
        <p className="text-mute">No attachments yet.</p>
      ) : null}
      {documents.length > 0 ? (
        <ul className="space-y-1.5">
          {documents.map((doc) => (
            <li
              key={doc.id}
              className="flex items-center justify-between gap-2 rounded-lg border border-line/80 bg-paper/70 px-3 py-2"
            >
              <div className="min-w-0">
                <p className="truncate text-ink" title={doc.filename}>
                  {doc.filename}
                </p>
                <p className="text-[0.65rem] text-mute">
                  {doc.uploaded_by} · {formatTimestamp(doc.uploaded_at)}
                </p>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={downloadingId === doc.id}
                  onClick={() => handleDownload(doc)}
                >
                  {downloadingId === doc.id ? 'Downloading…' : 'Download'}
                </Button>
                {canDeleteDoc(doc) ? (
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={deleteMutation.isPending}
                    onClick={() => {
                      if (
                        window.confirm(
                          `Delete attachment “${doc.filename}”? This cannot be undone.`,
                        )
                      ) {
                        deleteMutation.mutate(doc.id)
                      }
                    }}
                  >
                    Delete
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      ) : null}
      {error ? <p className="text-red-700">{error}</p> : null}
    </div>
  )
}

export function RequestDetailBody({
  requestId,
  variant = 'overlay',
  defaultTab = 'fulfillment',
  seedRequest,
  vertical = null,
  system = null,
}: {
  requestId: string
  variant?: 'overlay' | 'page'
  defaultTab?: RequestDetailTab
  seedRequest?: RequestRecord | null
  vertical?: string | null
  system?: string | null
}) {
  const queryClient = useQueryClient()
  const { isAdmin, isSuperAdmin, role, me, isLoading: meLoading } = useMe()
  const legalAdmin = isLegalAdminPersona(role)
  const matchingPersona =
    isVerticalOperatorRole(role) ? 'data_owner' : legalAdmin ? 'legal' : 'ops'
  const roleKnown = !meLoading && role != null
  const requestIdReady = isRequestUuid(requestId)
  const [tab, setTab] = useState<RequestDetailTab>(defaultTab)

  useEffect(() => {
    setTab(defaultTab)
  }, [requestId, defaultTab])

  const [selectedTimelineKey, setSelectedTimelineKey] = useState<string | null>(null)
  const [selectedTimelineEntry, setSelectedTimelineEntry] = useState<TimelineEntry | null>(null)

  useEffect(() => {
    setSelectedTimelineKey(null)
    setSelectedTimelineEntry(null)
  }, [requestId])

  const requestQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId],
    queryFn: () => getRequest(requestId),
    enabled: requestIdReady,
    initialData: seedRequest ?? undefined,
    placeholderData: (previous) => previous,
  })

  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId),
    enabled: requestIdReady,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const workbenchQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey-workbench'],
    queryFn: async () => {
      try {
        return await getRequestJourneyWorkbench(requestId)
      } catch (error) {
        // Deployed admin-api may not have U4 yet — fall back to ops journey derivation.
        if (error instanceof Error && /Admin API 404/.test(error.message)) {
          return null
        }
        throw error
      }
    },
    enabled: requestIdReady,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
    retry: false,
  })

  const locationSystem = useLocationSystemParam()
  const ownerVertical =
    matchingPersona === 'data_owner' ? trimScopeId(vertical) : null
  const scopedSystem = trimScopeId(system) ?? locationSystem

  const attentionQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      'overlay',
      requestId,
      ownerVertical,
      scopedSystem,
      matchingPersona,
    ],
    queryFn: () =>
      fetchOverlayAttentionItem(requestId, {
        vertical: ownerVertical,
        system: scopedSystem,
        ownerPersona: matchingPersona === 'data_owner',
      }),
    enabled: requestIdReady,
    staleTime: 10_000,
  })

  const matchingSystem =
    scopedSystem ?? systemFromAttentionItem(attentionQuery.data)
  const matchingQuery = useQuery({
    queryKey:
      matchingPersona === 'data_owner'
        ? [
            'admin-api',
            'ops',
            'requests',
            requestId,
            'verticals',
            ownerVertical,
            'matching-results',
            matchingSystem,
          ]
        : ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () =>
      isVerticalOperatorRole(role)
        ? fetchOwnerVerticalMatchingDetailOptional(
            requestId,
            ownerVertical as string,
            matchingSystem ?? undefined,
          )
        : fetchMatchingDetailOptional(requestId),
    enabled:
      requestIdReady &&
      roleKnown &&
      (role !== 'data_owner' || Boolean(ownerVertical)),
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const artifactQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'fulfillment', 'artifact', requestId],
    queryFn: () => getFulfillmentArtifact(requestId),
    enabled: requestIdReady,
    refetchInterval: 15_000,
    retry: false,
  })

  const identityQuery = useQuery({
    queryKey: ['admin-api', 'requests', requestId, 'identity-verification'],
    queryFn: () => getLatestIdentityVerification(requestId),
    enabled: requestIdReady,
    refetchInterval: 15_000,
  })

  const timelineQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
    queryFn: () => getRequestTimeline(requestId),
    enabled: requestIdReady,
    refetchInterval: 15_000,
    placeholderData: (previous) => previous,
  })

  const commentsQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'comments'],
    queryFn: () => getRequestComments(requestId),
    enabled: requestIdReady,
    refetchInterval: 15_000,
  })
  const [commentDraft, setCommentDraft] = useState('')
  const commentMutation = useMutation({
    mutationFn: (body: string) => postRequestComment(requestId, body),
    onSuccess: async () => {
      setCommentDraft('')
      actionToast.success({ title: 'Note posted', id: `request-comment-${requestId}` })
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', requestId, 'comments'],
      })
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'requests', requestId, 'timeline'],
      })
    },
    onError: (err) => {
      actionToast.error({
        title: "Couldn't post note",
        description: actionToast.safeErrorMessage(err),
      })
    },
  })
  const comments: RequestComment[] = commentsQuery.data ?? []

  const deliveryMutation = useMutation({
    mutationFn: (status: 'delivered' | 'failed' | 'recalled') =>
      patchAccessDeliveryStatus(requestId, { status }),
    onSuccess: async (_data, status) => {
      actionToast.success({
        title: deliverySuccessTitle(status),
        id: `request-delivery-${requestId}`,
      })
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
    },
    onError: (mutationError, status) => {
      actionToast.error({
        title: deliveryErrorTitle(status),
        description: actionToast.safeErrorMessage(mutationError),
        id: `request-delivery-${requestId}`,
        action: {
          label: 'Retry',
          onClick: () => {
            deliveryMutation.mutate(status)
          },
        },
      })
    },
  })

  const matchingDispositionMutation = useMutation({
    mutationFn: async ({
      action,
      responseStatus,
      dwids,
    }: {
      action: 'promote' | 'decline'
      responseStatus?: DropResponseStatusCode
      dwids?: string[]
    }) => {
      if (action === 'promote') {
        return postDropMatchingResultPromote(requestId, {
          response_status: responseStatus,
          ...(responseStatus === 5
            ? { dwids: [] }
            : responseStatus === 3 || responseStatus === 4
              ? { dwids: dwids ?? [] }
              : {}),
          ...(ownerVertical ? { vertical: ownerVertical } : {}),
          ...(matchingSystem ? { system: matchingSystem } : {}),
        })
      }
      return postDropMatchingResultDecline(requestId, {
        ...(ownerVertical ? { vertical: ownerVertical } : {}),
        ...(matchingSystem ? { system: matchingSystem } : {}),
      })
    },
    onSuccess: async (data, variables) => {
      if (variables.action === 'promote') {
        const copy = matchingReviewPromoteToast(
          data && typeof data === 'object' ? data : {},
        )
        if (copy.variant === 'warning') {
          actionToast.warning({
            title: copy.title,
            description: copy.description,
            id: `request-matching-disposition-${requestId}`,
          })
        } else {
          actionToast.success({
            title: copy.title,
            description: copy.description,
            id: `request-matching-disposition-${requestId}`,
          })
        }
      } else {
        const pending =
          data &&
          typeof data === 'object' &&
          'review_status' in data &&
          (data as { review_status?: string }).review_status === 'pending'
        actionToast.success({
          title: pending ? 'System declined' : 'Matching declined',
          description: pending
            ? 'Matching review stays open until remaining systems are decided.'
            : undefined,
          id: `request-matching-disposition-${requestId}`,
        })
      }
      await invalidateAll()
    },
    onError: (mutationError, variables) => {
      actionToast.error({
        title:
          variables.action === 'promote'
            ? "Couldn't approve matching"
            : "Couldn't decline matching",
        description: actionToast.safeErrorMessage(mutationError),
        id: `request-matching-disposition-${requestId}`,
        action: {
          label: 'Retry',
          onClick: () => {
            matchingDispositionMutation.mutate(variables)
          },
        },
      })
    },
  })

  const invalidateAll = async () => {
    await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
  }

  const journey = journeyQuery.data
  const matching = matchingQuery.data
  const attentionItem = attentionQuery.data

  useEffect(() => {
    if (
      matchingPersona === 'data_owner' &&
      matching?.review_status === 'pending' &&
      Boolean(matching.approval_id)
    ) {
      setTab('matching')
    }
  }, [matchingPersona, matching?.review_status, matching?.approval_id])
  const intakeSource = journey?.intake_source ?? requestQuery.data?.intake_source ?? 'manual'
  const displayLabel = requestQuery.data?.display_label
  const requestType = requestQuery.data?.request_type ?? null
  const derivedChrome = journey
    ? deriveWorkbenchChromeFromOpsJourney({
        stages: journey.stages,
        current_stage: journey.current_stage,
        intake_source: intakeSource,
        request_type: requestType,
      })
    : null
  const workbench = workbenchQuery.data
  const railStages = workbench?.stages ?? derivedChrome?.stages ?? []
  const railSubsteps = workbench ? undefined : derivedChrome?.substeps
  const splitPosture = workbench?.split_posture ?? derivedChrome?.split_posture ?? false

  const handleActivitySelect = (entry: TimelineEntry, key: string) => {
    if (selectedTimelineKey === key) {
      setSelectedTimelineKey(null)
      setSelectedTimelineEntry(null)
      return
    }
    setSelectedTimelineKey(key)
    setSelectedTimelineEntry(entry)
    const workbenchStage = timelineEntryWorkbenchStage(entry)
    if (workbenchStage) {
      setTab(workbenchStage)
    }
  }

  const assignmentToLegal = isAssignmentToLegalContext(attentionItem)
  const canMatchingDisposition =
    matching != null &&
    matching.review_status === 'pending' &&
    Boolean(matching.approval_id) &&
    (isSuperAdmin ||
      (legalAdmin && assignmentToLegal) ||
      (isVerticalOperatorRole(role) && !legalAdmin))

  const dropPreMatch =
    intakeSource === 'drop' &&
    matching == null &&
    (journey?.current_stage === 'received' ||
      journey?.current_stage === 'download' ||
      journey?.current_stage === 'land' ||
      journey?.current_stage === 'promote' ||
      journey?.current_stage === 'match')

  const dropResolved =
    intakeSource === 'drop'
      ? resolveDropStatusCode({
          journey,
          matching,
          attentionItem,
        })
      : null
  const dropStatusCode = dropResolved?.code ?? null
  const dropStatusIsRecommended = dropResolved?.isRecommended ?? false

  const stageActions = journey
    ? buildStageActions({
        requestId,
        journeyStage: journey.current_stage,
        attentionItem,
        artifactPending: Boolean(
          artifactQuery.data?.shareable_url || artifactQuery.data?.fulfillment_artifact_uri,
        ),
        accessDelivered: artifactQuery.data?.access_delivery_status === 'delivered',
      })
    : []

  const overlayCallout = useMemo(
    () =>
      resolveOverlayConnectorCallout({
        role,
        assignedVerticals: me?.verticals,
        reminders: me?.connector_reminders,
        attempts: matching?.attempts,
        journeyErrorCodes: [
          journey?.blocker,
          ...(journey?.stages ?? []).map((stage) => stage.blocker),
          ...(matching?.attempts ?? []).map((attempt) => attempt.error_code),
          ...(workbench?.matching_cluster ?? []).map((row) => row.blocker),
          ...(workbench?.fulfillment_cluster ?? []).flatMap((row) => [
            row.blocker,
            ...row.fulfillment_steps.map((step) => step.error_code),
          ]),
        ],
      }),
    [
      role,
      me?.verticals,
      me?.connector_reminders,
      matching?.attempts,
      journey?.blocker,
      journey?.stages,
      workbench?.matching_cluster,
      workbench?.fulfillment_cluster,
    ],
  )

  const loading = requestIdReady && journeyQuery.isPending && !journey

  if (!requestIdReady) {
    return (
      <div className="px-4 py-6 text-xs text-red-700">
        Could not load request journey.
      </div>
    )
  }

  if (loading) {
    return (
      <div className="px-4 py-8">
        <SkeletonLines lines={6} />
      </div>
    )
  }

  if (journeyQuery.isError || !journey) {
    return (
      <div className="px-4 py-6 text-xs text-red-700">
        Could not load request journey.
      </div>
    )
  }

  const pipelineSubsteps = workbench
    ? derivedChrome?.substeps.filter(
        (step) => step.parent === 'ingest' || step.parent === 'notice',
      )
    : railSubsteps

  const selectedStage = isWorkbenchStageKey(tab) ? tab : null

  const pipelineRail =
    workbenchQuery.isPending && !workbench && !derivedChrome ? (
      <p className="text-[0.7rem] text-mute">Loading stage rail…</p>
    ) : (
      <ThinJourneyPipeline
        stages={railStages}
        substeps={pipelineSubsteps}
        matchingCluster={workbench?.matching_cluster}
        fulfillmentCluster={workbench?.fulfillment_cluster}
        splitPosture={splitPosture}
        density={variant === 'page' ? 'comfortable' : 'compact'}
        showSubsteps={false}
        expandedStage={selectedStage}
        onStageActivate={(stage) => {
          if (isWorkbenchStageKey(stage)) setTab(stage)
        }}
      />
    )

  const stageSubsteps = (stageKey: WorkbenchStageKey) => (
    <JourneyStageSubsteps
      stages={railStages}
      stageKey={stageKey}
      substeps={pipelineSubsteps}
      matchingCluster={workbench?.matching_cluster}
      fulfillmentCluster={workbench?.fulfillment_cluster}
      density={variant === 'page' ? 'comfortable' : 'compact'}
    />
  )

  const selectedActivityDetail =
    selectedTimelineEntry && selectedStage ? (
      <div
        id="pipeline-activity-detail"
        role="region"
        aria-label="Selected activity detail"
        className="space-y-2 border-t border-line/70 pt-2"
      >
        <PipelineActivityDetail
          entry={selectedTimelineEntry}
          expandedStage={selectedStage}
          matching={matching}
          matchingPending={matchingQuery.isPending}
          matchingError={matchingQuery.isError}
        />
      </div>
    ) : null

  const commentsColumn = (
    <div className="flex min-h-0 flex-col space-y-2">
      <p className="text-[0.6rem] font-medium uppercase tracking-wide text-mute">
        Comments
        {comments.length > 0 ? (
          <span className="ml-1 tabular-nums opacity-70">({comments.length})</span>
        ) : null}
      </p>
      <div className="min-h-0 flex-1 space-y-1">
        {commentsQuery.isError ? (
          <p className="text-[0.7rem] text-red-700">Could not load comments.</p>
        ) : null}
        {!commentsQuery.isPending && !commentsQuery.isError && comments.length === 0 ? (
          <p className="text-[0.7rem] text-mute">No comments yet.</p>
        ) : null}
        {comments.map((comment) => (
          <div key={comment.id} className="border-b border-line/70 py-1.5 last:border-0">
            <div className="flex flex-wrap items-baseline justify-between gap-1">
              <span className="text-[0.65rem] font-medium text-ink">{comment.actor}</span>
              <span className="tabular-nums text-[0.6rem] text-mute">
                {formatTimestamp(comment.occurred_at)}
              </span>
            </div>
            <p className="whitespace-pre-wrap text-[0.7rem] text-ink-soft">{comment.body}</p>
          </div>
        ))}
      </div>
      <div className="flex shrink-0 items-end gap-2 border-t border-line pt-2">
        <textarea
          className="min-h-[3.5rem] max-h-32 flex-1 resize-y rounded-md border border-line bg-paper px-2 py-1.5 text-xs text-ink"
          value={commentDraft}
          onChange={(event) => setCommentDraft(event.currentTarget.value)}
          placeholder="Add a review note…"
          aria-label="Comment body"
          maxLength={2000}
        />
        <Button
          size="sm"
          disabled={commentMutation.isPending || commentDraft.trim().length === 0}
          onClick={() => commentMutation.mutate(commentDraft.trim())}
        >
          {commentMutation.isPending ? '…' : 'Post'}
        </Button>
      </div>
    </div>
  )

  return (
    <RequestDetailWorkbenchShell
      header={
        <>
          <RequestStageActionBar actions={stageActions} onInvalidate={invalidateAll} />
          {overlayCallout ? (
            <div className="shrink-0 border-b border-line px-4 py-2">
              <OverlayConnectorFreshnessCallout callout={overlayCallout} />
            </div>
          ) : null}
        </>
      }
      rail={pipelineRail}
      side={
        <RequestDetailSideColumn
          activity={
            <ActivityPanel
              requestId={requestId}
              entries={timelineQuery.data?.entries ?? []}
              isPending={timelineQuery.isPending && !timelineQuery.data}
              selectable
              selectedKey={selectedTimelineKey}
              onSelectEntry={handleActivitySelect}
              compact
            />
          }
          comments={commentsColumn}
        />
      }
    >
      <Tabs
        value={tab}
        onValueChange={(value) => setTab(value as RequestDetailTab)}
        className="flex min-h-0 flex-1 flex-col overflow-hidden"
      >
        <div className="shrink-0 border-b border-line px-3 py-1">
          <TabsList
            className="h-8 w-full justify-start gap-1 overflow-x-auto rounded-md border border-line bg-canvas p-0.5"
            aria-label="Request detail sections"
          >
            <TabsTrigger value="details" className={REQUEST_DETAIL_TAB_TRIGGER}>
              Overview
            </TabsTrigger>
            <TabsTrigger value="ingest" className={REQUEST_DETAIL_TAB_TRIGGER}>
              Ingest
            </TabsTrigger>
            <TabsTrigger value="matching" className={REQUEST_DETAIL_TAB_TRIGGER}>
              Matching
            </TabsTrigger>
            <TabsTrigger value="fulfillment" className={REQUEST_DETAIL_TAB_TRIGGER}>
              Fulfillment
            </TabsTrigger>
            <TabsTrigger value="notice" className={REQUEST_DETAIL_TAB_TRIGGER}>
              Notice
            </TabsTrigger>
          </TabsList>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <TabsContent value="details" className="mt-0 px-4 py-3">
            <RequestDetailsPanel
              requestId={requestId}
              intakeSource={intakeSource}
              displayLabel={displayLabel}
              requestContact={requestQuery.data?.contact}
              requestorState={requestQuery.data?.requestor_state}
              identityStatus={identityQuery.data?.status}
              matching={matching}
              dropStatusCode={dropStatusCode}
              dropStatusIsRecommended={dropStatusIsRecommended}
              dropPreMatch={dropPreMatch}
              ownerLanguage={matchingPersona === 'data_owner'}
            />
            <AttachmentsPanel requestId={requestId} />
          </TabsContent>
          <TabsContent value="ingest" className="mt-0 space-y-3 px-4 py-3">
            {stageSubsteps('ingest')}
            {selectedStage === 'ingest' ? selectedActivityDetail : null}
          </TabsContent>
          <TabsContent value="matching" className="mt-0 space-y-3 px-4 py-3">
            {stageSubsteps('matching')}
            {isAuth0MatchingScope(vertical, matchingSystem) ? (
              <Auth0MatchCandidatesList requestId={requestId} />
            ) : null}
            {isSuperAdmin && canMatchingDisposition ? (
              <p className="text-[0.65rem] text-habeas-navy">
                Ops override — you can set the CA DROP status and matched DWIDs, same as data owner.
                This is not Legal kickoff or Fulfillment start.
              </p>
            ) : isSuperAdmin ? (
              <p className="text-[0.65rem] text-mute">
                Ops override available when matching review is pending with an open approval.
              </p>
            ) : assignmentToLegal ? (
              <p className="text-[0.65rem] text-habeas-navy">
                Assignment to legal — review matching context (disposition remains data-owner
                canonical unless escalated here).
              </p>
            ) : legalAdmin ? (
              <p className="text-[0.65rem] text-mute">
                Read-only for legal/admin — matching disposition is data-owner-owned (KTD11).
              </p>
            ) : null}
            <MatchingReviewPanel
              requestId={requestId}
              matching={matching}
              isPending={matchingQuery.isPending}
              isError={matchingQuery.isError}
              canReviewActions={canMatchingDisposition}
              actionPending={matchingDispositionMutation.isPending}
              hideActions={!canMatchingDisposition}
              layout="tabs"
              compact
              connectorReminders={me?.connector_reminders}
              fetchConnectorConnections={Boolean(isAdmin || isSuperAdmin)}
              persona={matchingPersona}
              onPromote={(responseStatus, dwids) =>
                matchingDispositionMutation.mutate({
                  action: 'promote',
                  responseStatus,
                  dwids,
                })
              }
              onDecline={() => matchingDispositionMutation.mutate({ action: 'decline' })}
            />
            {selectedStage === 'matching' ? selectedActivityDetail : null}
          </TabsContent>
          <TabsContent value="fulfillment" className="mt-0 px-4 py-3">
            <div className="space-y-4">
              {stageSubsteps('fulfillment')}
              {matchingPersona === 'data_owner' ? (
                <OwnerFulfillmentStatusPanel
                  requestId={requestId}
                  cluster={workbench?.fulfillment_cluster ?? []}
                  assignedVerticals={me?.verticals}
                  assignedLabels={me?.assigned_vertical_labels}
                  canSubmit={isVerticalOperatorRole(role)}
                />
              ) : null}
              {workbench && matchingPersona !== 'data_owner' && (isSuperAdmin || isAdmin || legalAdmin) ? (
                <FulfillmentGateControls
                  requestId={requestId}
                  rows={workbench.fulfillment_cluster}
                  onInvalidate={invalidateAll}
                />
              ) : null}
              {matchingPersona === 'data_owner' ? null : (
                <>
                  <AccessHandoffPanel
                    requestId={requestId}
                    artifact={artifactQuery.data}
                    isPending={artifactQuery.isPending}
                    isError={artifactQuery.isError}
                    canMutate={Boolean(isSuperAdmin || isAdmin)}
                    busy={deliveryMutation.isPending}
                    onCopyUrl={() => {
                      const url =
                        artifactQuery.data?.shareable_url ??
                        artifactQuery.data?.fulfillment_artifact_uri
                      if (!url) return
                      const copyUrl = () => {
                        void navigator.clipboard.writeText(url).then(() => {
                          actionToast.copied('Copied URL', copyUrl)
                        })
                      }
                      copyUrl()
                    }}
                    onSetStatus={(status) => deliveryMutation.mutate(status)}
                  />
                  <div className="space-y-1">
                    <p className="taste-micro">Identity verification</p>
                    {identityQuery.data ? (
                      <p className="text-xs text-ink-soft">
                        Status:{' '}
                        <span className="capitalize text-ink">{identityQuery.data.status}</span>
                        <span className="text-mute">
                          {' '}
                          · {formatTimestamp(identityQuery.data.verified_at)}
                        </span>
                        {identityQuery.data.method ? (
                          <span className="text-mute">
                            {' '}
                            · {identityQuery.data.method}
                          </span>
                        ) : null}
                      </p>
                    ) : (
                      <p className="text-xs text-mute">
                        None recorded — use Identity verified in stage actions when ready.
                      </p>
                    )}
                  </div>
                  <AccessDeliveryEmailCard requestId={requestId} />
                </>
              )}
              {selectedStage === 'fulfillment' ? selectedActivityDetail : null}
            </div>
          </TabsContent>
          <TabsContent value="notice" className="mt-0 space-y-3 px-4 py-3">
            {stageSubsteps('notice')}
            <p className="text-[0.75rem] text-ink-soft">
              After approval, fulfilled DROP rows enter the next weekly upload batch
              (America/Los_Angeles) — not a consumer delivery URL.
            </p>
            {selectedStage === 'notice' ? selectedActivityDetail : null}
          </TabsContent>
        </div>
      </Tabs>
      {variant === 'overlay' ? (
        <div className="flex shrink-0 flex-wrap gap-2 border-t border-line px-4 py-2">
          <Link
            to="/requests/$requestId"
            params={{ requestId }}
            className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
          >
            Open full page →
          </Link>
          {isSuperAdmin ? (
            <Link
              to="/ops/runs"
              search={{ request_id: requestId }}
              className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline"
            >
              Runs for request →
            </Link>
          ) : null}
        </div>
      ) : null}
    </RequestDetailWorkbenchShell>
  )
}

export function RequestDetailOverlay({
  requestId,
  open,
  onOpenChange,
  returnFocusRef,
  seedRequest,
  vertical = null,
  system = null,
}: RequestDetailOverlayProps) {
  const contentRef = useRef<HTMLDivElement>(null)
  const { role, isLoading: meLoading } = useMe()
  const ownerLanguage = isVerticalOperatorRole(role)
  const roleKnown = !meLoading && role != null
  const locationSystem = useLocationSystemParam()
  const overlaySystem = trimScopeId(system) ?? locationSystem

  useEffect(() => {
    if (!open) return
    const timer = window.setTimeout(() => {
      const focusable = contentRef.current?.querySelector<HTMLElement>(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
      )
      focusable?.focus()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [open, requestId])

  const overlayRequestIdReady = isRequestUuid(requestId)

  // Shared query keys with RequestDetailBody — cache hit, no extra network when body loads.
  const journeyQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'requests', requestId, 'journey'],
    queryFn: () => getRequestJourney(requestId!),
    enabled: open && overlayRequestIdReady,
    placeholderData: (previous) => previous,
  })

  const ownerVertical = ownerLanguage ? trimScopeId(vertical) : null
  const attentionQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      'overlay',
      requestId,
      ownerVertical,
      overlaySystem,
      ownerLanguage ? 'data_owner' : 'ops',
    ],
    queryFn: () =>
      fetchOverlayAttentionItem(requestId!, {
        vertical: ownerVertical,
        system: overlaySystem,
        ownerPersona: ownerLanguage,
      }),
    enabled: open && overlayRequestIdReady,
    staleTime: 10_000,
  })

  const matchingSystem =
    overlaySystem ?? systemFromAttentionItem(attentionQuery.data)
  const matchingQuery = useQuery({
    queryKey: ownerLanguage
      ? [
          'admin-api',
          'ops',
          'requests',
          requestId,
          'verticals',
          ownerVertical,
          'matching-results',
          matchingSystem,
        ]
      : ['admin-api', 'ops', 'drop', 'matching-results', requestId],
    queryFn: () =>
      isVerticalOperatorRole(role)
        ? fetchOwnerVerticalMatchingDetailOptional(
            requestId!,
            ownerVertical as string,
            matchingSystem ?? undefined,
          )
        : fetchMatchingDetailOptional(requestId!),
    enabled:
      open &&
      overlayRequestIdReady &&
      roleKnown &&
      (role !== 'data_owner' || Boolean(ownerVertical)),
    placeholderData: (previous) => previous,
  })

  const intakeSource =
    journeyQuery.data?.intake_source ?? seedRequest?.intake_source ?? 'manual'
  const dropResolved =
    intakeSource === 'drop'
      ? resolveDropStatusCode({
          journey: journeyQuery.data,
          matching: matchingQuery.data,
          attentionItem: attentionQuery.data,
        })
      : null
  const dropStatusCode = dropResolved?.code ?? null
  const dropStatusIsRecommended = dropResolved?.isRecommended ?? false

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={contentRef}
        className={cn(
          'flex h-[96vh] max-h-[96vh] w-[96vw] max-w-[96vw] flex-col gap-0 overflow-hidden p-0',
          'translate-x-[-50%] translate-y-[-50%]',
        )}
        onCloseAutoFocus={(event) => {
          const target = returnFocusRef?.current
          if (target) {
            event.preventDefault()
            target.focus()
          }
        }}
        onEscapeKeyDown={() => onOpenChange(false)}
      >
        <DialogHeader className="shrink-0 space-y-1 border-b border-line px-4 py-2.5 pr-12">
          <div className="flex flex-wrap items-center gap-2">
            <DialogTitle className="font-mono text-sm">
              {requestId
                ? requestDetailHeaderLabel(
                    requestId,
                    intakeSource,
                    seedRequest?.display_label,
                  )
                : '—'}
            </DialogTitle>
            {intakeSource === 'drop' && dropStatusCode != null ? (
              <Badge
                variant="run"
                className="normal-case tracking-normal"
                title={
                  ownerLanguage
                    ? dropStatusIsRecommended
                      ? 'Recommended match result'
                      : 'Match result'
                    : dropStatusIsRecommended
                      ? 'Recommended CA DROP status from matching'
                      : 'CA DROP response status'
                }
              >
                {ownerLanguage
                  ? `Match result · ${ownerDropStatusLabel(dropStatusCode) ?? dropStatusCode}`
                  : `CA DROP · ${dropResponseStatusLabel(dropStatusCode)}`}
                {dropStatusIsRecommended ? ' (recommended)' : ''}
              </Badge>
            ) : intakeSource === 'drop' ? (
              <Badge variant="wait" className="normal-case tracking-normal">
                {ownerLanguage ? 'Match result · pending' : 'CA DROP · status pending'}
              </Badge>
            ) : null}
          </div>
          <DialogDescription className="sr-only">
            Request detail overlay — fulfillment, matching, and activity.
          </DialogDescription>
        </DialogHeader>
        {requestId && open && overlayRequestIdReady ? (
          <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
            <RequestDetailBody
              requestId={requestId}
              variant="overlay"
              defaultTab={ownerLanguage ? 'matching' : 'fulfillment'}
              seedRequest={seedRequest}
              vertical={vertical}
              system={overlaySystem ?? matchingSystem}
            />
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
