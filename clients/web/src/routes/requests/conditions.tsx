import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useState } from 'react'

import { SkeletonLines } from '@/components/AppShell'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  getRouteTriageCondition,
  putRouteTriageCondition,
  type RouteTriageCondition,
} from '@/lib/api'
import { canAccessLegalSurfaces, canMutateLegalSettings, ForbiddenState, useMe } from '@/lib/auth'

const USPS_STATES = [
  'AL',
  'AK',
  'AZ',
  'AR',
  'CA',
  'CO',
  'CT',
  'DE',
  'DC',
  'FL',
  'GA',
  'HI',
  'ID',
  'IL',
  'IN',
  'IA',
  'KS',
  'KY',
  'LA',
  'ME',
  'MD',
  'MA',
  'MI',
  'MN',
  'MS',
  'MO',
  'MT',
  'NE',
  'NV',
  'NH',
  'NJ',
  'NM',
  'NY',
  'NC',
  'ND',
  'OH',
  'OK',
  'OR',
  'PA',
  'RI',
  'SC',
  'SD',
  'TN',
  'TX',
  'UT',
  'VT',
  'VA',
  'WA',
  'WV',
  'WI',
  'WY',
] as const

type PredicateMode = 'requestor_state_not_in' | 'state_in'

function modeFromCondition(condition: RouteTriageCondition | undefined): PredicateMode {
  if (condition?.state_in?.length) return 'state_in'
  return 'requestor_state_not_in'
}

function statesFromCondition(condition: RouteTriageCondition | undefined): string[] {
  if (condition?.state_in?.length) return [...condition.state_in]
  if (condition?.requestor_state_not_in?.length) {
    return [...condition.requestor_state_not_in]
  }
  return ['CA', 'CO', 'CT', 'UT', 'VA']
}

export function ConditionsPage() {
  const queryClient = useQueryClient()
  const { role, isLoading: meLoading } = useMe()
  const allowed = canAccessLegalSurfaces(role)
  const canWrite = canMutateLegalSettings(role)

  const ruleQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'conditions', 'route-triage'],
    queryFn: getRouteTriageCondition,
    enabled: allowed,
    staleTime: 15_000,
  })

  const [mode, setMode] = useState<PredicateMode>('requestor_state_not_in')
  const [states, setStates] = useState<string[]>(['CA', 'CO', 'CT', 'UT', 'VA'])
  const [rationale, setRationale] = useState('')
  const [dirty, setDirty] = useState(false)

  useEffect(() => {
    if (!ruleQuery.data || dirty) return
    setMode(modeFromCondition(ruleQuery.data.condition_jsonb))
    setStates(statesFromCondition(ruleQuery.data.condition_jsonb))
    setRationale(ruleQuery.data.rationale)
  }, [ruleQuery.data, dirty])

  const saveMutation = useMutation({
    mutationFn: () => {
      const condition_jsonb: RouteTriageCondition =
        mode === 'state_in'
          ? { state_in: states }
          : { requestor_state_not_in: states }
      return putRouteTriageCondition({
        condition_jsonb,
        rationale,
      })
    },
    onSuccess: async () => {
      setDirty(false)
      await queryClient.invalidateQueries({
        queryKey: ['admin-api', 'ops', 'drop', 'conditions', 'route-triage'],
      })
    },
  })

  function toggleState(code: string) {
    setDirty(true)
    setStates((current) =>
      current.includes(code)
        ? current.filter((item) => item !== code)
        : [...current, code].sort((a, b) => a.localeCompare(b)),
    )
  }

  if (meLoading) {
    return (
      <section className="space-y-4 py-6">
        <SkeletonLines lines={5} />
      </section>
    )
  }

  if (!allowed) {
    return <ForbiddenState />
  }

  return (
    <section className="mx-auto max-w-3xl space-y-8">
      <header>
        <p className="taste-micro">Legal</p>
        <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">
          Conditions
        </h2>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Version the active route-to-Triage rule. Matching holds until Legal rejects or
          sends to matching — never a silent auto-reject.
        </p>
      </header>

      {ruleQuery.isPending ? (
        <div className="taste-panel-soft p-6">
          <SkeletonLines lines={4} />
        </div>
      ) : null}

      {ruleQuery.isError ? (
        <p className="text-sm text-red-700">
          Could not load the active condition
          {ruleQuery.error instanceof Error ? ` — ${ruleQuery.error.message}` : ''}.
        </p>
      ) : null}

      {ruleQuery.data ? (
        <div className="taste-panel-soft space-y-6 p-6 sm:p-7">
          {!canWrite ? (
            <p className="flex items-center gap-2 text-xs text-mute">
              <span aria-hidden="true">🔒</span>
              Read-only — admin role required to save changes.
            </p>
          ) : null}
          <div className="flex flex-wrap items-center gap-2 text-xs text-mute">
            <Badge variant="default" className="normal-case tracking-normal">
              Rule #{ruleQuery.data.id}
            </Badge>
            <span className="font-mono text-[0.65rem]">{ruleQuery.data.action_type}</span>
            {ruleQuery.data.effective_from ? (
              <span>Active since {new Date(ruleQuery.data.effective_from).toLocaleString()}</span>
            ) : null}
          </div>

          <fieldset className="space-y-2">
            <legend className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
              Predicate
            </legend>
            <label className="flex cursor-pointer items-start gap-2 text-sm text-ink-soft">
              <input
                type="radio"
                className="mt-1 accent-habeas-navy"
                checked={mode === 'requestor_state_not_in'}
                disabled={!canWrite}
                onChange={() => {
                  setMode('requestor_state_not_in')
                  setDirty(true)
                }}
              />
              <span>
                <span className="font-medium text-ink">In-scope allowlist</span>
                <span className="mt-0.5 block text-xs">
                  States <em>not</em> in the list route to Inbox · Triage (current seed style).
                </span>
              </span>
            </label>
            <label className="flex cursor-pointer items-start gap-2 text-sm text-ink-soft">
              <input
                type="radio"
                className="mt-1 accent-habeas-navy"
                checked={mode === 'state_in'}
                disabled={!canWrite}
                onChange={() => {
                  setMode('state_in')
                  setDirty(true)
                }}
              />
              <span>
                <span className="font-medium text-ink">Explicit Triage list</span>
                <span className="mt-0.5 block text-xs">
                  Only the selected states route to Triage; all others go to matching.
                </span>
              </span>
            </label>
          </fieldset>

          <div className="space-y-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                States ({states.length})
              </p>
              <p className="text-[0.65rem] text-mute">
                {mode === 'requestor_state_not_in'
                  ? 'Selected = in-scope (stay out of Triage)'
                  : 'Selected = route to Triage'}
              </p>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {USPS_STATES.map((code) => {
                const active = states.includes(code)
                return (
                  <button
                    key={code}
                    type="button"
                    disabled={!canWrite}
                    onClick={() => toggleState(code)}
                    className={
                      active
                        ? 'rounded border border-habeas-navy/40 bg-habeas-navy/10 px-2 py-1 font-mono text-[0.7rem] font-medium text-habeas-navy'
                        : 'rounded border border-line bg-paper px-2 py-1 font-mono text-[0.7rem] text-mute hover:border-habeas-navy/30 hover:text-ink'
                    }
                    aria-pressed={active}
                  >
                    {code}
                  </button>
                )
              })}
            </div>
          </div>

          <label className="block space-y-1.5 text-sm">
            <span className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
              Rationale
            </span>
            <textarea
              className="min-h-[5rem] w-full rounded-lg border border-line bg-paper-raised px-3 py-2 text-sm text-ink outline-none focus:border-habeas-mid disabled:opacity-60"
              value={rationale}
              disabled={!canWrite}
              onChange={(event) => {
                setRationale(event.target.value)
                setDirty(true)
              }}
              maxLength={2000}
            />
          </label>

          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              size="sm"
              disabled={
                !canWrite ||
                !dirty ||
                states.length === 0 ||
                rationale.trim().length === 0 ||
                saveMutation.isPending
              }
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? 'Saving…' : 'Save new version'}
            </Button>
            <Button asChild size="sm" variant="outline">
              <Link to="/requests/needs-attention" search={{ kind: 'triage' }}>
                Open Inbox · Triage
              </Link>
            </Button>
            {saveMutation.isSuccess ? (
              <span className="text-xs text-emerald-800">Version saved.</span>
            ) : null}
            {saveMutation.isError ? (
              <span className="text-xs text-red-700">
                {saveMutation.error instanceof Error
                  ? saveMutation.error.message
                  : 'Save failed'}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
    </section>
  )
}
