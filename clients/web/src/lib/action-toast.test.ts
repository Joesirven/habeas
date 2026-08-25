// @ts-nocheck — exercised via `bun test`; not part of app tsc graph
import { describe, expect, test } from 'bun:test'

import { SAFE_API_ERROR_DETAILS, safeErrorMessage } from './action-toast'
import { connectTestFailureMessage } from './api'

describe('safeErrorMessage', () => {
  test('unknown Error → generic message', () => {
    expect(safeErrorMessage(new Error('boom with secrets'))).toBe(
      'Something went wrong. Try again.',
    )
  })

  test('Admin API allowlisted detail → friendly string', () => {
    const err = new Error('Admin API 404: {"detail":"invite not found"}')
    expect(safeErrorMessage(err)).toBe(SAFE_API_ERROR_DETAILS['invite not found'])
  })

  test('Sheets provision failure → friendly string', () => {
    const err = new Error(
      'Admin API 502: {"detail":"failed to provision google sheets service account"}',
    )
    expect(safeErrorMessage(err)).toBe(
      SAFE_API_ERROR_DETAILS['failed to provision google sheets service account'],
    )
  })

  test('connection delete failure → friendly string', () => {
    const err = new Error('Admin API 500: {"detail":"failed to delete connection"}')
    expect(safeErrorMessage(err)).toBe(SAFE_API_ERROR_DETAILS['failed to delete connection'])
  })

  test('Admin API validation-array detail → generic', () => {
    const err = new Error(
      'Admin API 422: {"detail":[{"loc":["body","api_key"],"msg":"field required"}]}',
    )
    expect(safeErrorMessage(err)).toBe('Something went wrong. Try again.')
  })

  test('credential field noise → generic credentials message', () => {
    const err = new Error(
      'Admin API 400: {"detail":"Missing required credential field: api_key"}',
    )
    expect(safeErrorMessage(err)).toBe(
      'Could not save credentials. Check the fields and try again.',
    )
  })

  test('never echoes email or hash-like strings', () => {
    const err = new Error(
      'Admin API 500: {"detail":"failed for user@example.com hash=abcdef0123456789"}',
    )
    const msg = safeErrorMessage(err)
    expect(msg).not.toContain('@')
    expect(msg).not.toContain('abcdef')
  })
})

describe('connectTestFailureMessage', () => {
  test('owner message stays code-free', () => {
    expect(connectTestFailureMessage('auth_failed')).not.toContain('(')
    expect(connectTestFailureMessage('http_5xx')).not.toContain('(')
    expect(connectTestFailureMessage('http_5xx')).not.toContain('5xx')
  })
})
