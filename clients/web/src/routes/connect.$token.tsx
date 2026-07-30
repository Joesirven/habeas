import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  getConnectPreview,
  redeemConnect,
  type ConnectPreviewPayload,
} from '@/lib/api'

type CredentialField = ConnectPreviewPayload['fields'][number]

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

/** Allowlisted admin-api `detail` strings — never echo credential values or vendor bodies. */
const SAFE_API_ERROR_DETAILS: Record<string, string> = {
  'invite not found': 'This invite link is invalid or has expired.',
  'this connection cannot be redeemed via invite':
    'This connection cannot be completed through an invite link. Contact Habeas.',
}

/** Allowlisted connection-test codes from admin-api (`last_test_detail` contract). */
const SAFE_TEST_DETAIL_MESSAGES: Record<string, string> = {
  missing_credentials: 'Connection test could not run. Check the fields and try again.',
  unknown_system: 'Connection test failed. Ask your Habeas contact to send a new invite.',
  infra_only:
    'This system is provisioned by Habeas Infrastructure, not through this form.',
}

function safeApiDetail(detail: string, fallback: string): string {
  const normalized = detail.trim().toLowerCase()
  if (SAFE_API_ERROR_DETAILS[normalized]) {
    return SAFE_API_ERROR_DETAILS[normalized]
  }
  if (
    normalized.startsWith('missing required credential field:') ||
    normalized.startsWith('unknown credential fields for') ||
    normalized.startsWith('credential field ') ||
    normalized.includes('does not accept credentials via invite')
  ) {
    return 'Could not save credentials. Check the fields and try again.'
  }
  return fallback
}

function friendlyApiError(error: unknown, fallback: string): string {
  if (!(error instanceof Error)) return fallback
  const match = error.message.match(/Admin API \d+: (.+)/)
  if (match) {
    try {
      const parsed = JSON.parse(match[1]) as { detail?: unknown }
      if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
        return safeApiDetail(parsed.detail, fallback)
      }
    } catch {
      // fall through
    }
    if (error.message.includes('404')) {
      return 'This invite link is invalid or has expired.'
    }
  }
  return fallback
}

function formatTestFailureDetail(detail: string | null | undefined): string {
  const code = detail?.trim().toLowerCase()
  if (code && SAFE_TEST_DETAIL_MESSAGES[code]) {
    return SAFE_TEST_DETAIL_MESSAGES[code]
  }
  return 'Connection test failed. Ask your Habeas contact to send a new invite.'
}

function formatExpiresAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function TrustCopy({ text }: { text: string }) {
  const paragraphs = useMemo(
    () => text.split(/\n\n+/).map((part) => part.trim()).filter(Boolean),
    [text],
  )
  return (
    <div className="space-y-3 text-sm leading-relaxed text-[#64748B]">
      {paragraphs.map((paragraph, index) => (
        <p key={index}>{paragraph}</p>
      ))}
    </div>
  )
}

function CredentialInput({
  field,
  value,
  onChange,
  disabled,
}: {
  field: CredentialField
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}) {
  const inputType =
    field.input_type === 'password' ? 'password' : field.input_type === 'url' ? 'url' : 'text'

  return (
    <div className="space-y-1.5">
      <label htmlFor={field.id} className="block text-sm font-medium text-[#0F172A]">
        {field.label}
        {field.required ? <span className="text-[#64748B]"> · required</span> : null}
      </label>
      <input
        id={field.id}
        name={field.id}
        type={inputType}
        autoComplete="off"
        required={field.required}
        disabled={disabled}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className={FIELD_CLASS}
      />
      {field.help ? <p className="text-xs text-[#64748B]">{field.help}</p> : null}
    </div>
  )
}

function ConnectShell({ children }: { children: ReactNode }) {
  return (
    <div className="fixed inset-0 z-30 overflow-y-auto bg-[#F8FAFC]">
      <div className="mx-auto flex min-h-full max-w-lg flex-col px-4 py-10 sm:px-6 sm:py-14">
        <header className="mb-8 text-center">
          <img
            src="/habeas-logo.png"
            alt="Habeas"
            width={160}
            height={69}
            className="mx-auto h-10 w-auto"
            draggable={false}
          />
          <p className="mt-4 text-xs font-medium uppercase tracking-[0.14em] text-[#64748B]">
            Data Privacy Platform
          </p>
        </header>
        <main className="flex-1">{children}</main>
        <footer className="mt-10 text-center text-xs text-[#64748B]">
          Habeas · secure integration onboarding
        </footer>
      </div>
    </div>
  )
}

function ConnectCard({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-[#E2E8F0] bg-white p-6 shadow-sm sm:p-8">
      {children}
    </div>
  )
}

function ConnectForm({
  preview,
  token,
}: {
  preview: ConnectPreviewPayload
  token: string
}) {
  const [credentials, setCredentials] = useState<Record<string, string>>(() =>
    Object.fromEntries(preview.fields.map((field) => [field.id, ''])),
  )
  const [clientError, setClientError] = useState<string | null>(null)

  const redeemMutation = useMutation({
    mutationFn: (payload: Record<string, string>) => redeemConnect(token, payload),
    onMutate: () => setClientError(null),
  })

  const submitError =
    clientError ??
    (redeemMutation.isError
      ? friendlyApiError(
          redeemMutation.error,
          'Could not save credentials. Check the fields and try again.',
        )
      : null)

  const testFailed =
    redeemMutation.isSuccess && redeemMutation.data && !redeemMutation.data.test_ok

  const testFailureMessage = testFailed
    ? formatTestFailureDetail(redeemMutation.data?.detail)
    : null

  if (redeemMutation.isSuccess && redeemMutation.data.test_ok) {
    return (
      <ConnectCard>
        <div className="space-y-3 text-center">
          <div
            className="mx-auto flex size-12 items-center justify-center rounded-full bg-habeas-navy/10 text-habeas-navy"
            aria-hidden
          >
            <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <h1 className="text-xl font-medium text-[#0F172A]">Connected</h1>
          <p className="text-sm text-[#64748B]">You can close this page.</p>
        </div>
      </ConnectCard>
    )
  }

  function updateField(fieldId: string, value: string) {
    setCredentials((current) => ({ ...current, [fieldId]: value }))
  }

  function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    for (const field of preview.fields) {
      if (field.required && !credentials[field.id]?.trim()) {
        setClientError(`Enter ${field.label.toLowerCase()}.`)
        return
      }
    }
    redeemMutation.mutate(credentials)
  }

  return (
    <ConnectCard>
      <div className="space-y-6">
        <header className="space-y-2">
          <p className="text-xs font-medium uppercase tracking-wide text-habeas-navy">
            Secure connection
          </p>
          <h1 className="text-xl font-medium tracking-tight text-[#0F172A]">
            {preview.display_name}
          </h1>
          <p className="text-sm text-[#64748B]">
            For <span className="text-[#0F172A]">{preview.owner_email}</span>
          </p>
        </header>

        <TrustCopy text={preview.trust_copy} />

        <p className="rounded-md border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-2 text-xs text-[#64748B]">
          This link expires{' '}
          <time dateTime={preview.expires_at}>{formatExpiresAt(preview.expires_at)}</time>.
        </p>

        {preview.fields.length === 0 ? (
          <p className="text-sm text-[#64748B]">
            No credentials are collected on this page. Contact Habeas if you expected a form.
          </p>
        ) : (
          <form className="space-y-4" onSubmit={handleSubmit} noValidate>
            {preview.fields.map((field) => (
              <CredentialInput
                key={field.id}
                field={field}
                value={credentials[field.id] ?? ''}
                onChange={(value) => updateField(field.id, value)}
                disabled={redeemMutation.isPending}
              />
            ))}

            {submitError ? (
              <p className="text-sm text-red-700" role="alert">
                {submitError}
              </p>
            ) : null}
            {testFailed ? (
              <p className="text-sm text-red-700" role="alert">
                {testFailureMessage}
              </p>
            ) : null}

            <Button
              type="submit"
              disabled={redeemMutation.isPending}
              className="h-10 w-full bg-habeas-navy text-sm hover:bg-habeas-navy/90"
            >
              {redeemMutation.isPending ? 'Connecting…' : 'Connect securely'}
            </Button>
          </form>
        )}
      </div>
    </ConnectCard>
  )
}

export function ConnectTokenPage() {
  const { token } = useParams({ from: '/connect/$token' })

  const previewQuery = useQuery({
    queryKey: ['admin-api', 'connect', token],
    queryFn: () => getConnectPreview(token),
    retry: false,
  })

  return (
    <ConnectShell>
      {previewQuery.isPending ? (
        <ConnectCard>
          <div className="space-y-3" role="status" aria-label="Loading connection invite">
            <div className="h-4 w-2/3 animate-pulse rounded bg-[#E2E8F0]" />
            <div className="h-4 w-full animate-pulse rounded bg-[#E2E8F0]" />
            <div className="h-24 w-full animate-pulse rounded bg-[#E2E8F0]" />
          </div>
        </ConnectCard>
      ) : previewQuery.isError ? (
        <ConnectCard>
          <div className="space-y-3 text-center">
            <h1 className="text-lg font-medium text-[#0F172A]">Link unavailable</h1>
            <p className="text-sm text-[#64748B]">
              {friendlyApiError(
                previewQuery.error,
                'This invite link is invalid or has expired.',
              )}
            </p>
          </div>
        </ConnectCard>
      ) : previewQuery.data ? (
        <ConnectForm preview={previewQuery.data} token={token} />
      ) : null}
    </ConnectShell>
  )
}
