/**
 * Fleet discovery helpers — no hardcoded worker name lists.
 * Display order follows the API array order.
 */

import type { FleetWorkerRecord, FleetWorkersPayload } from '@/lib/api'

/** Prefer API array order — do not re-sort except optional label sort at call site. */
export function orderedWorkers(payload: FleetWorkersPayload | null | undefined): FleetWorkerRecord[] {
  return payload?.workers ?? []
}

export function workerKey(worker: FleetWorkerRecord): string {
  return worker.worker_key || worker.name || ''
}

export function orderedWorkerKeys(payload: FleetWorkersPayload | null | undefined): string[] {
  return orderedWorkers(payload).map(workerKey).filter(Boolean)
}

/** @deprecated Prefer orderedWorkerKeys — plan-b naming alias. */
export function orderedWorkerNames(payload: FleetWorkersPayload | null | undefined): string[] {
  return orderedWorkerKeys(payload)
}

export function workerByName(
  payload: FleetWorkersPayload | null | undefined,
  name: string,
): FleetWorkerRecord | undefined {
  return orderedWorkers(payload).find((worker) => workerKey(worker) === name)
}

export function workerByKey(
  payload: FleetWorkersPayload | null | undefined,
  key: string,
): FleetWorkerRecord | undefined {
  return workerByName(payload, key)
}

export function attemptTableForWorker(
  payload: FleetWorkersPayload | null | undefined,
  name: string,
): string | null {
  return workerByName(payload, name)?.attempt_table ?? null
}

export function workerDisplayLabel(worker: FleetWorkerRecord): string {
  if (worker.label?.trim()) return worker.label.trim()
  return workerKey(worker)
}

/** Alias used by Settings fleet panel. */
export function fleetWorkerDisplayName(worker: FleetWorkerRecord): string {
  return workerDisplayLabel(worker)
}

/**
 * Ready probe: prefer nested health, then top-level ok.
 * Returns null when neither signal is present.
 */
export function fleetHealthOk(worker: FleetWorkerRecord): boolean | null {
  if (worker.health?.ok != null) return worker.health.ok
  if (worker.ok != null) return worker.ok
  return null
}

export function isWorkerHealthy(worker: FleetWorkerRecord): boolean {
  return fleetHealthOk(worker) === true
}

export type JobFilterOption = { value: string; label: string }

/**
 * Build select options from discovered fleet.
 * Includes a leading “All workers” empty value for overview filters.
 */
export function buildJobFilterOptions(
  payload: FleetWorkersPayload | null | undefined,
): JobFilterOption[] {
  const options: JobFilterOption[] = [{ value: '', label: 'All workers' }]
  for (const worker of orderedWorkers(payload)) {
    const key = workerKey(worker)
    if (!key) continue
    options.push({ value: key, label: workerDisplayLabel(worker) })
  }
  return options
}

/** Trust discovery flag only — never invent a frontend allowlist. */
export function supportsUnifiedRuns(worker: FleetWorkerRecord): boolean {
  return worker.supports_unified_runs === true
}

export function workersSupportingUnifiedRuns(
  payload: FleetWorkersPayload | null | undefined,
): FleetWorkerRecord[] {
  return orderedWorkers(payload).filter(supportsUnifiedRuns)
}

export function formatScheduleCadence(cadence: string | null | undefined): string {
  if (!cadence) return '—'
  if (cadence.startsWith('every_') && cadence.endsWith('_days')) {
    const n = cadence.slice('every_'.length, -'_days'.length)
    return `Every ${n} days`
  }
  if (cadence.startsWith('on_')) {
    return `${cadence.slice(3).replaceAll('_and_', ' and ').replaceAll('_', ' ')} of the month`
  }
  return cadence.replaceAll('_', ' ')
}

export function parseMonthDaysInput(raw: string): number[] {
  const days = raw
    .split(/[,;\s]+/)
    .map((part) => Number(part.trim()))
    .filter((value) => Number.isInteger(value) && value >= 1 && value <= 31)
  return [...new Set(days)].sort((a, b) => a - b)
}

export function formatMonthDaysInput(days: number[] | null | undefined): string {
  return (days ?? []).join(', ')
}

/** Allowlisted columns from catalog entry or rows payload — never invent. */
export function resolveAttemptColumns(input: {
  columns?: string[]
  filterable_columns?: string[]
}): string[] {
  if (input.columns && input.columns.length > 0) return input.columns
  if (input.filterable_columns && input.filterable_columns.length > 0) {
    return input.filterable_columns
  }
  return []
}
