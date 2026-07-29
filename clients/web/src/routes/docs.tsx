const SECTIONS = [
  { id: 'how-it-works', label: 'How it works' },
  { id: 'how-tos', label: 'Your actions' },
  { id: 'features', label: 'Features' },
  { id: 'command-palette', label: '⌘K' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'faq', label: 'FAQ' },
] as const

type FeatureEntry = {
  id: string
  title: string
  one_liner: string
  detail: string[]
  gif: string
}

/** Catalog — GIFs in /docs-gifs/. Command palette lives in its own section. */
const FEATURES: FeatureEntry[] = [
  {
    id: 'operations-pulse',
    title: 'Operations pulse',
    one_liner: 'Live counts for your queue, team backlog, SLA risk, overdue, and median age.',
    detail: [
      'Sits at the top of Home so you see portfolio pressure before drilling into modules.',
      'Click a chip to expand a short explanation and jump into the matching Inbox or All requests filter.',
      'Assigned to you and team-wide counts ignore the analytics date window — they always show open work.',
    ],
    gif: 'operations-pulse.gif',
  },
  {
    id: 'fulfillment-batches',
    title: 'Fulfillment batches',
    one_liner: 'Recent intake batches by source and received time; select one to scope the funnel.',
    detail: [
      'Each row is an intake wave (for example California DROP or manual) grouped by received datetime.',
      'Selecting a batch scopes the pipeline funnel underneath to that wave only; clear selection to see everything.',
      'Use this when comparing volume or stage progress for a specific download or upload day.',
    ],
    gif: 'fulfillment-batches.gif',
  },
  {
    id: 'pipeline-funnel',
    title: 'Pipeline funnel',
    one_liner:
      'See how requests move through each journey stage; filter by batch or the whole portfolio.',
    detail: [
      'Stages follow the legal journey: receive → matching → data owner review → legal / pre-fulfillment → fulfillment → delivery / DROP notice.',
      'Widths show how many requests reached each stage; drops between stages are visible so you can spot where work stalls.',
      'Click a stage to open the cohort in All requests when you need the underlying list.',
    ],
    gif: 'pipeline-funnel.gif',
  },
  {
    id: 'inbox-legal-filter-chips',
    title: 'Legal inbox filter chips',
    one_liner:
      'Chips slice your queue: Unassigned, Assignment to legal, Fulfillment, Notice, Delivery, Pre-matching holds, Assigned to me.',
    detail: [
      'Inbox is your work queue — not the full inventory. One list; chips change which work kinds appear.',
      'Unassigned is claimable work. Assignment to legal is help requests from data owners. Notice and Delivery are DROP and access handoffs.',
      'Pre-matching holds are requests that must not enter matching until legal clears them.',
    ],
    gif: 'inbox-legal-filter-chips.gif',
  },
  {
    id: 'all-requests',
    title: 'All requests',
    one_liner:
      'Full request inventory — flat or grouped by intake batch — with source, attention, and search filters.',
    detail: [
      'Use All requests when you need history or cross-queue search, not day-to-day triage.',
      'Toggle flat vs batch grouping. Source and attention chips write into the URL so you can share a filtered view.',
      'Name search works on non–California DROP requests. DROP rows search by request id only until post-match identity exists.',
    ],
    gif: 'all-requests.gif',
  },
  {
    id: 'request-detail-overlay',
    title: 'Request detail overlay',
    one_liner:
      'Open any request from Inbox or All requests to review details, act, and close without leaving the list.',
    detail: [
      'Opening a row keeps list context — Escape or the scrim closes and returns focus to the list.',
      'Header shows the journey stage and stage-aware actions. Default tab for legal and admin is Fulfillment.',
      'Matching results are visible read-only unless a data owner assigned the request to legal for help.',
    ],
    gif: 'request-detail-overlay.gif',
  },
  {
    id: 'fulfillment-tab',
    title: 'Fulfillment tab',
    one_liner:
      'Default work tab: shareable access URL, delivery status controls, and identity verification summary.',
    detail: [
      'This is where legal does pre-fulfillment work: identity, kickoff, and access delivery status.',
      'Access packages expose a time-limited shareable URL and draft outbound copy for you to send outside the platform.',
      'Pair status updates with the next automated step — do not assume success if the UI shows Retry.',
    ],
    gif: 'fulfillment-tab.gif',
  },
  {
    id: 'stage-actions',
    title: 'Stage-aware actions',
    one_liner:
      'Contextual action bar for notice approve, delivery confirm, identity verified, and close.',
    detail: [
      'Only actions valid for the current journey stage appear — vocabulary matches Home funnel labels.',
      'Notice approve is the gate for Wednesday California DROP status upload.',
      'Close is always available; you may see a soft warning if other work is still outstanding.',
    ],
    gif: 'stage-actions.gif',
  },
  {
    id: 'inbox-notice-review',
    title: 'Notice review approval',
    one_liner:
      'Approve DROP notice so fulfilled requests can enter the weekly upload batch — your approval is the gate.',
    detail: [
      'Filter Inbox to Notice for California DROP items waiting on legal.',
      'Confirm response status, then approve. Without approval, Habeas will not include the request in the Wednesday upload.',
      'Amendments follow the same notice path after rematch changes a previously uploaded status.',
    ],
    gif: 'inbox-notice-review.gif',
  },
  {
    id: 'inbox-delivery-handoff',
    title: 'Access delivery handoff',
    one_liner: 'Delivery queue: shareable URL, status controls, outbound draft, confirm delivered.',
    detail: [
      'Filter Inbox to Delivery when an access package is ready for outbound send.',
      'Copy the draft and link, send via your normal channel, then mark delivered (or failed) in the platform.',
      'Delivery status is separate from California DROP Id/Status upload — access goes outside the DROP API.',
    ],
    gif: 'inbox-delivery-handoff.gif',
  },
  {
    id: 'identity-verification',
    title: 'Identity verification',
    one_liner: 'Record the identity decision on the Fulfillment tab; status shows on the request.',
    detail: [
      'Identity verification is a Fulfillment-tab action for legal and admin — not a separate Inbox chip.',
      'Full context stays inline on the row and overlay so you can see what was decided.',
      'Complete identity before kicking off access fulfillment when the journey requires it.',
    ],
    gif: 'identity-verification.gif',
  },
  {
    id: 'chrome-legal-settings',
    title: 'Settings',
    one_liner:
      'Conditions, deadlines, email templates, DROP schedule, and legal team — admin saves; legal read-only.',
    detail: [
      'Open Settings from the user strip (or ⌘K → Open Settings). Groups: Conditions, Deadlines & SLAs, Email templates, DROP schedule, Legal team.',
      'Admin and super admin can save. Legal can view but cannot mutate settings.',
      'Legal team membership drives who receives Assignment to legal fan-out.',
    ],
    gif: 'chrome-legal-settings.gif',
  },
  {
    id: 'chrome-docs',
    title: 'Docs',
    one_liner: 'In-app legal help: how DPAP works, how-tos, features, ⌘K key, timeline, and FAQ.',
    detail: [
      'Docs is a primary nav tab next to Inbox — use it during training and the review week.',
      'Left spine jumps between sections. Features include short GIFs plus how each surface works.',
      'This page is the take-home reference alongside live walkthroughs.',
    ],
    gif: 'chrome-docs.gif',
  },
  {
    id: 'chrome-upload-menu',
    title: 'Upload (+)',
    one_liner: 'Header + dropdown to start intake — Manual request or registered-agent batch.',
    detail: [
      'On Home (and related surfaces), the + menu starts Manual request or Agent batch upload.',
      'Registered-agent batches are cleaned by the platform, then ingest and matching run automatically.',
      'Manual entry is for exceptions — prefer agent batch or scheduled DROP intake when possible.',
    ],
    gif: 'chrome-upload-menu.gif',
  },
  {
    id: 'drop-upload-schedule',
    title: 'Weekly DROP upload schedule',
    one_liner:
      'Weekly upload day and time; notice approval decides which requests are included in the batch.',
    detail: [
      'Habeas uploads Id/Status (and amendments as bulk) on a weekly cadence — product default Wednesday 00:00 America/Los_Angeles.',
      'Configure day and time under Settings → DROP schedule. Home also shows the next scheduled run.',
      'Brokers must process DROP starting August 1, 2026 and report status within 45 days of retrieval; Habeas’s weekly batch is stricter and approval-gated.',
    ],
    gif: 'drop-upload-schedule.gif',
  },
]

const HOW_TOS = [
  {
    id: 'inbox',
    title: 'Work the Inbox',
    gif: 'inbox-legal-filter-chips.gif',
    steps: [
      'Open Inbox and use filter chips to focus the queue.',
      'Claim unassigned work with Take it when needed.',
      'Open a row to review and act in the detail overlay.',
    ],
  },
  {
    id: 'identity',
    title: 'Verify identity',
    gif: 'identity-verification.gif',
    steps: [
      'Open the request and stay on the Fulfillment tab.',
      'Review identity context shown inline.',
      'Record the identity decision, then continue to the next status step.',
    ],
  },
  {
    id: 'fulfillment',
    title: 'Kick off fulfillment',
    gif: 'fulfillment-tab.gif',
    steps: [
      'From Inbox or detail, pair your reply with the named status transition.',
      'That status update starts the next automated step.',
      'On failure: read the error, use Retry, or assign to legal — never assume success.',
    ],
  },
  {
    id: 'assignment',
    title: 'Handle assignment to legal',
    gif: 'stage-actions.gif',
    steps: [
      'Filter Inbox to Assignment to legal.',
      'Read the data owner’s comment for why help was needed.',
      'Resolve the matching or pre-fulfillment question and advance status.',
    ],
  },
  {
    id: 'notice',
    title: 'Approve a DROP notice',
    gif: 'inbox-notice-review.gif',
    steps: [
      'Open Inbox · Notice for California DROP items ready for review.',
      'Confirm the response status is correct.',
      'Approve — your approval is the gate for the Wednesday DROP upload batch.',
    ],
  },
  {
    id: 'delivery',
    title: 'Send access delivery and close',
    gif: 'inbox-delivery-handoff.gif',
    steps: [
      'Open Inbox · Delivery when an access package is ready.',
      'Copy the draft email and link, send outside the platform, then confirm delivered.',
      'Close the request when work is done (close is never blocked).',
    ],
  },
] as const

const COMMAND_PALETTE_KEY = [
  {
    group: 'Open',
    items: [
      { label: '⌘K / Ctrl+K', description: 'Open or close the command palette' },
      { label: 'Header Search', description: 'Same as ⌘K from the sticky header' },
      { label: 'Escape', description: 'Close the palette' },
      { label: '↑ / ↓', description: 'Move selection' },
      { label: 'Enter', description: 'Run the selected command' },
    ],
  },
  {
    group: 'Search groups',
    items: [
      { label: 'Requests', description: 'Find requests (DROP by id; others by name or id)' },
      { label: 'People', description: 'Jump to work for operators / legal team (not requesters)' },
      { label: 'Actions', description: 'Navigation shortcuts listed below' },
    ],
  },
  {
    group: 'Actions',
    items: [
      { label: 'Go to Home', description: 'Legal Home / portfolio' },
      { label: 'Go to All requests', description: 'Full inventory table' },
      { label: 'Go to Inbox', description: 'Legal work queue' },
      { label: 'Go to Docs', description: 'This documentation' },
      { label: 'Inbox · Unassigned', description: 'Claimable work' },
      { label: 'Inbox · Assignment to legal', description: 'Data-owner help queue' },
      { label: 'Inbox · Fulfillment', description: 'Pre-fulfillment work' },
      { label: 'Inbox · Notice', description: 'DROP notice approval' },
      { label: 'Inbox · Delivery', description: 'Access delivery handoff' },
      { label: 'Inbox · Pre-matching holds', description: 'Holds that block matching' },
      { label: 'Inbox · Assigned to me', description: 'Your claimed items' },
      { label: 'Upload request', description: 'Manual / agent intake' },
      { label: 'Open Settings', description: 'Conditions, SLAs, DROP schedule, legal team' },
    ],
  },
] as const

const FAQ = [
  {
    q: 'What happens when a request arrives?',
    a: 'Ingestion and matching run automatically — no human step until data owner review (or a pre-matching hold appears in your Inbox).',
  },
  {
    q: 'How do registered-agent requests come in?',
    a: 'Agents submit batch files; the platform cleans and ingests them automatically like other intake sources, then matching runs.',
  },
  {
    q: 'When does California DROP go live, and what’s required?',
    a: 'Brokers must access and process DROP requests starting August 1, 2026, and report status within 45 days of retrieval.',
  },
  {
    q: 'When does Habeas report DROP status?',
    a: 'Every Wednesday at 00:00 America/Los_Angeles, Habeas uploads Id/Status (plus bulk amendments) after Legal approves the notice — your notice approval is the gate.',
  },
  {
    q: 'Why does audit matter, and what do we record?',
    a: 'Every action records actor, timestamp, action type, and request id — metadata only, never personal information or comment text — so we have a defensible compliance trail.',
  },
  {
    q: 'Who confirms matches?',
    a: 'Data owners confirm, reject, or mark multi-person for their verticals; legal sees matching read-only unless a data owner assigns the request to legal.',
  },
  {
    q: 'Can I close a request anytime?',
    a: 'Yes — close is never blocked; you may see a soft warning if work is still outstanding.',
  },
] as const

function FeatureGif({ src, title }: { src: string; title: string }) {
  return (
    <img
      src={`/docs-gifs/${src}`}
      alt={`${title} demonstration`}
      className="w-full rounded-md border border-line bg-paper object-contain"
      loading="lazy"
    />
  )
}

function DocsSpine() {
  return (
    <nav
      className="sticky top-24 hidden max-h-[calc(100vh-7rem)] w-44 shrink-0 overflow-y-auto border-r border-line pr-4 lg:block"
      aria-label="Docs sections"
    >
      <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">On this page</p>
      <ul className="mt-3 space-y-1 text-[0.8125rem]">
        {SECTIONS.map((section) => (
          <li key={section.id}>
            <a
              href={`#${section.id}`}
              className="block border-l-2 border-transparent py-1 pl-3 text-mute transition-colors hover:border-habeas-navy/40 hover:text-ink"
            >
              {section.label}
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-6 text-[0.65rem] font-medium uppercase tracking-wide text-mute">Features</p>
      <ul className="mt-2 max-h-64 space-y-0.5 overflow-y-auto text-[0.75rem]">
        {FEATURES.map((feature) => (
          <li key={feature.id}>
            <a
              href={`#feature-${feature.id}`}
              className="block truncate py-0.5 pl-3 text-mute hover:text-ink"
            >
              {feature.title}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  )
}

export function DocsPage() {
  return (
    <div className="pb-16 lg:flex lg:items-start lg:gap-8">
      <DocsSpine />

      <div className="min-w-0 flex-1 space-y-12">
        <header>
          <p className="text-xs font-medium uppercase tracking-wide text-mute">Legal</p>
          <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">Docs</h2>
          <p className="mt-2 max-w-2xl text-sm text-ink-soft">
            How DPAP works, what legal does, platform features, ⌘K shortcuts, the pilot timeline,
            and FAQ.
          </p>
          <nav
            className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-b border-line pb-3 text-[0.8125rem] lg:hidden"
            aria-label="Docs sections (mobile)"
          >
            {SECTIONS.map((section) => (
              <a
                key={section.id}
                href={`#${section.id}`}
                className="text-mute transition-colors hover:text-ink"
              >
                {section.label}
              </a>
            ))}
          </nav>
        </header>

        <section id="how-it-works" className="scroll-mt-24 space-y-4">
          <h3 className="font-display text-lg font-medium text-ink">How DPAP works</h3>
          <p className="text-sm text-ink-soft">
            Journey:{' '}
            <span className="text-ink">
              receive → matching → data owner review → legal / pre-fulfillment → fulfillment →
              delivery / DROP notice
            </span>
            . <strong className="font-medium text-ink">Inbox</strong> is your work queue;{' '}
            <strong className="font-medium text-ink">All requests</strong> is inventory;{' '}
            <strong className="font-medium text-ink">Home</strong> is portfolio health.
          </p>
          <ul className="space-y-2 text-sm text-ink-soft">
            <li>
              <span className="font-medium text-ink">Automatic:</span> intake (web form, California
              DROP, registered-agent batches, manual), matching through completion, due-date
              calculation, weekly DROP status upload after notice approval, access file cut + draft
              email.
            </li>
            <li>
              <span className="font-medium text-ink">Data owners (not you):</span> confirm / not a
              match / multi-person. You review matching only when they assign the request to legal.
            </li>
            <li>
              <span className="font-medium text-ink">Your gates:</span> identity verification,
              fulfillment kickoff, assignment-to-legal items, DROP notice review, delivery
              confirmation, and close.
            </li>
          </ul>
        </section>

        <section id="how-tos" className="scroll-mt-24 space-y-6">
          <h3 className="font-display text-lg font-medium text-ink">Your actions</h3>
          <p className="text-sm text-ink-soft">Each how-to is three steps plus a short demo.</p>
          <div className="space-y-8">
            {HOW_TOS.map((item) => (
              <article key={item.id} id={`howto-${item.id}`} className="scroll-mt-24 space-y-3">
                <h4 className="text-sm font-medium text-ink">{item.title}</h4>
                <FeatureGif src={item.gif} title={item.title} />
                <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-soft">
                  {item.steps.map((step) => (
                    <li key={step}>{step}</li>
                  ))}
                </ol>
              </article>
            ))}
          </div>
        </section>

        <section id="features" className="scroll-mt-24 space-y-6">
          <div>
            <h3 className="font-display text-lg font-medium text-ink">Features</h3>
            <p className="mt-1 text-sm text-ink-soft">
              What each surface does — short demo, one sentence, and how it works.
            </p>
          </div>
          <div className="space-y-10">
            {FEATURES.map((feature) => (
              <article
                key={feature.id}
                id={`feature-${feature.id}`}
                className="scroll-mt-24 space-y-3"
              >
                <h4 className="text-sm font-medium text-ink">{feature.title}</h4>
                <p className="text-sm text-ink-soft">{feature.one_liner}</p>
                <FeatureGif src={feature.gif} title={feature.title} />
                <ul className="space-y-1.5 text-sm text-ink-soft">
                  {feature.detail.map((line) => (
                    <li key={line} className="flex gap-2">
                      <span className="mt-2 size-1 shrink-0 rounded-full bg-habeas-navy/50" />
                      <span>{line}</span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>
        </section>

        <section id="command-palette" className="scroll-mt-24 space-y-6">
          <div>
            <h3 className="font-display text-lg font-medium text-ink">Command palette</h3>
            <p className="mt-1 text-sm text-ink-soft">
              Jump anywhere without hunting the nav. Open with{' '}
              <kbd className="rounded border border-line bg-paper px-1.5 py-0.5 font-mono text-[0.7rem] text-ink">
                ⌘K
              </kbd>{' '}
              (Mac) or{' '}
              <kbd className="rounded border border-line bg-paper px-1.5 py-0.5 font-mono text-[0.7rem] text-ink">
                Ctrl+K
              </kbd>{' '}
              (Windows / Linux), or the header Search control.
            </p>
          </div>
          <FeatureGif src="chrome-command-palette.gif" title="Command palette" />
          <div className="space-y-5">
            <h4 className="text-sm font-medium text-ink">Key</h4>
            {COMMAND_PALETTE_KEY.map((block) => (
              <div key={block.group}>
                <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
                  {block.group}
                </p>
                <dl className="mt-2 divide-y divide-line/70 rounded-md border border-line bg-paper">
                  {block.items.map((item) => (
                    <div
                      key={item.label}
                      className="grid gap-1 px-3 py-2 sm:grid-cols-[minmax(0,11rem)_1fr] sm:gap-3"
                    >
                      <dt className="font-mono text-[0.75rem] text-ink">{item.label}</dt>
                      <dd className="text-sm text-ink-soft">{item.description}</dd>
                    </div>
                  ))}
                </dl>
              </div>
            ))}
          </div>
        </section>

        <section id="timeline" className="scroll-mt-24 space-y-4">
          <h3 className="font-display text-lg font-medium text-ink">Timeline</h3>
          <ol className="relative space-y-4 border-l border-line pl-5 text-sm text-ink-soft">
            <li>
              <span className="absolute -left-[5px] mt-1.5 size-2 rounded-full bg-[var(--habeas-navy,#1E4191)]" />
              <span className="font-medium text-ink">Jul 28, 2026 — Feedback session 1.</span> Live
              walkthrough of DPAP for legal.
            </li>
            <li>
              <span className="absolute -left-[5px] mt-1.5 size-2 rounded-full bg-line" />
              <span className="font-medium text-ink">Following week — Review &amp; testing.</span>{' '}
              Legal explores the platform; use Docs as the take-home reference.
            </li>
            <li>
              <span className="absolute -left-[5px] mt-1.5 size-2 rounded-full bg-line" />
              <span className="font-medium text-ink">Next week (TBD) — Feedback session 2.</span>{' '}
              Then live platform testing that week: web form, registered agents, and California DROP
              connected — process in parallel with existing Jira and DPAP to compare experiences.
            </li>
            <li>
              <span className="absolute -left-[5px] mt-1.5 size-2 rounded-full bg-line" />
              <span className="font-medium text-ink">
                End of that week — Feedback session 3 + legal training.
              </span>{' '}
              Same week: data-owner onboarding (two trainings, TBD) and California DROP go-live
              readiness.
            </li>
            <li>
              <span className="absolute -left-[5px] mt-1.5 size-2 rounded-full bg-line" />
              <span className="font-medium text-ink">Aug 1, 2026 — California DROP obligation.</span>{' '}
              Brokers must access and process DROP; report status within 45 days of retrieval.
              Habeas uploads statuses every Wednesday after Legal notice approval.
            </li>
          </ol>
        </section>

        <section id="faq" className="scroll-mt-24 space-y-4">
          <h3 className="font-display text-lg font-medium text-ink">FAQ</h3>
          <dl className="space-y-4">
            {FAQ.map((item) => (
              <div key={item.q}>
                <dt className="text-sm font-medium text-ink">{item.q}</dt>
                <dd className="mt-1 text-sm text-ink-soft">{item.a}</dd>
              </div>
            ))}
          </dl>
        </section>
      </div>
    </div>
  )
}
