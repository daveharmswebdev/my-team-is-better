import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, waitFor, within } from 'storybook/test'
import type {
  OpponentCreditOut,
  OpponentResultOut,
  TeamCaseEnvelope,
  VerdictCardState,
} from '../../lib/api/types'
import { TEXAS_ELO } from '../EvidenceReceipts/eloLedgerFixture'
import { VerdictCard } from '../VerdictCard/VerdictCard'
import { VerdictModal } from './VerdictModal'

const OPPONENTS = [
  'Louisiana-Lafayette',
  'Ohio State',
  'Rice',
  'Missouri',
  'Oklahoma',
  'Colorado',
  'Texas Tech',
  'Oklahoma State',
  'Baylor',
  'Kansas',
  'Texas A&M',
  'USC',
]

function game(index: number, opponent: string): OpponentResultOut {
  return {
    // Distinct per game, in the upstream `games.id` shape (issue #218).
    game_id: 252460251 + index * 70000,
    opponent_team_id: index + 2,
    opponent_name: opponent,
    opponent_rank: index + 3,
    opponent_rating: 9.5 - index * 0.4,
    result: 'W',
    team_score: 30 + index,
    opponent_score: 14 + (index % 5),
    week: index + 1,
    season_type: index === OPPONENTS.length - 1 ? 'postseason' : 'regular',
    // Venue and `neutral_site` come off the same expression: the API cannot
    // send a row where they disagree (issue #294). The rest alternate, so a
    // side-swap could not hide behind a uniformly home schedule.
    venue:
      index === OPPONENTS.length - 1
        ? 'neutral'
        : index % 2 === 0
          ? 'home'
          : 'away',
    neutral_site: index === OPPONENTS.length - 1,
  }
}

function credit(index: number, opponent: string): OpponentCreditOut {
  return {
    opponent_team_id: index + 2,
    opponent_name: opponent,
    games_played: 1,
    wins: 1,
    losses: 0,
    credit: 0.02 - index * 0.001,
    contribution: 0.006 - index * 0.0003,
    explanation: `Beat ${opponent} ${30 + index}-${14 + (index % 5)}. That earns the flat 0.60 every win banks, plus a margin bonus for the score.`,
  }
}

const SHORT_SUCCESS: TeamCaseEnvelope = {
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
      entries: [credit(0, 'Ohio State')],
      residual_contribution: 0.00634,
    },
    elo_ledger: null,
    games: [game(1, 'Ohio State')],
    quality_wins: [game(1, 'Ohio State')],
    worst_loss: null,
  },
  narration: {
    text: "Texas went 13-0 and beat everybody worth beating. That's the champ, no debate needed.",
    contested: false,
    cached: false,
  },
}

/** A full season of receipts under a long narration: more than any screen holds. */
const LONG_SUCCESS: TeamCaseEnvelope = {
  evidence: {
    ...SHORT_SUCCESS.evidence,
    rating_breakdown: {
      entries: OPPONENTS.map((opponent, index) => credit(index, opponent)),
      residual_contribution: 0.00134,
    },
    games: OPPONENTS.map((opponent, index) => game(index, opponent)),
    quality_wins: OPPONENTS.slice(0, 8).map((opponent, index) =>
      game(index, opponent),
    ),
  },
  narration: {
    text: [
      'Texas went 13-0 and beat everybody worth beating.',
      'They went into Columbus in September and came out with a win nobody else managed all year.',
      'Then they ran the Big 12 like it owed them money, and finished it off against the team half the country had already crowned.',
      "That's the champ. No debate needed, but pull up a stool and I'll have it anyway.",
    ].join(' '),
    contested: false,
    cached: true,
  },
}

const SHARE_URL =
  'https://my-team-is-better.lol/?q=team_case&sport=cfb&year=2005&engine=keener&team=Texas'

/**
 * Stories render a `VerdictCard` inside the modal, as `HomePage` does. The
 * card's state is a story-only arg, since the modal takes children and
 * nothing else.
 */
interface StoryArgs {
  verdict: VerdictCardState
}

const meta = {
  title: 'components/VerdictModal',
  component: VerdictModal,
  tags: ['autodocs'],
  parameters: { layout: 'fullscreen' },
  args: {
    open: true,
    title: 'The verdict',
    closeLabel: 'Close the verdict',
    onClose: fn(),
    children: null,
    verdict: { status: 'loading' },
  },
  render: ({ verdict, ...args }) => (
    <VerdictModal {...args}>
      <VerdictCard
        state={verdict}
        onSelectYear={fn()}
        onSelectCandidate={fn()}
        shareUrl={verdict.status === 'success' ? SHARE_URL : undefined}
      />
    </VerdictModal>
  ),
} satisfies Meta<StoryArgs & Parameters<typeof VerdictModal>[0]>

export default meta

type Story = StoryObj<typeof meta>

/** Focus starts on the close button, which is at least 44x44px. */
export const Loading: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = canvas.getByRole('dialog', { name: 'The verdict' })
    await expect(within(dialog).getByRole('status')).toHaveTextContent(
      /getting the verdict/i,
    )
    const close = within(dialog).getByRole('button', {
      name: 'Close the verdict',
    })
    await waitFor(() => expect(close).toHaveFocus())
    const box = close.getBoundingClientRect()
    await expect(box.width).toBeGreaterThanOrEqual(44)
    await expect(box.height).toBeGreaterThanOrEqual(44)
  },
}

/** An error keeps its correction pills, inside the modal. */
export const UnknownYearError: Story = {
  args: {
    verdict: {
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
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement).getByRole('dialog', {
      name: 'The verdict',
    })
    const alert = within(dialog).getByRole('alert')
    await expect(
      within(alert).getByRole('button', { name: '2005' }),
    ).toBeVisible()
  },
}

export const Success: Story = {
  args: { verdict: { status: 'success', envelope: SHORT_SUCCESS } },
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement).getByRole('dialog', {
      name: 'The verdict',
    })
    await expect(
      within(dialog).getByRole('button', { name: 'Share this verdict' }),
    ).toBeVisible()
  },
}

/**
 * A long verdict scrolls inside the modal, not the page behind it, and the
 * close button stays in view at the bottom.
 */
export const LongSuccessScrolls: Story = {
  args: { verdict: { status: 'success', envelope: LONG_SUCCESS } },
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement).getByRole('dialog', {
      name: 'The verdict',
    })
    const close = within(dialog).getByRole('button', {
      name: 'Close the verdict',
    })
    await expect(dialog.scrollHeight).toBeGreaterThan(dialog.clientHeight)

    dialog.scrollTo({ top: dialog.scrollHeight, behavior: 'instant' })

    await waitFor(() => expect(dialog.scrollTop).toBeGreaterThan(0))
    await expect(window.scrollY).toBe(0)
    const closeBox = close.getBoundingClientRect()
    await expect(closeBox.top).toBeGreaterThanOrEqual(0)
    await expect(closeBox.bottom).toBeLessThanOrEqual(window.innerHeight)
    await expect(
      within(dialog).getByRole('button', { name: 'Share this verdict' }),
    ).toBeVisible()
  },
}

/** Escape and the close button each ask to close exactly once. */
export const CloseRequests: Story = {
  args: { verdict: { status: 'success', envelope: SHORT_SUCCESS } },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement).getByRole('dialog', {
      name: 'The verdict',
    })
    const close = within(dialog).getByRole('button', {
      name: 'Close the verdict',
    })
    await waitFor(() => expect(close).toHaveFocus())

    await userEvent.keyboard('{Escape}')
    await expect(args.onClose).toHaveBeenCalledTimes(1)
    // Controlled: the story never passes `open={false}`, so it stays open.
    await expect(dialog).toHaveAttribute('open')

    await userEvent.click(close)
    await expect(args.onClose).toHaveBeenCalledTimes(2)
  },
}

/**
 * Issue #216 overlap: a rating's panel opens inside the verdict. Escape
 * closes that panel only. The next Escape closes the verdict.
 */
export const EscapeClosesARatingPanelFirst: Story = {
  args: {
    verdict: {
      status: 'success',
      envelope: {
        ...SHORT_SUCCESS,
        evidence: {
          ...SHORT_SUCCESS.evidence,
          method: 'elo',
          team_name: TEXAS_ELO.team_name,
          rating: TEXAS_ELO.rating,
          rating_breakdown: { entries: [], residual_contribution: 0 },
          elo_ledger: TEXAS_ELO.elo_ledger,
        },
      },
    },
  },
  play: async ({ canvasElement, args }) => {
    const dialog = within(canvasElement).getByRole('dialog', {
      name: 'The verdict',
    })
    const trigger = within(dialog).getByRole('button', { name: '1,661' })
    trigger.focus()
    await userEvent.keyboard('{Enter}')
    await expect(
      await within(dialog).findByRole('dialog', {
        name: 'Texas Elo rating, game by game',
      }),
    ).toBeVisible()

    await userEvent.keyboard('{Escape}')

    await waitFor(() =>
      expect(
        within(dialog).queryByRole('dialog', {
          name: 'Texas Elo rating, game by game',
        }),
      ).toBeNull(),
    )
    await expect(args.onClose).not.toHaveBeenCalled()
    await expect(dialog).toHaveAttribute('open')

    await userEvent.keyboard('{Escape}')
    await expect(args.onClose).toHaveBeenCalledTimes(1)
  },
}
