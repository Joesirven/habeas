import { useCallback, useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import {
  findTourNavAnchor,
  markTourSessionDismissed,
  type OwnerQuickStartTourStep,
  type TourPersistence,
  writeTourPersistence,
} from '@/lib/quick-start-tour'

type QuickStartTourProps = {
  userId: string
  steps: readonly OwnerQuickStartTourStep[]
  onFinish: (result: TourPersistence) => void
  onDismiss: () => void
}

type AnchorRect = {
  top: number
  left: number
  width: number
  height: number
}

function measureAnchor(step: OwnerQuickStartTourStep): AnchorRect | null {
  const anchor = findTourNavAnchor(step)
  if (!anchor) return null
  const rect = anchor.getBoundingClientRect()
  return {
    top: rect.top,
    left: rect.left,
    width: rect.width,
    height: rect.height,
  }
}

export function QuickStartTour({ userId, steps, onFinish, onDismiss }: QuickStartTourProps) {
  const [stepIndex, setStepIndex] = useState(0)
  const [anchorRect, setAnchorRect] = useState<AnchorRect | null>(null)

  const effectiveSteps = useMemo(() => {
    if (typeof document === 'undefined') return steps
    const anchored = steps.filter((entry) => findTourNavAnchor(entry) != null)
    return anchored.length > 0 ? anchored : steps
  }, [steps])

  const step = effectiveSteps[stepIndex]
  const isLastStep = stepIndex >= effectiveSteps.length - 1

  const refreshAnchor = useCallback(() => {
    if (!step) return
    setAnchorRect(measureAnchor(step))
  }, [step])

  useEffect(() => {
    refreshAnchor()
    const onLayout = () => refreshAnchor()
    window.addEventListener('resize', onLayout)
    window.addEventListener('scroll', onLayout, true)
    return () => {
      window.removeEventListener('resize', onLayout)
      window.removeEventListener('scroll', onLayout, true)
    }
  }, [refreshAnchor])

  function handleSkip() {
    writeTourPersistence(userId, 'skipped')
    onFinish('skipped')
  }

  function handleNext() {
    if (isLastStep) {
      writeTourPersistence(userId, 'completed')
      onFinish('completed')
      return
    }
    setStepIndex((index) => index + 1)
  }

  function handleDismiss() {
    markTourSessionDismissed(userId)
    onDismiss()
  }

  if (!step) return null

  const popoverTop = anchorRect ? anchorRect.top + anchorRect.height + 10 : 72
  const popoverLeft = anchorRect ? Math.max(12, anchorRect.left) : 24

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-modal="true" aria-label="Quick start tour">
      <button
        type="button"
        className="absolute inset-0 bg-ink/25"
        aria-label="Dismiss tour for this login"
        onClick={handleDismiss}
      />

      {anchorRect ? (
        <div
          className="pointer-events-none absolute rounded-md ring-2 ring-habeas-navy ring-offset-2 ring-offset-white"
          style={{
            top: anchorRect.top - 4,
            left: anchorRect.left - 4,
            width: anchorRect.width + 8,
            height: anchorRect.height + 8,
          }}
          aria-hidden="true"
        />
      ) : null}

      <div
        className="absolute z-[101] w-[min(20rem,calc(100vw-1.5rem))] rounded-md border border-line bg-white p-4 shadow-lg"
        style={{ top: popoverTop, left: popoverLeft }}
      >
        <p className="text-[0.65rem] font-medium uppercase tracking-[0.12em] text-mute">
          Quick start · {stepIndex + 1} of {effectiveSteps.length}
        </p>
        <h2 className="mt-2 text-sm font-semibold text-ink">{step.title}</h2>
        <p className="mt-2 text-sm leading-relaxed text-ink-soft">{step.body}</p>
        {!anchorRect ? (
          <p className="mt-2 text-xs text-amber-800">
            Could not anchor to <span className="font-medium">{step.navLabel}</span> in the nav —
            content still applies once the tab is visible for your role.
          </p>
        ) : null}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={handleSkip}>
            Skip tour
          </Button>
          <div className="flex items-center gap-2">
            <Button type="button" variant="outline" size="sm" onClick={handleDismiss}>
              Not now
            </Button>
            <Button type="button" size="sm" onClick={handleNext}>
              {isLastStep ? 'Done' : 'Next'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
