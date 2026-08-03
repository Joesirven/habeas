import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useEffect, useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import {
  connectRedeemSystemLabel,
  connectTestFailureMessage,
  connectTestSuccessDescription,
  getConnectPreview,
  getMe,
  redeemConnect,
  type ConnectPreviewPayload,
  type MePayload,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'

type CredentialField = ConnectPreviewPayload['fields'][number]

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

/** Allowlisted admin-api `detail` strings — never echo credential values or vendor bodies. */
const SAFE_API_ERROR_DETAILS: Record<string, string> = {
  'invite not found': 'This invite link is invalid or has expired.',
  'this connection cannot be redeemed via invite':
    'This connection cannot be completed through an invite link. Contact Habeas.',
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

function RedeemPendingOverlay({ systemLabel }: { systemLabel: string }) {
  const [phase, setPhase] = useState<'saving' | 'testing'>('saving')

  useEffect(() => {
    const timer = window.setTimeout(() => setPhase('testing'), 1800)
    return () => window.clearTimeout(timer)
  }, [])

  const message =
    phase === 'saving'
      ? 'Saving credentials securely…'
      : `Testing ${systemLabel} connection…`

  return (
    <div
      className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-lg bg-white/90 px-6 text-center backdrop-blur-[2px]"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={message}
    >
      <span
        className="mb-3 inline-block size-8 animate-spin rounded-full border-2 border-habeas-navy/20 border-t-habeas-navy"
        aria-hidden
      />
      <p className="text-sm font-medium text-[#0F172A]">{message}</p>
    </div>
  )
}

function formatExpiresAt(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  })
}

function formatExpiresIn(iso: string): string {
  const ends = new Date(iso).getTime()
  if (Number.isNaN(ends)) return formatExpiresAt(iso)
  const ms = ends - Date.now()
  if (ms <= 0) return 'already expired'
  const hours = Math.floor(ms / (1000 * 60 * 60))
  const minutes = Math.floor((ms % (1000 * 60 * 60)) / (1000 * 60))
  if (hours >= 48) {
    const days = Math.floor(hours / 24)
    return `in about ${days} day${days === 1 ? '' : 's'}`
  }
  if (hours >= 1) {
    return `in about ${hours} hour${hours === 1 ? '' : 's'}`
  }
  return `in about ${Math.max(1, minutes)} minute${minutes === 1 ? '' : 's'}`
}

function firstNameFromEmail(email: string): string {
  const local = email.split('@')[0]?.trim() ?? ''
  if (!local) return 'there'
  const token = local.split(/[._+-]/)[0] ?? local
  if (!token) return 'there'
  return token.charAt(0).toUpperCase() + token.slice(1).toLowerCase()
}

function emailsMatch(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase()
}

type WizardStep = 'confirm' | 'instructions' | 'credentials'

function WizardProgress({ step }: { step: WizardStep }) {
  const steps: { id: WizardStep; label: string }[] = [
    { id: 'confirm', label: 'Confirm' },
    { id: 'instructions', label: 'Privacy' },
    { id: 'credentials', label: 'Credentials' },
  ]
  const activeIndex = steps.findIndex((entry) => entry.id === step)
  return (
    <ol className="mb-6 flex gap-2" aria-label="Setup steps">
      {steps.map((entry, index) => {
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
                  : 'border-[#E2E8F0] bg-[#F8FAFC] text-[#475569]'
            }`}
          >
            {index + 1}. {entry.label}
          </li>
        )
      })}
    </ol>
  )
}

/** Original silver logo — sits on a dark navy band for contrast. */
function HabeasConnectLogo() {
  return (
    <img
      src="/habeas-logo.png"
      alt="Habeas"
      width={200}
      height={86}
      className="mx-auto h-11 w-auto sm:h-12"
      draggable={false}
    />
  )
}

function PrivacySecuritySection({ expiresAt }: { expiresAt: string }) {
  return (
    <section className="space-y-4 text-sm leading-relaxed text-[#334155]" aria-labelledby="connect-privacy-heading">
      <h2 id="connect-privacy-heading" className="sr-only">
        Privacy and security
      </h2>
      <p>
        This form is secure. Credentials you paste here go straight into{' '}
        <span className="font-medium text-[#0F172A]">Google Cloud Secret Manager</span>. They are
        not stored in the Data Privacy app database, and other people who use the site cannot open
        or copy them.
      </p>
      <p>
        This invite link expires{' '}
        <span className="font-medium text-[#0F172A]">{formatExpiresIn(expiresAt)}</span> (
        <time dateTime={expiresAt}>{formatExpiresAt(expiresAt)}</time>) and works once.
      </p>
      <p>
        When Habeas looks people up in your system, identifiers are hashed for matching. Traffic
        is encrypted in transit. Matching runs automatically — site operators do not browse your
        records or credentials, and results are not shown freely for casual review.
      </p>
      <p>
        Especially for HR and people systems: this connection is only for privacy-request
        fulfillment you already authorized — not general HR reporting, and not shared access for
        other Habeas users.
      </p>
    </section>
  )
}

function FieldHelp({ help }: { help: string }) {
  const lines = help
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  const steps = lines.filter((line) => /^\d+\.\s/.test(line))
  const notes = lines.filter((line) => !/^\d+\.\s/.test(line))

  return (
    <div className="space-y-2 text-sm leading-relaxed text-[#475569]">
      {steps.length > 0 ? (
        <ol className="list-decimal space-y-1.5 pl-4 text-[#334155]">
          {steps.map((step) => (
            <li key={step}>{step.replace(/^\d+\.\s*/, '')}</li>
          ))}
        </ol>
      ) : null}
      {notes.map((note) => (
        <p key={note}>{note}</p>
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
    <div className="space-y-2">
      <label htmlFor={field.id} className="block text-sm font-medium text-[#0F172A]">
        {field.label}
        {field.required ? <span className="font-normal text-[#475569]"> · required</span> : null}
      </label>
      {field.help ? <FieldHelp help={field.help} /> : null}
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
    </div>
  )
}

function ConnectShell({ children }: { children: ReactNode }) {
  // z-[60] above AppShell sticky header (z-40) and role switcher so they cannot cover the logo.
  return (
    <div className="fixed inset-0 z-[60] flex flex-col overflow-y-auto bg-[#F8FAFC]">
      <header className="shrink-0 bg-habeas-navy px-4 py-6 sm:px-6 sm:py-7">
        <HabeasConnectLogo />
        <p className="mt-3 text-center text-[11px] font-medium uppercase tracking-[0.16em] text-white/80">
          Data Privacy · Secure connection
        </p>
      </header>
      <div className="mx-auto flex w-full max-w-lg flex-1 flex-col px-4 py-8 sm:px-6 sm:py-10">
        <main className="flex-1">{children}</main>
        <footer className="mt-10 text-center text-xs text-[#475569]">
          Secure integration onboarding
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
  me,
}: {
  preview: ConnectPreviewPayload
  token: string
  me: MePayload
}) {
  const [step, setStep] = useState<WizardStep>('confirm')
  const [credentials, setCredentials] = useState<Record<string, string>>(() =>
    Object.fromEntries(preview.fields.map((field) => [field.id, ''])),
  )
  const [clientError, setClientError] = useState<string | null>(null)
  const systemLabel = connectRedeemSystemLabel(preview)

  const redeemMutation = useMutation({
    mutationFn: (payload: Record<string, string>) => redeemConnect(token, payload),
    onMutate: () => setClientError(null),
    onSuccess: (data) => {
      if (data.test_ok) {
        actionToast.success({
          title: 'Connection test passed',
          description: connectTestSuccessDescription(data.detail, preview.display_name),
        })
        return
      }
      const message = connectTestFailureMessage(data.detail)
      actionToast.error({
        title: 'Connection test failed',
        description: message,
      })
    },
    onError: (error) => {
      actionToast.error({
        title: 'Could not connect',
        description: friendlyApiError(
          error,
          'Could not save credentials. Check the fields and try again.',
        ),
      })
    },
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
    ? connectTestFailureMessage(redeemMutation.data?.detail)
    : null

  const inviteeFirst = firstNameFromEmail(preview.owner_email)
  const signedInFirst = firstNameFromEmail(me.email)
  const isInvitee = emailsMatch(me.email, preview.owner_email)

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
          <h1 className="text-xl font-medium text-[#0F172A]">Connection test passed</h1>
          <p className="text-sm text-[#475569]">
            Thanks, {signedInFirst}. We saved your credentials and verified the{' '}
            {systemLabel} connection successfully. You can close this page.
          </p>
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
      <WizardProgress step={step} />

      {step === 'confirm' ? (
        <div className="space-y-5">
          <header className="space-y-2 border-b border-[#E2E8F0] pb-5">
            <p className="text-xs font-medium uppercase tracking-wide text-habeas-navy">
              Step 1 · Confirm who you are
            </p>
            <h1 className="text-xl font-medium tracking-tight text-[#0F172A]">
              Hi, {signedInFirst}
            </h1>
            <p className="text-sm leading-relaxed text-[#334155]">
              You are signed in as{' '}
              <span className="font-medium text-[#0F172A]">{me.email}</span>.
            </p>
          </header>

          <div className="space-y-3 rounded-md border border-[#E2E8F0] bg-[#F8FAFC] px-3 py-3 text-xs leading-relaxed text-[#334155]">
            <h2 className="text-xs font-semibold text-[#0F172A]">This invite</h2>
            <ul className="space-y-1.5">
              <li className="flex gap-2">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-habeas-navy" aria-hidden />
                <span>
                  Connection: <span className="font-medium text-[#0F172A]">{preview.display_name}</span>
                </span>
              </li>
              <li className="flex gap-2">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-habeas-navy" aria-hidden />
                <span>
                  Prepared for:{' '}
                  <span className="font-medium text-[#0F172A]">{preview.owner_email}</span>
                  {inviteeFirst !== 'there' ? ` (${inviteeFirst})` : null}
                </span>
              </li>
              <li className="flex gap-2">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-habeas-navy" aria-hidden />
                <span>
                  Expires {formatExpiresIn(preview.expires_at)} (
                  <time dateTime={preview.expires_at}>{formatExpiresAt(preview.expires_at)}</time>)
                </span>
              </li>
            </ul>
          </div>

          {isInvitee ? (
            <div className="space-y-3">
              <p className="text-sm text-[#334155]">
                Confirm you are <span className="font-medium text-[#0F172A]">{inviteeFirst}</span>{' '}
                ({preview.owner_email}) to continue setting up this connection.
              </p>
              <Button
                type="button"
                className="h-10 w-full bg-habeas-navy text-sm hover:bg-habeas-navy/90"
                onClick={() => setStep('instructions')}
              >
                Yes — continue as {inviteeFirst}
              </Button>
            </div>
          ) : (
            <div className="space-y-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-3 text-xs text-amber-950">
              <p className="font-semibold">Wrong Google account</p>
              <p>
                This invite is for <span className="font-medium">{preview.owner_email}</span>, but
                you signed in as <span className="font-medium">{me.email}</span>.
              </p>
              <p>Sign out, then open this link again while signed in as the invited owner.</p>
            </div>
          )}
        </div>
      ) : null}

      {step === 'instructions' ? (
        <div className="space-y-5">
          <header className="space-y-2 border-b border-[#E2E8F0] pb-5">
            <p className="text-xs font-medium uppercase tracking-wide text-habeas-navy">
              Step 2 · Privacy & security
            </p>
            <h1 className="text-xl font-medium tracking-tight text-[#0F172A]">
              How we handle what you share
            </h1>
            <p className="text-sm text-[#475569]">
              A short overview before you enter credentials for {preview.display_name}.
            </p>
          </header>

          <PrivacySecuritySection expiresAt={preview.expires_at} />

          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              type="button"
              variant="outline"
              className="h-10 flex-1 text-sm"
              onClick={() => setStep('confirm')}
            >
              Back
            </Button>
            <Button
              type="button"
              className="h-10 flex-1 bg-habeas-navy text-sm hover:bg-habeas-navy/90"
              onClick={() => setStep('credentials')}
            >
              Continue to credentials
            </Button>
          </div>
        </div>
      ) : null}

      {step === 'credentials' ? (
        <div className="relative space-y-5">
          {redeemMutation.isPending ? <RedeemPendingOverlay systemLabel={systemLabel} /> : null}

          <header className="space-y-2 border-b border-[#E2E8F0] pb-5">
            <p className="text-xs font-medium uppercase tracking-wide text-habeas-navy">
              Step 3 · Credentials
            </p>
            <h1 className="text-xl font-medium tracking-tight text-[#0F172A]">
              {preview.display_name}
            </h1>
            <p className="text-sm text-[#475569]">
              Follow the steps below, then paste each value into the matching field.
            </p>
          </header>

          {preview.fields.length === 0 ? (
            <p className="text-sm text-[#475569]">
              No credentials are collected on this page. Contact Habeas if you expected a form.
            </p>
          ) : (
            <form className="space-y-5" onSubmit={handleSubmit} noValidate>
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
                <div className="space-y-1" role="alert">
                  <p className="text-sm text-red-700">{testFailureMessage}</p>
                  <p className="text-xs text-[#475569]">
                    This invite is still valid. Correct the values and try again.
                  </p>
                </div>
              ) : null}

              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 flex-1 text-sm"
                  disabled={redeemMutation.isPending}
                  onClick={() => setStep('instructions')}
                >
                  Back
                </Button>
                <Button
                  type="submit"
                  disabled={redeemMutation.isPending}
                  className="h-10 flex-1 bg-habeas-navy text-sm hover:bg-habeas-navy/90"
                >
                  Connect securely
                </Button>
              </div>
            </form>
          )}
        </div>
      ) : null}
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

  const meQuery = useQuery({
    queryKey: ['admin-api', 'me', 'connect'],
    queryFn: getMe,
    retry: false,
  })

  return (
    <ConnectShell>
      {previewQuery.isPending || meQuery.isPending ? (
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
            <p className="text-sm text-[#475569]">
              {friendlyApiError(
                previewQuery.error,
                'This invite link is invalid or has expired.',
              )}
            </p>
          </div>
        </ConnectCard>
      ) : meQuery.isError || !meQuery.data ? (
        <ConnectCard>
          <div className="space-y-3 text-center">
            <h1 className="text-lg font-medium text-[#0F172A]">Sign in required</h1>
            <p className="text-sm text-[#475569]">
              Sign in with your Habeas Google account, then reload this invite link.
            </p>
          </div>
        </ConnectCard>
      ) : previewQuery.data ? (
        <ConnectForm preview={previewQuery.data} token={token} me={meQuery.data} />
      ) : null}
    </ConnectShell>
  )
}
