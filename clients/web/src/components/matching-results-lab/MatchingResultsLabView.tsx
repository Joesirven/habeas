import type { ComponentType } from 'react'

import type { MatchingResultLabMethodId } from '@/components/inbox-status-lab/status-selector-types'

import {
  MATCHING_RESULTS_LAB_VIEW_MODULES,
  type MatchingResultsLabViewExportName,
  type MatchingResultsViewProps,
} from './matching-results-lab-types'
import { ApplySelectionView } from './views/ApplySelectionView'
import { ComboboxView } from './views/ComboboxView'
import { CommandPaletteView } from './views/CommandPaletteView'
import { InlineChipsView } from './views/InlineChipsView'
import { NativeSelectView } from './views/NativeSelectView'
import { RadioPopoverView } from './views/RadioPopoverView'
import { SegmentedView } from './views/SegmentedView'
import { SplitButtonView } from './views/SplitButtonView'
import { StepperConfirmView } from './views/StepperConfirmView'
import { TwoTierView } from './views/TwoTierView'

const MATCHING_RESULTS_LAB_VIEW_EXPORTS: Record<
  MatchingResultsLabViewExportName,
  ComponentType<MatchingResultsViewProps>
> = {
  NativeSelectView,
  SegmentedView,
  RadioPopoverView,
  ComboboxView,
  SplitButtonView,
  InlineChipsView,
  CommandPaletteView,
  StepperConfirmView,
  TwoTierView,
  ApplySelectionView,
}

export function MatchingResultsLabView({
  method,
  ...viewProps
}: {
  method: MatchingResultLabMethodId
} & MatchingResultsViewProps) {
  const exportName = MATCHING_RESULTS_LAB_VIEW_MODULES[method]
  const Component = MATCHING_RESULTS_LAB_VIEW_EXPORTS[exportName] ?? TwoTierView
  const fillPage = method === 'apply-selection'
  return (
    <div className={fillPage ? 'flex h-full min-h-0 flex-col' : undefined}>
      <Component {...viewProps} />
    </div>
  )
}
