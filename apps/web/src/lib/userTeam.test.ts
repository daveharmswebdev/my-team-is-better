import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import {
  USER_TEAM_STORAGE_KEY,
  getStoredUserTeam,
  setStoredUserTeam,
} from './userTeam'

describe('userTeam local storage helpers', () => {
  beforeEach(() => {
    window.localStorage.clear()
  })
  afterEach(() => {
    window.localStorage.clear()
  })

  it('returns an empty string when nothing has been stored yet', () => {
    expect(getStoredUserTeam()).toBe('')
  })

  it('persists a value under the documented storage key', () => {
    setStoredUserTeam('Texas')

    expect(window.localStorage.getItem(USER_TEAM_STORAGE_KEY)).toBe('Texas')
    expect(getStoredUserTeam()).toBe('Texas')
  })

  it('removes the stored value when set to an empty/blank string', () => {
    setStoredUserTeam('Texas')
    setStoredUserTeam('   ')

    expect(window.localStorage.getItem(USER_TEAM_STORAGE_KEY)).toBeNull()
    expect(getStoredUserTeam()).toBe('')
  })
})
