/**
 * Temporary pending-settings walkthrough lab.
 * Teardown after the invite-teammates login prompt decision.
 * Not in primary NavMenu — URL only: /dev/pending-settings
 */

import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  PENDING_SETTING_INVITE_USERS,
  type PendingSettingStatus,
} from '@/lib/api'
import { cn } from '@/lib/utils'

const LAB_FIRST_NAME = 'Jose'
const LAB_STATES: readonly PendingSettingStatus[] = ['pending', 'skipped', 'done']

const STATE_BADGE: Record<PendingSettingStatus, 'wait' | 'default' | 'ok'> = {
  pending: 'wait',
  skipped: 'default',
  done: 'ok',
}

const STATE_LABEL: Record<PendingSettingStatus, string> = {
  pending: 'Pending',
  skipped: 'Skipped',
  done: 'Done',
}

function WalkthroughDialog({
  status,
  interactive,
  onInvite,
  onSkip,
}: {
  status: PendingSettingStatus
  interactive?: boolean
  onInvite?: () => void
  onSkip?: () => void
}) {
  const copy = walkthroughCopy(status)
  return (
    <div className="flex min-h-[22rem] flex-col items-center justify-center bg-paper px-4 py-10">
      <section
        className="w-full max-w-md rounded-xl border border-line bg-white p-6 shadow-sm"
        role="dialog"
        aria-labelledby={`pending-settings-title-${status}`}
        aria-describedby={`pending-settings-body-${status}`}
      >
        <p className="taste-micro">Settings</p>
        <h2
          id={`pending-settings-title-${status}`}
          className="mt-3 font-display text-xl font-medium tracking-tight text-ink"
        >
          {copy.title}
        </h2>
        <p
          id={`pending-settings-body-${status}`}
          className="mt-3 text-sm leading-relaxed text-ink-soft"
        >
          {copy.body}
        </p>
        <div className="mt-6 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          {status === 'pending' ? (
            <>
              <Button
                type="button"
                variant="outline"
                onClick={interactive ? onSkip : undefined}
              >
                No other team members
              </Button>
              <Button type="button" onClick={interactive ? onInvite : undefined}>
                Invite teammates
              </Button>
            </>
          ) : (
            <Button type="button" variant="outline" disabled>
              {copy.footer}
            </Button>
          )}
        </div>
      </section>
    </div>
  )
}

function walkthroughCopy(status: PendingSettingStatus): {
  title: string
  body: string
  footer: string
} {
  if (status === 'skipped') {
    return {
      title: 'No other team members',
      body: `Hello ${LAB_FIRST_NAME}. This prompt was skipped. Login continues to the app and will not ask again.`,
      footer: 'Prompt dismissed',
    }
  }
  if (status === 'done') {
    return {
      title: 'Invite teammates',
      body: `Hello ${LAB_FIRST_NAME}. This setting is done — teammates were invited or already present. Login continues to the app and will not ask again.`,
      footer: 'Prompt complete',
    }
  }
  return {
    title: 'Invite data users to your vertical',
    body: `Hello ${LAB_FIRST_NAME}. Add teammates who can review matches and fulfill requests, or continue without other team members.`,
    footer: '',
  }
}

export function PendingSettingsLabPage() {
  const [status, setStatus] = useState<PendingSettingStatus>('pending')

  return (
    <section className="space-y-8">
      <div className="rounded-[0.75rem] border border-dashed border-amber-300 bg-amber-50/80 px-3 py-2 text-xs text-amber-950">
        Temporary lab — teardown after the login pending-settings decision. Login
        setting id: <span className="font-mono">{PENDING_SETTING_INVITE_USERS}</span>.
        Not in primary nav.
      </div>

      <header>
        <p className="taste-micro">Temporary · teardown after decision</p>
        <h2 className="mt-3 font-display text-3xl font-medium tracking-tight text-ink">
          Pending-settings walkthrough
        </h2>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Login prompt chrome copied from AppShell (paper, navy buttons, taste-micro).
          Pending shows Invite teammates / No other team members. Skipped and done
          do not re-prompt on login.
        </p>
        <p className="mt-2 font-mono text-[0.65rem] text-mute">
          http://127.0.0.1:5174/dev/pending-settings
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        {LAB_STATES.map((next) => (
          <Button
            key={next}
            type="button"
            size="sm"
            variant={status === next ? 'default' : 'outline'}
            onClick={() => setStatus(next)}
          >
            {STATE_LABEL[next]}
          </Button>
        ))}
        <Badge variant={STATE_BADGE[status]}>{STATE_LABEL[status]}</Badge>
      </div>

      <div className="overflow-hidden rounded-xl border border-line">
        <WalkthroughDialog
          status={status}
          interactive
          onInvite={() => setStatus('done')}
          onSkip={() => setStatus('skipped')}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {LAB_STATES.map((state) => (
          <button
            key={state}
            type="button"
            onClick={() => setStatus(state)}
            className={cn(
              'overflow-hidden rounded-xl border text-left transition-colors',
              status === state ? 'border-habeas-navy/40' : 'border-line',
            )}
          >
            <div className="flex items-center justify-between border-b border-line bg-white px-3 py-2">
              <p className="taste-micro">{STATE_LABEL[state]}</p>
              <Badge variant={STATE_BADGE[state]}>{state}</Badge>
            </div>
            <WalkthroughDialog status={state} />
          </button>
        ))}
      </div>
    </section>
  )
}
