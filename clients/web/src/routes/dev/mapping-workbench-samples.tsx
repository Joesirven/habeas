// @ts-nocheck — /dev paths are omitted from the product router Register.
/**
 * Temporary lab — eight mapping-workbench HTML samples (header → assign → format,
 * derived Email/Phone/NDZ). Fixture UI only; tear down after pick.
 */
import { Link, useNavigate } from '@tanstack/react-router'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export const MAPPING_WORKBENCH_SAMPLE_IDS = [
  'a',
  'b',
  'c',
  'd',
  'e',
  'f',
  'g',
  'h',
] as const

export type MappingWorkbenchSampleId =
  (typeof MAPPING_WORKBENCH_SAMPLE_IDS)[number]

export type MappingWorkbenchLabSearch = {
  v?: MappingWorkbenchSampleId
}

const SAMPLES: Record<
  MappingWorkbenchSampleId,
  { letter: string; title: string; blurb: string; file: string }
> = {
  a: {
    letter: 'A',
    title: 'Attio stepper',
    blurb: 'Header → Assign → Format → Confirm with live derived chips.',
    file: '01-attio-stepper.html',
  },
  b: {
    letter: 'B',
    title: 'Midday modal',
    blurb: 'Confirm-import modal over a dimmed connection page.',
    file: '02-midday-confirm-modal.html',
  },
  c: {
    letter: 'C',
    title: 'Spreadsheet header pick',
    blurb: 'CSV grid; pick header row; assign columns; format drawer.',
    file: '03-spreadsheet-header-pick.html',
  },
  d: {
    letter: 'D',
    title: 'Dual pane preview',
    blurb: 'Left map columns; right live sample preview; partial NDZ.',
    file: '04-dual-pane-preview.html',
  },
  e: {
    letter: 'E',
    title: 'Capability rail',
    blurb: 'Large derived Email/Phone/NDZ cards; lists follow variables.',
    file: '05-capability-rail.html',
  },
  f: {
    letter: 'F',
    title: 'Three-column ops',
    blurb: 'Headers | canonical targets | format; sticky derived bar.',
    file: '06-three-column-ops.html',
  },
  g: {
    letter: 'G',
    title: 'Post-upload sheet',
    blurb: 'Upload-ready card + full-height right drawer workbench.',
    file: '07-post-upload-sheet.html',
  },
  h: {
    letter: 'H',
    title: 'Compact ops table',
    blurb: 'Dense single page; no wizard chrome. (Strip invented keys if picked.)',
    file: '08-compact-ops-table.html',
  },
}

const STATIC_BASE = '/dev/mapping-workbench-samples'

export function parseMappingWorkbenchLabSearch(
  search: Record<string, unknown>,
): MappingWorkbenchLabSearch {
  const raw = typeof search.v === 'string' ? search.v.trim().toLowerCase() : ''
  if ((MAPPING_WORKBENCH_SAMPLE_IDS as readonly string[]).includes(raw)) {
    return { v: raw as MappingWorkbenchSampleId }
  }
  return {}
}

export function MappingWorkbenchSamplesPage({
  search,
}: {
  search?: MappingWorkbenchLabSearch
}) {
  const navigate = useNavigate()
  const variant = search?.v ?? 'a'
  const meta = SAMPLES[variant]
  const src = `${STATIC_BASE}/${meta.file}`

  return (
    <div className="flex h-[calc(100vh-3.5rem)] flex-col bg-canvas">
      <header className="shrink-0 border-b border-line bg-white px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
              Temporary lab
            </p>
            <h1 className="mt-0.5 text-lg font-semibold text-habeas-navy">
              Mapping workbench samples
            </h1>
            <p className="mt-1 max-w-2xl text-sm text-slate-600">
              Pick a layout for header → assign → format/clean. Email / Phone / NDZ
              chips are derived (not toggles). Fixture HTML only — admin-api-dev is
              live for the rest of the SPA.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="wait">admin-web-dev</Badge>
            <Button asChild variant="outline" size="sm">
              <Link to="/dev">All labs</Link>
            </Button>
            <Button asChild variant="outline" size="sm">
              <a href={src} target="_blank" rel="noreferrer">
                Open sample alone
              </a>
            </Button>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {MAPPING_WORKBENCH_SAMPLE_IDS.map((id) => {
            const item = SAMPLES[id]
            const active = id === variant
            return (
              <button
                key={id}
                type="button"
                className={cn(
                  'rounded-md border px-2.5 py-1 text-left text-xs transition',
                  active
                    ? 'border-habeas-navy bg-habeas-navy text-white'
                    : 'border-line bg-white text-ink hover:border-habeas-mid',
                )}
                onClick={() => {
                  void navigate({
                    to: '/dev/mapping-workbench-samples',
                    search: { v: id },
                    replace: true,
                  })
                }}
              >
                <span className="font-semibold">{item.letter}</span>
                <span className="ml-1 opacity-90">{item.title}</span>
              </button>
            )
          })}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          <span className="font-medium text-slate-700">
            {meta.letter} · {meta.title}.
          </span>{' '}
          {meta.blurb}
        </p>
      </header>
      <iframe
        key={variant}
        title={`Sample ${meta.letter} — ${meta.title}`}
        src={src}
        className="min-h-0 w-full flex-1 border-0 bg-white"
      />
    </div>
  )
}
