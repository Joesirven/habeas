/**
 * Any-order owner wizard flow model — pure TypeScript, no React.
 *
 * The wizard is a hub with per-system subflows. Navigation is a true history
 * stack: advancing pushes the step you go to, Back pops to the step you
 * actually came from. Draft data (credentials, mapping, formats) lives in the
 * dialog runner, not here.
 */

export type WizardStep =
  | { kind: 'hub' }
  | { kind: 'choice'; system: string }
  | { kind: 'cred'; system: string; fieldIndex: number }
  | { kind: 'live-test'; system: string }
  | { kind: 'live-seed-choice'; system: string }
  | { kind: 'upload'; system: string }
  | { kind: 'mapping'; system: string }
  | { kind: 'format'; system: string; formatId: 'email' | 'phone' | 'name' | 'delimiter' }
  | { kind: 'sheets'; system: string }
  | { kind: 'cadence'; system: string }
  | { kind: 'system-done'; system: string }

export interface SubflowInput {
  system: string
  liveAllowed: boolean
  uploadAllowed: boolean
  isSheets: boolean
  credentialFields: Array<{
    id: string
    label: string
    help?: string
    required: boolean
    input_type: string
  }>
}

function liveBranchSteps(input: SubflowInput): WizardStep[] {
  const { system, credentialFields } = input
  const credSteps: WizardStep[] = credentialFields.map((_, fieldIndex) => ({
    kind: 'cred',
    system,
    fieldIndex,
  }))
  return [
    ...credSteps,
    { kind: 'live-test', system },
    // Seed-upload offer only when upload is actually allowed for this system —
    // otherwise it is a backdoor into a mode the catalog does not advertise.
    ...(input.uploadAllowed
      ? ([{ kind: 'live-seed-choice', system }] as const)
      : []),
    { kind: 'cadence', system },
    { kind: 'system-done', system },
  ]
}

function uploadBranchSteps(input: SubflowInput): WizardStep[] {
  const { system } = input
  return [
    { kind: 'upload', system },
    { kind: 'mapping', system },
    { kind: 'cadence', system },
    { kind: 'system-done', system },
  ]
}

/**
 * Steps for one system's subflow (hub excluded).
 *
 * Upload branches intentionally end at cadence/system-done: format steps are
 * known only after mapping, so the runner inserts formatStepsForMapping(...)
 * between mapping and cadence at runtime. Systems allowing both modes return
 * only the choice step; the runner pushes branchSteps(input, mode) once the
 * owner picks a mode.
 */
export function systemSubflowSteps(input: SubflowInput): WizardStep[] {
  const { system, liveAllowed, uploadAllowed, isSheets } = input
  if (isSheets) {
    return [
      { kind: 'sheets', system },
      { kind: 'cadence', system },
      { kind: 'system-done', system },
    ]
  }
  if (liveAllowed && uploadAllowed) {
    return [{ kind: 'choice', system }]
  }
  if (uploadAllowed) {
    return uploadBranchSteps(input)
  }
  if (liveAllowed) {
    return liveBranchSteps(input)
  }
  return []
}

/**
 * Steps for one mode branch of a both-modes system, pushed after the choice
 * step resolves. The live branch skips credential steps entirely when the
 * system has no credential fields (starts at live-test).
 */
export function branchSteps(input: SubflowInput, mode: 'live' | 'upload'): WizardStep[] {
  return mode === 'live' ? liveBranchSteps(input) : uploadBranchSteps(input)
}

/**
 * Format steps to insert after mapping, derived from the confirmed mapping
 * (identifier field id -> source column; empty/unset means unmapped).
 * Delimiter applies only to in-cell multi-PII, which only email/phone use.
 */
export function formatStepsForMapping(
  system: string,
  mapping: Record<string, string>,
): WizardStep[] {
  const mapped = (field: string) => typeof mapping[field] === 'string' && mapping[field].length > 0
  const steps: WizardStep[] = []
  if (mapped('email')) steps.push({ kind: 'format', system, formatId: 'email' })
  if (mapped('phone')) steps.push({ kind: 'format', system, formatId: 'phone' })
  if (mapped('full_name')) steps.push({ kind: 'format', system, formatId: 'name' })
  if (mapped('email') || mapped('phone')) {
    steps.push({ kind: 'format', system, formatId: 'delimiter' })
  }
  return steps
}

/** History stack: index 0 is the hub, the last element is the current step. */
export type StepStack = WizardStep[]

export function initialStack(): StepStack {
  return [{ kind: 'hub' }]
}

export function stackTop(stack: StepStack): WizardStep {
  return stack.length === 0 ? { kind: 'hub' } : stack[stack.length - 1]
}

export function pushStep(stack: StepStack, step: WizardStep): StepStack {
  return [...stack, step]
}

export function pushSteps(stack: StepStack, steps: WizardStep[]): StepStack {
  return steps.length === 0 ? stack : [...stack, ...steps]
}

/** Back navigation. Floors at the hub — the hub itself is never popped. */
export function popStep(stack: StepStack): StepStack {
  if (stack.length === 0) return initialStack()
  if (stack.length === 1) return stack
  return stack.slice(0, -1)
}

export function resetToHub(stack: StepStack): StepStack {
  void stack
  return initialStack()
}

/**
 * Enter a system's subflow: drop any in-progress history, then land on the
 * subflow's first step. Only the first step is pushed — the stack is a true
 * history, so later steps are pushed by the runner as the owner advances
 * (including runtime-only steps like branch/format steps).
 */
export function startSystem(stack: StepStack, steps: WizardStep[]): StepStack {
  const hub = resetToHub(stack)
  return steps.length === 0 ? hub : pushStep(hub, steps[0])
}

export function isSystemComplete(c: { wizard_completed_at?: string | null }): boolean {
  return typeof c.wizard_completed_at === 'string' && c.wizard_completed_at.length > 0
}
