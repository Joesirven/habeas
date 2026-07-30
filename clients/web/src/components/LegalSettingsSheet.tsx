import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { ConditionsEditor } from '@/components/legal/ConditionsEditor'
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
  fetchAdminApi,
  getLegalSlaSettings,
  getLegalTeam,
  listEmailTemplates,
  listEmailTemplateTypes,
  patchLegalSlaSettings,
  removeLegalTeamMember,
  renderEmailTemplate,
  upsertEmailTemplate,
  type EmailTemplateType,
} from '@/lib/api'
import { canMutateLegalSettings, useMe } from '@/lib/auth'

/** R19/KD11 — request-type labels for the template type switcher. */
const TEMPLATE_TYPE_LABELS: Record<EmailTemplateType, string> = {
  access: 'Access delivery',
  delete: 'Delete confirmation',
  opt_out: 'Opt-out confirmation',
  combined: 'Combined confirmation',
  general: 'General notice',
}

export const OPEN_LEGAL_SETTINGS_EVENT = 'open-legal-settings'

const WEEKDAY_OPTIONS = [
  'Monday',
  'Tuesday',
  'Wednesday',
  'Thursday',
  'Friday',
  'Saturday',
  'Sunday',
] as const

type SettingsTab =
  | 'conditions'
  | 'deadlines'
  | 'templates'
  | 'drop_schedule'
  | 'legal_team'

type LegalDropSchedule = {
  day_of_week: number
  time_local: string
  timezone: string
  weekly_label: string
  updated_at: string | null
}

function getLegalDropSchedule() {
  return fetchAdminApi<LegalDropSchedule>('/legal/settings/drop-schedule')
}

function patchLegalDropSchedule(body: { day_of_week?: number; time_local?: string }) {
  return fetchAdminApi<LegalDropSchedule>('/legal/settings/drop-schedule', {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

type LegalSettingsSheetProps = {
  triggerVariant?: 'banner' | 'header'
}

export function LegalSettingsSheet({ triggerVariant = 'banner' }: LegalSettingsSheetProps) {
  const { role } = useMe()
  const canWrite = canMutateLegalSettings(role)
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<SettingsTab>('conditions')
  const [teamEmail, setTeamEmail] = useState('')
  const [selectedTemplateType, setSelectedTemplateType] = useState<EmailTemplateType>('access')
  const [draftSubject, setDraftSubject] = useState('')
  const [draftBody, setDraftBody] = useState('')
  const [activeTemplateField, setActiveTemplateField] = useState<'subject' | 'body'>('body')
  const subjectInputRef = useRef<HTMLInputElement | null>(null)
  const bodyTextareaRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    function onOpenSettings() {
      setOpen(true)
    }
    document.addEventListener(OPEN_LEGAL_SETTINGS_EVENT, onOpenSettings)
    return () => document.removeEventListener(OPEN_LEGAL_SETTINGS_EVENT, onOpenSettings)
  }, [])

  const templatesQuery = useQuery({
    queryKey: ['admin-api', 'requests', 'email-templates'],
    queryFn: listEmailTemplates,
    enabled: tab === 'templates',
  })

  const templateTypesQuery = useQuery({
    queryKey: ['admin-api', 'requests', 'email-templates', 'types'],
    queryFn: listEmailTemplateTypes,
    enabled: tab === 'templates',
  })

  const selectedTypeInfo = templateTypesQuery.data?.find(
    (info) => info.type === selectedTemplateType,
  )

  const upsertTemplateMutation = useMutation({
    mutationFn: ({ slug, subject, body }: { slug: string; subject: string; body: string }) =>
      upsertEmailTemplate(slug, {
        subject,
        body,
        placeholder_schema: selectedTypeInfo?.variables ?? [],
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'requests', 'email-templates'],
      })
    },
  })

  const previewTemplateMutation = useMutation({
    mutationFn: (slug: string) => renderEmailTemplate(slug),
  })

  useEffect(() => {
    const slug = templateTypesQuery.data?.find(
      (info) => info.type === selectedTemplateType,
    )?.slug
    if (!slug) return
    const existing = templatesQuery.data?.find((template) => template.slug === slug)
    setDraftSubject(existing?.subject ?? '')
    setDraftBody(existing?.body ?? '')
    previewTemplateMutation.reset()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTemplateType, templateTypesQuery.data, templatesQuery.data])

  function insertTemplateVariable(variable: string) {
    const token = `{{${variable}}}`
    if (activeTemplateField === 'subject') {
      const el = subjectInputRef.current
      const pos = el?.selectionStart ?? draftSubject.length
      setDraftSubject(draftSubject.slice(0, pos) + token + draftSubject.slice(pos))
      requestAnimationFrame(() => {
        el?.focus()
        el?.setSelectionRange(pos + token.length, pos + token.length)
      })
    } else {
      const el = bodyTextareaRef.current
      const pos = el?.selectionStart ?? draftBody.length
      setDraftBody(draftBody.slice(0, pos) + token + draftBody.slice(pos))
      requestAnimationFrame(() => {
        el?.focus()
        el?.setSelectionRange(pos + token.length, pos + token.length)
      })
    }
  }

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

  const dropScheduleQuery = useQuery({
    queryKey: ['admin-api', 'legal', 'settings', 'drop-schedule'],
    queryFn: getLegalDropSchedule,
    enabled: tab === 'drop_schedule',
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

  const dropScheduleMutation = useMutation({
    mutationFn: patchLegalDropSchedule,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['admin-api', 'legal', 'settings', 'drop-schedule'],
      })
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
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <button
          type="button"
          className={
            triggerVariant === 'header'
              ? 'inline-flex h-8 items-center justify-center rounded-md border border-line bg-white px-3 text-xs font-medium text-ink transition hover:bg-panel focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-habeas-mid'
              : 'rounded border border-line bg-white px-1.5 py-0.5 text-[0.65rem] text-ink-soft outline-none transition-colors hover:border-habeas-navy/35 hover:text-ink focus-visible:border-habeas-navy/40'
          }
          aria-label="Settings"
        >
          Settings
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
          <ConditionsEditor canWrite={canWrite} enabled={open && tab === 'conditions'} compact />
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
              Open Deadlines & SLAs
            </Link>
          </div>
        ) : null}
        {tab === 'templates' ? (
          <div className="space-y-3 text-sm">
            <div className="flex flex-wrap gap-2">
              {(templateTypesQuery.data ?? []).map((info) => (
                <button
                  key={info.type}
                  type="button"
                  className={
                    selectedTemplateType === info.type
                      ? 'taste-btn-primary text-xs'
                      : 'taste-btn text-xs'
                  }
                  onClick={() => setSelectedTemplateType(info.type)}
                >
                  {TEMPLATE_TYPE_LABELS[info.type] ?? info.type}
                </button>
              ))}
            </div>
            {templatesQuery.isPending || templateTypesQuery.isPending ? (
              <p className="text-mute">Loading templates…</p>
            ) : selectedTypeInfo ? (
              <div className="space-y-2">
                <p className="text-xs text-mute">
                  Slug <span className="font-mono">{selectedTypeInfo.slug}</span>
                </p>
                <div>
                  <p className="mb-1 text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                    Variables (fields visible on request detail — KD11)
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedTypeInfo.variables.map((variable) => (
                      <button
                        key={variable}
                        type="button"
                        disabled={!canWrite}
                        title={`Insert into ${activeTemplateField}`}
                        className="rounded border border-line bg-paper px-1.5 py-0.5 font-mono text-[0.65rem] text-ink-soft transition hover:border-habeas-navy/40 disabled:cursor-not-allowed disabled:opacity-50"
                        onClick={() => insertTemplateVariable(variable)}
                      >
                        {`{{${variable}}}`}
                      </button>
                    ))}
                  </div>
                </div>
                <label className="block text-xs text-ink-soft">
                  Subject
                  <input
                    ref={subjectInputRef}
                    type="text"
                    className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm disabled:opacity-60"
                    value={draftSubject}
                    disabled={!canWrite}
                    onFocus={() => setActiveTemplateField('subject')}
                    onChange={(event) => setDraftSubject(event.target.value)}
                  />
                </label>
                <label className="block text-xs text-ink-soft">
                  Body
                  <textarea
                    ref={bodyTextareaRef}
                    rows={8}
                    className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm disabled:opacity-60"
                    value={draftBody}
                    disabled={!canWrite}
                    onFocus={() => setActiveTemplateField('body')}
                    onChange={(event) => setDraftBody(event.target.value)}
                  />
                </label>
                <div className="flex items-center gap-2">
                  {canWrite ? (
                    <Button
                      type="button"
                      size="sm"
                      disabled={upsertTemplateMutation.isPending || !draftSubject || !draftBody}
                      onClick={() =>
                        upsertTemplateMutation.mutate({
                          slug: selectedTypeInfo.slug,
                          subject: draftSubject,
                          body: draftBody,
                        })
                      }
                    >
                      {upsertTemplateMutation.isPending ? 'Saving…' : 'Save template'}
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    disabled={previewTemplateMutation.isPending}
                    onClick={() => previewTemplateMutation.mutate(selectedTypeInfo.slug)}
                  >
                    Preview
                  </Button>
                </div>
                {upsertTemplateMutation.isError ? (
                  <p className="text-xs text-red-700">
                    {upsertTemplateMutation.error instanceof Error
                      ? upsertTemplateMutation.error.message
                      : 'Save failed.'}
                  </p>
                ) : null}
                {previewTemplateMutation.data ? (
                  <div className="rounded-md border border-line bg-white px-2.5 py-2 text-xs">
                    <p className="font-medium text-ink">{previewTemplateMutation.data.subject}</p>
                    <p className="mt-1 whitespace-pre-wrap text-ink-soft">
                      {previewTemplateMutation.data.body}
                    </p>
                  </div>
                ) : null}
              </div>
            ) : (
              <p className="text-mute">No template types configured.</p>
            )}
          </div>
        ) : null}
        {tab === 'drop_schedule' ? (
          <div className="space-y-3 text-sm">
            {dropScheduleQuery.data ? (
              <>
                <p className="text-ink-soft">{dropScheduleQuery.data.weekly_label}</p>
                <p className="text-xs text-mute">
                  Weekly California DROP batch upload · {dropScheduleQuery.data.timezone}
                </p>
                <div className="grid gap-2 sm:grid-cols-2">
                  <label className="block text-xs text-ink-soft">
                    Day of week
                    <select
                      className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm"
                      value={dropScheduleQuery.data.day_of_week}
                      disabled={!canWrite}
                      onChange={(event) => {
                        if (!canWrite) return
                        dropScheduleMutation.mutate({
                          day_of_week: Number.parseInt(event.target.value, 10),
                        })
                      }}
                    >
                      {WEEKDAY_OPTIONS.map((label, index) => (
                        <option key={label} value={index}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="block text-xs text-ink-soft">
                    Time (PT)
                    <input
                      type="time"
                      className="mt-1 w-full rounded border border-line bg-paper px-2 py-1 text-sm"
                      defaultValue={dropScheduleQuery.data.time_local}
                      disabled={!canWrite}
                      onBlur={(event) => {
                        if (!canWrite || !event.target.value) return
                        dropScheduleMutation.mutate({ time_local: event.target.value })
                      }}
                    />
                  </label>
                </div>
              </>
            ) : (
              <p className="text-mute">Loading DROP schedule…</p>
            )}
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
