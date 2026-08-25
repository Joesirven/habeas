export type InboxStatusOption = { id: string; label: string }

export type StatusSelectorProps = {
  value: string | null
  onChange: (statusId: string) => void
  options: InboxStatusOption[]
  scope: 'batch' | 'request'
  disabled?: boolean
  pending?: boolean
  layout?: 'default' | 'toolbar'
}

export const STATUS_LAB_METHODS = [
  { id: 'native-select', label: '1 · Native select' },
  { id: 'segmented', label: '2 · Segmented pills' },
  { id: 'radio-popover', label: '3 · Radio popover' },
  { id: 'combobox', label: '4 · Searchable combobox' },
  { id: 'split-button', label: '5 · Split button' },
  { id: 'inline-chips', label: '6 · Inline chips' },
  { id: 'command-palette', label: '7 · Command palette' },
  { id: 'stepper-confirm', label: '8 · Step + confirm' },
  { id: 'two-tier', label: '9 · Batch default + row override' },
  { id: 'apply-selection', label: '10 · Apply to selected rows' },
] as const

export type StatusLabMethodId = (typeof STATUS_LAB_METHODS)[number]['id']

export const STATUS_LAB_METHOD_STORAGE_KEY = 'habeas-cli.inbox-status-lab.method'

export function readStatusLabMethod(): StatusLabMethodId {
  try {
    const raw = localStorage.getItem(STATUS_LAB_METHOD_STORAGE_KEY)
    if (raw && STATUS_LAB_METHODS.some((row) => row.id === raw)) {
      return raw as StatusLabMethodId
    }
  } catch {
    /* private mode / blocked storage */
  }
  return 'two-tier'
}

export function writeStatusLabMethod(method: StatusLabMethodId): void {
  try {
    localStorage.setItem(STATUS_LAB_METHOD_STORAGE_KEY, method)
  } catch {
    /* private mode / blocked storage */
  }
}

/** Ten matching-results render philosophies. Ids stay aligned with status-lab methods. */
export const MATCHING_RESULT_LAB_METHODS = [
  { id: 'native-select', label: '1 · Spreadsheet table' },
  { id: 'segmented', label: '2 · Decision cards' },
  { id: 'radio-popover', label: '3 · Compact + popover' },
  { id: 'combobox', label: '4 · Search-first' },
  { id: 'split-button', label: '5 · Primary + overflow' },
  { id: 'inline-chips', label: '6 · Chip density' },
  { id: 'command-palette', label: '7 · Keyboard commands' },
  { id: 'stepper-confirm', label: '8 · Linear wizard' },
  { id: 'two-tier', label: '9 · Summary + rows (default)' },
  { id: 'apply-selection', label: '10 · Full-page columns' },
] as const

export type MatchingResultLabMethodId = (typeof MATCHING_RESULT_LAB_METHODS)[number]['id']

export const MATCHING_RESULT_LAB_METHOD_STORAGE_KEY =
  'habeas-cli.matching-results-lab.method'

export function readMatchingResultLabMethod(): MatchingResultLabMethodId {
  try {
    const raw = localStorage.getItem(MATCHING_RESULT_LAB_METHOD_STORAGE_KEY)
    if (raw && MATCHING_RESULT_LAB_METHODS.some((row) => row.id === raw)) {
      return raw as MatchingResultLabMethodId
    }
  } catch {
    /* private mode / blocked storage */
  }
  return 'two-tier'
}

export function writeMatchingResultLabMethod(method: MatchingResultLabMethodId): void {
  try {
    localStorage.setItem(MATCHING_RESULT_LAB_METHOD_STORAGE_KEY, method)
  } catch {
    /* private mode / blocked storage */
  }
}

/** Owner matching-review lab — 10 layout philosophies. Default v10 (two-tier). */
export const OWNER_MATCHING_REVIEW_METHODS = [
  { id: 'v01', label: '1 · Operator table' },
  { id: 'v02', label: '2 · KPI + table' },
  { id: 'v03', label: '3 · Split meta / table' },
  { id: 'v04', label: '4 · Case file' },
  { id: 'v05', label: '5 · Evidence cards' },
  { id: 'v06', label: '6 · Narrative columns' },
  { id: 'v07', label: '7 · Decision first' },
  { id: 'v08', label: '8 · Hero person' },
  { id: 'v09', label: '9 · Guided confirm' },
  { id: 'v10', label: '10 · Two-tier (default)' },
] as const

export type OwnerMatchingReviewMethodId = (typeof OWNER_MATCHING_REVIEW_METHODS)[number]['id']

export const OWNER_MATCHING_REVIEW_METHOD_STORAGE_KEY =
  'habeas-cli.owner-matching-review.method'

export function readOwnerMatchingReviewMethod(): OwnerMatchingReviewMethodId {
  try {
    const raw = localStorage.getItem(OWNER_MATCHING_REVIEW_METHOD_STORAGE_KEY)
    if (raw === 'two-tier') return 'v10'
    if (raw && OWNER_MATCHING_REVIEW_METHODS.some((row) => row.id === raw)) {
      return raw as OwnerMatchingReviewMethodId
    }
  } catch {
    /* private mode / blocked storage */
  }
  return 'v10'
}

export function writeOwnerMatchingReviewMethod(method: OwnerMatchingReviewMethodId): void {
  try {
    localStorage.setItem(OWNER_MATCHING_REVIEW_METHOD_STORAGE_KEY, method)
  } catch {
    /* private mode / blocked storage */
  }
}
