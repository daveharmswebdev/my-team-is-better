import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, waitFor, within } from 'storybook/test'
import { NETWORK_ERROR_COPY } from '../../lib/api/client'
import type { ComparisonEnvelope, TeamCaseEnvelope } from '../../lib/api/types'
import { TEXAS_ELO, USC_ELO } from '../EvidenceReceipts/eloLedgerFixture'
import { VerdictCard } from './VerdictCard'

const teamCaseEnvelope: TeamCaseEnvelope = {
  evidence: {
    year: 2005,
    method: 'keener',
    team_id: 1,
    team_name: 'Texas',
    rank: 1,
    rating: 0.01234,
    wins: 13,
    losses: 0,
    ties: 0,
    rating_breakdown: {
      entries: [
        {
          opponent_team_id: 2,
          opponent_name: 'Michigan',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.02,
          contribution: 0.006,
          explanation:
            "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
        },
      ],
      residual_contribution: 0.00634,
    },
    elo_ledger: null,
    games: [],
    quality_wins: [
      {
        game_id: 252740251,
        opponent_team_id: 2,
        opponent_name: 'Michigan',
        opponent_rank: 3,
        opponent_rating: 9.5,
        result: 'W',
        team_score: 27,
        opponent_score: 14,
        week: 5,
        season_type: 'regular',
        venue: 'away',
        venue_reliable: true,
        neutral_site: false,
      },
    ],
    worst_loss: null,
  },
  narration: {
    text: "Texas went 13-0 and beat everybody worth beating. That's the champ, no debate needed.",
    contested: false,
    cached: false,
  },
  other_method_ranks: [],
}

const comparisonEnvelope: ComparisonEnvelope = {
  evidence: {
    year: 2005,
    method: 'keener',
    team_a: {
      team_id: 1,
      team_name: 'Texas',
      rank: 1,
      rating: 0.01234,
      wins: 13,
      losses: 0,
      ties: 0,
      rating_breakdown: {
        entries: [
          {
            opponent_team_id: 3,
            opponent_name: 'Ohio State',
            games_played: 1,
            wins: 1,
            losses: 0,
            credit: 0.019,
            contribution: 0.0057,
            explanation:
              "Snuck out a 24-21 win — 53% of the points, barely above even. That's the flat 0.60 every win banks, plus just a 0.01 margin bonus.",
          },
        ],
        residual_contribution: 0.00664,
      },
      elo_ledger: null,
      quality_wins: [],
      worst_loss: null,
    },
    team_b: {
      team_id: 2,
      team_name: 'USC',
      rank: 2,
      rating: 0.01147,
      wins: 12,
      losses: 1,
      ties: 0,
      rating_breakdown: {
        entries: [
          {
            opponent_team_id: 3,
            opponent_name: 'Ohio State',
            games_played: 1,
            wins: 0,
            losses: 1,
            credit: 0.015,
            contribution: 0.0045,
            explanation:
              'Got run over, 3-52 — 5% of the points, clamped at the 15% floor. Still banks the flat 0.05 every loss keeps, nobody walks away with zero, but no margin bonus at that end of the scale.',
          },
        ],
        residual_contribution: 0.00697,
      },
      elo_ledger: null,
      quality_wins: [],
      worst_loss: null,
    },
    head_to_head: { played: false, meetings: [] },
    common_opponents: [
      {
        opponent_team_id: 3,
        opponent_name: 'Ohio State',
        opponent_rank: 4,
        team_a_meetings: [
          {
            game_id: 252600194,
            result: 'W',
            team_score: 38,
            opponent_score: 24,
            week: 3,
            season_type: 'regular',
            venue: 'away',
            venue_reliable: true,
          },
        ],
        team_b_meetings: [
          {
            game_id: 253160194,
            result: 'L',
            team_score: 17,
            opponent_score: 20,
            week: 11,
            season_type: 'regular',
            venue: 'home',
            venue_reliable: true,
          },
        ],
      },
    ],
    rating_diff: 0.00087,
    verdict: 'Texas was better -- higher rating, better résumé.',
  },
  narration: {
    text: "It's close, but Texas edges USC. Reasonable people can disagree here.",
    contested: true,
    cached: true,
  },
  team_a_other_method_ranks: [],
  team_b_other_method_ranks: [],
}

const meta = {
  title: 'components/VerdictCard',
  component: VerdictCard,
  tags: ['autodocs'],
  args: {
    onSelectYear: fn(),
    onSelectCandidate: fn(),
    onSelectMethod: fn(),
  },
} satisfies Meta<typeof VerdictCard>

export default meta

type Story = StoryObj<typeof meta>

export const Loading: Story = {
  args: {
    state: { status: 'loading' },
  },
}

/**
 * A success card offers "Share this verdict" (issue #184) whenever the page
 * hands it a share link, as `HomePage` does for every verdict. Since #474 it
 * is first in the card on a desktop and floats bottom-right on a phone.
 */
export const TeamCaseSuccess: Story = {
  args: {
    state: { status: 'success', envelope: teamCaseEnvelope },
    shareUrl:
      'https://my-team-is-better.lol/?q=team_case&sport=cfb&year=2005&engine=keener&team=Texas',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('button', { name: 'Share this verdict' }),
    ).toBeVisible()
  },
}

export const ComparisonSuccess: Story = {
  args: {
    state: { status: 'success', envelope: comparisonEnvelope },
    shareUrl:
      'https://my-team-is-better.lol/?q=compare&sport=cfb&year=2005&engine=keener&a=Texas&b=USC',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('button', { name: 'Share this verdict' }),
    ).toBeVisible()
  },
}

/** Whether `first` comes before `second` in reading (document) order. */
function precedes(first: Element, second: Element): boolean {
  return (
    (first.compareDocumentPosition(second) &
      Node.DOCUMENT_POSITION_FOLLOWING) !==
    0
  )
}

/**
 * Issue #474 on a desktop: one inline Share button, the primary action,
 * first in the card; then the two teams with rank and record; then the
 * verdict.
 */
export const ComparisonOnDesktop: Story = {
  ...ComparisonSuccess,
  globals: { viewport: { value: 'desktop', isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getAllByRole('button', { name: /^Share/ }),
    ).toHaveLength(1)
    const share = canvas.getByRole('button', { name: 'Share this verdict' })
    const teams = canvas.getByRole('list', { name: 'Teams compared' })
    await expect(teams).toHaveTextContent('Texas Rank #1 · 13-0')
    await expect(teams).toHaveTextContent('USC Rank #2 · 12-1')
    const narration = canvas.getByText(/Texas edges USC/)
    await expect(precedes(share, teams)).toBe(true)
    await expect(precedes(teams, narration)).toBe(true)
    await expect(
      canvasElement.querySelector('[data-layout="floating"]'),
    ).toBeNull()
  },
}

/**
 * Issue #474 on a phone: the teams, the verdict, the receipts -- and one
 * Share button floating bottom-right, at least 56px, out of the flow.
 */
export const ComparisonOnPhone: Story = {
  ...ComparisonSuccess,
  globals: { viewport: { value: 'mobile2', isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getAllByRole('button', { name: /^Share/ }),
    ).toHaveLength(1)
    const share = canvas.getByRole('button', { name: 'Share this verdict' })
    await expect(share).toHaveTextContent(/^Share$/)
    const box = share.getBoundingClientRect()
    await expect(box.width).toBeGreaterThanOrEqual(56)
    await expect(box.height).toBeGreaterThanOrEqual(56)
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight)
    const teams = canvas.getByRole('list', { name: 'Teams compared' })
    const receipts = canvas.getByRole('region', {
      name: 'comparison evidence',
    })
    await expect(precedes(teams, receipts)).toBe(true)
    await expect(precedes(receipts, share)).toBe(true)
  },
}

/**
 * A `beforeEach` that takes away the share sheet and gives the clipboard
 * `writeText` -- own properties on `navigator`, removed again after.
 */
function withClipboard(writeText: (text: string) => Promise<void>) {
  return () => {
    Object.defineProperty(navigator, 'share', {
      value: undefined,
      configurable: true,
      writable: true,
    })
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
      writable: true,
    })
    return () => {
      Reflect.deleteProperty(navigator, 'share')
      Reflect.deleteProperty(navigator, 'clipboard')
    }
  }
}

/**
 * Scrolled to the bottom of the page (a standalone card scrolls the
 * document), the receipts end above the floating stack -- button plus
 * whatever it shows -- not under it.
 */
async function expectReceiptsClearOfOverlay(canvasElement: HTMLElement) {
  const slot = canvasElement.querySelector('[data-layout="floating"]')
  const stack = slot?.firstElementChild
  const last = slot?.previousElementSibling
  await expect(stack).toBeTruthy()
  await expect(last).toBeTruthy()
  await waitFor(() => {
    window.scrollTo(0, document.documentElement.scrollHeight)
    return expect(last?.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      stack?.getBoundingClientRect().top ?? 0,
    )
  })
}

/** Issue #474, round 2: the "Link copied" toast never sits over the receipts. */
export const ComparisonOnPhoneLinkCopied: Story = {
  ...ComparisonSuccess,
  globals: { viewport: { value: 'mobile2', isRotated: false } },
  beforeEach: withClipboard(() => Promise.resolve()),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Share this verdict' }),
    )
    await expect(await canvas.findByText('Link copied')).toBeVisible()
    await expectReceiptsClearOfOverlay(canvasElement)
  },
}

/**
 * Issue #474, round 2: the manual-copy box makes room for itself, and has a
 * dismiss button that puts focus back on Share.
 */
export const ComparisonOnPhoneManualCopy: Story = {
  ...ComparisonSuccess,
  globals: { viewport: { value: 'mobile2', isRotated: false } },
  beforeEach: withClipboard(() =>
    Promise.reject(new Error('Clipboard blocked')),
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const share = canvas.getByRole('button', { name: 'Share this verdict' })
    await userEvent.click(share)
    await expect(
      await canvas.findByRole('textbox', { name: 'Copy this link' }),
    ).toBeVisible()
    await expectReceiptsClearOfOverlay(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Dismiss the link' }),
    )
    await expect(
      canvas.queryByRole('textbox', { name: 'Copy this link' }),
    ).toBeNull()
    await expect(share).toHaveFocus()
  },
}

/** Issue #474: a team case's header is its one team, with rank and record. */
export const TeamCaseOnDesktop: Story = {
  ...TeamCaseSuccess,
  globals: { viewport: { value: 'desktop', isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const share = canvas.getByRole('button', { name: 'Share this verdict' })
    const teams = canvas.getByTestId('verdict-teams')
    await expect(teams).toHaveTextContent('Texas Rank #1 · 13-0')
    await expect(precedes(share, teams)).toBe(true)
  },
}

/** Issue #474: the same team case on a phone, its Share button floating. */
export const TeamCaseOnPhone: Story = {
  ...TeamCaseSuccess,
  globals: { viewport: { value: 'mobile2', isRotated: false } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getAllByRole('button', { name: /^Share/ }),
    ).toHaveLength(1)
    const share = canvas.getByRole('button', { name: 'Share this verdict' })
    await expect(
      canvasElement.querySelector('[data-layout="floating"]'),
    ).toContainElement(share)
    await expect(canvas.getByTestId('verdict-teams')).toHaveTextContent(
      'Texas Rank #1 · 13-0',
    )
  },
}

/**
 * Issues #154 and #183: a team case answered by Elo, as the API really sends
 * it -- with the engine's game-by-game ledger. The card names the engine that
 * answered, prints the rating on Elo's scale, and hovering the rating opens
 * that ledger through the card.
 */
export const TeamCaseAnsweredByElo: Story = {
  args: {
    state: {
      status: 'success',
      envelope: {
        ...teamCaseEnvelope,
        evidence: {
          ...teamCaseEnvelope.evidence,
          method: 'elo',
          team_name: TEXAS_ELO.team_name,
          rating: TEXAS_ELO.rating,
          rating_breakdown: { entries: [], residual_contribution: 0 },
          elo_ledger: TEXAS_ELO.elo_ledger,
        },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('Engine: Elo (second opinion)')).toBeVisible()
    await userEvent.hover(canvas.getByRole('button', { name: '1,661' }))
    await expect(
      await canvas.findByRole('dialog', {
        name: 'Texas Elo rating, game by game',
      }),
    ).toBeVisible()
  },
}

/**
 * Issues #154 and #183: a comparison answered by Elo -- the same quiet engine
 * label, and each team's rating opens that team's own ledger through the card.
 */
export const ComparisonAnsweredByElo: Story = {
  args: {
    state: {
      status: 'success',
      envelope: {
        ...comparisonEnvelope,
        evidence: {
          ...comparisonEnvelope.evidence,
          method: 'elo',
          team_a: {
            ...comparisonEnvelope.evidence.team_a,
            team_name: TEXAS_ELO.team_name,
            rating: TEXAS_ELO.rating,
            rating_breakdown: { entries: [], residual_contribution: 0 },
            elo_ledger: TEXAS_ELO.elo_ledger,
          },
          team_b: {
            ...comparisonEnvelope.evidence.team_b,
            team_name: USC_ELO.team_name,
            rating: USC_ELO.rating,
            rating_breakdown: { entries: [], residual_contribution: 0 },
            elo_ledger: USC_ELO.elo_ledger,
          },
          rating_diff: TEXAS_ELO.rating - USC_ELO.rating,
        },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('Engine: Elo (second opinion)')).toBeVisible()
    for (const [label, team] of [
      ['1,661', 'Texas'],
      ['1,527', 'USC'],
    ] as const) {
      const trigger = canvas.getByRole('button', { name: label })
      await userEvent.hover(trigger)
      await expect(
        await canvas.findByRole('dialog', {
          name: `${team} Elo rating, game by game`,
        }),
      ).toBeVisible()
      await userEvent.unhover(trigger)
      await expect(canvas.queryByRole('dialog')).toBeNull()
    }
  },
}

/**
 * Issue #155: Texas 2005 under Keener (#1), with where Elo ranks it (#1,
 * as the fixture db has it) and a control to ask Elo instead. The API's
 * `elo_career` entry is never shown. Renders exactly like
 * `OtherEngineRanksPennState2005`, ranks aside (`VerdictCard.test.tsx`).
 */
export const OtherEngineRanksTexas2005: Story = {
  args: {
    state: {
      status: 'success',
      envelope: {
        ...teamCaseEnvelope,
        other_method_ranks: [
          { method: 'elo', rank: 1 },
          { method: 'elo_career', rank: 2 },
        ],
      },
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('Elo (second opinion): #1')).toBeVisible()
    await expect(canvas.queryByText(/Elo, career/)).toBeNull()
    await userEvent.click(
      canvas.getByRole('button', { name: 'Ask Elo (second opinion)' }),
    )
    await expect(args.onSelectMethod).toHaveBeenCalledWith('elo')
  },
}

/**
 * Issue #155: Penn State 2005 under Keener (#3), with where Elo ranks it
 * (#6, as the fixture db and production have it). The same quiet line as
 * `OtherEngineRanksTexas2005`: the engines have no mandate to agree.
 */
export const OtherEngineRanksPennState2005: Story = {
  args: {
    state: {
      status: 'success',
      envelope: {
        ...teamCaseEnvelope,
        evidence: {
          ...teamCaseEnvelope.evidence,
          team_name: 'Penn State',
          rank: 3,
          wins: 11,
          losses: 1,
        },
        narration: {
          text: "Penn State went 11-1 and that's a top-three team on the math.",
          contested: false,
          cached: false,
        },
        other_method_ranks: [
          { method: 'elo', rank: 6 },
          { method: 'elo_career', rank: 8 },
        ],
      },
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByText('Elo (second opinion): #6')).toBeVisible()
    await expect(canvas.queryByText(/Elo, career/)).toBeNull()
    await userEvent.click(
      canvas.getByRole('button', { name: 'Ask Elo (second opinion)' }),
    )
    await expect(args.onSelectMethod).toHaveBeenCalledWith('elo')
  },
}

/** Issue #155: a compare verdict shows a line for each team, and one control. */
export const OtherEngineRanksComparison: Story = {
  args: {
    state: {
      status: 'success',
      envelope: {
        ...comparisonEnvelope,
        team_a_other_method_ranks: [{ method: 'elo', rank: 1 }],
        team_b_other_method_ranks: [{ method: 'elo', rank: 2 }],
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByText('Texas · Elo (second opinion): #1'),
    ).toBeVisible()
    await expect(
      canvas.getByText('USC · Elo (second opinion): #2'),
    ).toBeVisible()
    await expect(
      canvas.getAllByRole('button', { name: 'Ask Elo (second opinion)' }),
    ).toHaveLength(1)
  },
}

export const UnknownYearError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'unknown_year',
        body: {
          error: 'unknown_year',
          year: 1899,
          available_years: [2003, 2004, 2005],
        },
      },
    },
  },
}

export const AmbiguousTeamError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'ambiguous_team',
        body: {
          error: 'ambiguous_team',
          query: 'Texas St',
          candidates: ['Texas', 'Texas State'],
        },
      },
    },
  },
}

/**
 * `unknown_team` -- a not-found state with no pick list at all, by contract
 * (correction pills were removed from this error kind).
 */
export const UnknownTeamErrorNotFound: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'unknown_team',
        body: {
          error: 'unknown_team',
          query: 'Abilene Christian',
          year: 2010,
          sport: 'cfb',
        },
      },
    },
  },
}

export const SameTeamComparisonError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'same_team_comparison',
        body: { error: 'same_team_comparison', team_name: 'Texas' },
      },
    },
  },
}

export const NetworkError: Story = {
  args: {
    state: {
      status: 'error',
      error: {
        kind: 'network_error',
        message: NETWORK_ERROR_COPY,
      },
    },
  },
}
