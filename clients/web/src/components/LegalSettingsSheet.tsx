import { useQuery } from '@tanstack/react-query'
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
import { getRouteTriageCondition, listEmailTemplates } from '@/lib/api'
import { canMutateLegalSettings, useMe } from '@/lib/auth'

type SettingsTab = 'conditions' | 'slas' | 'templates'

export function LegalSettingsSheet() {
  const { role } = useMe()
  const canWrite = canMutateLegalSettings(role)
  const [tab, setTab] = useState<SettingsTab>('conditions')

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

  const tabs: { id: SettingsTab; label: string }[] = [
    { id: 'conditions', label: 'Conditions' },
    { id: 'slas', label: 'SLAs' },
    { id: 'templates', label: 'Templates' },
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
            <Button asChild size="sm" variant="outline">
              <Link to="/requests/conditions">
                {canWrite ? 'Open Conditions editor' : 'View Conditions'}
              </Link>
            </Button>
          </div>
        ) : null}
        {tab === 'slas' ? (
          <div className="space-y-3 text-sm text-ink-soft">
            <p>
              Breach clocks and waiting-on-review presets ship with journey monitors. Inbox rows
              show overdue / due soon from the matching-review SLA window.
            </p>
            <Button asChild size="sm" variant="outline">
              <Link to="/requests/slas">Open SLAs</Link>
            </Button>
          </div>
        ) : null}
        {tab === 'templates' ? (
          <div className="space-y-3 text-sm text-ink-soft">
            {templatesQuery.isPending ? <p>Loading templates…</p> : null}
            <ul className="space-y-2">
              {(templatesQuery.data ?? []).map((template) => (
                <li key={template.id} className="rounded border border-line px-3 py-2">
                  <p className="font-medium text-ink">{template.slug}</p>
                  <p className="text-xs text-mute">{template.subject}</p>
                </li>
              ))}
            </ul>
            {!canWrite ? (
              <p className="text-xs text-mute">Template editing is admin-only.</p>
            ) : null}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
