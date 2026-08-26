// @ts-nocheck — matching-results-lab is omitted from the product router Register.
/** Matching-results lab — left queue + owner matching-review variations (V01–V10). */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { type ComponentType, useCallback, useEffect, useMemo, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import {
  InboxViewSettingsPopover,
  type InboxViewSettingsPatch,
} from '@/components/inbox/InboxViewSettingsPopover'
import { OwnerMatchingReviewMethodToolbar } from '@/components/inbox-status-lab/StatusLabToolbar'
import { OwnerMatchingReviewV01 } from '@/components/inbox-status-lab/owner-matching-review-v01'
import { OwnerMatchingReviewV02 } from '@/components/inbox-status-lab/owner-matching-review-v02'
import { OwnerMatchingReviewV03 } from '@/components/inbox-status-lab/owner-matching-review-v03'
import { OwnerMatchingReviewV04 } from '@/components/inbox-status-lab/owner-matching-review-v04'
import { OwnerMatchingReviewV05 } from '@/components/inbox-status-lab/owner-matching-review-v05'
import { OwnerMatchingReviewV06 } from '@/components/inbox-status-lab/owner-matching-review-v06'
import { OwnerMatchingReviewV07 } from '@/components/inbox-status-lab/owner-matching-review-v07'
import { OwnerMatchingReviewV08 } from '@/components/inbox-status-lab/owner-matching-review-v08'
import { OwnerMatchingReviewV09 } from '@/components/inbox-status-lab/owner-matching-review-v09'
import { OwnerMatchingReviewV10 } from '@/components/inbox-status-lab/owner-matching-review-v10'
import {
  OWNER_MATCHING_REVIEW_METHODS,
  type OwnerMatchingReviewMethodId,
  readOwnerMatchingReviewMethod,
} from '@/components/inbox-status-lab/status-selector-types'
import {
  dwidsForStatus,
  filterMatchedPeople,
  matchingLabPeopleSource,
  matchingLabRequestId,
  matchingLabResolveSystemId,
  matchingLabTarget,
  parseDropStatusId,
  type MatchingLabPeopleSource,
  type MatchingResultsViewProps,
  type SearchPeopleFn,
} from '@/components/matching-results-lab/matching-results-lab-types'
import {
  fetchMatchingDetailOptional,
  ownerDropStatusLabel,
} from '@/components/requests/RequestTriageDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  canAccessOpsSurfaces,
  ForbiddenState,
  isLegalAdminPersona,
  isVerticalOperatorRole,
  useMe,
} from '@/lib/auth'
import {
  DROP_RESPONSE_STATUS_OPTIONS,
  fetchOwnerVerticalMatchingDetailOptional,
  getAuth0MatchCandidates,
  getNeedsAttention,
  getOwnerMatchingNeedsAttention,
  postDropMatchingResultPromote,
  searchMdrPeople,
  suggestedDropResponseStatus,
  type Auth0MatchCandidate,
  type MatchedPersonContact,
  type MdrPeopleSearchPayload,
  type NeedsAttentionItem,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  buildInboxGroupingStacks,
  inboxDateSourceKey,
  inboxDateSourceLabel,
  inboxIntakeSourceLabel,
  matchTypeLabel,
} from '@/lib/inbox-batch-status'
import {
  coalesceInboxReviewItems,
  expandInboxReviewBySystem,
  inboxItemHasSystem,
  inboxSystemFilterOptions,
  inboxReviewItemKey,
  inboxReviewItemVerticalLabel,
  isInboxIdentifierSurface,
  reviewTargetsFromItem,
  toggleSelectedRequestGroup,
  toggleSelectedRequestId,
} from '@/lib/inbox-status-lab'
import {
  isWorkbenchStageKey,
  opsStageToWorkbench,
  workbenchStageLabel,
  WORKBENCH_STAGE_ORDER,
  type WorkbenchStageKey,
} from '@/lib/legalJourneyLabels'
import { cn, isRequestUuid, paginate } from '@/lib/utils'

import {
  INBOX_LIST_COLLAPSED_COLS,
  INBOX_LIST_EXPANDED_COLS,
  INBOX_LIST_HOVER_FLYOUT,
  InboxCatalogFilterToolbar,
  InboxPaginationBar,
  InboxQueueRows,
  inboxItemTitle,
  catalogOptionsFromItems,
  coerceGroupedInboxRows,
  dueBucket,
  findThreadRow,
  firstIndividualInboxTarget,
  inboxItemSystemId,
  mergeInboxCatalogSearch,
  normalizeInboxItem,
  ownerVisibleInboxItems,
  useInboxListCollapsed,
  type InboxCatalogSearch,
  type InboxStackKind,
} from './needs-attention'

type MatchFilter = 'all' | 'single_match' | 'multi_match' | 'not_found' | 'unknown'
type DueFilter = 'all' | 'overdue' | 'due_soon' | 'on_track'

type OwnerReviewProps = MatchingResultsViewProps & {
  activeSystem?: string | null
  onSelectSystem?: (system: string) => void
}

const OWNER_REVIEW_VIEWS: Partial<
  Record<OwnerMatchingReviewMethodId, ComponentType<OwnerReviewProps>>
> = {
  v01: OwnerMatchingReviewV01,
  v02: OwnerMatchingReviewV02,
  v03: OwnerMatchingReviewV03,
  v04: OwnerMatchingReviewV04,
  v05: OwnerMatchingReviewV05,
  v06: OwnerMatchingReviewV06,
  v07: OwnerMatchingReviewV07,
  v08: OwnerMatchingReviewV08,
  v09: OwnerMatchingReviewV09,
  v10: OwnerMatchingReviewV10,
}

function OwnerMatchingReviewVariation({
  method,
  ...viewProps
}: { method: OwnerMatchingReviewMethodId } & OwnerReviewProps) {
  const Component = OWNER_REVIEW_VIEWS[method]
  if (!Component) {
    const label = OWNER_MATCHING_REVIEW_METHODS.find((row) => row.id === method)?.label ?? method
    return (
      <p className="p-4 text-xs text-ink-soft" role="status">
        Loading variation {label}…
      </p>
    )
  }
  return <Component {...viewProps} />
}

function peopleSourceFromVertical(
  vertical: string | null | undefined,
): MatchingLabPeopleSource | null {
  const id = vertical?.trim().toLowerCase()
  if (id === 'data' || id === 'cassandra') return 'mdr'
  if (id === 'auth0') return 'auth0'
  return null
}

function contactsFromMdrSearch(payload: MdrPeopleSearchPayload): MatchedPersonContact[] {
  return Array.isArray(payload.contacts) ? payload.contacts : []
}

function auth0CandidateToContact(candidate: Auth0MatchCandidate): MatchedPersonContact {
  const row = candidate as Auth0MatchCandidate & Partial<MatchedPersonContact>
  return {
    dwid: row.dwid?.trim() || candidate.vendor_record_id,
    state: row.state ?? '',
    first_initial: row.first_initial ?? null,
    last_initial: row.last_initial ?? null,
    last_name: row.last_name,
    dob: row.dob ?? null,
    email: row.email ?? null,
    phones: row.phones ?? [],
  }
}

function isHumanHeaderLabel(label: string, rawId: string | null | undefined): boolean {
  const trimmed = label.trim()
  if (!trimmed || trimmed === '—' || trimmed === 'Unknown') return false
  const slug = (rawId ?? '').trim()
  if (!slug) return true
  if (trimmed === slug) return false
  const fold = (value: string) => value.toLowerCase().replaceAll(/[\s/_-]+/g, '')
  if (fold(trimmed) === fold(slug) && trimmed === trimmed.toLowerCase()) return false
  return true
}

function inboxItemWorkbenchStep(item: NeedsAttentionItem): WorkbenchStageKey {
  const stage = (item.current_stage ?? '').trim().toLowerCase()
  if (isWorkbenchStageKey(stage)) return stage
  return opsStageToWorkbench(stage) ?? 'ingest'
}

type ActiveTarget =
  | { kind: 'thread'; batchKey: string }
  | { kind: 'request'; itemKey: string }

const INBOX_PAGE_SIZE = 30

export function MatchingResultsLabPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const search = useSearch({ from: '/requests/matching-results-lab' })
  const { role, isAdmin, isLoading: identityLoading, me } = useMe()
  const legalPersona = isLegalAdminPersona(role)
  const dataOwnerPersona = isVerticalOperatorRole(role)
  const canReview = Boolean(isAdmin) || dataOwnerPersona
  const [reviewMethod, setReviewMethod] = useState<OwnerMatchingReviewMethodId>(() =>
    readOwnerMatchingReviewMethod(),
  )

  const [matchFilter, setMatchFilter] = useState<MatchFilter>('all')
  const [dueFilter, setDueFilter] = useState<DueFilter>('all')
  const [activeTarget, setActiveTarget] = useState<ActiveTarget | null>(null)
  const [selectedKeys, setSelectedKeys] = useState<Set<string>>(new Set())
  const [expandedThreads, setExpandedThreads] = useState<Set<string>>(new Set())
  const [statusId, setStatusId] = useState<string | null>(null)
  const [selectedDwids, setSelectedDwids] = useState<string[]>([])
  const [batchDefaultStatus, setBatchDefaultStatus] = useState<string | null>(null)
  const [useBatchDefault, setUseBatchDefault] = useState(true)
  const [mobilePane, setMobilePane] = useState<'queue' | 'detail'>('queue')
  const [page, setPage] = useState(1)
  const [groupByBatch, setGroupByBatch] = useState(true)
  const [groupBySystem, setGroupBySystem] = useState(false)
  const [groupByStatus, setGroupByStatus] = useState(false)
  const [sourceFilter, setSourceFilter] = useState<string | undefined>(undefined)
  const [stepFilter, setStepFilter] = useState<string | undefined>(undefined)
  const [activeConnectionSystem, setActiveConnectionSystem] = useState<string | null>(null)
  const {
    pinnedCollapsed,
    hoverOpen,
    effectiveCollapsed,
    setPinnedCollapsed,
    onRailEnter,
    onRailLeave,
  } = useInboxListCollapsed()

  const verticalFilter = search.vertical?.trim() || undefined
  const systemFilter = search.system?.trim() || undefined
  const inboxFetchLimit = Math.min(1000, page * INBOX_PAGE_SIZE)

  const queueQuery = useQuery({
    queryKey: [
      'admin-api',
      'ops',
      'requests',
      'needs-attention',
      'matching-results-lab',
      dataOwnerPersona ? 'data-owner' : 'ops',
      inboxFetchLimit,
      verticalFilter ?? null,
      systemFilter ?? null,
    ],
    queryFn: () =>
      dataOwnerPersona
        ? getOwnerMatchingNeedsAttention({
            limit: inboxFetchLimit,
            offset: 0,
            vertical: verticalFilter,
            system: systemFilter,
          })
        : getNeedsAttention({
            limit: inboxFetchLimit,
            offset: 0,
            kind: 'matching',
            vertical: verticalFilter,
            system: systemFilter,
          }),
    enabled: canAccessOpsSurfaces(role),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const items = useMemo(() => {
    const raw = queueQuery.data?.items ?? []
    const scoped = dataOwnerPersona ? ownerVisibleInboxItems(raw, me?.verticals) : raw
    const normalized = scoped.map(normalizeInboxItem)
    return coalesceInboxReviewItems(
      dataOwnerPersona ? expandInboxReviewBySystem(normalized) : normalized,
    )
  }, [dataOwnerPersona, me?.verticals, queueQuery.data?.items])

  const matchOptions = useMemo(() => {
    const counts = new Map<MatchFilter, number>()
    for (const item of items) {
      const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
      counts.set(key, (counts.get(key) ?? 0) + 1)
    }
    return (['single_match', 'multi_match', 'not_found', 'unknown'] as MatchFilter[])
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => ({
        id: key,
        label: matchTypeLabel(key, dataOwnerPersona),
        count: counts.get(key) ?? 0,
      }))
  }, [dataOwnerPersona, items])

  const dueOptions = useMemo(() => {
    const counts = new Map<DueFilter, number>()
    for (const item of items) {
      const bucket = dueBucket(item)
      if (bucket === 'unknown') continue
      counts.set(bucket, (counts.get(bucket) ?? 0) + 1)
    }
    return (['overdue', 'due_soon', 'on_track'] as DueFilter[])
      .filter((key) => (counts.get(key) ?? 0) > 0)
      .map((key) => ({
        id: key,
        label: key === 'overdue' ? 'Overdue' : key === 'due_soon' ? 'Soon' : 'On track',
        count: counts.get(key) ?? 0,
      }))
  }, [items])

  const verticalFilterOptions = useMemo(() => {
    if (dataOwnerPersona) {
      const assigned = (me?.assigned_vertical_labels ?? []).map((row) => ({
        id: row.vertical_id,
        label: row.display_label,
      }))
      if (assigned.length > 0) return assigned
    }
    const fromApi = queueQuery.data?.filter_verticals ?? []
    return fromApi.length > 0 ? fromApi : catalogOptionsFromItems(items, 'vertical')
  }, [
    dataOwnerPersona,
    items,
    me?.assigned_vertical_labels,
    queueQuery.data?.filter_verticals,
  ])

  const systemFilterOptions = useMemo(() => {
    const fromApi = queueQuery.data?.filter_systems ?? []
    const options = fromApi.length > 0 ? fromApi : catalogOptionsFromItems(items, 'system')
    return inboxSystemFilterOptions(options, verticalFilter)
  }, [items, queueQuery.data?.filter_systems, verticalFilter])

  const showSystem = systemFilterOptions.length >= 2
  const groupingActive = groupByBatch || (groupBySystem && showSystem) || groupByStatus

  const sourceOptions = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of items) {
      const intake = item.intake_source?.trim()
      if (intake && !isInboxIdentifierSurface(intake)) {
        counts.set(intake, (counts.get(intake) ?? 0) + 1)
      }
    }
    const preferred = ['drop', 'webform', 'csv', 'manual']
    const ordered = preferred.filter((id) => counts.has(id))
    const extras = [...counts.keys()]
      .filter((id) => !preferred.includes(id))
      .sort()
    return [...ordered, ...extras].map((id) => ({
      id,
      label: inboxIntakeSourceLabel(id),
      count: counts.get(id) ?? 0,
    }))
  }, [items])

  const stepOptions = useMemo(() => {
    const counts = new Map<WorkbenchStageKey, number>()
    for (const item of items) {
      const step = inboxItemWorkbenchStep(item)
      counts.set(step, (counts.get(step) ?? 0) + 1)
    }
    return WORKBENCH_STAGE_ORDER.filter((id) => (counts.get(id) ?? 0) > 0).map((id) => ({
      id,
      label: workbenchStageLabel(id),
      count: counts.get(id) ?? 0,
    }))
  }, [items])

  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      if (matchFilter !== 'all') {
        const key = (item.match_type as MatchFilter | undefined) ?? 'unknown'
        if (key !== matchFilter) return false
      }
      if (dueFilter !== 'all' && dueBucket(item) !== dueFilter) return false
      if (verticalFilter && item.vertical?.trim() !== verticalFilter) return false
      if (systemFilter && !inboxItemHasSystem(item, systemFilter)) return false
      if (
        sourceFilter &&
        !isInboxIdentifierSurface(sourceFilter) &&
        item.intake_source?.trim() !== sourceFilter
      ) {
        return false
      }
      if (stepFilter && inboxItemWorkbenchStep(item) !== stepFilter) return false
      return true
    })
  }, [dueFilter, items, matchFilter, sourceFilter, stepFilter, systemFilter, verticalFilter])

  const inboxRows = useMemo(() => {
    if (!groupingActive) {
      return coerceGroupedInboxRows(
        filteredItems.map((item) => ({ kind: 'request' as const, item })),
        false,
      )
    }
    const stacks = buildInboxGroupingStacks(
      filteredItems,
      {
        byDateSource: groupByBatch,
        bySystem: groupBySystem && showSystem,
        byStatus: groupByStatus,
        reminders: me?.connector_reminders,
      },
      dataOwnerPersona,
    )
    const stackKind: InboxStackKind =
      groupByBatch && groupByStatus
        ? 'batch_status'
        : groupByBatch && groupBySystem && showSystem
          ? 'batch_type'
          : groupByStatus
            ? 'status'
            : groupBySystem && showSystem
              ? 'system'
              : 'date_source'
    return coerceGroupedInboxRows(
      stacks.map((stack) => ({
        kind: 'thread' as const,
        stackKind,
        batchKey: stack.key || inboxDateSourceKey(stack.items[0]!),
        batchLabel: stack.label || inboxDateSourceLabel(stack.items[0]!),
        items: stack.items,
      })),
      true,
    )
  }, [
    dataOwnerPersona,
    filteredItems,
    groupByBatch,
    groupByStatus,
    groupBySystem,
    groupingActive,
    me?.connector_reminders,
    showSystem,
  ])

  useEffect(() => {
    setExpandedThreads(new Set())
  }, [groupByBatch, groupBySystem, groupByStatus])

  useEffect(() => {
    setPage(1)
  }, [
    dueFilter,
    groupByBatch,
    groupByStatus,
    groupBySystem,
    matchFilter,
    sourceFilter,
    stepFilter,
    systemFilter,
    verticalFilter,
  ])

  const {
    items: pagedInboxRows,
    totalPages: inboxLocalTotalPages,
    currentPage: inboxCurrentPage,
    start: inboxPageStart,
    end: inboxPageEnd,
    total: inboxPageTotal,
  } = paginate(inboxRows, page, INBOX_PAGE_SIZE)

  const rawInboxTotal = queueQuery.data?.total ?? items.length
  const moreRowsToLoad = items.length < Math.min(rawInboxTotal, 1000)
  const inboxTotalPages = moreRowsToLoad
    ? Math.max(inboxLocalTotalPages, inboxCurrentPage + 1)
    : inboxLocalTotalPages

  const filteredKeys = useMemo(
    () => filteredItems.map((item) => inboxReviewItemKey(item)),
    [filteredItems],
  )
  const allFilteredSelected =
    filteredKeys.length > 0 && filteredKeys.every((key) => selectedKeys.has(key))
  const someFilteredSelected = filteredKeys.some((key) => selectedKeys.has(key))

  useEffect(() => {
    if (inboxRows.length === 0) {
      setActiveTarget(null)
      return
    }
    const stillValid =
      activeTarget != null &&
      (activeTarget.kind === 'thread'
        ? findThreadRow(inboxRows, activeTarget.batchKey) != null
        : filteredItems.some((item) => inboxReviewItemKey(item) === activeTarget.itemKey))
    if (!stillValid) {
      const pick = firstIndividualInboxTarget(inboxRows)
      if (!pick) {
        setActiveTarget(null)
        return
      }
      if (pick.expandBatchKey) {
        setExpandedThreads((previous) => {
          if (previous.has(pick.expandBatchKey!)) return previous
          const next = new Set(previous)
          next.add(pick.expandBatchKey!)
          return next
        })
      }
      setActiveTarget(pick.target)
    }
  }, [activeTarget, filteredItems, inboxRows])

  const activeThread =
    activeTarget?.kind === 'thread' ? findThreadRow(inboxRows, activeTarget.batchKey) : null
  const activeItem =
    activeTarget?.kind === 'request'
      ? (filteredItems.find((item) => inboxReviewItemKey(item) === activeTarget.itemKey) ?? null)
      : (activeThread?.items[0] ?? null)
  const resolvedActiveKey = activeItem ? inboxReviewItemKey(activeItem) : null

  const ownerVertical = dataOwnerPersona ? activeItem?.vertical?.trim() || null : null
  const ownerSystem = dataOwnerPersona && activeItem
    ? (activeConnectionSystem ?? inboxItemSystemId(activeItem))
    : null

  useEffect(() => {
    setActiveConnectionSystem(activeItem ? inboxItemSystemId(activeItem) : null)
  }, [resolvedActiveKey, activeItem?.system, activeItem?.system_id])
  const requestIdReady = Boolean(activeItem && isRequestUuid(activeItem.request_id))

  const matchingQuery = useQuery({
    queryKey: ownerVertical
      ? [
          'admin-api',
          'ops',
          'requests',
          activeItem?.request_id,
          'verticals',
          ownerVertical,
          'matching-results',
          ownerSystem,
          'results-lab',
        ]
      : ['admin-api', 'ops', 'drop', 'matching-results', activeItem?.request_id, 'results-lab'],
    queryFn: () => {
      if (!activeItem) return null
      if (dataOwnerPersona) {
        if (!ownerVertical) return null
        return fetchOwnerVerticalMatchingDetailOptional(
          activeItem.request_id,
          ownerVertical,
          ownerSystem ?? undefined,
        )
      }
      return fetchMatchingDetailOptional(activeItem.request_id)
    },
    enabled:
      canAccessOpsSurfaces(role) &&
      requestIdReady &&
      (!dataOwnerPersona || Boolean(ownerVertical)),
    refetchInterval: 10_000,
    placeholderData: (previous) => previous,
  })

  const detail = matchingQuery.data ?? null
  const contacts = detail?.matched_contacts ?? []
  const peopleSource =
    matchingLabPeopleSource(
      ownerSystem ?? matchingLabResolveSystemId(activeItem, detail),
    ) ?? peopleSourceFromVertical(ownerVertical ?? activeItem?.vertical ?? detail?.vertical)
  const searchRequestId = activeItem ? matchingLabRequestId(activeItem.request_id) : null

  const searchPeople = useCallback<SearchPeopleFn>(
    async (query) => {
      const needle = query.trim()
      if (!needle) return []
      if (peopleSource === 'mdr') {
        // Request-wide GET /ops/drop/matching-contacts/search 403s data_owner.
        if (dataOwnerPersona) {
          actionToast.info({
            id: 'matching-lab-mdr-search-ops-only',
            title: 'Person search is ops-only',
            description: 'Vertical review shows counts and codes only — no PII.',
          })
          return []
        }
        return contactsFromMdrSearch(await searchMdrPeople(needle, { state: 'CA' }))
      }
      if (peopleSource === 'auth0') {
        if (!searchRequestId) return []
        const payload = await getAuth0MatchCandidates(searchRequestId)
        return filterMatchedPeople(
          (payload.candidates ?? []).map(auth0CandidateToContact),
          needle,
        )
      }
      return []
    },
    [dataOwnerPersona, peopleSource, searchRequestId],
  )

  useEffect(() => {
    if (!activeItem) return
    const suggested = suggestedDropResponseStatus(
      detail?.match_type ?? activeItem.match_type,
      detail?.match_count ?? activeItem.match_count,
    )
    const nextStatus = String(suggested)
    setStatusId(nextStatus)
    if (batchDefaultStatus == null) setBatchDefaultStatus(nextStatus)
    setSelectedDwids(nextStatus === '5' ? [] : contacts.map((contact) => contact.dwid))
    setUseBatchDefault(true)
  }, [resolvedActiveKey, detail?.match_type, detail?.match_count, contacts.length])

  const statusOptions = useMemo(
    () =>
      DROP_RESPONSE_STATUS_OPTIONS.map((row) => ({
        id: String(row.code),
        label: dataOwnerPersona ? (ownerDropStatusLabel(row.code) ?? row.label) : row.label,
      })),
    [dataOwnerPersona],
  )

  function patchCatalogSearch(patch: { vertical?: string; system?: string }) {
    void navigate({
      to: '/requests/matching-results-lab',
      search: (prev: InboxCatalogSearch) => mergeInboxCatalogSearch(prev, patch),
      replace: true,
    })
  }

  function handleViewSettingsChange(patch: InboxViewSettingsPatch) {
    if ('groupByBatch' in patch && patch.groupByBatch != null) {
      setGroupByBatch(patch.groupByBatch)
    }
    if ('groupBySystem' in patch && patch.groupBySystem != null) {
      setGroupBySystem(patch.groupBySystem)
    }
    if ('groupByStatus' in patch && patch.groupByStatus != null) {
      setGroupByStatus(patch.groupByStatus)
    }
    if ('matchFilter' in patch && patch.matchFilter != null) {
      setMatchFilter(patch.matchFilter as MatchFilter)
    }
    if ('dueFilter' in patch && patch.dueFilter != null) {
      setDueFilter(patch.dueFilter as DueFilter)
    }
    if ('system' in patch) {
      patchCatalogSearch({ system: patch.system })
    }
    if ('source' in patch) {
      setSourceFilter(patch.source)
    }
    if ('step' in patch) {
      setStepFilter(patch.step)
    }
  }

  function handleStatusChange(next: string) {
    setStatusId(next)
    if (next === '5') setSelectedDwids([])
    else if (selectedDwids.length === 0) {
      setSelectedDwids(contacts.map((contact) => contact.dwid))
    }
    if (useBatchDefault) setUseBatchDefault(false)
  }

  function handleBatchDefaultChange(next: string) {
    setBatchDefaultStatus(next)
    if (useBatchDefault) {
      setStatusId(next)
      setSelectedDwids(next === '5' ? [] : contacts.map((contact) => contact.dwid))
    }
  }

  const applyMutation = useMutation({
    mutationFn: async (input: {
      mode: 'active' | 'selection'
      statusId?: string
      selectedDwids?: string[]
    }) => {
      const responseStatus = parseDropStatusId(input.statusId ?? statusId)
      if (responseStatus == null) throw new Error('missing_status')
      const activeDwids = input.selectedDwids ?? selectedDwids
      const targets =
        input.mode === 'selection'
          ? filteredItems.filter((item) => selectedKeys.has(inboxReviewItemKey(item)))
          : activeItem
            ? [activeItem]
            : []
      let applied = 0
      for (const item of targets) {
        const requestId = matchingLabRequestId(item.request_id)
        if (!requestId) continue
        const postTargets =
          input.mode === 'selection'
            ? reviewTargetsFromItem(item)
            : [
                matchingLabTarget({
                  ...item,
                  system: ownerSystem ?? inboxItemSystemId(item) ?? item.system,
                }),
              ]
        const isActive = inboxReviewItemKey(item) === resolvedActiveKey
        for (const target of postTargets) {
          let rowDwids = isActive
            ? dwidsForStatus(String(responseStatus), contacts, activeDwids)
            : []
          if (!isActive) {
            const rowDetail =
              dataOwnerPersona && target.vertical
                ? await fetchOwnerVerticalMatchingDetailOptional(
                    requestId,
                    target.vertical,
                    target.system ?? undefined,
                  )
                : await fetchMatchingDetailOptional(requestId)
            const rowContacts = rowDetail?.matched_contacts ?? []
            const rowSelected = activeDwids.filter((dwid) =>
              rowContacts.some((contact) => contact.dwid === dwid),
            )
            rowDwids = dwidsForStatus(String(responseStatus), rowContacts, rowSelected)
          }
          if ((responseStatus === 3 || responseStatus === 4) && rowDwids.length === 0) {
            throw new Error('status 3/4 requires at least one person id')
          }
          await postDropMatchingResultPromote(requestId, {
            response_status: responseStatus,
            dwids: rowDwids,
            vertical: target.vertical,
            system: target.system,
          })
          applied += 1
        }
      }
      return { applied }
    },
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'ops'] })
      actionToast.success({
        title: 'Match result applied',
        description: `Updated ${result.applied} item${result.applied === 1 ? '' : 's'}.`,
      })
    },
    onError: (error, input) => {
      actionToast.error({
        title: 'Could not apply match result',
        description: actionToast.safeErrorMessage(error),
        action: { label: 'Retry', onClick: () => applyMutation.mutate(input) },
      })
    },
  })

  function toggleSelected(key: string) {
    setSelectedKeys((previous) => toggleSelectedRequestId(previous, key))
  }

  function toggleThreadSelect(keys: string[]) {
    setSelectedKeys((previous) => toggleSelectedRequestGroup(previous, keys))
  }

  function toggleSelectAll() {
    setSelectedKeys((previous) => {
      if (allFilteredSelected) {
        const next = new Set(previous)
        for (const key of filteredKeys) next.delete(key)
        return next
      }
      const next = new Set(previous)
      for (const key of filteredKeys) next.add(key)
      return next
    })
  }

  function toggleThreadExpand(batchKey: string) {
    setExpandedThreads((previous) => {
      const next = new Set(previous)
      if (next.has(batchKey)) next.delete(batchKey)
      else next.add(batchKey)
      return next
    })
  }

  const applyUsesSelection = selectedKeys.size > 0
  const ownerBlocked = dataOwnerPersona && activeItem != null && !ownerVertical
  const selectedInFilterCount = filteredKeys.filter((key) => selectedKeys.has(key)).length
  const explorerPending = applyMutation.isPending

  if (identityLoading) {
    return <p className="text-sm text-slate-500">Loading identity…</p>
  }
  if (!canAccessOpsSurfaces(role)) {
    return <ForbiddenState />
  }

  if (legalPersona) {
    return (
      <section className="space-y-3 py-6">
        <p className="text-xs text-ink-soft">
          Results lab is for ops and data-owner matching review — open Inbox for Legal work.
        </p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void navigate({ to: '/requests/needs-attention' })}
        >
          Open inbox
        </Button>
      </section>
    )
  }

  const loading = queueQuery.isPending && !queueQuery.data

  const reviewViewProps: MatchingResultsViewProps = {
    item: activeItem,
    detail,
    contacts,
    loading: matchingQuery.isPending && Boolean(activeItem),
    ownerLanguage: dataOwnerPersona,
    statusOptions,
    statusId: useBatchDefault && batchDefaultStatus ? batchDefaultStatus : statusId,
    onStatusChange: handleStatusChange,
    selectedDwids,
    onSelectedDwidsChange: setSelectedDwids,
    disabled: !canReview,
    pending: explorerPending,
    onApply: (draft) =>
      applyMutation.mutate({
        mode: applyUsesSelection ? 'selection' : 'active',
        statusId: draft?.statusId,
        selectedDwids: draft?.selectedDwids,
      }),
    batchDefaultStatus,
    onBatchDefaultStatusChange: handleBatchDefaultChange,
    useBatchDefault,
    onUseBatchDefaultChange: setUseBatchDefault,
    selectedCount: selectedKeys.size,
    onApplySelection: () => applyMutation.mutate({ mode: 'selection' }),
    onSearchPeople: peopleSource ? searchPeople : undefined,
  }

  const reviewTitle = activeItem ? inboxItemTitle(activeItem) : null
  const reviewVertical = activeItem ? inboxReviewItemVerticalLabel(activeItem) : null
  const reviewSource = activeItem ? inboxIntakeSourceLabel(activeItem.intake_source) : null
  const humanReviewVertical =
    reviewVertical && activeItem && isHumanHeaderLabel(reviewVertical, activeItem.vertical)
      ? reviewVertical
      : null
  const humanReviewSource =
    reviewSource && activeItem && isHumanHeaderLabel(reviewSource, activeItem.intake_source)
      ? reviewSource
      : null

  return (
    <section className="flex h-[calc(100vh-5rem)] flex-col gap-2">
      <div className="taste-panel flex min-h-0 flex-1 flex-col overflow-hidden">
        <div
          className={cn(
            'min-w-0 shrink-0 items-center gap-1 overflow-x-auto border-b border-line px-2.5 py-1.5',
            mobilePane === 'detail' ? 'hidden md:flex' : 'flex',
          )}
          role="toolbar"
          aria-label="Inbox filters"
        >
          <InboxCatalogFilterToolbar
            vertical={verticalFilter}
            verticalOptions={verticalFilterOptions}
            onPatch={patchCatalogSearch}
            hideVertical={dataOwnerPersona}
          />
          <InboxViewSettingsPopover
            groupByBatch={groupByBatch}
            groupBySystem={groupBySystem}
            groupByStatus={groupByStatus}
            matchFilter={matchFilter}
            dueFilter={dueFilter}
            systemFilter={systemFilter}
            sourceFilter={sourceFilter}
            stepFilter={stepFilter}
            systemOptions={systemFilterOptions}
            sourceOptions={sourceOptions}
            stepOptions={stepOptions}
            matchOptions={matchOptions}
            dueOptions={dueOptions}
            showSystem={showSystem}
            onChange={handleViewSettingsChange}
          />
          <div className="ml-auto flex shrink-0 items-center gap-2">
            {queueQuery.isFetching && !queueQuery.isPending ? (
              <span className="taste-frost-chip text-[0.65rem]">Refreshing</span>
            ) : null}
            <Badge variant="default" className="normal-case tracking-normal">
              Results lab
            </Badge>
            <OwnerMatchingReviewMethodToolbar
              method={reviewMethod}
              onMethodChange={setReviewMethod}
              className="border-0 bg-transparent px-0 py-0"
            />
          </div>
        </div>

        <div
          className={cn(
            'grid min-h-0 flex-1 grid-cols-1 overflow-hidden',
            pinnedCollapsed
              ? INBOX_LIST_COLLAPSED_COLS
              : INBOX_LIST_EXPANDED_COLS,
          )}
        >
          <div
            className={cn(
              'relative min-h-0',
              mobilePane === 'detail' ? 'hidden md:block' : 'block',
            )}
          >
          <div
            className={cn(
              'flex h-full min-h-0 flex-col border-line bg-paper md:border-r',
              pinnedCollapsed &&
                hoverOpen &&
                INBOX_LIST_HOVER_FLYOUT,
            )}
            onMouseEnter={onRailEnter}
            onMouseLeave={onRailLeave}
          >
            <div
              className={cn(
                'flex items-center gap-2 border-b border-line',
                effectiveCollapsed ? 'justify-center px-1 py-2' : 'flex-wrap px-3 py-2',
              )}
            >
              <button
                type="button"
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md border border-line text-[0.7rem] text-ink-soft hover:border-ink/30 hover:text-ink"
                aria-label={pinnedCollapsed ? 'Keep request list open' : 'Collapse request list'}
                title={pinnedCollapsed ? 'Keep list open' : 'Collapse list'}
                aria-pressed={pinnedCollapsed}
                onClick={() => setPinnedCollapsed(!pinnedCollapsed)}
              >
                {pinnedCollapsed ? '»' : '«'}
              </button>
              {effectiveCollapsed ? null : (
                <>
                  <label className="inline-flex cursor-pointer items-center gap-2 text-xs text-ink-soft">
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 rounded border-line accent-habeas-navy"
                      checked={allFilteredSelected}
                      ref={(element) => {
                        if (element) {
                          element.indeterminate = someFilteredSelected && !allFilteredSelected
                        }
                      }}
                      onChange={toggleSelectAll}
                      disabled={filteredKeys.length === 0}
                      aria-label="Select all matching current filters"
                    />
                    Select all
                  </label>
                  <div className="ml-auto flex items-center gap-2">
                    {selectedKeys.size > 0 ? (
                      <span className="taste-frost-chip tabular-nums text-[0.65rem]">
                        {allFilteredSelected
                          ? `All ${filteredKeys.length}`
                          : `${selectedInFilterCount} of ${filteredKeys.length}`}
                        <button
                          type="button"
                          className="ml-1.5 text-mute hover:text-ink"
                          onClick={() => setSelectedKeys(new Set())}
                          aria-label="Clear selection"
                        >
                          ×
                        </button>
                      </span>
                    ) : null}
                  </div>
                </>
              )}
            </div>

            {effectiveCollapsed ? (
              <div className="min-h-0 flex-1" aria-hidden />
            ) : (
              <div className="min-h-0 flex-1 overflow-y-auto">
                {loading ? (
                  <div className="p-4">
                    <SkeletonLines lines={6} />
                  </div>
                ) : null}
                {queueQuery.isError ? (
                  <div className="space-y-2 p-4">
                    <p className="text-xs text-red-700">Could not load matching items.</p>
                    <Button size="sm" variant="outline" onClick={() => void queueQuery.refetch()}>
                      Retry
                    </Button>
                  </div>
                ) : null}
                {!loading && !queueQuery.isError && filteredItems.length === 0 ? (
                  <p className="p-6 text-xs text-ink-soft">No matching-review items.</p>
                ) : null}

                {!loading && !queueQuery.isError && filteredItems.length > 0 ? (
                  <ul
                    className={cn(
                      groupingActive ? 'space-y-0 bg-canvas/40 p-0' : 'divide-y divide-line',
                    )}
                  >
                    <InboxQueueRows
                      groupingActive={groupingActive}
                      rows={pagedInboxRows}
                      selectedKeys={selectedKeys}
                      activeTarget={activeTarget}
                      expandedThreads={expandedThreads}
                      dataOwnerPersona={dataOwnerPersona}
                      connectorReminders={me?.connector_reminders}
                      onToggleThreadSelect={toggleThreadSelect}
                      onToggleThreadExpand={toggleThreadExpand}
                      onOpenThread={(batchKey) => {
                        toggleThreadExpand(batchKey)
                        setActiveTarget({ kind: 'thread', batchKey })
                        setMobilePane('detail')
                      }}
                      onToggleItem={toggleSelected}
                      onOpenItem={(itemKey) => {
                        setActiveTarget({ kind: 'request', itemKey })
                        setMobilePane('detail')
                      }}
                    />
                  </ul>
                ) : null}
              </div>
            )}

            {!effectiveCollapsed && !loading && !queueQuery.isError && filteredItems.length > 0 ? (
              <InboxPaginationBar
                start={inboxPageStart}
                end={inboxPageEnd}
                total={inboxPageTotal}
                currentPage={inboxCurrentPage}
                totalPages={inboxTotalPages}
                onPrev={() => setPage(Math.max(1, inboxCurrentPage - 1))}
                onNext={() => setPage(Math.min(inboxTotalPages, inboxCurrentPage + 1))}
              />
            ) : null}
          </div>
          </div>

          <div
            className={cn(
              'flex h-full min-h-0 min-w-0 flex-col overflow-hidden',
              mobilePane === 'queue' ? 'hidden md:flex' : 'flex',
            )}
          >
            {activeItem ? (
              <div className="flex h-full min-h-0 flex-col overflow-hidden">
                <div className="shrink-0 space-y-2 border-b border-line px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setMobilePane('queue')}
                    className="text-[0.7rem] font-medium text-habeas-navy underline-offset-2 hover:underline md:hidden"
                  >
                    ← Queue
                  </button>
                  {reviewTitle ? (
                    <p className="text-sm font-semibold text-ink">{reviewTitle}</p>
                  ) : null}
                  {humanReviewSource || humanReviewVertical ? (
                    <p className="text-[0.65rem] text-ink-soft">
                      {[humanReviewSource, humanReviewVertical].filter(Boolean).join(' · ')}
                    </p>
                  ) : null}
                  {activeItem.request_id ? (
                    <span className="sr-only">Request {activeItem.request_id}</span>
                  ) : null}
                  {activeThread ? (
                    <p className="text-[0.65rem] text-ink-soft">
                      {activeThread.batchLabel} · {activeThread.items.length} items · reviewing first
                    </p>
                  ) : null}
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
                  {ownerBlocked ? (
                    <p className="text-xs text-ink-soft">
                      Owner matching results use the vertical URL. This row has no vertical.
                    </p>
                  ) : matchingQuery.isError ? (
                    <div className="space-y-2">
                      <p className="text-xs text-ink-soft">Could not load matching results.</p>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void matchingQuery.refetch()}
                      >
                        Retry
                      </Button>
                    </div>
                  ) : (
                    <OwnerMatchingReviewVariation
                      method={reviewMethod}
                      activeSystem={ownerSystem}
                      onSelectSystem={setActiveConnectionSystem}
                      {...reviewViewProps}
                    />
                  )}
                </div>
              </div>
            ) : (
              <div className="flex h-full items-center justify-center p-8 text-xs text-ink-soft">
                {loading ? 'Loading review queue…' : 'Select a request to review.'}
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  )
}
