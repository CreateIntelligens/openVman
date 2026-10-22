import { beforeEach, describe, expect, it } from 'vitest'
import {
  ADMIN_HANDOFF_KEY,
  takeAdminHandoff,
  writeAdminHandoff,
  type AdminHandoff,
} from './adminHandoff'

const NOW = 1_800_000_000_000

function handoff(overrides: Partial<AdminHandoff> = {}): AdminHandoff {
  return { v: 1, accountId: 'acct1', characterId: 'c2', projectId: 'proj-B', createdAt: NOW, ...overrides }
}

describe('admin handoff', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('round-trips a fresh handoff for the same account and removes it', () => {
    writeAdminHandoff(handoff())
    expect(localStorage.getItem(ADMIN_HANDOFF_KEY)).not.toBeNull()
    expect(takeAdminHandoff('acct1', NOW + 5_000)).toEqual(handoff())
    expect(localStorage.getItem(ADMIN_HANDOFF_KEY)).toBeNull()
    // 一次性：再拿一次就沒有了。
    expect(takeAdminHandoff('acct1', NOW + 5_000)).toBeNull()
  })

  it('rejects another account but still deletes the entry', () => {
    writeAdminHandoff(handoff())
    expect(takeAdminHandoff('someone-else', NOW)).toBeNull()
    expect(localStorage.getItem(ADMIN_HANDOFF_KEY)).toBeNull()
  })

  it('rejects expired and future-dated entries', () => {
    writeAdminHandoff(handoff())
    expect(takeAdminHandoff('acct1', NOW + 120_001)).toBeNull()
    writeAdminHandoff(handoff())
    expect(takeAdminHandoff('acct1', NOW - 1)).toBeNull()
    writeAdminHandoff(handoff())
    expect(takeAdminHandoff('acct1', NOW + 120_000)).not.toBeNull()
    writeAdminHandoff(handoff())
    expect(takeAdminHandoff('acct1', NOW + 10, 5)).toBeNull()
  })

  it('rejects malformed or wrong-version entries and deletes them', () => {
    localStorage.setItem(ADMIN_HANDOFF_KEY, '{not json')
    expect(takeAdminHandoff('acct1', NOW)).toBeNull()
    expect(localStorage.getItem(ADMIN_HANDOFF_KEY)).toBeNull()

    localStorage.setItem(ADMIN_HANDOFF_KEY, JSON.stringify({ ...handoff(), v: 2 }))
    expect(takeAdminHandoff('acct1', NOW)).toBeNull()

    localStorage.setItem(ADMIN_HANDOFF_KEY, JSON.stringify({ ...handoff(), characterId: 42 }))
    expect(takeAdminHandoff('acct1', NOW)).toBeNull()

    localStorage.setItem(ADMIN_HANDOFF_KEY, JSON.stringify({ ...handoff(), createdAt: 'now' }))
    expect(takeAdminHandoff('acct1', NOW)).toBeNull()
    expect(localStorage.getItem(ADMIN_HANDOFF_KEY)).toBeNull()
  })

  it('needs an account id to accept anything', () => {
    writeAdminHandoff(handoff({ accountId: '' }))
    expect(takeAdminHandoff('', NOW)).toBeNull()
    expect(localStorage.getItem(ADMIN_HANDOFF_KEY)).toBeNull()
  })

  it('survives storage that throws', () => {
    const original = Object.getOwnPropertyDescriptor(window, 'localStorage')
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new Error('blocked')
      },
    })
    try {
      expect(() => writeAdminHandoff(handoff())).not.toThrow()
      expect(takeAdminHandoff('acct1', NOW)).toBeNull()
    } finally {
      if (original) Object.defineProperty(window, 'localStorage', original)
    }
  })
})
