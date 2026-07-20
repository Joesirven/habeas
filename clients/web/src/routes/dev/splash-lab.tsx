import { PostAuthSplash, SPLASH_VARIANTS } from '@/components/PostAuthSplash'

/** Temporary gallery of 20 post-auth bumper variations. Remove after picking one. */
export function SplashLabPage() {
  return (
    <section className="space-y-8">
      <div className="rounded-[1rem] border border-[#6EB8E0]/60 bg-black px-4 py-3 font-mono text-xs text-[#F2F4F7]">
        <p className="tracking-[0.14em] text-[#6EB8E0] uppercase">
          Type lockup v3 · Habeas Data Privacy Platform / DPP
        </p>
        <p className="mt-1 text-white/70">
          Typography-led idents (chrome, stacked, DPP mono, teletext, extrude, chyron, arcs,
          split). Hard refresh if you still see SunsetBands. Lab:{' '}
          <a className="text-[#6EB8E0] underline" href="http://127.0.0.1:5173/dev/splash-lab">
            http://127.0.0.1:5173/dev/splash-lab
          </a>
        </p>
      </div>

      <header>
        <p className="taste-micro">Temporary · pick a bumper</p>
        <h2 className="mt-3 font-display text-3xl font-medium tracking-tight text-ink">
          Post-auth splash lab
        </h2>
        <p className="mt-2 max-w-xl text-sm text-ink-soft">
          Twenty type-led 1984 idents: “Habeas Data Privacy Platform” or DPP lockups, assembling
          on black in Habeas black / silver / blue. Click a card to fullscreen.
        </p>
      </header>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {SPLASH_VARIANTS.map((variant) => (
          <a
            key={variant.id}
            href={`#v${variant.id}`}
            className="group block overflow-hidden rounded-[1rem] border border-line bg-ink"
          >
            <div className="relative aspect-[4/3] overflow-hidden bg-black">
              <PostAuthSplash variant={variant.id} className="!absolute inset-0 !min-h-0" />
            </div>
            <div className="border-t border-white/10 px-3 py-2">
              <p className="font-mono text-[0.65rem] uppercase tracking-[0.12em] text-white/55">
                {String(variant.id).padStart(2, '0')} · {variant.name}
              </p>
              <p className="mt-0.5 text-xs text-white/75">{variant.blurb}</p>
            </div>
          </a>
        ))}
      </div>

      {SPLASH_VARIANTS.map((variant) => (
        <div
          key={`full-${variant.id}`}
          id={`v${variant.id}`}
          className="fixed inset-0 z-[200] hidden target:block bg-black"
        >
          <a href="#_" className="absolute inset-0 cursor-default" aria-label="Close variation" />
          <div className="relative z-10 h-full w-full">
            <PostAuthSplash variant={variant.id} />
            <a
              href="#_"
              className="absolute right-4 top-4 z-20 rounded border border-white/30 bg-black/50 px-3 py-1.5 font-mono text-xs text-white"
            >
              Close · {variant.name}
            </a>
          </div>
        </div>
      ))}
    </section>
  )
}
