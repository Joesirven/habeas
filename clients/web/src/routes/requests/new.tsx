import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'

import { createManualRequest, type ManualRequestInput } from '@/lib/api'

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
  const [form, setForm] = useState<ManualRequestInput>(initialForm)

  const createMutation = useMutation({
    mutationFn: createManualRequest,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-api', 'requests'] })
      navigate({ to: '/requests' })
    },
  })

  function updateField<K extends keyof ManualRequestInput>(key: K, value: ManualRequestInput[K]) {
    setForm((current) => ({ ...current, [key]: value }))
  }

  return (
    <section className="mx-auto max-w-2xl space-y-10">
      <header>
        <p className="taste-micro">Intake</p>
        <h2 className="mt-3 font-display text-[2.5rem] font-medium leading-none tracking-tight text-ink">
          Manual request
        </h2>
        <p className="mt-3 text-sm text-ink-soft">
          Legal-team intake. Creates a normalized request and enqueues matching.
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

        {createMutation.isError ? (
          <p className="text-sm text-red-700">{String(createMutation.error)}</p>
        ) : null}

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
