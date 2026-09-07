import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ChangeEvent } from 'react'

import { Button } from '@/components/ui/button'
import { Spinner } from '@/components/ui/spinner'
import {
  connectTestFailureMessage,
  uploadOwnerConnectorCsv,
  type OwnerUploadResult,
} from '@/lib/api'
import { actionToast } from '@/lib/action-toast'
import {
  EMAIL_FORMAT_OPTIONS,
  MULTI_PII_DELIMITER_OPTIONS,
  NAME_FORMAT_OPTIONS,
  PHONE_FORMAT_OPTIONS,
  UPLOAD_IDENTIFIER_FIELDS,
  delimiterValueFromKey,
  deriveListCapability,
  parseCsvHeaderRow,
  suggestUploadColumnMapping,
  systemWizardCopy,
  uploadMappingComplete,
} from '@/lib/owner-connector-ui'

import { OWNER_FIELD_CLASS, WizardStepShell } from './wizard-shared'

export type UploadStepFormats = {
  email?: string
  phone?: string
  name?: string
  /** MULTI_PII_DELIMITER_OPTIONS key — converted to the API value here. */
  delimiter?: string
}

export function UploadFileStep({
  system,
  verticalId,
  columnMapping,
  formats,
  initialFile = null,
  initialHeaders = [],
  onBack,
  onUploaded,
  onFileSelected,
}: {
  system: string
  verticalId: string
  columnMapping: Record<string, string>
  formats: UploadStepFormats
  /** Restore the previously picked file after Back (the dialog retains it). */
  initialFile?: File | null
  initialHeaders?: string[]
  onBack: () => void
  onUploaded: (result: OwnerUploadResult, headers: string[]) => void
  onFileSelected?: (file: File | null) => void
}) {
  const [file, setFile] = useState<File | null>(initialFile)
  const [headers, setHeaders] = useState<string[]>(initialHeaders)
  const activeRef = useRef(true)

  useEffect(() => {
    activeRef.current = true
    return () => {
      activeRef.current = false
    }
  }, [])

  const uploadMutation = useMutation({
    mutationFn: () => {
      if (!file) throw new Error('Choose a CSV file first.')
      const formatPayload: {
        emailFormat?: string
        phoneFormat?: string
        nameFormat?: 'first_last' | 'last_first'
      } = {}
      if (formats.email) formatPayload.emailFormat = formats.email
      if (formats.phone) formatPayload.phoneFormat = formats.phone
      if (formats.name === 'first_last' || formats.name === 'last_first') {
        formatPayload.nameFormat = formats.name
      }
      const mapping = Object.values(columnMapping).some((value) => value?.trim())
        ? columnMapping
        : null
      const delimiter = formats.delimiter ? delimiterValueFromKey(formats.delimiter) : null
      return uploadOwnerConnectorCsv(verticalId, system, file, delimiter, mapping, formatPayload)
    },
    onSuccess: (result) => {
      if (!activeRef.current) return
      // Mapping is always the next step, so needs_mapping advances like success.
      if (result.ok || result.detail === 'upload_needs_mapping') {
        const detected = result.detected_headers?.filter((header) => header.trim()) ?? []
        onUploaded(result, detected.length > 0 ? detected : headers)
      }
    },
  })

  async function handleFileChange(event: ChangeEvent<HTMLInputElement>) {
    const next = event.target.files?.[0] ?? null
    // Reset the input so re-picking the SAME path fires onChange — the
    // rejected-rows recovery copy tells the owner to do exactly that.
    event.target.value = ''
    setFile(next)
    setHeaders([])
    uploadMutation.reset()
    onFileSelected?.(next)
    if (!next) return
    try {
      // Header row lives at the top — no need to read a multi-MB file whole.
      const text = await next.slice(0, 64_000).text()
      setHeaders(parseCsvHeaderRow(text))
    } catch {
      setHeaders([])
    }
  }

  const result = uploadMutation.isSuccess ? uploadMutation.data : null
  const rowsRejected = Boolean(result && !result.ok && result.detail === 'upload_rows_rejected')
  const resultFailed = Boolean(
    result &&
      !result.ok &&
      result.detail !== 'upload_rows_rejected' &&
      result.detail !== 'upload_needs_mapping',
  )
  const failed = uploadMutation.isError || resultFailed

  return (
    <WizardStepShell
      title="Upload your file"
      description={
        systemWizardCopy(system)?.uploadHowto ??
        'Upload your export as-is. Email alone or phone alone is enough — you will match columns next.'
      }
      onBack={onBack}
      primary={
        <Button
          type="button"
          size="sm"
          disabled={!file || uploadMutation.isPending}
          onClick={() => uploadMutation.mutate()}
        >
          {uploadMutation.isPending
            ? 'Uploading…'
            : failed || rowsRejected
              ? 'Try again'
              : 'Upload & check'}
        </Button>
      }
    >
      <div className="space-y-3">
        <label className="block space-y-1 text-xs">
          <span className="font-medium text-ink">CSV file</span>
          <input
            type="file"
            accept=".csv,text/csv"
            className="block w-full text-xs text-ink file:mr-2 file:rounded file:border file:border-line file:bg-white file:px-2 file:py-1"
            onChange={(event) => void handleFileChange(event)}
          />
        </label>

        {file && headers.length > 0 ? (
          <p className="text-[11px] text-mute">
            Found {headers.length} column{headers.length === 1 ? '' : 's'}:{' '}
            {headers.slice(0, 4).join(', ')}
            {headers.length > 4 ? '…' : ''}
          </p>
        ) : null}

        {uploadMutation.isPending ? (
          <div
            className="flex items-center gap-2 rounded-md border border-line bg-canvas px-3 py-2.5"
            role="status"
            aria-live="polite"
            aria-busy="true"
          >
            <Spinner className="size-4" />
            <p className="text-xs text-ink">Uploading and checking your file…</p>
          </div>
        ) : null}

        {rowsRejected && result ? (
          <div
            className="space-y-1 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-900"
            role="alert"
          >
            <p className="font-medium">Some rows need cleaning</p>
            <p>{connectTestFailureMessage(result.detail)}</p>
            <p>
              {result.rejected_row_count != null
                ? `${result.rejected_row_count} row(s) failed validation. `
                : ''}
              Fix them in your file, then choose it again.
            </p>
          </div>
        ) : null}

        {resultFailed && result ? (
          <div
            className="space-y-1 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-900"
            role="alert"
          >
            <p className="font-medium">Upload check failed</p>
            <p>{connectTestFailureMessage(result.detail)}</p>
          </div>
        ) : null}

        {uploadMutation.isError ? (
          <div
            className="space-y-1 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-xs text-red-900"
            role="alert"
          >
            <p className="font-medium">Upload failed</p>
            <p>
              {actionToast.safeErrorMessage(uploadMutation.error, 'Check the file and try again.')}
            </p>
          </div>
        ) : null}
      </div>
    </WizardStepShell>
  )
}

export function MappingStep({
  headers,
  mapping,
  onChange,
  onBack,
  onContinue,
}: {
  headers: string[]
  mapping: Record<string, string>
  onChange: (mapping: Record<string, string>) => void
  onBack: () => void
  onContinue: () => void
}) {
  const suggestedForRef = useRef<string | null>(null)

  useEffect(() => {
    if (headers.length === 0) return
    const signature = headers.join('\u001f')
    if (suggestedForRef.current === signature) return
    suggestedForRef.current = signature
    const hasAny = Object.values(mapping).some((value) => value?.trim())
    if (hasAny) return
    onChange(suggestUploadColumnMapping(headers))
  }, [headers, mapping, onChange])

  const capability = deriveListCapability(mapping)

  return (
    <WizardStepShell
      title="Assign columns"
      description="Map source headers to canonical variables. Email, Phone, and NDZ follow the mapping — you do not pick lists."
      onBack={onBack}
      primary={
        <Button
          type="button"
          size="sm"
          disabled={!uploadMappingComplete(mapping)}
          onClick={onContinue}
        >
          Continue
        </Button>
      }
    >
      <div className="space-y-3">
        <div className="rounded-md border border-line bg-canvas px-3 py-2">
          <p className="text-[10px] font-semibold uppercase tracking-wide text-mute">
            DROP list types · derived
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {(
              [
                { id: 'Email', on: capability.email, hint: 'email mapped' },
                { id: 'Phone', on: capability.phone, hint: 'phone mapped' },
                {
                  id: 'NDZ',
                  on: capability.ndz,
                  hint: `${capability.ndzMappedCount} of 4 name / DOB / ZIP`,
                },
              ] as const
            ).map((chip) => (
              <span
                key={chip.id}
                className={
                  chip.on
                    ? 'rounded-md border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-800'
                    : 'rounded-md border border-line bg-white px-2 py-0.5 text-[11px] text-mute'
                }
              >
                {chip.id}
                <span className="ml-1 font-normal text-mute">
                  {chip.on ? 'on' : chip.hint}
                </span>
              </span>
            ))}
          </div>
        </div>
        {headers.length === 0 ? (
          <p className="rounded-md border border-line bg-canvas px-3 py-2.5 text-xs text-ink">
            No columns were detected in that file. Go back and check that it's a CSV with a
            header row.
          </p>
        ) : null}
        {UPLOAD_IDENTIFIER_FIELDS.map((field) => {
          const selected = mapping[field.id] ?? ''
          const usedElsewhere = new Set(
            Object.entries(mapping)
              .filter(([id, value]) => id !== field.id && value?.trim())
              .map(([, value]) => value),
          )
          const stale = Boolean(selected && !headers.includes(selected))
          return (
            <label key={field.id} className="block space-y-1 text-xs">
              <span className="font-medium text-ink">{field.label}</span>
              <select
                className={OWNER_FIELD_CLASS}
                value={selected}
                onChange={(event) => onChange({ ...mapping, [field.id]: event.target.value })}
                aria-label={`Map ${field.label} column`}
              >
                <option value="">Not in file</option>
                {stale ? <option value={selected}>{selected} (not in this file)</option> : null}
                {headers.map((header) => (
                  <option
                    key={`${field.id}-${header}`}
                    value={header}
                    disabled={usedElsewhere.has(header)}
                  >
                    {header}
                  </option>
                ))}
              </select>
            </label>
          )
        })}
      </div>
    </WizardStepShell>
  )
}

type FormatStepId = 'email' | 'phone' | 'name' | 'delimiter'

const FORMAT_STEP_CONTENT: Record<
  FormatStepId,
  { title: string; help: string; options: readonly { id: string; label: string }[] }
> = {
  email: {
    title: 'Email format',
    help: 'How strictly should we check email values? Standard works for most exports.',
    options: EMAIL_FORMAT_OPTIONS,
  },
  phone: {
    title: 'Phone format',
    help: 'How are phone numbers written in your file? US 10-digit works for most exports.',
    options: PHONE_FORMAT_OPTIONS,
  },
  name: {
    title: 'How are names written in your file?',
    help: 'We use this to read a full-name column as first and last name.',
    options: NAME_FORMAT_OPTIONS,
  },
  delimiter: {
    title: 'Can a cell contain more than one email or phone?',
    help: 'If a column can hold several values, tell us what separates them.',
    options: MULTI_PII_DELIMITER_OPTIONS.map((option) => ({ id: option.key, label: option.label })),
  },
}

function formatStepDescription(formatId: FormatStepId, columnLabel?: string): string {
  const fallback = FORMAT_STEP_CONTENT[formatId].help
  const column = columnLabel?.trim()
  if (!column) return fallback
  if (formatId === 'email') {
    return `How strictly should we check values in the "${column}" column? Standard works for most exports.`
  }
  if (formatId === 'phone') {
    return `How are phone numbers written in the "${column}" column? US 10-digit works for most exports.`
  }
  if (formatId === 'name') {
    return `How should we read the "${column}" column as first and last name?`
  }
  return `If ${column} can hold several values in one cell, tell us what separates them.`
}

export function FormatStep({
  formatId,
  value,
  onChange,
  onBack,
  onContinue,
  columnLabel,
}: {
  formatId: FormatStepId
  value: string
  onChange: (value: string) => void
  onBack: () => void
  onContinue: () => void
  /** Mapped source column — phone/email/delimiter copy names this column. */
  columnLabel?: string
}) {
  const content = FORMAT_STEP_CONTENT[formatId]

  return (
    <WizardStepShell
      title={content.title}
      description={formatStepDescription(formatId, columnLabel)}
      onBack={onBack}
      primary={
        <Button type="button" size="sm" onClick={onContinue}>
          Continue
        </Button>
      }
    >
      <div className="space-y-2" role="radiogroup" aria-label={content.title}>
        {content.options.map((option) => (
          <label
            key={option.id}
            className="flex cursor-pointer items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-sm text-ink transition hover:border-habeas-mid"
          >
            <input
              type="radio"
              name={`owner-upload-format-${formatId}`}
              value={option.id}
              checked={value === option.id}
              onChange={() => onChange(option.id)}
              className="accent-habeas-navy"
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </WizardStepShell>
  )
}
