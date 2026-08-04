import { useMutation, useQuery } from '@tanstack/react-query'
import { useParams } from '@tanstack/react-router'
import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  ConfirmActionDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Spinner } from '@/components/ui/spinner'
import { Toaster } from '@/components/ui/sonner'
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
import { firstNameFromEmail } from '@/lib/utils'

type CredentialField = ConnectPreviewPayload['fields'][number]

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

/** Allowlisted admin-api `detail` strings — never echo credential values or vendor bodies. */
const SAFE_API_ERROR_DETAILS: Record<string, string> = {
  'invite not found': 'This invite link is invalid or has expired.',
  'this connection cannot be redeemed via invite':
    'This connection cannot be completed through an invite link. Contact Habeas.',
  'invite expired': 'This invite link has expired. Ask for a new invite.',
  'invite already used': 'This invite link was already used.',
  'secret not stored':
    'No credentials are stored for this connection yet. Ask Habeas to send a new invite.',
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
    const timer = window.setTimeout(() => setPhase('testing'), 1200)
    return () => window.clearTimeout(timer)
  }, [])

  const title = phase === 'saving' ? 'Saving credentials…' : `Testing ${systemLabel}…`
  const detail =
    phase === 'saving'
      ? 'Writing your keys to Google’s secure vault.'
      : `Checking that Habeas can authenticate with ${systemLabel}.`

  return (
    <div
      className="absolute inset-0 z-10 flex flex-col items-center justify-center rounded-lg bg-white/95 px-6 text-center backdrop-blur-[2px]"
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-label={title}
    >
      <div className="w-full max-w-sm rounded-lg border border-[#E2E8F0] bg-white p-5 shadow-sm">
        <div className="mx-auto mb-3 flex size-10 items-center justify-center rounded-full bg-habeas-navy/10">
          <Spinner className="size-5" />
        </div>
        <p className="text-sm font-medium text-[#0F172A]">{title}</p>
        <p className="mt-1 text-xs text-[#475569]">{detail}</p>
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-[#E2E8F0]">
          <div
            className={`h-full rounded-full bg-habeas-navy transition-all duration-700 ${
              phase === 'saving' ? 'w-1/2' : 'w-full'
            }`}
          />
        </div>
      </div>
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

function emailsMatch(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase()
}

type WizardStep = 'confirm' | 'instructions' | 'credentials' | 'test'

function WizardProgress({ step }: { step: WizardStep }) {
  const steps: { id: WizardStep; label: string }[] = [
    { id: 'confirm', label: 'Confirm' },
    { id: 'instructions', label: 'Privacy' },
    { id: 'credentials', label: 'Credentials' },
    { id: 'test', label: 'Test' },
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
  const tiles: { title: string; body: string }[] = [
    {
      title: 'Your keys stay locked away',
      body: 'They go into Google’s secure vault — not our app database, and not visible to other people on this site.',
    },
    {
      title: 'All data is protected and encrypted',
      body: 'Your data is protected and encrypted at all times — in transit and at rest.',
    },
    {
      title: 'Only you see your results',
      body: 'Other data owners, IT, and Habeas staff building this tool cannot browse your system’s results. Access is by permission only.',
    },
    {
      title: 'This link expires and works once',
      body: `Expires ${formatExpiresIn(expiresAt)}. After you connect successfully, it cannot be used again.`,
    },
    {
      title: 'We’ll ask for updated keys every 6 months',
      body: 'A regular key refresh keeps authentication current and helps protect against stale or compromised credentials.',
    },
  ]

  return (
    <section className="space-y-3 text-sm text-[#334155]" aria-labelledby="connect-privacy-heading">
      <h2 id="connect-privacy-heading" className="sr-only">
        Privacy and security
      </h2>
      <ul className="space-y-3">
        {tiles.map((item) => (
          <li
            key={item.title}
            className="rounded-md border border-[#E2E8F0] bg-[#F8FAFC] px-3.5 py-3"
          >
            <p className="font-medium text-[#0F172A]">{item.title}</p>
            <p className="mt-1 leading-snug text-[#475569]">{item.body}</p>
          </li>
        ))}
      </ul>
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
  // Dialogs use z-[70]+ so confirm/success feedback stays above this shell.
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
      {/* Connect shell covers AppShell toaster — mount one above the shell. */}
      <Toaster style={{ zIndex: 80 } as CSSProperties} />
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
  demoMode = false,
  initialStep = 'confirm',
}: {
  preview: ConnectPreviewPayload
  token: string
  me: MePayload
  demoMode?: boolean
  initialStep?: WizardStep
}) {
  const [step, setStep] = useState<WizardStep>(initialStep)
  const [credentials, setCredentials] = useState<Record<string, string>>(() =>
    Object.fromEntries(preview.fields.map((field) => [field.id, ''])),
  )
  const [clientError, setClientError] = useState<string | null>(null)
  const [confirmTestOpen, setConfirmTestOpen] = useState(false)
  const [successOpen, setSuccessOpen] = useState(false)
  const systemLabel = connectRedeemSystemLabel(preview)

  const redeemMutation = useMutation({
    mutationFn: async (payload: Record<string, string>) => {
      if (demoMode) {
        await new Promise((resolve) => window.setTimeout(resolve, 1600))
        return { status: 'connected', test_ok: true as const, detail: 'mailchimp_ok' }
      }
      return redeemConnect(token, payload)
    },
    onMutate: () => setClientError(null),
    onSuccess: (data) => {
      setConfirmTestOpen(false)
      if (data.test_ok) {
        setSuccessOpen(true)
        actionToast.success({
          title: 'Connection confirmed',
          description: connectTestSuccessDescription(data.detail, preview.display_name),
        })
        return
      }
      actionToast.error({
        title: 'Connection test failed',
        description: connectTestFailureMessage(data.detail),
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
      })
    },
    onError: (error) => {
      setConfirmTestOpen(false)
      actionToast.error({
        title: 'Could not connect',
        description: friendlyApiError(
          error,
          'Could not save credentials. Check the fields and try again.',
        ),
        action: {
          label: 'Retry',
          onClick: () => setConfirmTestOpen(true),
        },
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

  const testPassed =
    redeemMutation.isSuccess && redeemMutation.data?.test_ok === true

  const testFailureMessage = testFailed
    ? connectTestFailureMessage(redeemMutation.data?.detail)
    : null

  const inviteeFirst = firstNameFromEmail(preview.owner_email)
  const signedInFirst = firstNameFromEmail(me.email)
  const isInvitee = emailsMatch(me.email, preview.owner_email)

  function updateField(fieldId: string, value: string) {
    setCredentials((current) => ({ ...current, [fieldId]: value }))
  }

  function validateCredentials(): boolean {
    for (const field of preview.fields) {
      if (field.required && !credentials[field.id]?.trim()) {
        setClientError(`Enter ${field.label.toLowerCase()}.`)
        return false
      }
    }
    setClientError(null)
    return true
  }

  function handleCredentialsContinue(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!validateCredentials()) return
    redeemMutation.reset()
    setSuccessOpen(false)
    setStep('test')
  }

  function runCredentialTest() {
    // Keep the confirm dialog open with "Working…" until the mutation settles.
    redeemMutation.mutate(credentials)
  }

  const filledSummary = preview.fields
    .filter((field) => credentials[field.id]?.trim())
    .map((field) => field.label)

  return (
    <ConnectCard>
      <div className="relative">
        {redeemMutation.isPending ? <RedeemPendingOverlay systemLabel={systemLabel} /> : null}
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
        <div className="space-y-5">
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
            <form className="space-y-5" onSubmit={handleCredentialsContinue} noValidate>
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

              <div className="flex flex-col gap-2 sm:flex-row">
                <Button
                  type="button"
                  variant="outline"
                  className="h-10 flex-1 text-sm"
                  onClick={() => setStep('instructions')}
                >
                  Back
                </Button>
                <Button
                  type="submit"
                  className="h-10 flex-1 bg-habeas-navy text-sm hover:bg-habeas-navy/90"
                >
                  Continue to test
                </Button>
              </div>
            </form>
          )}
        </div>
      ) : null}

      {step === 'test' ? (
        <div className="space-y-5">
          <header className="space-y-2 border-b border-[#E2E8F0] pb-5">
            <p className="text-xs font-medium uppercase tracking-wide text-habeas-navy">
              Step 4 · Test connection
            </p>
            <h1 className="text-xl font-medium tracking-tight text-[#0F172A]">
              Make sure your keys work
            </h1>
            <p className="text-sm text-[#475569]">
              We’ll save them securely, then check that Habeas can reach {systemLabel}.
            </p>
          </header>

          <div className="space-y-2 rounded-md border border-[#E2E8F0] bg-[#F8FAFC] px-3.5 py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium text-[#0F172A]">{preview.display_name}</span>
              <Badge
                variant={
                  redeemMutation.isPending
                    ? 'run'
                    : testPassed
                      ? 'ok'
                      : testFailed
                        ? 'fail'
                        : 'wait'
                }
              >
                {redeemMutation.isPending
                  ? 'Testing…'
                  : testPassed
                    ? 'Passed'
                    : testFailed
                      ? 'Failed'
                      : 'Ready to test'}
              </Badge>
            </div>
            <p className="text-xs text-[#475569]">
              Fields provided: {filledSummary.length > 0 ? filledSummary.join(', ') : 'none yet'}
            </p>
          </div>

          {redeemMutation.isPending ? (
            <div
              className="flex items-start gap-3 rounded-md border border-sky-200 bg-sky-50 px-3.5 py-3"
              role="status"
              aria-live="polite"
            >
              <Spinner className="mt-0.5 size-4 text-sky-700" />
              <div className="min-w-0 text-sm">
                <p className="font-medium text-sky-950">Testing your connection</p>
                <p className="mt-0.5 text-xs text-sky-900/80">
                  Saving keys, then verifying with {systemLabel}. This usually takes a few seconds.
                </p>
              </div>
            </div>
          ) : null}

          {testPassed ? (
            <div
              className="space-y-2 rounded-md border border-emerald-200 bg-emerald-50 px-3.5 py-3"
              role="status"
            >
              <p className="font-medium text-emerald-900">Connection confirmed</p>
              <p className="text-sm text-emerald-900/80">
                {connectTestSuccessDescription(
                  redeemMutation.data?.detail,
                  preview.display_name,
                )}
              </p>
              <p className="text-xs text-emerald-900/70">
                Thanks, {signedInFirst}. You can close this page.
              </p>
            </div>
          ) : null}

          {testFailed ? (
            <div
              className="space-y-2 rounded-md border border-red-200 bg-red-50 px-3.5 py-3"
              role="alert"
            >
              <p className="font-medium text-red-900">Connection test failed</p>
              <p className="text-sm text-red-800">{testFailureMessage}</p>
              <p className="text-xs text-red-800/80">
                This invite is still valid. Go back, fix the values, and test again.
              </p>
            </div>
          ) : null}

          {submitError && !testPassed ? (
            <p className="text-sm text-red-700" role="alert">
              {submitError}
            </p>
          ) : null}

          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              type="button"
              variant="outline"
              className="h-10 flex-1 text-sm"
              disabled={redeemMutation.isPending || testPassed}
              onClick={() => {
                redeemMutation.reset()
                setSuccessOpen(false)
                setStep('credentials')
              }}
            >
              Back
            </Button>
            {!testPassed ? (
              <Button
                type="button"
                className="h-10 flex-1 bg-habeas-navy text-sm hover:bg-habeas-navy/90"
                disabled={redeemMutation.isPending}
                onClick={() => setConfirmTestOpen(true)}
              >
                {testFailed ? 'Test again' : redeemMutation.isPending ? 'Testing…' : 'Test connection'}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}

        <ConfirmActionDialog
          open={confirmTestOpen}
          onOpenChange={(open) => {
            if (redeemMutation.isPending) return
            setConfirmTestOpen(open)
          }}
          title={`Test ${systemLabel} connection?`}
          description="We’ll save your keys in Google’s secure vault, then verify Habeas can authenticate. Values are never shown back in this app."
          confirmLabel="Yes, test now"
          cancelLabel="Cancel"
          confirming={redeemMutation.isPending}
          confirmingTitle="Testing connection…"
          confirmingDescription="Saving keys securely, then verifying with the provider. Keep this tab open."
          onConfirm={runCredentialTest}
        />

        <Dialog open={successOpen} onOpenChange={setSuccessOpen}>
          <DialogContent className="max-w-md" onOpenAutoFocus={(event) => event.preventDefault()}>
            <DialogHeader>
              <DialogTitle>Credentials confirmed</DialogTitle>
              <DialogDescription>
                {connectTestSuccessDescription(
                  redeemMutation.data?.detail,
                  preview.display_name,
                )}
              </DialogDescription>
            </DialogHeader>
            <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
              <Badge variant="ok" className="mb-2">
                Passed
              </Badge>
              <p>
                Thanks, {signedInFirst}. Your {systemLabel} connection is ready.
              </p>
            </div>
            <DialogFooter>
              <Button
                type="button"
                className="bg-habeas-navy hover:bg-habeas-navy/90"
                onClick={() => setSuccessOpen(false)}
              >
                Done
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </ConnectCard>
  )
}

export function ConnectTokenPage() {
  const { token } = useParams({ from: '/connect/$token' })
  const isPrivacyPreview = import.meta.env.DEV && token === 'privacy-preview'
  const isWizardPreview = import.meta.env.DEV && token === 'wizard-preview'
  const skipApi = isPrivacyPreview || isWizardPreview

  const previewQuery = useQuery({
    queryKey: ['admin-api', 'connect', token],
    queryFn: () => getConnectPreview(token),
    retry: false,
    enabled: !skipApi,
  })

  const meQuery = useQuery({
    queryKey: ['admin-api', 'me', 'connect'],
    queryFn: getMe,
    retry: false,
    enabled: !skipApi,
  })

  // Local UI review only — skip API so Privacy / Credentials / Test can be opened without a live invite.
  if (isPrivacyPreview) {
    const expiresAt = new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString()
    return (
      <ConnectShell>
        <ConnectCard>
          <div className="space-y-5">
            <WizardProgress step="instructions" />
            <header className="space-y-2 border-b border-[#E2E8F0] pb-5">
              <p className="text-xs font-medium uppercase tracking-wide text-habeas-navy">
                Step 2 · Privacy & security
              </p>
              <h1 className="text-xl font-medium tracking-tight text-[#0F172A]">
                How we handle what you share
              </h1>
              <p className="text-sm text-[#475569]">
                A short overview before you enter credentials for Production Mailchimp.
              </p>
            </header>
            <PrivacySecuritySection expiresAt={expiresAt} />
          </div>
        </ConnectCard>
      </ConnectShell>
    )
  }

  if (isWizardPreview) {
    const expiresAt = new Date(Date.now() + 72 * 60 * 60 * 1000).toISOString()
    const demoPreview: ConnectPreviewPayload = {
      system: 'mailchimp',
      display_name: 'Production Mailchimp',
      owner_email: 'dev-owner-1@example.com',
      fields: [
        {
          id: 'api_key',
          label: 'API key',
          input_type: 'password',
          required: true,
          help: '1. In Mailchimp, open your profile → Extras → API keys.\n2. Create a key for Habeas privacy automation.\n3. Paste it below.',
        },
      ],
      trust_copy: '',
      expires_at: expiresAt,
    }
    const demoMe: MePayload = {
      email: 'dev-owner-1@example.com',
      role: 'data_owner',
      real_role: 'data_owner',
    }
    return (
      <ConnectShell>
        <ConnectForm
          preview={demoPreview}
          token={token}
          me={demoMe}
          demoMode
          initialStep="credentials"
        />
      </ConnectShell>
    )
  }

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
