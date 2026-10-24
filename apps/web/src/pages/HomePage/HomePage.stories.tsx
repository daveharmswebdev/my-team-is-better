import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, waitFor, within } from 'storybook/test'
import {
  TEXAS_ELO,
  USC_ELO,
} from '../../components/EvidenceReceipts/eloLedgerFixture'
import type {
  ComparisonEnvelope,
  OpponentResultOut,
  TeamCaseEnvelope,
  TeamCaseOut,
  TeamsOut,
} from '../../lib/api/types'
import { HomePage } from './HomePage'

/**
 * The whole home page under the a11y addon (issue #219): the form, the
 * verdict modal, its receipts and an open rating disclosure, together, so
 * axe's `heading-order` rule checks the composed outline rather than each
 * component on its own.
 *
 * Under the modal that outline is the dialog's alone: `showModal()` makes
 * the page behind inert, so axe never sees the page's h1 there, and these
 * stories can't catch an h1 -> verdict skip. Only `Idle` checks the page's
 * own outline; the "heading outline (issue #219)" cases in HomePage.test.tsx
 * pin the verdict's continuation under the h1.
 *
 * Like the other page stories (AboutPage, PlayerComparePage), these drive the
 * page through a stubbed `window.fetch` -- there is no shared mock helper
 * yet (#221 tracks moving every story to one): `/api/years` and `/api/teams`
 * get a small catalog, each `/api/verdict/*` endpoint its story's handler,
 * and everything else falls through to the real `fetch`. A verdict story
 * lands on a share link (issue #184), which asks its question on mount with
 * no typing.
 */
type Handler = () => Promise<Response>

interface Handlers {
  champion?: Handler
  teamCase?: Handler
  compare?: Handler
}

const TEAMS: TeamsOut = {
  teams: ['Texas', 'USC', 'Ohio State'],
  team_details: [
    { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
    { name: 'USC', mascot: 'Trojans', aliases: [] },
    { name: 'Ohio State', mascot: 'Buckeyes', aliases: ['OSU'] },
  ],
}

function never(): Promise<Response> {
  return new Promise(() => {})
}

function jsonResponse(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function installFetch(handlers: Handlers) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(
      typeof input === 'string' ? input : input.toString(),
      window.location.href,
    )
    switch (url.pathname) {
      case '/api/years':
        return jsonResponse(200, { years: [2004, 2005] })
      case '/api/teams':
        return jsonResponse(200, TEAMS)
      case '/api/verdict/champion':
        return (handlers.champion ?? never)()
      case '/api/verdict/team-case':
        return (handlers.teamCase ?? never)()
      case '/api/verdict/compare':
        return (handlers.compare ?? never)()
      default:
        return realFetch(input, init)
    }
  }) as typeof fetch
}

function atSearch(search: string, handlers: Handlers = {}) {
  return function RouterDecorator(Story: () => React.JSX.Element) {
    installFetch(handlers)
    return (
      <MemoryRouter initialEntries={[`/${search}`]}>
        <Routes>
          <Route path="/" element={<Story />} />
        </Routes>
      </MemoryRouter>
    )
  }
}

const TEAM_CASE_LINK =
  '?q=team_case&sport=cfb&year=2005&engine=keener&team=Texas'

function game(
  overrides: Partial<OpponentResultOut> &
    Pick<OpponentResultOut, 'game_id' | 'opponent_team_id' | 'opponent_name'>,
): OpponentResultOut {
  return {
    opponent_rank: null,
    opponent_rating: 4.2,
    result: 'W',
    team_score: 31,
    opponent_score: 17,
    week: 1,
    season_type: 'regular',
    venue: 'home',
    neutral_site: false,
    venue_reliable: true,
    ...overrides,
  }
}

// `game_id`s follow the upstream `games.id` shape for 2005 (issue #218).
const OHIO_STATE_WIN = game({
  game_id: 252520194,
  opponent_team_id: 194,
  opponent_name: 'Ohio State',
  opponent_rank: 4,
  opponent_rating: 9.1,
  team_score: 25,
  opponent_score: 22,
  week: 2,
  venue: 'away',
})
const OKLAHOMA_WIN = game({
  game_id: 252810201,
  opponent_team_id: 201,
  opponent_name: 'Oklahoma',
  opponent_rating: 5.3,
  team_score: 45,
  opponent_score: 12,
  week: 6,
  venue: 'neutral',
  neutral_site: true,
})
const USC_WIN = game({
  game_id: 260040251,
  opponent_team_id: 30,
  opponent_name: 'USC',
  opponent_rank: 1,
  opponent_rating: 11.8,
  team_score: 41,
  opponent_score: 38,
  week: 1,
  season_type: 'postseason',
  venue: 'neutral',
  neutral_site: true,
})

const TEXAS_2005: TeamCaseOut = {
  year: 2005,
  method: 'keener',
  team_id: 251,
  team_name: 'Texas',
  rank: 1,
  rating: 0.0195,
  wins: 13,
  losses: 0,
  ties: 0,
  rating_breakdown: {
    entries: [
      {
        opponent_team_id: 30,
        opponent_name: 'USC',
        games_played: 1,
        wins: 1,
        losses: 0,
        credit: 0.0061,
        contribution: 0.0042,
        explanation: 'Beat them once; they were the strongest team you played.',
      },
      {
        opponent_team_id: 194,
        opponent_name: 'Ohio State',
        games_played: 1,
        wins: 1,
        losses: 0,
        credit: 0.0049,
        contribution: 0.0031,
        explanation: 'Beat them once, on the road.',
      },
    ],
    residual_contribution: 0.0122,
  },
  elo_ledger: null,
  games: [OHIO_STATE_WIN, OKLAHOMA_WIN, USC_WIN],
  quality_wins: [USC_WIN, OHIO_STATE_WIN],
  worst_loss: null,
}

const TEAM_CASE: TeamCaseEnvelope = {
  evidence: TEXAS_2005,
  narration: {
    text: 'Texas went 13-0 and beat the No. 1 team in the Rose Bowl. The numbers are the numbers.',
    contested: false,
    cached: true,
  },
  // Issue #155: where Elo ranks Texas 2005, as the fixture db has it.
  other_method_ranks: [{ method: 'elo', rank: 1 }],
}

const CHAMPION: TeamCaseEnvelope = {
  ...TEAM_CASE,
  narration: {
    text: 'Your 2005 champion is Texas. Thirteen wins, no losses, done.',
    contested: false,
    cached: true,
  },
}

const TEAM_CASE_ELO: TeamCaseEnvelope = {
  evidence: {
    ...TEXAS_2005,
    method: 'elo',
    rating: TEXAS_ELO.rating,
    rating_breakdown: { entries: [], residual_contribution: 0 },
    elo_ledger: TEXAS_ELO.elo_ledger,
  },
  narration: TEAM_CASE.narration,
  other_method_ranks: [{ method: 'keener', rank: 1 }],
}

function summary(
  team: typeof TEXAS_ELO,
  rank: number,
): ComparisonEnvelope['evidence']['team_a'] {
  return {
    team_id: team.team_id,
    team_name: team.team_name,
    rank,
    rating: team.rating,
    wins: team.wins,
    losses: team.losses,
    ties: team.ties,
    rating_breakdown: { entries: [], residual_contribution: 0 },
    elo_ledger: team.elo_ledger,
    quality_wins: [],
    worst_loss: null,
  }
}

const COMPARE_ELO: ComparisonEnvelope = {
  evidence: {
    year: 2005,
    method: 'elo',
    team_a: summary(TEXAS_ELO, 1),
    team_b: summary(USC_ELO, 2),
    head_to_head: {
      played: true,
      meetings: [
        {
          game_id: 260040251,
          week: 1,
          season_type: 'postseason',
          neutral_site: true,
          home_team: 'USC',
          away_team: 'Texas',
          home_points: 38,
          away_points: 41,
          winner: 'Texas',
          venue_reliable: true,
        },
      ],
    },
    common_opponents: [],
    rating_diff: TEXAS_ELO.rating - USC_ELO.rating,
    verdict: 'Texas was better.',
  },
  narration: {
    text: 'Texas over USC. They played; Texas won. This is math.',
    contested: false,
    cached: true,
  },
  team_a_other_method_ranks: [{ method: 'keener', rank: 1 }],
  team_b_other_method_ranks: [{ method: 'keener', rank: 2 }],
}

const COMPARE_KEENER: ComparisonEnvelope = {
  ...COMPARE_ELO,
  evidence: {
    ...COMPARE_ELO.evidence,
    method: 'keener',
    team_a: {
      ...COMPARE_ELO.evidence.team_a,
      rating: TEXAS_2005.rating,
      rating_breakdown: TEXAS_2005.rating_breakdown,
      elo_ledger: null,
    },
    team_b: {
      ...COMPARE_ELO.evidence.team_b,
      rating: 0.0171,
      rating_breakdown: {
        entries: [],
        residual_contribution: 0.0171,
      },
      elo_ledger: null,
    },
    rating_diff: TEXAS_2005.rating - 0.0171,
  },
  team_a_other_method_ranks: [{ method: 'elo', rank: 1 }],
  team_b_other_method_ranks: [{ method: 'elo', rank: 2 }],
}

/** The verdict modal, once its answer is on screen. */
async function verdict(canvasElement: HTMLElement, narration: string) {
  const dialog = await within(canvasElement).findByRole('dialog', {
    name: 'The verdict',
  })
  await expect(await within(dialog).findByText(narration)).toBeVisible()
  return dialog
}

/** Hovers the first rating in the verdict open, so axe checks its panel's headings too. */
async function openFirstRating(dialog: HTMLElement, panelName: RegExp) {
  const trigger = within(dialog)
    .getAllByRole('button')
    .find((button) => button.getAttribute('aria-haspopup') === 'dialog')
  await expect(trigger).toBeDefined()
  if (trigger !== undefined) {
    await userEvent.hover(trigger)
  }
  await expect(
    await within(dialog).findByRole('dialog', { name: panelName }),
  ).toBeVisible()
}

const meta = {
  title: 'pages/HomePage',
  component: HomePage,
  tags: ['autodocs'],
  parameters: {
    layout: 'fullscreen',
    a11y: {
      // axe-core runs `heading-order` by default (it is a best-practice rule,
      // and addon-a11y turns off only `region`). Listed here so this page's
      // stories keep checking the composed outline even if a default ever
      // changes (issue #219). Enabling a rule needs no a11y exemption.
      config: { rules: [{ id: 'heading-order', enabled: true }] },
    },
  },
} satisfies Meta<typeof HomePage>

export default meta

type Story = StoryObj<typeof meta>

/** The form on its own, before any question is asked. */
export const Idle: Story = {
  decorators: [atSearch('')],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('heading', { level: 1, name: 'My Team Is Better' }),
    ).toBeVisible()
    // The form defaults Year to the newest season the catalog reports.
    await waitFor(() =>
      expect(canvas.getByLabelText(/year/i)).toHaveValue(2005),
    )
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/** A question asked, its answer not back yet. */
export const Loading: Story = {
  decorators: [atSearch(TEAM_CASE_LINK, { teamCase: never })],
  play: async ({ canvasElement }) => {
    const dialog = await within(canvasElement).findByRole('dialog', {
      name: 'The verdict',
    })
    await expect(within(dialog).getByRole('status')).toHaveTextContent(
      /getting the verdict/i,
    )
  },
}

/** "Who was the champion?", with the champion's Keener breakdown open. */
export const ChampionVerdict: Story = {
  decorators: [
    atSearch('?q=champion&sport=cfb&year=2005&engine=keener', {
      champion: () => jsonResponse(200, CHAMPION),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await verdict(canvasElement, CHAMPION.narration.text)
    await openFirstRating(dialog, /Texas rating breakdown/)
  },
}

/** "Make the case for my team", with its Keener breakdown open. */
export const TeamCaseVerdict: Story = {
  decorators: [
    atSearch(TEAM_CASE_LINK, {
      teamCase: () => jsonResponse(200, TEAM_CASE),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await verdict(canvasElement, TEAM_CASE.narration.text)
    await openFirstRating(dialog, /Texas rating breakdown/)
  },
}

/** The same case asked of Elo, with its game-by-game ledger open. */
export const TeamCaseVerdictElo: Story = {
  decorators: [
    atSearch('?q=team_case&sport=cfb&year=2005&engine=elo&team=Texas', {
      teamCase: () => jsonResponse(200, TEAM_CASE_ELO),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await verdict(canvasElement, TEAM_CASE_ELO.narration.text)
    await openFirstRating(dialog, /Texas Elo rating, game by game/)
  },
}

/** "Who was better?", under Elo, with the first team's ledger open under its name. */
export const CompareVerdict: Story = {
  decorators: [
    atSearch('?q=compare&sport=cfb&year=2005&engine=elo&a=Texas&b=USC', {
      compare: () => jsonResponse(200, COMPARE_ELO),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await verdict(canvasElement, COMPARE_ELO.narration.text)
    await openFirstRating(dialog, /Texas Elo rating, game by game/)
  },
}

/** The same comparison under Keener, with the first team's breakdown open. */
export const CompareVerdictKeener: Story = {
  decorators: [
    atSearch('?q=compare&sport=cfb&year=2005&engine=keener&a=Texas&b=USC', {
      compare: () => jsonResponse(200, COMPARE_KEENER),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await verdict(canvasElement, COMPARE_KEENER.narration.text)
    await openFirstRating(dialog, /Texas rating breakdown/)
  },
}

/** A season the API doesn't have: the error, with its year pills, in the modal. */
export const UnknownYearError: Story = {
  decorators: [
    atSearch('?q=team_case&sport=cfb&year=2019&engine=keener&team=Texas', {
      teamCase: () =>
        jsonResponse(404, {
          detail: {
            error: 'unknown_year',
            year: 2019,
            available_years: [2004, 2005],
          },
        }),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await within(canvasElement).findByRole('dialog', {
      name: 'The verdict',
    })
    const alert = await within(dialog).findByRole('alert')
    await expect(
      within(alert).getByRole('button', { name: '2005' }),
    ).toBeVisible()
  },
}

/** The API never answered: the network error line, in the narrator's voice. */
export const NetworkError: Story = {
  decorators: [
    atSearch(TEAM_CASE_LINK, {
      teamCase: () => Promise.reject(new TypeError('Failed to fetch')),
    }),
  ],
  play: async ({ canvasElement }) => {
    const dialog = await within(canvasElement).findByRole('dialog', {
      name: 'The verdict',
    })
    await expect(await within(dialog).findByRole('alert')).toBeVisible()
  },
}
