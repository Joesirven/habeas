// @ts-nocheck — /dev paths are omitted from the product router Register.
/**
 * Temporary lab — eight owner connect/map layouts. Not primary nav.
 * Tear down after pick. Fixture only: no secrets leave this tab.
 */
import { Link, useNavigate } from '@tanstack/react-router'
import { useMemo, useState, type ReactNode } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  CADENCE_OPTION_RARELY,
  CADENCE_OPTION_WEEKLY,
  CADENCE_OPTION_WITH_NEW_BATCHES,
  LIVE_CONNECT_FAILURE_HINT,
  LIVE_CONNECT_RETRY_LABEL,
  LIVE_CONNECT_SETUP_UPLOAD_LABEL,
  LIVE_PING_NOT_EXTRACT_HINT,
  MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE,
  SYSTEM_COPY,
  UPLOAD_IDENTIFIER_FIELDS,
  UPLOAD_SAMPLE_CSV,
  allowsLive,
  allowsUpload,
  buildVerticalWizardSteps,
  displayStatusChip,
  liveConnectFailureActions,
  liveConnectSuccessFollowOn,
  livePingIsNotMatchingExtract,
  mappingFollowOnCopy,
  parseCsvHeaderRow,
  parseVerticalWizardStepId,
  suggestUploadColumnMapping,
  uploadMappingComplete,
  wizardProgressPercent,
  type CadenceOptionId,
} from '@/lib/owner-connector-ui'
import { cn } from '@/lib/utils'

export const OWNER_MAP_LAB_VARIANT_IDS = [
  'a',
  'b',
  'c',
  'd',
  'e',
  'f',
  'g',
  'h',
] as const

export type OwnerMapLabVariantId = (typeof OWNER_MAP_LAB_VARIANT_IDS)[number]

export type OwnerMapLabSearch = {
  v?: OwnerMapLabVariantId
}

export function parseOwnerMapLabSearch(
  search: Record<string, unknown>,
): OwnerMapLabSearch {
  const raw = typeof search.v === 'string' ? search.v.trim().toLowerCase() : ''
  if ((OWNER_MAP_LAB_VARIANT_IDS as readonly string[]).includes(raw)) {
    return { v: raw as OwnerMapLabVariantId }
  }
  return {}
}

const FIELD_CLASS =
  'w-full rounded-md border border-line bg-white px-3 py-2 text-sm text-ink outline-none transition focus:border-habeas-mid focus:ring-2 focus:ring-habeas-mid/20'

const SAMPLE_CSV = UPLOAD_SAMPLE_CSV.remap

type FixtureKind = 'upload' | 'live_ping' | 'infra'
type LiveOutcome = 'idle' | 'pass' | 'fail'
type WorkPane = 'connect' | 'mapping' | 'upload'

type FixtureSystem = {
  id: string
  label: string
  verticalLabel: string
  approaches: readonly string[]
  kind: FixtureKind
  note: string
}

const FIXTURES: readonly FixtureSystem[] = [
  {
    id: 'axios_hq',
    label: 'Axios HQ',
    verticalLabel: 'Communications',
    approaches: ['upload'],
    kind: 'upload',
    note: 'Upload a fresh file every batch. Habeas does not connect to Axios HQ directly.',
  },
  {
    id: 'lever',
    label: 'Lever',
    verticalLabel: 'People/HR',
    approaches: ['live', 'upload'],
    kind: 'live_ping',
    note: 'A passing Live test only checks Users read/list. Matching still needs a mapped upload.',
  },
  {
    id: 'paylocity',
    label: 'Paylocity',
    verticalLabel: 'People/HR',
    approaches: ['live', 'upload'],
    kind: 'live_ping',
    note: 'Live is SFTP, not an API. A passing ping is not matching-ready.',
  },
  {
    id: 'cassandra',
    label: 'Cassandra',
    verticalLabel: 'Infrastructure',
    approaches: [],
    kind: 'infra',
    note: 'Infra / suppress-only. No owner mapping and no hash extract.',
  },
]

const VARIANT_META: Record<
  OwnerMapLabVariantId,
  { letter: string; title: string; blurb: string; pick?: boolean }
> = {
  a: {
    letter: 'A',
    title: 'Honest split-rail',
    blurb:
      'Production pick. Left rail lists systems; the right pane is connect or map. Live success opens mapping. Live fail keeps Retry and Set up manual upload equal. Email or phone is enough.',
    pick: true,
  },
  b: {
    letter: 'B',
    title: 'Linear stepper',
    blurb: 'Current wizard density — one step at a time, progress bar, Back / Continue.',
  },
  c: {
    letter: 'C',
    title: 'Compact column',
    blurb: 'Narrow single column. Same copy, less chrome.',
  },
  d: {
    letter: 'D',
    title: 'Two-pane',
    blurb: 'Connect on the left, map on the right. Mapping stays inert until Live passes or upload is chosen.',
  },
  e: {
    letter: 'E',
    title: 'Fail cards',
    blurb: 'After Live fail, choose Retry or Set up manual upload as equal cards.',
  },
  f: {
    letter: 'F',
    title: 'Upload-first',
    blurb: 'CSV + mapping is the default path. Live is optional for Lever and Paylocity.',
  },
  g: {
    letter: 'G',
    title: 'Workbench',
    blurb: 'Ops workbench rail: Connect → Map → Cadence → Confirm, with per-system clusters.',
  },
  h: {
    letter: 'H',
    title: 'Table + drawer',
    blurb: 'Dense ops table. Row opens a right drawer. Cassandra is infra-only.',
  },
}

function sampleHeaders(): string[] {
  return parseCsvHeaderRow(SAMPLE_CSV.body)
}

function fixtureById(id: string): FixtureSystem {
  return FIXTURES.find((row) => row.id === id) ?? FIXTURES[0]
}

function IdentifierHint() {
  return (
    <p className="text-[11px] leading-relaxed text-mute">
      Map identifier columns if the headers differ. Email or phone is enough. First name and last
      name are optional.
    </p>
  )
}

function CassandraInfraCard({ compact = false }: { compact?: boolean }) {
  const chip = displayStatusChip('view_only')
  return (
    <article
      className={cn(
        'rounded-md border border-line bg-canvas px-3 py-2.5',
        compact ? 'text-xs' : '',
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-medium text-ink">Cassandra</p>
        <Badge variant={chip.variant}>{chip.label}</Badge>
        <Badge variant="default">Infra</Badge>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-mute">
        Suppress-only infrastructure. No owner mapping, no hash extract, and no Live credentials
        on this surface.
      </p>
    </article>
  )
}

function MappingSelects({
  mapping,
  onChange,
  headers,
}: {
  mapping: Record<string, string>
  onChange: (next: Record<string, string>) => void
  headers: readonly string[]
}) {
  const ready = uploadMappingComplete(mapping)
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-ink">Column mapping</p>
      <p className="text-[11px] text-mute">
        Sample headers from <span className="font-mono">{SAMPLE_CSV.filename}</span> — not a live
        file.
      </p>
      {UPLOAD_IDENTIFIER_FIELDS.map((field) => (
        <label key={field.id} className="block space-y-1 text-xs">
          <span className="text-ink">
            {field.label}
            {field.id === 'email' || field.id === 'phone' ? (
              <span className="ml-1 font-normal text-mute">enough on its own</span>
            ) : (
              <span className="ml-1 font-normal text-mute">optional</span>
            )}
          </span>
          <select
            className={FIELD_CLASS}
            value={mapping[field.id] ?? ''}
            onChange={(event) =>
              onChange({ ...mapping, [field.id]: event.target.value })
            }
            aria-label={`Map ${field.label} column`}
          >
            <option value="">Select a column…</option>
            {headers.map((header) => (
              <option key={`${field.id}:${header}`} value={header}>
                {header}
              </option>
            ))}
          </select>
        </label>
      ))}
      {ready ? (
        <p className="text-[11px] text-emerald-800">At least one identifier is mapped.</p>
      ) : (
        <IdentifierHint />
      )}
    </div>
  )
}

function EqualFailActions({
  onRetry,
  onUpload,
}: {
  onRetry: () => void
  onUpload: () => void
}) {
  return (
    <div className="grid grid-cols-2 gap-2">
      <Button type="button" size="sm" variant="outline" onClick={onRetry}>
        {LIVE_CONNECT_RETRY_LABEL}
      </Button>
      <Button type="button" size="sm" variant="outline" onClick={onUpload}>
        {LIVE_CONNECT_SETUP_UPLOAD_LABEL}
      </Button>
    </div>
  )
}

function LiveCredsFields({
  system,
  values,
  onChange,
}: {
  system: FixtureSystem
  values: Record<string, string>
  onChange: (id: string, value: string) => void
}) {
  const fields =
    system.id === 'lever'
      ? [{ id: 'api_key', label: 'API key', secret: true }]
      : [
          { id: 'sftp_host', label: 'SFTP host', secret: false },
          { id: 'sftp_username', label: 'SFTP username', secret: false },
          { id: 'sftp_password', label: 'SFTP password', secret: true },
        ]
  return (
    <div className="space-y-3">
      {fields.map((field) => (
        <label key={field.id} className="block space-y-1 text-xs">
          <span className="font-medium text-ink">{field.label}</span>
          <input
            className={FIELD_CLASS}
            type={field.secret ? 'password' : 'text'}
            autoComplete="off"
            value={values[field.id] ?? ''}
            onChange={(event) => onChange(field.id, event.target.value)}
            placeholder="Fixture only — not saved"
          />
        </label>
      ))}
      <p className="text-[11px] text-mute">
        Dummy values stay in this tab. Nothing is written to Secret Manager.
      </p>
    </div>
  )
}

function FixtureLiveToggle({
  value,
  onChange,
  disabled,
}: {
  value: LiveOutcome
  onChange: (next: LiveOutcome) => void
  disabled?: boolean
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-[11px] text-mute">Simulate Live</span>
      {(['idle', 'pass', 'fail'] as const).map((outcome) => (
        <Button
          key={outcome}
          type="button"
          size="sm"
          variant={value === outcome ? 'default' : 'outline'}
          disabled={disabled}
          onClick={() => onChange(outcome)}
        >
          {outcome === 'idle' ? 'Ready' : outcome === 'pass' ? 'Pass' : 'Fail'}
        </Button>
      ))}
    </div>
  )
}

function useOwnerMapFixture(initialId = 'lever') {
  const headers = useMemo(() => sampleHeaders(), [])
  const [systemId, setSystemId] = useState(initialId)
  const [liveBySystem, setLiveBySystem] = useState<Record<string, LiveOutcome>>({
    lever: 'idle',
    paylocity: 'idle',
  })
  const [paneBySystem, setPaneBySystem] = useState<Record<string, WorkPane>>({})
  const [credsBySystem, setCredsBySystem] = useState<Record<string, Record<string, string>>>({})
  const [mappingBySystem, setMappingBySystem] = useState<Record<string, Record<string, string>>>(
    () => ({
      axios_hq: suggestUploadColumnMapping(headers),
      lever: suggestUploadColumnMapping(headers),
      paylocity: suggestUploadColumnMapping(headers),
    }),
  )

  const system = fixtureById(systemId)
  const live = liveBySystem[systemId] ?? 'idle'
  const pane = paneBySystem[systemId] ?? (system.kind === 'upload' ? 'upload' : 'connect')
  const mapping = mappingBySystem[systemId] ?? {}
  const creds = credsBySystem[systemId] ?? {}
  const failure = liveConnectFailureActions({
    system: system.id,
    allowedApproaches: system.approaches,
  })
  const success = liveConnectSuccessFollowOn({
    system: system.id,
    allowedApproaches: system.approaches,
  })

  function setLive(next: LiveOutcome) {
    setLiveBySystem((current) => ({ ...current, [systemId]: next }))
    if (next === 'pass') {
      setPaneBySystem((current) => ({ ...current, [systemId]: 'mapping' }))
    }
    if (next === 'idle' || next === 'fail') {
      setPaneBySystem((current) => ({
        ...current,
        [systemId]: current[systemId] === 'upload' ? 'upload' : 'connect',
      }))
    }
  }

  function setPane(next: WorkPane) {
    setPaneBySystem((current) => ({ ...current, [systemId]: next }))
  }

  function setMapping(next: Record<string, string>) {
    setMappingBySystem((current) => ({ ...current, [systemId]: next }))
  }

  function setCred(id: string, value: string) {
    setCredsBySystem((current) => ({
      ...current,
      [systemId]: { ...(current[systemId] ?? {}), [id]: value },
    }))
  }

  function selectSystem(id: string) {
    setSystemId(id)
  }

  return {
    headers,
    system,
    systemId,
    live,
    pane,
    mapping,
    creds,
    failure,
    success,
    selectSystem,
    setLive,
    setPane,
    setMapping,
    setCred,
    liveBySystem,
    mappingBySystem,
  }
}

function SystemRail({
  selectedId,
  onSelect,
}: {
  selectedId: string
  onSelect: (id: string) => void
}) {
  return (
    <ul className="space-y-1">
      {FIXTURES.map((row) => {
        const selected = row.id === selectedId
        const chip =
          row.kind === 'infra'
            ? displayStatusChip('view_only')
            : row.kind === 'upload'
              ? displayStatusChip('needs_setup')
              : displayStatusChip('action_required')
        return (
          <li key={row.id}>
            <button
              type="button"
              onClick={() => onSelect(row.id)}
              className={cn(
                'w-full rounded-md border px-2.5 py-2 text-left transition-colors',
                selected
                  ? 'border-habeas-navy bg-white ring-1 ring-habeas-navy'
                  : 'border-line bg-white hover:border-line-strong',
              )}
            >
              <span className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-ink">{row.label}</span>
                <Badge variant={chip.variant}>{chip.label}</Badge>
              </span>
              <span className="mt-0.5 block text-[11px] text-mute">{row.verticalLabel}</span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function ConnectBody({
  fixture,
  live,
  creds,
  onCred,
  onLive,
  onUpload,
  compact,
}: {
  fixture: ReturnType<typeof useOwnerMapFixture>
  live: LiveOutcome
  creds: Record<string, string>
  onCred: (id: string, value: string) => void
  onLive: (next: LiveOutcome) => void
  onUpload: () => void
  compact?: boolean
}) {
  const { system, failure, success } = fixture
  if (system.kind === 'infra') return <CassandraInfraCard compact={compact} />
  if (system.kind === 'upload') {
    return (
      <div className="space-y-2">
        <p className="text-xs leading-relaxed text-ink-soft">
          {SYSTEM_COPY.axios_hq?.uploadHowto}
        </p>
        <IdentifierHint />
        <Button type="button" size="sm" onClick={onUpload}>
          Continue to mapping
        </Button>
      </div>
    )
  }

  const copy = SYSTEM_COPY[system.id]
  return (
    <div className="space-y-3">
      <p className="text-xs leading-relaxed text-ink-soft">{copy?.liveHowto}</p>
      <LiveCredsFields system={system} values={creds} onChange={onCred} />
      <FixtureLiveToggle value={live} onChange={onLive} />
      {live === 'pass' ? (
        <div
          className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900"
          role="status"
        >
          <p className="font-medium">Connection confirmed</p>
          <p className="mt-0.5">{success.hint}</p>
        </div>
      ) : null}
      {live === 'fail' ? (
        <div
          className="space-y-2 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900"
          role="alert"
        >
          <p className="font-medium">Connection test failed</p>
          <p>{failure.hint}</p>
          <EqualFailActions onRetry={() => onLive('idle')} onUpload={onUpload} />
        </div>
      ) : null}
      {live === 'idle' ? (
        <p className="text-[11px] text-mute">
          Continue stays off until the connection test passes. {LIVE_CONNECT_FAILURE_HINT}
        </p>
      ) : null}
    </div>
  )
}

function MappingBody({
  fixture,
  showSimulate = false,
}: {
  fixture: ReturnType<typeof useOwnerMapFixture>
  showSimulate?: boolean
}) {
  const { system, mapping, setMapping, headers, live } = fixture
  if (system.kind === 'infra') return <CassandraInfraCard />
  const copy = mappingFollowOnCopy(system.label)
  return (
    <div className="space-y-3">
      {showSimulate && system.kind === 'live_ping' ? (
        <FixtureLiveToggle value={live} onChange={fixture.setLive} />
      ) : null}
      <div>
        <h3 className="text-sm font-medium text-ink">{copy.title}</h3>
        <p className="mt-1 text-xs leading-relaxed text-ink-soft">{copy.intro}</p>
      </div>
      {livePingIsNotMatchingExtract(system.id) && live === 'pass' ? (
        <p className="rounded-md border border-line bg-canvas px-3 py-2 text-[11px] text-mute">
          {LIVE_PING_NOT_EXTRACT_HINT}
        </p>
      ) : null}
      <MappingSelects mapping={mapping} onChange={setMapping} headers={headers} />
    </div>
  )
}

function LabFrame({
  title,
  children,
}: {
  title: string
  children: ReactNode
}) {
  return (
    <article className="rounded-md border border-line bg-white">
      <header className="border-b border-line px-4 py-3">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Fixture
        </p>
        <h2 className="mt-1 text-sm font-semibold text-ink">{title}</h2>
      </header>
      <div className="p-4">{children}</div>
    </article>
  )
}

/** A — Honest split-rail (production pick). */
function VariantA() {
  const fixture = useOwnerMapFixture('lever')
  const { system, pane, selectSystem, setLive, setPane, setCred, live, creds } = fixture
  const showMapping =
    pane === 'mapping' || pane === 'upload' || system.kind === 'upload'

  return (
    <LabFrame title="A · Honest split-rail">
      <div className="grid gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
        <aside className="space-y-2">
          <p className="text-[11px] font-medium uppercase tracking-wide text-mute">Systems</p>
          <SystemRail selectedId={system.id} onSelect={selectSystem} />
        </aside>
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-ink">{system.label}</p>
              <p className="text-xs text-mute">{system.note}</p>
            </div>
            {system.kind === 'live_ping' && live === 'pass' ? (
              <Button type="button" size="sm" onClick={() => setPane('mapping')}>
                Continue to mapping
              </Button>
            ) : null}
          </div>
          {system.kind === 'infra' ? (
            <CassandraInfraCard />
          ) : showMapping && (live === 'pass' || pane === 'upload' || system.kind === 'upload') ? (
            <MappingBody fixture={fixture} showSimulate />
          ) : (
            <ConnectBody
              fixture={fixture}
              live={live}
              creds={creds}
              onCred={setCred}
              onLive={setLive}
              onUpload={() => setPane('upload')}
            />
          )}
        </div>
      </div>
      <p className="mt-4 text-[11px] text-mute">{MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE}</p>
    </LabFrame>
  )
}

const CADENCE_COPY: Record<CadenceOptionId, { label: string; description: string }> = {
  [CADENCE_OPTION_RARELY]: {
    label: 'This list rarely changes',
    description: 'One good extract or upload is enough until you choose otherwise.',
  },
  [CADENCE_OPTION_WITH_NEW_BATCHES]: {
    label: 'Keep current with new request batches',
    description: 'Refresh when Habeas promotes a new DROP intake batch (12-hour floor).',
  },
  [CADENCE_OPTION_WEEKLY]: {
    label: 'Weekly',
    description: 'Matching needs a successful upload or refresh within the last 7 days.',
  },
}

/** B — Linear stepper at current wizard density. */
function VariantB() {
  const [vertical, setVertical] = useState<'people_hr' | 'communications'>('people_hr')
  const fixture = useOwnerMapFixture(vertical === 'communications' ? 'axios_hq' : 'lever')
  const steps = useMemo(
    () =>
      buildVerticalWizardSteps({
        systems:
          vertical === 'communications'
            ? [{ system: 'axios_hq', allowedApproaches: ['upload'] }]
            : [
                { system: 'lever', allowedApproaches: ['live', 'upload'] },
                { system: 'paylocity', allowedApproaches: ['live', 'upload'] },
              ],
      }),
    [vertical],
  )
  const [stepIndex, setStepIndex] = useState(0)
  const [cadence, setCadence] = useState<CadenceOptionId | null>(null)
  const step = steps[stepIndex]
  const parsed = step ? parseVerticalWizardStepId(step.id) : null
  const percent = wizardProgressPercent(stepIndex, steps.length)
  const stepSystem =
    parsed && 'system' in parsed ? fixtureById(parsed.system) : fixture.system

  function goTo(index: number) {
    setStepIndex(index)
    const entry = steps[index]
    if (!entry) return
    const next = parseVerticalWizardStepId(entry.id)
    if (next && 'system' in next) fixture.selectSystem(next.system)
  }

  let body: ReactNode = null
  if (parsed?.kind === 'cadence') {
    body = (
      <fieldset className="space-y-2">
        <legend className="text-xs font-medium text-ink">Refresh cadence</legend>
        {(Object.keys(CADENCE_COPY) as CadenceOptionId[]).map((id) => (
          <label
            key={id}
            className={cn(
              'flex cursor-pointer gap-2 rounded-md border px-3 py-2 text-xs',
              cadence === id ? 'border-habeas-navy ring-1 ring-habeas-navy' : 'border-line',
            )}
          >
            <input
              type="radio"
              name="lab-cadence"
              checked={cadence === id}
              onChange={() => setCadence(id)}
            />
            <span>
              <span className="block font-medium text-ink">{CADENCE_COPY[id].label}</span>
              <span className="text-mute">{CADENCE_COPY[id].description}</span>
            </span>
          </label>
        ))}
      </fieldset>
    )
  } else if (parsed?.kind === 'confirm') {
    body = (
      <p className="text-xs text-ink-soft">
        Setup is ready to complete. Connecting does not start matching by itself.
      </p>
    )
  } else if (parsed?.kind === 'howto-live' || parsed?.kind === 'howto-upload' || parsed?.kind === 'howto') {
    const copy = SYSTEM_COPY[stepSystem.id]
    body = (
      <p className="text-xs leading-relaxed text-ink-soft">
        {parsed.kind === 'howto-live' ? copy?.liveHowto : copy?.uploadHowto ?? copy?.howto}
      </p>
    )
  } else if (parsed?.kind === 'live-creds') {
    body = (
      <ConnectBody
        fixture={fixture}
        live={fixture.live}
        creds={fixture.creds}
        onCred={fixture.setCred}
        onLive={fixture.setLive}
        onUpload={() => {
          const uploadIdx = steps.findIndex(
            (entry) =>
              parsed && 'system' in parsed && entry.id === `${parsed.system}-howto-upload`,
          )
          if (uploadIdx >= 0) goTo(uploadIdx)
        }}
      />
    )
  } else if (parsed?.kind === 'mapping' || parsed?.kind === 'upload' || parsed?.kind === 'mapping-clean') {
    body = <MappingBody fixture={fixture} />
  }

  return (
    <LabFrame title="B · Linear stepper">
      <div className="mb-3 flex flex-wrap gap-1">
        <Button
          type="button"
          size="sm"
          variant={vertical === 'people_hr' ? 'default' : 'outline'}
          onClick={() => {
            setVertical('people_hr')
            fixture.selectSystem('lever')
            setStepIndex(0)
          }}
        >
          People/HR
        </Button>
        <Button
          type="button"
          size="sm"
          variant={vertical === 'communications' ? 'default' : 'outline'}
          onClick={() => {
            setVertical('communications')
            fixture.selectSystem('axios_hq')
            setStepIndex(0)
          }}
        >
          Communications
        </Button>
      </div>
      <div className="mb-3 h-1.5 overflow-hidden rounded-full bg-line">
        <div
          className="h-full rounded-full bg-habeas-navy"
          style={{ width: `${percent}%` }}
        />
      </div>
      <p className="mb-3 font-mono text-[11px] text-mute">
        Step {stepIndex + 1} / {steps.length}
        {step ? ` · ${step.id}` : ''}
      </p>
      <ol className="mb-3 flex flex-wrap gap-1">
        {steps.map((entry, index) => (
          <li key={entry.id}>
            <button
              type="button"
              onClick={() => goTo(index)}
              className={cn(
                'rounded border px-1.5 py-0.5 text-[0.65rem]',
                index === stepIndex
                  ? 'border-habeas-navy bg-habeas-navy text-white'
                  : index < stepIndex
                    ? 'border-emerald-200 bg-emerald-50 text-emerald-900'
                    : 'border-line bg-canvas text-mute',
              )}
            >
              {index + 1}
            </button>
          </li>
        ))}
      </ol>
      {body}
      <div className="mt-4 flex justify-between">
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={stepIndex === 0}
          onClick={() => goTo(Math.max(0, stepIndex - 1))}
        >
          Back
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={stepIndex >= steps.length - 1}
          onClick={() => goTo(Math.min(steps.length - 1, stepIndex + 1))}
        >
          Continue
        </Button>
      </div>
      <div className="mt-4">
        <CassandraInfraCard compact />
      </div>
    </LabFrame>
  )
}

/** C — Compact single-column. */
function VariantC() {
  const fixture = useOwnerMapFixture('paylocity')
  return (
    <LabFrame title="C · Compact single-column">
      <div className="mx-auto max-w-md space-y-3">
        <label className="block text-xs">
          <span className="font-medium text-ink">System</span>
          <select
            className={cn(FIELD_CLASS, 'mt-1')}
            value={fixture.systemId}
            onChange={(event) => fixture.selectSystem(event.target.value)}
          >
            {FIXTURES.map((row) => (
              <option key={row.id} value={row.id}>
                {row.label}
              </option>
            ))}
          </select>
        </label>
        {fixture.system.kind === 'infra' ? (
          <CassandraInfraCard compact />
        ) : fixture.pane === 'mapping' || fixture.pane === 'upload' || fixture.live === 'pass' ? (
          <MappingBody fixture={fixture} showSimulate />
        ) : (
          <ConnectBody
            fixture={fixture}
            live={fixture.live}
            creds={fixture.creds}
            onCred={fixture.setCred}
            onLive={fixture.setLive}
            onUpload={() => fixture.setPane('upload')}
            compact
          />
        )}
      </div>
    </LabFrame>
  )
}

/** D — Two-pane connect | map. */
function VariantD() {
  const fixture = useOwnerMapFixture('lever')
  const mappingUnlocked =
    fixture.system.kind === 'upload' ||
    fixture.live === 'pass' ||
    fixture.pane === 'upload'
  return (
    <LabFrame title="D · Two-pane connect | map">
      <div className="mb-3">
        <SystemRail selectedId={fixture.systemId} onSelect={fixture.selectSystem} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <section className="rounded-md border border-line p-3">
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-mute">
            Connect
          </p>
          <ConnectBody
            fixture={fixture}
            live={fixture.live}
            creds={fixture.creds}
            onCred={fixture.setCred}
            onLive={fixture.setLive}
            onUpload={() => fixture.setPane('upload')}
          />
        </section>
        <section
          className={cn(
            'rounded-md border p-3',
            mappingUnlocked ? 'border-line' : 'border-dashed border-line bg-canvas',
          )}
        >
          <p className="mb-2 text-[11px] font-medium uppercase tracking-wide text-mute">Map</p>
          {fixture.system.kind === 'infra' ? (
            <p className="text-xs text-mute">Cassandra has no mapping step.</p>
          ) : mappingUnlocked ? (
            <MappingBody fixture={fixture} />
          ) : (
            <p className="text-xs text-mute">
              Mapping unlocks after a passing Live test or Set up manual upload. A Live ping is
              not matching-ready.
            </p>
          )}
        </section>
      </div>
    </LabFrame>
  )
}

/** E — Card chooser after live fail. */
function VariantE() {
  const fixture = useOwnerMapFixture('lever')
  const [chooser, setChooser] = useState<'retry' | 'upload' | null>(null)
  return (
    <LabFrame title="E · Card chooser after Live fail">
      <div className="mb-3 flex flex-wrap gap-1">
        {FIXTURES.filter((row) => row.kind !== 'infra').map((row) => (
          <Button
            key={row.id}
            type="button"
            size="sm"
            variant={fixture.systemId === row.id ? 'default' : 'outline'}
            onClick={() => {
              fixture.selectSystem(row.id)
              setChooser(null)
            }}
          >
            {row.label}
          </Button>
        ))}
      </div>
      {fixture.system.kind === 'upload' ? (
        <MappingBody fixture={fixture} />
      ) : fixture.live !== 'fail' || chooser === 'retry' ? (
        <div className="space-y-3">
          <ConnectBody
            fixture={fixture}
            live={chooser === 'retry' ? 'idle' : fixture.live}
            creds={fixture.creds}
            onCred={fixture.setCred}
            onLive={(next) => {
              setChooser(null)
              fixture.setLive(next)
            }}
            onUpload={() => {
              setChooser('upload')
              fixture.setPane('upload')
            }}
          />
          {fixture.live === 'pass' ? <MappingBody fixture={fixture} /> : null}
        </div>
      ) : chooser === 'upload' ? (
        <MappingBody fixture={fixture} />
      ) : (
        <div className="space-y-3">
          <div
            className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-900"
            role="alert"
          >
            <p className="font-medium">Connection test failed</p>
            <p className="mt-0.5">{fixture.failure.hint}</p>
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <button
              type="button"
              onClick={() => {
                setChooser('retry')
                fixture.setLive('idle')
              }}
              className="rounded-md border border-line p-3 text-left hover:border-habeas-navy"
            >
              <p className="text-sm font-medium text-ink">{LIVE_CONNECT_RETRY_LABEL}</p>
              <p className="mt-1 text-xs text-mute">
                Paste credentials again and re-run the connectivity ping.
              </p>
            </button>
            <button
              type="button"
              onClick={() => {
                setChooser('upload')
                fixture.setPane('upload')
              }}
              className="rounded-md border border-line p-3 text-left hover:border-habeas-navy"
            >
              <p className="text-sm font-medium text-ink">{LIVE_CONNECT_SETUP_UPLOAD_LABEL}</p>
              <p className="mt-1 text-xs text-mute">
                Export a CSV and map identifier columns. Email or phone is enough.
              </p>
            </button>
          </div>
        </div>
      )}
      <div className="mt-4">
        <CassandraInfraCard compact />
      </div>
    </LabFrame>
  )
}

/** F — Upload-first, live optional. */
function VariantF() {
  const fixture = useOwnerMapFixture('axios_hq')
  const [liveOpen, setLiveOpen] = useState(false)
  return (
    <LabFrame title="F · Upload-first, Live optional">
      <div className="mb-3 flex flex-wrap gap-1">
        {FIXTURES.map((row) => (
          <Button
            key={row.id}
            type="button"
            size="sm"
            variant={fixture.systemId === row.id ? 'default' : 'outline'}
            onClick={() => fixture.selectSystem(row.id)}
          >
            {row.label}
          </Button>
        ))}
      </div>
      {fixture.system.kind === 'infra' ? (
        <CassandraInfraCard />
      ) : (
        <div className="space-y-4">
          <section className="space-y-2 rounded-md border border-line p-3">
            <p className="text-xs font-medium text-ink">Upload (default)</p>
            <p className="text-xs leading-relaxed text-ink-soft">
              {SYSTEM_COPY[fixture.system.id]?.uploadHowto ??
                SYSTEM_COPY.axios_hq?.uploadHowto}
            </p>
            <MappingBody fixture={fixture} />
          </section>
          {allowsLive(fixture.system.approaches) ? (
            <section className="rounded-md border border-dashed border-line p-3">
              <button
                type="button"
                className="text-xs font-medium text-habeas-navy underline-offset-2 hover:underline"
                onClick={() => setLiveOpen((open) => !open)}
              >
                {liveOpen ? 'Hide Live connection' : 'Optional: test a Live connection'}
              </button>
              {liveOpen ? (
                <div className="mt-3">
                  <ConnectBody
                    fixture={fixture}
                    live={fixture.live}
                    creds={fixture.creds}
                    onCred={fixture.setCred}
                    onLive={fixture.setLive}
                    onUpload={() => fixture.setPane('upload')}
                  />
                </div>
              ) : (
                <p className="mt-1 text-[11px] text-mute">
                  Live is optional. A passing ping is not matching-ready.
                </p>
              )}
            </section>
          ) : null}
        </div>
      )}
    </LabFrame>
  )
}

const WORKBENCH_STAGES = ['connect', 'map', 'cadence', 'confirm'] as const

/** G — Timeline / workbench (ops-ia). */
function VariantG() {
  const fixture = useOwnerMapFixture('lever')
  const [stage, setStage] = useState<(typeof WORKBENCH_STAGES)[number]>('connect')
  return (
    <LabFrame title="G · Timeline / workbench">
      <ol className="mb-4 grid grid-cols-4 gap-1">
        {WORKBENCH_STAGES.map((id) => (
          <li key={id}>
            <button
              type="button"
              onClick={() => setStage(id)}
              className={cn(
                'w-full rounded-md border px-2 py-1.5 text-[11px] font-medium capitalize',
                stage === id
                  ? 'border-habeas-navy bg-habeas-navy text-white'
                  : 'border-line bg-canvas text-mute',
              )}
            >
              {id}
            </button>
          </li>
        ))}
      </ol>
      {stage === 'connect' ? (
        <div className="space-y-3">
          {FIXTURES.map((row) => (
            <article key={row.id} className="rounded-md border border-line px-3 py-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-ink">
                  {row.label}
                  <span className="ml-2 font-normal text-mute">{row.verticalLabel}</span>
                </p>
                {row.kind === 'infra' ? (
                  <Badge variant="default">Suppress-only</Badge>
                ) : row.kind === 'upload' ? (
                  <Badge variant="wait">Upload every batch</Badge>
                ) : (
                  <Badge
                    variant={
                      fixture.liveBySystem[row.id] === 'pass'
                        ? 'ok'
                        : fixture.liveBySystem[row.id] === 'fail'
                          ? 'fail'
                          : 'wait'
                    }
                  >
                    Live ping
                  </Badge>
                )}
              </div>
              {row.kind === 'infra' ? (
                <p className="mt-1 text-[11px] text-mute">{row.note}</p>
              ) : (
                <button
                  type="button"
                  className="mt-1 text-[11px] text-habeas-navy underline-offset-2 hover:underline"
                  onClick={() => fixture.selectSystem(row.id)}
                >
                  {fixture.systemId === row.id ? 'Selected' : 'Open cluster'}
                </button>
              )}
            </article>
          ))}
          {fixture.system.kind !== 'infra' ? (
            <ConnectBody
              fixture={fixture}
              live={fixture.live}
              creds={fixture.creds}
              onCred={fixture.setCred}
              onLive={fixture.setLive}
              onUpload={() => {
                fixture.setPane('upload')
                setStage('map')
              }}
            />
          ) : (
            <CassandraInfraCard />
          )}
        </div>
      ) : null}
      {stage === 'map' ? (
        fixture.system.kind === 'infra' ? (
          <p className="text-xs text-mute">Cassandra has no mapping cluster.</p>
        ) : (
          <MappingBody fixture={fixture} />
        )
      ) : null}
      {stage === 'cadence' ? (
        <p className="text-xs text-ink-soft">
          Axios HQ refreshes every batch. Lever and Paylocity follow the cadence you pick after
          mapping. Cassandra has no cadence.
        </p>
      ) : null}
      {stage === 'confirm' ? (
        <p className="text-xs text-ink-soft">{MODE_STEP_CONNECTING_NOT_MATCHING_FOOTNOTE}</p>
      ) : null}
    </LabFrame>
  )
}

/** H — Dense ops table + drawer. */
function VariantH() {
  const fixture = useOwnerMapFixture('lever')
  const [open, setOpen] = useState(false)

  function openRow(id: string) {
    fixture.selectSystem(id)
    setOpen(true)
  }

  return (
    <LabFrame title="H · Dense ops table + drawer">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>System</TableHead>
            <TableHead>Vertical</TableHead>
            <TableHead>Mode</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Mapping</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {FIXTURES.map((row) => {
            const live = fixture.liveBySystem[row.id]
            const mapped = uploadMappingComplete(fixture.mappingBySystem[row.id] ?? {})
            const mode =
              row.kind === 'infra'
                ? '—'
                : allowsUpload(row.approaches) && allowsLive(row.approaches)
                  ? 'Live + upload'
                  : 'Upload'
            const chip =
              row.kind === 'infra'
                ? displayStatusChip('view_only')
                : live === 'pass' || mapped
                  ? displayStatusChip('connected')
                  : live === 'fail'
                    ? displayStatusChip('action_required')
                    : displayStatusChip('needs_setup')
            return (
              <TableRow
                key={row.id}
                className="cursor-pointer"
                onClick={() => openRow(row.id)}
              >
                <TableCell className="font-medium text-ink">{row.label}</TableCell>
                <TableCell className="text-mute">{row.verticalLabel}</TableCell>
                <TableCell>{mode}</TableCell>
                <TableCell>
                  <Badge variant={chip.variant}>{chip.label}</Badge>
                </TableCell>
                <TableCell className="text-mute">
                  {row.kind === 'infra' ? 'None' : mapped ? 'Ready' : 'Needed'}
                </TableCell>
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
      <p className="mt-2 text-[11px] text-mute">Select a row to open the drawer.</p>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="fixed inset-y-0 right-0 left-auto top-0 h-full max-h-none w-full max-w-md translate-x-0 translate-y-0 overflow-y-auto rounded-none border-l p-5">
          <DialogHeader>
            <DialogTitle>{fixture.system.label}</DialogTitle>
            <DialogDescription>{fixture.system.note}</DialogDescription>
          </DialogHeader>
          {fixture.system.kind === 'infra' ? (
            <CassandraInfraCard />
          ) : fixture.pane === 'mapping' ||
            fixture.pane === 'upload' ||
            fixture.live === 'pass' ||
            fixture.system.kind === 'upload' ? (
            <MappingBody fixture={fixture} showSimulate />
          ) : (
            <ConnectBody
              fixture={fixture}
              live={fixture.live}
              creds={fixture.creds}
              onCred={fixture.setCred}
              onLive={fixture.setLive}
              onUpload={() => fixture.setPane('upload')}
            />
          )}
        </DialogContent>
      </Dialog>
    </LabFrame>
  )
}

const VARIANT_VIEWS: Record<OwnerMapLabVariantId, () => ReactNode> = {
  a: () => <VariantA />,
  b: () => <VariantB />,
  c: () => <VariantC />,
  d: () => <VariantD />,
  e: () => <VariantE />,
  f: () => <VariantF />,
  g: () => <VariantG />,
  h: () => <VariantH />,
}

export function OwnerMapAlternativesPage({
  search,
}: {
  search?: OwnerMapLabSearch
}) {
  const navigate = useNavigate()
  const variant = search?.v ?? 'a'
  const meta = VARIANT_META[variant]
  const View = VARIANT_VIEWS[variant]

  return (
    <section className="mx-auto max-w-6xl space-y-4 p-4 sm:p-6">
      <header className="space-y-1">
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.14em] text-mute">
          Temporary · not in primary nav
        </p>
        <h1 className="text-xl font-semibold text-ink">Owner map alternatives</h1>
        <p className="max-w-3xl text-sm text-ink-soft">
          Eight fixture layouts for connect → map. Default is <strong>A · Honest split-rail</strong>{' '}
          (production pick). Switch with the control below or{' '}
          <span className="font-mono text-xs">?v=a</span> through{' '}
          <span className="font-mono text-xs">?v=h</span>. Values never leave this tab.{' '}
          <Link className="text-habeas-navy underline-offset-2 hover:underline" to="/dev">
            All labs
          </Link>
          . Production wizard stays at{' '}
          <Link
            className="text-habeas-navy underline-offset-2 hover:underline"
            to="/owner/connectors"
          >
            /owner/connectors
          </Link>
          .
        </p>
      </header>

      <Tabs
        value={variant}
        onValueChange={(next) => {
          if (!(OWNER_MAP_LAB_VARIANT_IDS as readonly string[]).includes(next)) return
          void navigate({
            to: '/dev/owner-map-alternatives',
            search: { v: next as OwnerMapLabVariantId },
            replace: true,
          })
        }}
      >
        <TabsList className="flex h-auto min-h-8 w-full flex-wrap justify-start gap-0.5">
          {OWNER_MAP_LAB_VARIANT_IDS.map((id) => (
            <TabsTrigger key={id} value={id} className="px-2">
              {VARIANT_META[id].letter}
              {VARIANT_META[id].pick ? ' · pick' : ''} {VARIANT_META[id].title}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      <p className="text-xs leading-relaxed text-mute">{meta.blurb}</p>
      {View()}
    </section>
  )
}
