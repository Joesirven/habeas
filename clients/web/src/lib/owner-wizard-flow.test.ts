// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'
import {
  branchSteps,
  formatStepsForMapping,
  initialStack,
  isSystemComplete,
  popStep,
  pushStep,
  pushSteps,
  resetToHub,
  stackTop,
  startSystem,
  systemSubflowSteps,
  type StepStack,
  type SubflowInput,
  type WizardStep,
} from './owner-wizard-flow'

function credField(id: string) {
  return { id, label: id, required: true, input_type: 'password' }
}

const PAYLOCITY_CRED_FIELDS = [
  'client_id',
  'client_secret',
  'company_id',
  'sftp_host',
  'sftp_username',
  'sftp_password',
  'sftp_path',
].map(credField)

function subflowInput(overrides: Partial<SubflowInput>): SubflowInput {
  return {
    system: 'test_system',
    liveAllowed: false,
    uploadAllowed: false,
    isSheets: false,
    credentialFields: [],
    ...overrides,
  }
}

function kinds(steps: WizardStep[]): string[] {
  return steps.map((step) => step.kind)
}

describe('systemSubflowSteps', () => {
  test('sheets system → sheets, cadence, system-done', () => {
    const steps = systemSubflowSteps(subflowInput({ system: 'hr_alumni', isSheets: true }))
    expect(kinds(steps)).toEqual(['sheets', 'cadence', 'system-done'])
    expect(steps.every((step) => step.system === 'hr_alumni')).toBe(true)
  })

  test('upload-only axios → upload, mapping, cadence, system-done', () => {
    const steps = systemSubflowSteps(
      subflowInput({ system: 'axios_headquarters', uploadAllowed: true }),
    )
    expect(kinds(steps)).toEqual(['upload', 'mapping', 'cadence', 'system-done'])
  })

  test('live-only lever → cred per field, live-test, cadence, system-done (no seed backdoor)', () => {
    const steps = systemSubflowSteps(
      subflowInput({
        system: 'lever',
        liveAllowed: true,
        credentialFields: [credField('api_key')],
      }),
    )
    expect(kinds(steps)).toEqual(['cred', 'live-test', 'cadence', 'system-done'])
    expect(steps[0]).toEqual({ kind: 'cred', system: 'lever', fieldIndex: 0 })
  })

  test('live branch with upload allowed keeps the live-seed-choice offer', () => {
    const steps = branchSteps(
      subflowInput({
        system: 'lever',
        liveAllowed: true,
        uploadAllowed: true,
        credentialFields: [credField('api_key')],
      }),
      'live',
    )
    expect(kinds(steps)).toEqual([
      'cred',
      'live-test',
      'live-seed-choice',
      'cadence',
      'system-done',
    ])
  })

  test('both paylocity → choice only; branch pushed at runtime', () => {
    const steps = systemSubflowSteps(
      subflowInput({
        system: 'paylocity',
        liveAllowed: true,
        uploadAllowed: true,
        credentialFields: PAYLOCITY_CRED_FIELDS,
      }),
    )
    expect(steps).toEqual([{ kind: 'choice', system: 'paylocity' }])
  })

  test('live with 0 credential fields skips cred steps, starts at live-test', () => {
    const steps = systemSubflowSteps(
      subflowInput({ system: 'auth0', liveAllowed: true, credentialFields: [] }),
    )
    expect(kinds(steps)).toEqual(['live-test', 'cadence', 'system-done'])
  })

  test('nothing allowed → empty subflow', () => {
    expect(systemSubflowSteps(subflowInput({ system: 'cassandra' }))).toEqual([])
  })
})

describe('branchSteps', () => {
  const paylocity = subflowInput({
    system: 'paylocity',
    liveAllowed: true,
    uploadAllowed: true,
    credentialFields: PAYLOCITY_CRED_FIELDS,
  })

  test('live branch: one cred step per field, then test/seed/cadence/done', () => {
    const steps = branchSteps(paylocity, 'live')
    expect(kinds(steps)).toEqual([
      'cred',
      'cred',
      'cred',
      'cred',
      'cred',
      'cred',
      'cred',
      'live-test',
      'live-seed-choice',
      'cadence',
      'system-done',
    ])
    const credSteps = steps.filter((step) => step.kind === 'cred')
    expect(credSteps.map((step) => step.fieldIndex)).toEqual([0, 1, 2, 3, 4, 5, 6])
  })

  test('live branch with no credential fields starts at live-test', () => {
    const steps = branchSteps(subflowInput({ system: 'lever', liveAllowed: true }), 'live')
    expect(kinds(steps)).toEqual(['live-test', 'cadence', 'system-done'])
  })

  test('upload branch: upload, mapping, cadence, system-done', () => {
    const steps = branchSteps(paylocity, 'upload')
    expect(kinds(steps)).toEqual(['upload', 'mapping', 'cadence', 'system-done'])
  })
})

describe('formatStepsForMapping', () => {
  const formatIds = (mapping: Record<string, string>) =>
    formatStepsForMapping('sys', mapping).map((step) => step.formatId)

  test('email only → email + delimiter', () => {
    expect(formatIds({ email: 'Email' })).toEqual(['email', 'delimiter'])
  })

  test('email + phone → email, phone, delimiter', () => {
    expect(formatIds({ email: 'Email', phone: 'Cell' })).toEqual(['email', 'phone', 'delimiter'])
  })

  test('full_name only → name, no delimiter', () => {
    expect(formatIds({ full_name: 'Employee' })).toEqual(['name'])
  })

  test('email + phone + full_name → email, phone, name, delimiter', () => {
    expect(formatIds({ email: 'Email', phone: 'Cell', full_name: 'Employee' })).toEqual([
      'email',
      'phone',
      'name',
      'delimiter',
    ])
  })

  test('no identifiers mapped → no format steps', () => {
    expect(formatStepsForMapping('sys', {})).toEqual([])
    expect(formatIds({ first_name: 'First', last_name: 'Last' })).toEqual([])
  })

  test('empty-string mapping values count as unmapped', () => {
    expect(formatIds({ email: '', phone: 'Cell' })).toEqual(['phone', 'delimiter'])
  })
})

describe('step stack', () => {
  const uploadSubflow = systemSubflowSteps(
    subflowInput({ system: 'axios_headquarters', uploadAllowed: true }),
  )

  test('initialStack is the hub', () => {
    const stack = initialStack()
    expect(stack).toEqual([{ kind: 'hub' }])
    expect(stackTop(stack)).toEqual({ kind: 'hub' })
  })

  test('pushStep appends and does not mutate the input stack', () => {
    const stack = initialStack()
    const next = pushStep(stack, uploadSubflow[0])
    expect(next).toEqual([{ kind: 'hub' }, { kind: 'upload', system: 'axios_headquarters' }])
    expect(stack).toEqual([{ kind: 'hub' }])
    expect(stackTop(next)).toEqual({ kind: 'upload', system: 'axios_headquarters' })
  })

  test('pushSteps appends many; empty push returns the same stack', () => {
    const stack = initialStack()
    const next = pushSteps(stack, uploadSubflow.slice(0, 2))
    expect(kinds(next)).toEqual(['hub', 'upload', 'mapping'])
    expect(pushSteps(next, [])).toBe(next)
  })

  test('popStep returns to the previous step and floors at the hub', () => {
    let stack = initialStack()
    stack = pushStep(stack, uploadSubflow[0])
    stack = pushStep(stack, uploadSubflow[1])
    stack = popStep(stack)
    expect(stackTop(stack)).toEqual({ kind: 'upload', system: 'axios_headquarters' })
    stack = popStep(stack)
    expect(stack).toEqual([{ kind: 'hub' }])
    stack = popStep(stack)
    expect(stack).toEqual([{ kind: 'hub' }])
  })

  test('resetToHub drops all history', () => {
    let stack = pushSteps(initialStack(), uploadSubflow)
    stack = resetToHub(stack)
    expect(stack).toEqual([{ kind: 'hub' }])
  })

  test('startSystem resets to hub and lands on the first subflow step', () => {
    let stack = pushSteps(initialStack(), uploadSubflow)
    stack = startSystem(stack, systemSubflowSteps(subflowInput({ system: 'lever', liveAllowed: true, credentialFields: [credField('api_key')] })))
    expect(kinds(stack)).toEqual(['hub', 'cred'])
    expect(stackTop(stack)).toEqual({ kind: 'cred', system: 'lever', fieldIndex: 0 })
  })

  test('startSystem with an empty subflow stays at the hub', () => {
    const stack = startSystem(initialStack(), [])
    expect(stack).toEqual([{ kind: 'hub' }])
  })

  test('choice then branch: push branchSteps after the choice step', () => {
    const paylocity = subflowInput({
      system: 'paylocity',
      liveAllowed: true,
      uploadAllowed: true,
      credentialFields: PAYLOCITY_CRED_FIELDS,
    })
    let stack = startSystem(initialStack(), systemSubflowSteps(paylocity))
    expect(stackTop(stack)).toEqual({ kind: 'choice', system: 'paylocity' })
    stack = pushSteps(stack, branchSteps(paylocity, 'upload').slice(0, 1))
    expect(stackTop(stack)).toEqual({ kind: 'upload', system: 'paylocity' })
    stack = popStep(stack)
    expect(stackTop(stack)).toEqual({ kind: 'choice', system: 'paylocity' })
  })
})

describe('isSystemComplete', () => {
  test('true only when wizard_completed_at is a non-empty string', () => {
    expect(isSystemComplete({ wizard_completed_at: '2026-08-27T00:00:00Z' })).toBe(true)
    expect(isSystemComplete({ wizard_completed_at: null })).toBe(false)
    expect(isSystemComplete({ wizard_completed_at: '' })).toBe(false)
    expect(isSystemComplete({})).toBe(false)
  })
})

