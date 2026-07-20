import { useEffect, useState, type CSSProperties, type ReactNode } from 'react'

import { HabeasLogoImg, DppTitle, PresentationLine } from '../shared'
import { SPLASH_PALETTE } from '../palette'
import type { SplashStageProps, SplashVariantModule } from '../types'
import './batch-d.css'

function Stage({
  variantClass,
  children,
  autoFinish,
  durationMs = 3400,
  onDone,
  className = '',
}: SplashStageProps & { variantClass: string; children: ReactNode }) {
  const [phase, setPhase] = useState<'in' | 'hold' | 'out'>('in')
  useEffect(() => {
    if (!autoFinish) return
    const t1 = window.setTimeout(() => setPhase('hold'), 500)
    const t2 = window.setTimeout(() => setPhase('out'), durationMs - 450)
    const t3 = window.setTimeout(() => onDone?.(), durationMs)
    return () => {
      window.clearTimeout(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [autoFinish, durationMs, onDone])

  return (
    <div
      className={`splash-d-stage ${variantClass} splash-d-phase-${phase} ${className}`}
      style={
        {
          '--cat-black': SPLASH_PALETTE.black,
          '--cat-silver': SPLASH_PALETTE.silver,
          '--cat-silver-hi': SPLASH_PALETTE.silverHi,
          '--cat-blue': SPLASH_PALETTE.blue,
          '--cat-blue-deep': SPLASH_PALETTE.blueDeep,
        } as CSSProperties
      }
      role="status"
      aria-label="CataPriv Platform loading"
    >
      {children}
    </div>
  )
}

const BOOT_LINES = [
  'HABEAS SYS  64K RAM OK',
  'DROP HASH INDEX ........ CHECK',
  'PRIVACY QUEUE .......... ONLINE',
  'AUDIT SINK ............. MOUNT',
  'CONTROL PLANE .......... READY',
] as const

const TITLE_LINE = 'CataPriv Platform (DPP)'

/** v10 — Teletext / home-computer boot log → title line → logo. */
function V10(props: SplashStageProps) {
  const [visible, setVisible] = useState(0)
  const [showLogo, setShowLogo] = useState(false)

  useEffect(() => {
    let timers: number[] = []
    const clear = () => {
      timers.forEach(window.clearTimeout)
      timers = []
    }
    const run = () => {
      clear()
      setVisible(0)
      setShowLogo(false)
      BOOT_LINES.forEach((_, i) => {
        timers.push(window.setTimeout(() => setVisible(i + 1), 280 + i * 320))
      })
      timers.push(
        window.setTimeout(() => setVisible(BOOT_LINES.length + 1), 280 + BOOT_LINES.length * 320),
      )
      timers.push(
        window.setTimeout(() => setShowLogo(true), 280 + BOOT_LINES.length * 320 + 420),
      )
    }
    run()
    if (!props.autoFinish) {
      const loop = window.setInterval(run, 4200)
      return () => {
        clear()
        window.clearInterval(loop)
      }
    }
    return () => clear()
  }, [props.autoFinish])

  const titleOn = visible > BOOT_LINES.length

  return (
    <Stage variantClass="splash-d-v10" {...props}>
      <div className="splash-d-scan" aria-hidden />
      <div className="splash-d-teletext">
        <header className="splash-d-tt-bar">
          <span>P100</span>
          <span>HABEAS</span>
          <span>TELETEXT</span>
        </header>
        <pre className="splash-d-bootlog">
          {BOOT_LINES.map((line, i) => (
            <span
              key={line}
              className={`splash-d-boot-line${i < visible ? ' is-on' : ''}`}
            >
              {line}
            </span>
          ))}
          <span className={`splash-d-boot-line splash-d-boot-title${titleOn ? ' is-on' : ''}`}>
            {TITLE_LINE}
          </span>
        </pre>
        <div className={`splash-d-boot-logo${showLogo ? ' is-on' : ''}`}>
          <HabeasLogoImg />
        </div>
      </div>
    </Stage>
  )
}

/** v11 — Typewriter “Habeas” then DPP with block cursor; small logo optional. */
function V11(props: SplashStageProps) {
  const brand = 'Habeas'
  const dpp = 'CataPriv Platform (DPP)'
  const [brandLen, setBrandLen] = useState(0)
  const [dppLen, setDppLen] = useState(0)
  const [phase, setTypePhase] = useState<'brand' | 'dpp' | 'done'>('brand')
  const [showLogo, setShowLogo] = useState(false)

  useEffect(() => {
    let cancelled = false
    let timers: number[] = []

    const clear = () => {
      timers.forEach(window.clearTimeout)
      timers = []
    }

    const reset = () => {
      setBrandLen(0)
      setDppLen(0)
      setTypePhase('brand')
      setShowLogo(false)
    }

    const typeBrand = () => {
      let i = 0
      const tick = () => {
        if (cancelled) return
        i += 1
        setBrandLen(i)
        if (i < brand.length) {
          timers.push(window.setTimeout(tick, 95))
        } else {
          setTypePhase('dpp')
          timers.push(window.setTimeout(typeDpp, 380))
        }
      }
      timers.push(window.setTimeout(tick, 200))
    }

    const typeDpp = () => {
      let i = 0
      const tick = () => {
        if (cancelled) return
        i += 1
        setDppLen(i)
        if (i < dpp.length) {
          timers.push(window.setTimeout(tick, 48))
        } else {
          setTypePhase('done')
          timers.push(window.setTimeout(() => setShowLogo(true), 280))
        }
      }
      tick()
    }

    const run = () => {
      clear()
      reset()
      typeBrand()
    }

    run()
    let loop: number | undefined
    if (!props.autoFinish) {
      loop = window.setInterval(run, 4000)
    }

    return () => {
      cancelled = true
      clear()
      if (loop) window.clearInterval(loop)
    }
  }, [props.autoFinish])

  return (
    <Stage variantClass="splash-d-v11" {...props}>
      <div className="splash-d-scan splash-d-scan--soft" aria-hidden />
      <div className="splash-d-typewriter">
        <p className="splash-d-tw-brand">
          {brand.slice(0, brandLen)}
          {phase === 'brand' ? <span className="splash-d-cursor" aria-hidden /> : null}
        </p>
        <p className="splash-d-tw-dpp">
          {dpp.slice(0, dppLen)}
          {phase === 'dpp' || (phase === 'done' && !showLogo) ? (
            <span className="splash-d-cursor" aria-hidden />
          ) : null}
        </p>
        <div className={`splash-d-tw-logo${showLogo ? ' is-on' : ''}`}>
          <HabeasLogoImg />
        </div>
      </div>
    </Stage>
  )
}

const PROMPT_LINES = [
  { prefix: '#', text: 'init privacy.core' },
  { prefix: '>', text: 'mount drop_hash_index' },
  { prefix: '>', text: 'bind admin_api :8080' },
  { prefix: '>', text: 'exec catapriv --ready' },
] as const

/** v12 — Shell prompt lines, then hard-cut full-bleed logo card. */
function V12(props: SplashStageProps) {
  const [lineCount, setLineCount] = useState(0)
  const [takeover, setTakeover] = useState(false)

  useEffect(() => {
    let timers: number[] = []
    const clear = () => {
      timers.forEach(window.clearTimeout)
      timers = []
    }
    const run = () => {
      clear()
      setLineCount(0)
      setTakeover(false)
      PROMPT_LINES.forEach((_, i) => {
        timers.push(window.setTimeout(() => setLineCount(i + 1), 220 + i * 340))
      })
      timers.push(
        window.setTimeout(() => setTakeover(true), 220 + PROMPT_LINES.length * 340 + 200),
      )
    }
    run()
    if (!props.autoFinish) {
      const loop = window.setInterval(run, 4000)
      return () => {
        clear()
        window.clearInterval(loop)
      }
    }
    return () => clear()
  }, [props.autoFinish])

  return (
    <Stage variantClass="splash-d-v12" {...props}>
      {!takeover ? (
        <div className="splash-d-prompt">
          <p className="splash-d-prompt-host">habeas@dpp ~</p>
          {PROMPT_LINES.map((row, i) => (
            <p
              key={row.text}
              className={`splash-d-prompt-line${i < lineCount ? ' is-on' : ''}`}
            >
              <span className="splash-d-prompt-pfx">{row.prefix}</span> {row.text}
            </p>
          ))}
          {lineCount >= PROMPT_LINES.length ? (
            <p className="splash-d-prompt-line is-on splash-d-prompt-ready">
              <span className="splash-d-prompt-pfx">#</span> ready
              <span className="splash-d-cursor" aria-hidden />
            </p>
          ) : (
            <p className="splash-d-prompt-line is-on splash-d-prompt-waiting">
              <span className="splash-d-cursor" aria-hidden />
            </p>
          )}
        </div>
      ) : (
        <div className="splash-d-takeover">
          <HabeasLogoImg />
          <DppTitle />
          <PresentationLine />
        </div>
      )}
    </Stage>
  )
}

const renderers: Record<number, (p: SplashStageProps) => ReactNode> = {
  10: V10,
  11: V11,
  12: V12,
}

export const batchD: SplashVariantModule = {
  meta: [
    { id: 10, name: 'Teletext Boot', blurb: 'Boot log then full-bleed title.' },
    { id: 11, name: 'Cursor Blink', blurb: 'Typewriter Habeas then DPP.' },
    { id: 12, name: 'Hash Prompt', blurb: 'Monochrome terminal → logo.' },
  ],
  render: (id, props) => renderers[id]?.(props) ?? renderers[10](props),
}
