import { useId } from 'react'

import {
  formatMatchedContactsSummary,
  MatchedContactsPanel,
} from '@/components/requests/RequestTriageDialog'

import {
  ResultApplyBar,
  ResultMatchMeta,
  applyNeedsPeople,
  resultViewEmpty,
  statusSelectClass,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

function optionLabel(
  options: MatchingResultsViewProps['statusOptions'],
  value: string | null,
): string {
  if (value == null) return 'Choose status…'
  return options.find((option) => option.id === value)?.label ?? value
}

/** Batch default + row override — summary, then full contact rows with DWID checklist. */
export function TwoTierView({
  item,
  detail,
  contacts,
  loading,
  ownerLanguage,
  statusOptions,
  statusId,
  onStatusChange,
  selectedDwids,
  onSelectedDwidsChange,
  disabled,
  pending,
  onApply,
  batchDefaultStatus,
  onBatchDefaultStatusChange,
  useBatchDefault,
  onUseBatchDefaultChange,
}: MatchingResultsViewProps) {
  const empty = resultViewEmpty(loading, Boolean(item))
  const checkboxId = useId()
  if (empty) return empty

  const followingDefault = useBatchDefault && batchDefaultStatus != null
  const effectiveStatus = followingDefault ? batchDefaultStatus : statusId
  const peopleCleared = effectiveStatus === '5'

  function setUseDefault(next: boolean) {
    onUseBatchDefaultChange(next)
    if (next && batchDefaultStatus != null) {
      onStatusChange(batchDefaultStatus)
    }
  }

  return (
    <div className="space-y-3">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />

      <div className="space-y-2 rounded-md border border-line bg-paper px-2.5 py-2">
        <div className="space-y-1">
          <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
            Batch default
          </label>
          <select
            className={statusSelectClass()}
            value={batchDefaultStatus ?? ''}
            disabled={disabled || pending}
            aria-label="Batch default status"
            onChange={(event) => {
              if (event.target.value) onBatchDefaultStatusChange(event.target.value)
            }}
          >
            <option value="" disabled>
              Choose status…
            </option>
            {statusOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div className="flex items-start gap-2">
          <input
            id={checkboxId}
            type="checkbox"
            className="mt-1 size-3.5 rounded border-line text-habeas-navy accent-habeas-navy"
            checked={useBatchDefault}
            disabled={disabled || pending || batchDefaultStatus == null}
            onChange={(event) => setUseDefault(event.target.checked)}
          />
          <label htmlFor={checkboxId} className="min-w-0 text-xs text-ink">
            Use batch default for this row
            <span className="block text-[0.65rem] text-ink-soft">
              {batchDefaultStatus != null
                ? optionLabel(statusOptions, batchDefaultStatus)
                : 'No batch default set'}
            </span>
          </label>
        </div>

        {followingDefault ? (
          <p className="text-[0.65rem] text-ink-soft" aria-live="polite">
            Row follows batch default — uncheck to override.
          </p>
        ) : (
          <div className="space-y-1">
            <label className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">
              Row override
            </label>
            <select
              className={statusSelectClass()}
              value={statusId ?? ''}
              disabled={disabled || pending}
              aria-label="Row status override"
              onChange={(event) => {
                if (event.target.value) onStatusChange(event.target.value)
              }}
            >
              <option value="" disabled>
                Choose status…
              </option>
              {statusOptions.map((option) => (
                <option key={option.id} value={option.id}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      <div className="rounded-md border border-line bg-canvas px-2.5 py-2">
        <p className="text-[0.65rem] font-medium uppercase tracking-wide text-mute">Summary</p>
        <p className="text-xs text-ink">
          {effectiveStatus == null ? (
            'No status yet'
          ) : (
            <>
              {optionLabel(statusOptions, effectiveStatus)}
              <span className="text-ink-soft">
                {followingDefault ? ' · batch default' : ' · row override'}
              </span>
            </>
          )}
        </p>
        <p className="text-[0.65rem] text-ink-soft">
          {peopleCleared
            ? 'No people sent'
            : formatMatchedContactsSummary(contacts, selectedDwids)}
        </p>
      </div>

      <MatchedContactsPanel
        matching={detail ?? undefined}
        contacts={contacts}
        selectable={!peopleCleared}
        selectedDwids={selectedDwids}
        onSelectedDwidsChange={onSelectedDwidsChange}
        disabled={disabled || pending || peopleCleared}
      />

      <ResultApplyBar
        pending={pending}
        disabled={
          disabled ||
          effectiveStatus == null ||
          applyNeedsPeople(effectiveStatus, selectedDwids)
        }
        onApply={onApply}
      />
    </div>
  )
}
