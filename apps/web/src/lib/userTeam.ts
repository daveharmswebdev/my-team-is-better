/**
 * Guest-first "your team" persistence (PRD §5.3 / this issue's brief): a
 * small value that lives only in the browser's `localStorage`, never synced
 * to a server, sent as `user_team` on every verdict request once set.
 */

export const USER_TEAM_STORAGE_KEY = 'myTeamIsBetter.userTeam'

export function getStoredUserTeam(): string {
  try {
    return window.localStorage.getItem(USER_TEAM_STORAGE_KEY) ?? ''
  } catch {
    // localStorage unavailable (e.g. private browsing/blocked storage) --
    // degrade to "no team set" rather than throwing.
    return ''
  }
}

export function setStoredUserTeam(value: string): void {
  try {
    if (value.trim() === '') {
      window.localStorage.removeItem(USER_TEAM_STORAGE_KEY)
    } else {
      window.localStorage.setItem(USER_TEAM_STORAGE_KEY, value)
    }
  } catch {
    // Fails silently -- the field still works for the current page load, it
    // just won't persist across visits.
  }
}
