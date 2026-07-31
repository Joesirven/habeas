import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import {
  createManualRequest,
  postAgentBatchUpload,
  type ManualRequestInput,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import { canAccessLegalSurfaces, useMe } from '@/lib/auth'

const initialForm: ManualRequestInput = {
  request_type: 'delete',
  state: 'CA',
  first_name: '',
  last_name: '',
  email: '',
  phone: '',
  zip: '',
}

const fieldClass =
  'w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid'

export function ManualRequestPage() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { role } = useMe()
  const showUpload = canAccessLegalSurfaces(role)
  const [form, setForm] = useState<ManualRequestInput>(initialForm)

  const createMutation = useMutation({
    mutationFn: createManualRequest,
    onSuccess: async (record) => {
      await queryClient.invalidateQueries({ queryKey: ['admin-api', 'requests'] })
      actionToast.successAfterNavigate({
        title: 'Request created',
        description: `Request ${record.id}`,
        action: {
          label: 'View',
          onClick: () => navigate({ to: '/requests' }),
        },
      })
      navigate({ to: '/requests' })
    },
    onError: (error, variables) => {
      actionToast.error({
        title: 'Could not create request',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => createMutation.mutate(variables),
        },
      })
    },
  })

  const uploadMutation = useMutation({
    mutationFn: postAgentBatchUpload,
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ['admin-api'] })
      actionToast.success({
        title: 'Batch uploaded',
        description: `${result.inserted_count} inserted · ${result.skipped_row_count} skipped`,
        action: {
          label: 'View triage',
          onClick: () =>
            navigate({ to: '/requests/needs-attention', search: { kind: 'triage' } }),
        },
      })
    },
    onError: (error, file) => {
      actionToast.error({
        title: 'Upload failed',
        description: actionToast.safeErrorMessage(error),
        action: {
          label: 'Retry',
          onClick: () => uploadMutation.mutate(file),
        },
      })
    },
  })

  function updateField<K extends keyof ManualRequestInput>(key: K, value: ManualRequestInput[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  return (
    <section className="mx-auto max-w-2xl space-y-10">
      {showUpload ? (
        <div className="space-y-4">
          <header>
            <p className="taste-micro">Legal</p>
            <h2 className="mt-3 font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
              Agent batch upload
            </h2>
            <p className="mt-3 text-sm text-ink-soft">
              Upload the agent CSV as-is — the platform cleans rows, then the dispatcher routes
              condition hits to Inbox · Triage (or matching when clear).
            </p>
            <p className="mt-2 text-xs text-mute">
              After upload, open{' '}
              <Link
                to="/requests/needs-attention"
                search={{ kind: 'triage' }}
                className="font-medium text-habeas-navy underline-offset-2 hover:underline"
              >
                Inbox · Triage
              </Link>{' '}
              for holds.
            </p>
          </header>
          <div className="taste-panel-soft space-y-4 p-6 sm:p-7">
            <input
              type="file"
              accept=".csv,text/csv"
              className="block w-full text-sm text-ink-soft file:mr-3 file:rounded-md file:border-0 file:bg-habeas-navy/10 file:px-3 file:py-1.5 file:text-xs file:font-medium file:text-habeas-navy"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file) uploadMutation.mutate(file)
              }}
            />
            {uploadMutation.isPending ? (
              <p className="text-sm text-ink-soft">Cleaning and inserting…</p>
            ) : null}
          </div>
        </div>
      ) : null}

      <header>
        <p className="taste-micro">Intake</p>
        <h2 className="mt-3 font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
          Manual request
        </h2>
        <p className="mt-3 text-sm text-ink-soft">
          Ad-hoc Legal intake. Creates a thin request row for matching.
        </p>
      </header>

      <form
        className="taste-panel-soft space-y-5 p-6 sm:p-7"
        onSubmit={(event) => {
          event.preventDefault()
          createMutation.mutate(form)
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1.5 text-sm text-ink-soft">
            First name
            <input
              className={fieldClass}
              value={form.first_name ?? ''}
              onChange={(event) => updateField('first_name', event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm text-ink-soft">
            Last name
            <input
              className={fieldClass}
              value={form.last_name ?? ''}
              onChange={(event) => updateField('last_name', event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm text-ink-soft">
            Email
            <input
              type="email"
              className={fieldClass}
              value={form.email ?? ''}
              onChange={(event) => updateField('email', event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm text-ink-soft">
            Phone
            <input
              className={fieldClass}
              value={form.phone ?? ''}
              onChange={(event) => updateField('phone', event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm text-ink-soft">
            ZIP
            <input
              className={fieldClass}
              value={form.zip ?? ''}
              onChange={(event) => updateField('zip', event.target.value)}
            />
          </label>
          <label className="space-y-1.5 text-sm text-ink-soft">
            State
            <input
              required
              maxLength={2}
              className={`${fieldClass} uppercase`}
              value={form.state}
              onChange={(event) => updateField('state', event.target.value.toUpperCase())}
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-3 pt-1">
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="taste-btn-primary"
          >
            {createMutation.isPending ? 'Submitting…' : 'Submit request'}
          </button>
          <Link to="/requests" className="taste-btn">
            Cancel
          </Link>
        </div>
      </form>
    </section>
  )
}
