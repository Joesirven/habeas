import { toast } from 'sonner'

export type ActionToastAction = {
  label: string
  onClick: () => void
}

export type ActionToastInput = {
  title: string
  description?: string
  action?: ActionToastAction
  id?: string | number
  duration?: number
}

const GENERIC_ERROR = 'Something went wrong. Try again.'

/** Allowlisted API detail strings → operator-facing copy (no raw dumps). */
export const SAFE_API_ERROR_DETAILS: Record<string, string> = {
  'invite not found': 'This invite link is invalid or has expired.',
  'this connection cannot be redeemed via invite':
    'This connection cannot be completed through an invite link. Contact Habeas.',
  'invite expired': 'This invite link has expired. Ask for a new invite.',
  'invite already used': 'This invite link was already used.',
  'connection not found': 'That connection could not be found.',
  'invalid credentials': 'The credentials could not be verified.',
  'test failed': 'Connection test failed. Check the values and try again.',
  unauthorized: 'You are not allowed to do that.',
  forbidden: 'You are not allowed to do that.',
  missing_credentials: 'Connection test could not run. Check the fields and try again.',
  unknown_system: 'Connection test failed. Ask your Habeas contact to send a new invite.',
  infra_only:
    'This system is provisioned by Habeas Infrastructure, not through this form.',
}

function isCredentialFieldNoise(detail: string): boolean {
  const normalized = detail.trim().toLowerCase()
  return (
    normalized.startsWith('missing required credential field:') ||
    normalized.startsWith('unknown credential fields for') ||
    normalized.startsWith('credential field ') ||
    normalized.includes('does not accept credentials via invite')
  )
}

const SUCCESS_DURATION_MS = 6_000
const SUCCESS_NAVIGATE_DURATION_MS = 10_000
const ERROR_DURATION_MS = Number.POSITIVE_INFINITY

function dismissAction(): ActionToastAction {
  return {
    label: 'Dismiss',
    onClick: () => {
      /* Sonner closes on action click by default */
    },
  }
}

function resolveAction(action?: ActionToastAction): ActionToastAction {
  return action ?? dismissAction()
}

function extractAdminApiDetail(message: string): string | null {
  const match = message.match(/^Admin API \d+:\s*([\s\S]+)$/i)
  if (!match) return null
  const raw = match[1]?.trim()
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed === 'object' && parsed !== null && 'detail' in parsed) {
      const detail = (parsed as { detail: unknown }).detail
      if (typeof detail === 'string') return detail
      return null
    }
  } catch {
    if (!raw.startsWith('{') && !raw.startsWith('[')) return raw
  }
  return null
}

/** Map unknown errors to privacy-safe toast copy. Never echo raw API bodies. */
export function safeErrorMessage(error: unknown, fallback = GENERIC_ERROR): string {
  if (error == null) return fallback
  if (typeof error === 'string') {
    const normalized = error.trim().toLowerCase()
    if (SAFE_API_ERROR_DETAILS[normalized]) return SAFE_API_ERROR_DETAILS[normalized]
    if (isCredentialFieldNoise(error)) {
      return 'Could not save credentials. Check the fields and try again.'
    }
    return fallback
  }
  if (error instanceof Error) {
    const detail = extractAdminApiDetail(error.message)
    if (detail) {
      const normalized = detail.trim().toLowerCase()
      if (SAFE_API_ERROR_DETAILS[normalized]) return SAFE_API_ERROR_DETAILS[normalized]
      if (isCredentialFieldNoise(detail)) {
        return 'Could not save credentials. Check the fields and try again.'
      }
      return fallback
    }
    if (error.message.includes('404')) {
      return 'This invite link is invalid or has expired.'
    }
    const normalized = error.message.trim().toLowerCase()
    if (SAFE_API_ERROR_DETAILS[normalized]) return SAFE_API_ERROR_DETAILS[normalized]
    return fallback
  }
  return fallback
}

function show(
  kind: 'success' | 'error' | 'warning' | 'info',
  input: ActionToastInput,
  defaultDuration: number,
) {
  const action = resolveAction(input.action)
  const opts = {
    id: input.id,
    description: input.description,
    duration: input.duration ?? defaultDuration,
    action: {
      label: action.label,
      onClick: action.onClick,
    },
  }
  switch (kind) {
    case 'success':
      return toast.success(input.title, opts)
    case 'error':
      return toast.error(input.title, opts)
    case 'warning':
      return toast.warning(input.title, opts)
    case 'info':
      return toast.info(input.title, opts)
  }
}

export const actionToast = {
  success(input: ActionToastInput) {
    return show('success', input, SUCCESS_DURATION_MS)
  },
  /** Longer-lived success after navigate-away. */
  successAfterNavigate(input: ActionToastInput) {
    return show('success', input, SUCCESS_NAVIGATE_DURATION_MS)
  },
  error(input: ActionToastInput) {
    return show('error', input, ERROR_DURATION_MS)
  },
  warning(input: ActionToastInput) {
    return show('warning', input, ERROR_DURATION_MS)
  },
  info(input: ActionToastInput) {
    return show('info', input, SUCCESS_DURATION_MS)
  },
  /** Clipboard success — fixed title only; never put copied value in description. */
  copied(label: string, onCopyAgain?: () => void) {
    return show(
      'success',
      {
        title: label,
        action: onCopyAgain
          ? { label: 'Copy again', onClick: onCopyAgain }
          : dismissAction(),
      },
      SUCCESS_DURATION_MS,
    )
  },
  promise<T>(
    work: Promise<T>,
    messages: {
      loading: string
      success: (data: T) => ActionToastInput
      error: (err: unknown) => ActionToastInput
      id?: string | number
    },
  ) {
    return toast.promise(work, {
      id: messages.id,
      loading: messages.loading,
      success: (data) => {
        const next = messages.success(data)
        const action = resolveAction(next.action)
        return {
          message: next.title,
          description: next.description,
          duration: next.duration ?? SUCCESS_NAVIGATE_DURATION_MS,
          action: { label: action.label, onClick: action.onClick },
        }
      },
      error: (err) => {
        const next = messages.error(err)
        const action = resolveAction(next.action)
        return {
          message: next.title,
          description: next.description ?? safeErrorMessage(err),
          duration: next.duration ?? ERROR_DURATION_MS,
          action: { label: action.label, onClick: action.onClick },
        }
      },
    })
  },
  dismiss: toast.dismiss,
  safeErrorMessage,
}
