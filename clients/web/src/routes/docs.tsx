const SECTIONS = [
  { id: 'how-it-works', label: 'How it works' },
  { id: 'how-tos', label: 'Your actions' },
  { id: 'rollout', label: 'Rollout' },
  { id: 'faq', label: 'FAQ' },
] as const

const HOW_TOS = [
  {
    id: 'inbox',
    title: 'Work the Inbox',
    steps: [
      'Open Inbox and use filter chips to focus the queue.',
      'Claim unassigned work with Take it when needed.',
      'Open a row to review and act in the detail overlay.',
    ],
  },
  {
    id: 'identity',
    title: 'Verify identity',
    steps: [
      'Open the request and stay on the Fulfillment tab.',
      'Review identity context shown inline.',
      'Record the identity decision, then continue to the next status step.',
    ],
  },
  {
    id: 'fulfillment',
    title: 'Kick off fulfillment',
    steps: [
      'From Inbox or detail, pair your reply with the named status transition.',
      'That status update starts the next automated step.',
      'On failure: read the error, use Retry, or assign to legal — never assume success.',
    ],
  },
  {
    id: 'assignment',
    title: 'Handle assignment to legal',
    steps: [
      'Filter Inbox to Assignment to legal.',
      'Read the data owner’s comment for why help was needed.',
      'Resolve the matching or pre-fulfillment question and advance status.',
    ],
  },
  {
    id: 'notice',
    title: 'Approve a DROP notice',
    steps: [
      'Open Inbox · Notice for California DROP items ready for review.',
      'Confirm the response status is correct.',
      'Approve — your approval is the gate for the Wednesday DROP upload batch.',
    ],
  },
  {
    id: 'delivery',
    title: 'Send access delivery and close',
    steps: [
      'Open Inbox · Delivery when an access package is ready.',
      'Copy the draft email and link, send outside the platform, then confirm delivered.',
      'Close the request when work is done (close is never blocked).',
    ],
  },
  {
    id: 'command-palette',
    title: 'Use the command palette (⌘K / Ctrl+K)',
    steps: [
      'Press ⌘K (Mac) or Ctrl+K (Windows/Linux) anywhere in the app.',
      'Search Requests, People (operators), or Actions.',
      'Jump to Home, Inbox filters, Upload, Settings, or Docs without hunting the nav.',
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

function GifPlaceholder({ label }: { label: string }) {
  return (
    <div
      className="flex min-h-[9rem] items-center justify-center rounded-md border border-dashed border-line bg-paper px-4 text-center text-xs text-mute"
      role="img"
      aria-label={`GIF placeholder: ${label}`}
    >
      GIF coming soon — {label}
    </div>
  )
}

export function DocsPage() {
  return (
    <section className="mx-auto max-w-3xl space-y-10 pb-16">
      <header>
        <p className="text-xs font-medium uppercase tracking-wide text-mute">Legal</p>
        <h2 className="mt-2 font-display text-2xl font-medium tracking-tight text-ink">Docs</h2>
        <p className="mt-2 max-w-2xl text-sm text-ink-soft">
          What the platform does behind the scenes, the actions legal needs to take, and the
          pilot timeline — short answers only.
        </p>
        <nav
          className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-b border-line pb-3 text-[0.8125rem]"
          aria-label="Docs sections"
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
        <p className="text-sm text-ink-soft">
          Each how-to is three steps. GIFs will land here as we record them.
        </p>
        <div className="space-y-8">
          {HOW_TOS.map((item) => (
            <article key={item.id} id={`howto-${item.id}`} className="scroll-mt-24 space-y-3">
              <h4 className="text-sm font-medium text-ink">{item.title}</h4>
              <GifPlaceholder label={item.title} />
              <ol className="list-decimal space-y-1 pl-5 text-sm text-ink-soft">
                {item.steps.map((step) => (
                  <li key={step}>{step}</li>
                ))}
              </ol>
            </article>
          ))}
        </div>
      </section>

      <section id="rollout" className="scroll-mt-24 space-y-4">
        <h3 className="font-display text-lg font-medium text-ink">Rollout &amp; key dates</h3>
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
    </section>
  )
}
