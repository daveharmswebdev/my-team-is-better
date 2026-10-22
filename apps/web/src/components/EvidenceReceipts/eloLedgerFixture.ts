import type {
  EloGameStepOut,
  EloLedgerOut,
  GameResult,
} from '../../lib/api/types'
import fixture from './eloLedgerFixture.json'

/**
 * Engine-true Elo ledgers for tests and stories (issue #183). The numbers live
 * in `eloLedgerFixture.json`, a byte-for-byte copy of what the engine's own
 * Elo functions produced with the CFB constants -- never hand-edit them, and
 * never recompute them in TypeScript. This module only narrows the JSON's
 * string fields to their literal unions, throwing rather than casting.
 *
 * `venue_reliable` (issue #349) is not in the JSON: the engine's Elo functions
 * leave it at the contract's default, `True`, and only evidence derives it
 * from the season. So `TEXAS_ELO` and `USC_ELO` are ledgers whose venues the
 * API vouches for, and `TEXAS_ELO_UNRELIABLE_VENUES` is the same ledger with
 * every venue unvouched -- what a pre-2008 CFB season off #359's override list
 * sends. The numbers are identical either way: reliability is display only.
 */

export interface EloFixtureTeam {
  team_name: string
  team_id: number
  rating: number
  wins: number
  losses: number
  ties: number
  elo_ledger: EloLedgerOut
}

type RawStep = Omit<EloGameStepOut, 'venue' | 'result' | 'venue_reliable'> & {
  venue: string
  result: string
}

interface RawTeam {
  team_id: number
  rating: number
  wins: number
  losses: number
  ties: number
  elo_ledger: Omit<EloLedgerOut, 'steps'> & { steps: RawStep[] }
}

function venue(value: string): EloGameStepOut['venue'] {
  if (value === 'home' || value === 'away' || value === 'neutral') {
    return value
  }
  throw new Error(`eloLedgerFixture: unknown venue ${value}`)
}

function result(value: string): GameResult {
  if (value === 'W' || value === 'L' || value === 'T') {
    return value
  }
  throw new Error(`eloLedgerFixture: unknown result ${value}`)
}

function team(team_name: string, raw: RawTeam): EloFixtureTeam {
  return {
    ...raw,
    team_name,
    elo_ledger: {
      ...raw.elo_ledger,
      steps: raw.elo_ledger.steps.map((step) => ({
        ...step,
        venue: venue(step.venue),
        result: result(step.result),
        venue_reliable: true,
      })),
    },
  }
}

/** Texas 2005: 4-0-1 -- home, away win, two neutral sites, an away tie, a postseason game. */
export const TEXAS_ELO: EloFixtureTeam = team('Texas', fixture.Texas)

/** USC 2005: 1-1. */
export const USC_ELO: EloFixtureTeam = team('USC', fixture.USC)

/**
 * Texas 2005's ledger as a pre-2008 CFB season sends it (issue #349): the same
 * engine numbers, home-field adjustments included, with no venue the API can
 * vouch for.
 */
export const TEXAS_ELO_UNRELIABLE_VENUES: EloFixtureTeam = {
  ...TEXAS_ELO,
  elo_ledger: {
    ...TEXAS_ELO.elo_ledger,
    steps: TEXAS_ELO.elo_ledger.steps.map((step) => ({
      ...step,
      venue_reliable: false,
    })),
  },
}
