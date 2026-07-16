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
    <section className="mx-auto max-w-2xl space-y-6">
      <div>
        <h2 className="text-2xl font-semibold text-white">Manual request</h2>
        <p className="mt-2 text-slate-400">Legal-team intake. Creates a normalized request and enqueues matching.</p>
      </div>

      <form
        className="space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-6"
        onSubmit={(event) => {
          event.preventDefault()
          createMutation.mutate(form)
        }}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-1 text-sm text-slate-300">
            First name
            <input
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              value={form.first_name ?? ''}
              onChange={(event) => updateField('first_name', event.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Last name
            <input
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              value={form.last_name ?? ''}
              onChange={(event) => updateField('last_name', event.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Email
            <input
              type="email"
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              value={form.email ?? ''}
              onChange={(event) => updateField('email', event.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            Phone
            <input
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              value={form.phone ?? ''}
              onChange={(event) => updateField('phone', event.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            ZIP
            <input
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white"
              value={form.zip ?? ''}
              onChange={(event) => updateField('zip', event.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            State
            <input
              required
              maxLength={2}
              className="w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white uppercase"
              value={form.state}
              onChange={(event) => updateField('state', event.target.value.toUpperCase())}
            />
          </label>
        </div>

        {createMutation.isError ? (
          <p className="text-sm text-red-300">{String(createMutation.error)}</p>
        ) : null}

        <div className="flex gap-3">
          <button
            type="submit"
            disabled={createMutation.isPending}
            className="rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-500 disabled:opacity-50"
          >
            {createMutation.isPending ? 'Submitting…' : 'Submit request'}
          </button>
          <Link to="/requests" className="rounded-lg border border-slate-700 px-4 py-2 text-sm text-slate-300">
            Cancel
          </Link>
        </div>
      </form>
    </section>
  )
}
