import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import {
  addLegalTeamMember,
  getLegalSlaSettings,
  getLegalTeam,
  getRouteTriageCondition,
  listEmailTemplates,
  patchLegalSlaSettings,
  removeLegalTeamMember,
} from '@/lib/api'
import { canMutateLegalSettings, useMe } from '@/lib/auth'

type SettingsTab =
  | 'conditions'
  | 'deadlines'
  | 'templates'
  | 'drop_schedule'
  | 'legal_team'

export function LegalSettingsSheet() {
  const { role } = useMe()
  const canWrite = canMutateLegalSettings(role)
  const queryClient = useQueryClient()
  const [tab, setTab] = useState<SettingsTab>('conditions')
  const [teamEmail, setTeamEmail] = useState('')

  const conditionQuery = useQuery({
    queryKey: ['admin-api', 'ops', 'drop', 'conditions', 'route-triage'],
    queryFn: getRouteTriageCondition,
    enabled: tab === 'conditions',
  })

  const templatesQuery = useQuery({
    queryKey: ['admin-api', 'requests', 'email-templates'],
    queryFn: listEmailTemplates,
    enabled: tab === 'templates',
  })

  const slaQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'settings', 'sla'],
    queryFn: getLegalSlaSettings,
    enabled: tab === 'deadlines',
  })

  const teamQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'team'],
    queryFn: getLegalTeam,
    enabled: tab === 'legal_team',
  })

  const slaMutation = useMutation({
    mutationFn: patchLegalSlaSettings,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'legal', 'settings', 'sla'] })
    },
  })

  const addTeamMutation = useMutation({
    mutationFn: addLegalTeamMember,
    onSuccess: () => {
      setTeamEmail('')
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'legal', 'team'] })
    },
  })

  const removeTeamMutation = useMutation({
    mutationFn: removeLegalTeamMember,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin-api', 'legal', 'team'] })
    },
  })

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: 'conditions', label: 'Conditions' },
    { id: 'deadlines', label: 'Deadlines & SLAs' },
    { id: 'templates', label: 'Email templates' },
    { id: 'drop_schedule', label: 'DROP schedule' },
    { id: 'legal_team', label: 'Legal team' },
  ]

  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          className="text-mute transition-colors hover:text-ink"
          aria-label="Settings"
        >
          ⚙
        </button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
        </DialogHeader>
        {!canWrite ? (
          <p className="flex items-center gap-2 text-xs text-mute">
            <span aria-hidden="true">🔒</span>
            Read-only — admin role required to save changes.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2 border-b border-line pb-3">
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              className={tab === item.id ? 'taste-btn-primary text-xs' : 'taste-btn text-xs'}
              onClick={() => setTab(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        {tab === 'conditions' ? (
          <div className="space-y-3 text-sm text-ink-soft">
            {conditionQuery.isPending ? <p>Loading conditions…</p> : null}
            {conditionQuery.data ? (
              <p>
                Active rule #{conditionQuery.data.id}:{' '}
                <code className="text-xs text-ink">
                  {JSON.stringify(conditionQuery.data.condition_jsonb)}
                </code>
              </p>
            ) : null}
            <Link to="/requests/conditions" className="text-xs text-habeas-navy hover:underline">
              Open full Conditions editor
            </Link>
          </div>
        ) : null}
        {tab === 'deadlines' ? (
          <div className="space-y-3 text-sm">
            {slaQuery.data ? (
              <div className="grid gap-2 sm:grid-cols-2">
                {(
                  [
                    ['data_owner_review_days', 'Data owner review (days)'],
                    ['legal_pre_fulfillment_days', 'Legal / pre-fulfillment (days)'],
                    ['fulfillment_days', 'Fulfillment (days)'],
                    ['lifecycle_days', 'Overall lifecycle (days)'],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="block text-xs text-ink-soft">
                    {label}
                    <input
                      type="number"
                      min={1}
                      className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm"
                      defaultValue={slaQuery.data[key]}
                      disabled={!canWrite}
                      onBlur={(event) => {
                        if (!canWrite) return
                        const value = Number.parseInt(event.target.value, 10)
                        if (!Number.isFinite(value)) return
                        slaMutation.mutate({ [key]: value })
                      }}
                    />
                  </label>
                ))}
              </div>
            ) : (
              <p className="text-mute">Loading SLA settings…</p>
            )}
            <Link to="/requests/slas" className="text-xs text-habeas-navy hover:underline">
              Open SLA monitor
            </Link>
          </div>
        ) : null}
        {tab === 'templates' ? (
          <div className="space-y-2 text-sm text-ink-soft">
            {templatesQuery.isPending ? <p>Loading templates…</p> : null}
            {(templatesQuery.data ?? []).map((template) => (
              <p key={template.id}>
                <span className="font-medium text-ink">{template.slug}</span>
                {template.subject ? ` — ${template.subject}` : ''}
              </p>
            ))}
          </div>
        ) : null}
        {tab === 'drop_schedule' ? (
          <div className="space-y-2 text-sm text-ink-soft">
            <p>
              Weekly California DROP batch upload — default Wednesday 00:00 America/Los_Angeles.
              Configure cadence on the ops worker schedules surface (super_admin).
            </p>
          </div>
        ) : null}
        {tab === 'legal_team' ? (
          <div className="space-y-3 text-sm">
            <p className="text-xs text-ink-soft">
              Members receive assignment-to-legal notifications and Inbox fan-out.
            </p>
            <ul className="space-y-1">
              {(teamQuery.data ?? []).map((member) => (
                <li key={member.email} className="flex items-center justify-between gap-2">
                  <span className="font-mono text-xs">{member.email}</span>
                  {canWrite ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => removeTeamMutation.mutate(member.email)}
                    >
                      Remove
                    </Button>
                  ) : null}
                </li>
              ))}
            </ul>
            {canWrite ? (
              <form
                className="flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (!teamEmail.trim()) return
                  addTeamMutation.mutate(teamEmail.trim())
                }}
              >
                <input
                  type="email"
                  className="flex-1 rounded border border-line bg-paper px-2 py-1 text-sm"
                  placeholder="legal@example.com"
                  value={teamEmail}
                  onChange={(event) => setTeamEmail(event.target.value)}
                />
                <Button type="submit" size="sm">
                  Add
                </Button>
              </form>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
