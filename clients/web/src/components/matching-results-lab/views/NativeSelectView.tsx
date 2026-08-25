import { formatMatchedContactLabel } from '@/components/requests/RequestTriageDialog'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

import {
  ResultApplyBar,
  ResultMatchMeta,
  applyNeedsPeople,
  resultViewEmpty,
  statusSelectClass,
} from '../ResultViewChrome'
import type { MatchingResultsViewProps } from '../matching-results-lab-types'

function setRowInclude(
  selectedDwids: string[],
  dwid: string,
  include: boolean,
): string[] {
  const has = selectedDwids.includes(dwid)
  if (include) return has ? selectedDwids : [...selectedDwids, dwid]
  return has ? selectedDwids.filter((id) => id !== dwid) : selectedDwids
}

/** Spreadsheet: people rows with native `<select>` cells for status and include. */
export function NativeSelectView({
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
}: MatchingResultsViewProps) {
  const empty = resultViewEmpty(loading, Boolean(item))
  if (empty) return empty

  const locked = disabled || pending
  const notFound = statusId === '5'
  const rows = contacts.length > 0 ? contacts : null

  function handleStatusChange(next: string) {
    if (!next) return
    onStatusChange(next)
    if (next === '5') onSelectedDwidsChange([])
  }

  const statusSelect = (
    <select
      className={statusSelectClass(true)}
      value={statusId ?? ''}
      disabled={locked}
      aria-label="Set match status"
      onChange={(event) => handleStatusChange(event.target.value)}
    >
      <option value="" disabled>
        Choose…
      </option>
      {statusOptions.map((option) => (
        <option key={option.id} value={option.id}>
          {option.label}
        </option>
      ))}
    </select>
  )

  return (
    <div className="space-y-2">
      <ResultMatchMeta item={item} detail={detail} ownerLanguage={ownerLanguage} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Person</TableHead>
            <TableHead>State</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Include</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows == null ? (
            <TableRow>
              <TableCell className="text-xs text-mute">—</TableCell>
              <TableCell className="text-xs text-mute">—</TableCell>
              <TableCell>{statusSelect}</TableCell>
              <TableCell className="text-xs text-mute">—</TableCell>
            </TableRow>
          ) : (
            rows.map((contact, index) => {
              const included = !notFound && selectedDwids.includes(contact.dwid)
              return (
                <TableRow key={contact.dwid}>
                  <TableCell className="max-w-[10rem] truncate text-xs text-ink">
                    {formatMatchedContactLabel(contact)}
                  </TableCell>
                  <TableCell className="text-xs text-ink-soft">{contact.state || '—'}</TableCell>
                  {index === 0 ? (
                    <TableCell rowSpan={rows.length} className="align-top">
                      {statusSelect}
                    </TableCell>
                  ) : null}
                  <TableCell>
                    <select
                      className={statusSelectClass(true)}
                      value={included ? 'yes' : 'no'}
                      disabled={locked || notFound}
                      aria-label={`Include row ${index + 1}`}
                      onChange={(event) => {
                        onSelectedDwidsChange(
                          setRowInclude(selectedDwids, contact.dwid, event.target.value === 'yes'),
                        )
                      }}
                    >
                      <option value="yes">Yes</option>
                      <option value="no">No</option>
                    </select>
                  </TableCell>
                </TableRow>
              )
            })
          )}
        </TableBody>
      </Table>
      <ResultApplyBar
        pending={pending}
        disabled={disabled || statusId == null || applyNeedsPeople(statusId, selectedDwids)}
        onApply={onApply}
      />
    </div>
  )
}
