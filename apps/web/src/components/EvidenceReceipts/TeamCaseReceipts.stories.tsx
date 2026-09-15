import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import type { TeamCaseOut } from '../../lib/api/types'
import { TEXAS_ELO } from './eloLedgerFixture'
import { TeamCaseReceipts } from './TeamCaseReceipts'

// `game_id`s follow the upstream `games.id` shape for 2005 (e.g. 252880251):
// distinct per game, since every list keys on them (issue #218).
const qualityWin = {
  game_id: 252740251,
  opponent_team_id: 2,
  opponent_name: 'Michigan',
  opponent_rank: 3,
  opponent_rating: 9.5,
  result: 'W' as const,
  team_score: 27,
  opponent_score: 14,
  week: 5,
  season_type: 'regular',
  neutral_site: false,
}

const openerWin = {
  game_id: 252460251,
  opponent_team_id: 3,
  opponent_name: 'LSU',
  opponent_rank: null,
  opponent_rating: 4.2,
  result: 'W' as const,
  team_score: 24,
  opponent_score: 17,
  week: 1,
  season_type: 'regular',
  neutral_site: false,
}

const midseasonWin = {
  game_id: 253090251,
  opponent_team_id: 4,
  opponent_name: 'Tennessee',
  opponent_rank: null,
  opponent_rating: 3.9,
  result: 'W' as const,
  team_score: 31,
  opponent_score: 10,
  week: 10,
  season_type: 'regular',
  neutral_site: false,
}

const lateSeasonWin = {
  game_id: 253190251,
  opponent_team_id: 5,
  opponent_name: 'Oklahoma',
  opponent_rank: 8,
  opponent_rating: 8.1,
  result: 'W' as const,
  team_score: 20,
  opponent_score: 13,
  week: 12,
  season_type: 'regular',
  neutral_site: true,
}

const bowlWin = {
  game_id: 260040030,
  opponent_team_id: 6,
  opponent_name: 'USC',
  opponent_rank: 2,
  opponent_rating: 9.8,
  result: 'W' as const,
  team_score: 41,
  opponent_score: 38,
  // Bowl weeks are numbered independently of the regular season upstream,
  // so this can carry the same raw `week` as an early regular-season game.
  week: 1,
  season_type: 'postseason',
  neutral_site: true,
}

const undefeated: TeamCaseOut = {
  year: 2005,
  method: 'keener',
  team_id: 1,
  team_name: 'Texas',
  rank: 1,
  rating: 0.01234,
  wins: 13,
  losses: 0,
  ties: 0,
  // Real entries, not just a residual-only placeholder -- lets the rating
  // breakdown disclosure (hover/tap the rating value) show real per-opponent
  // credit. Contribution + residual sum exactly to `rating`
  // (0.005 + 0.00734 = 0.01234).
  rating_breakdown: {
    entries: [
      {
        opponent_team_id: 2,
        opponent_name: 'Michigan',
        games_played: 1,
        wins: 1,
        losses: 0,
        credit: 0.03,
        contribution: 0.005,
        explanation:
          "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
      },
    ],
    residual_contribution: 0.00734,
  },
  elo_ledger: null,
  games: [openerWin, qualityWin, midseasonWin, lateSeasonWin, bowlWin],
  quality_wins: [qualityWin],
  worst_loss: null,
}

const meta = {
  title: 'components/EvidenceReceipts/TeamCaseReceipts',
  component: TeamCaseReceipts,
  tags: ['autodocs'],
} satisfies Meta<typeof TeamCaseReceipts>

export default meta

type Story = StoryObj<typeof meta>

export const Undefeated: Story = {
  args: {
    evidence: undefeated,
  },
}

const worstLoss = {
  game_id: 252950251,
  opponent_team_id: 7,
  opponent_name: 'Baylor',
  opponent_rank: null,
  opponent_rating: 2.1,
  result: 'L' as const,
  team_score: 14,
  opponent_score: 27,
  week: 8,
  season_type: 'regular',
  neutral_site: false,
}

export const WithALoss: Story = {
  args: {
    evidence: {
      ...undefeated,
      wins: 11,
      losses: 1,
      // Baylor is a distinct opponent (its own `opponent_team_id`/`week`),
      // present in both `games` and `worst_loss` -- the realistic shape a
      // real API response has, same as `qualityWin`/Michigan above.
      games: [...undefeated.games, worstLoss],
      worst_loss: worstLoss,
    },
  },
}

const tiedGame = {
  game_id: 331021016,
  opponent_team_id: 16,
  opponent_name: 'Minnesota Vikings',
  opponent_rank: null,
  opponent_rating: 5.4,
  result: 'T' as const,
  team_score: 26,
  opponent_score: 26,
  week: 7,
  season_type: 'regular',
  neutral_site: false,
}

/**
 * A season with a tie (issue #83): the record reads W-L-T ("8-8-1") and the
 * tied game carries its own neutral "T" tag, announced as "Tie" -- never the
 * loss styling. A tie is never a quality win or the worst loss.
 */
export const WithATie: Story = {
  args: {
    evidence: {
      ...undefeated,
      wins: 8,
      losses: 8,
      ties: 1,
      games: [...undefeated.games, tiedGame],
    },
  },
}

const coloradoWeek7 = {
  game_id: 252880251,
  opponent_team_id: 38,
  opponent_name: 'Colorado',
  opponent_rank: 19,
  opponent_rating: 7.7,
  result: 'W' as const,
  team_score: 42,
  opponent_score: 17,
  week: 7,
  season_type: 'regular',
  neutral_site: false,
}

const coloradoTitleGame = {
  ...coloradoWeek7,
  game_id: 253370251,
  team_score: 70,
  opponent_score: 3,
  week: 14,
  neutral_site: true,
}

/**
 * A rematch (issue #218): real 2005 Texas beat Colorado in week 7 and again
 * in the Big 12 title game. Both are quality wins and both sit in the full
 * schedule, each as its own row keyed on its own `game_id` -- the same
 * `opponent_team_id` twice is two games, not one.
 */
export const Rematch: Story = {
  args: {
    evidence: {
      ...undefeated,
      games: [...undefeated.games, coloradoWeek7, coloradoTitleGame],
      quality_wins: [qualityWin, coloradoWeek7, coloradoTitleGame],
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const qualityWins = canvas.getByRole('list', { name: /quality wins/i })
    await expect(within(qualityWins).getAllByText(/vs Colorado/)).toHaveLength(
      2,
    )
    const schedule = canvas.getByRole('list', { name: /full schedule/i })
    await expect(within(schedule).getAllByText(/vs Colorado/)).toHaveLength(2)
  },
}

/**
 * Demonstrates the rating breakdown disclosure wired into the champion/
 * team-case flows -- hover (or Tab to focus, then press Enter) the rating
 * value to see the per-opponent credit that adds up to it, same disclosure
 * `ComparisonReceipts` already uses for the compare flow.
 */
export const RatingBreakdown: Story = {
  args: {
    evidence: undefeated,
  },
}

const texasElo: TeamCaseOut = {
  ...undefeated,
  method: 'elo',
  rating: TEXAS_ELO.rating,
  wins: TEXAS_ELO.wins,
  losses: TEXAS_ELO.losses,
  ties: TEXAS_ELO.ties,
  rating_breakdown: { entries: [], residual_contribution: 0 },
  elo_ledger: TEXAS_ELO.elo_ledger,
}

/**
 * An Elo team case (epic #147 / issues #82, #183): the rating prints on Elo's
 * own whole-point scale ("1,661"), and hovering it opens the engine's own
 * game-by-game ledger -- the rule, the start, every game's worked step and
 * the rating the card rounds.
 */
export const Elo: Story = {
  args: { evidence: texasElo },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText(/Rating/)).toBeVisible()
    await userEvent.hover(canvas.getByRole('button', { name: '1,661' }))
    await expect(
      await canvas.findByRole('dialog', {
        name: 'Texas Elo rating, game by game',
      }),
    ).toBeVisible()
    await expect(canvasElement.textContent).not.toMatch(/Keener/)
  },
}

/**
 * An Elo response from a stale API/db with no ledger: the plain rating and
 * one honest line, never an empty or invented panel.
 */
export const EloLedgerUnavailable: Story = {
  args: { evidence: { ...texasElo, elo_ledger: null } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText(/Rating 1,661/)).toBeVisible()
    await expect(canvas.queryByRole('button')).toBeNull()
    await expect(
      canvas.getByText(
        "This rating's game-by-game work isn't available right now.",
      ),
    ).toBeVisible()
  },
}

/** Career Elo: nothing to open yet, and one line says why. */
export const EloCareer: Story = {
  args: {
    evidence: { ...texasElo, method: 'elo_career', elo_ledger: null },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.queryByRole('button')).toBeNull()
    await expect(
      canvas.getByText(
        "Career Elo carries ratings across seasons, and its game-by-game work isn't shown yet.",
      ),
    ).toBeVisible()
  },
}
