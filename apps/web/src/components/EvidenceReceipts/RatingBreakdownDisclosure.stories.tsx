import type { Meta, StoryObj } from '@storybook/react-vite'
import type { RatingBreakdownOut } from '../../lib/api/types'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'

function touchMatchMediaStub(query: string): MediaQueryList {
  return {
    matches: true,
    media: query,
    onchange: null,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    dispatchEvent: () => false,
  } as MediaQueryList
}

const breakdown: RatingBreakdownOut = {
  entries: [
    {
      opponent_team_id: 84,
      opponent_name: 'Indiana',
      games_played: 1,
      wins: 1,
      losses: 0,
      credit: 0.018,
      contribution: 0.002,
      explanation:
        "Snuck out a 24-21 win — 53% of the points, barely above even. That's the flat 0.60 every win banks, plus just a 0.01 margin bonus.",
    },
    {
      opponent_team_id: 127,
      opponent_name: 'Michigan State',
      games_played: 1,
      wins: 1,
      losses: 0,
      credit: 0.021,
      contribution: 0.00227,
      explanation:
        "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
    },
    {
      opponent_team_id: 999,
      opponent_name: 'Rutgers',
      games_played: 1,
      wins: 0,
      losses: 1,
      credit: -0.004,
      contribution: -0.0004,
      explanation:
        'Got run over, 3-52 — 5% of the points, clamped at the 15% floor. Still banks the flat 0.05 every loss keeps, nobody walks away with zero, but no margin bonus at that end of the scale.',
    },
  ],
  // Real, not negligible -- typically ~47-53% of a team's rating (Keener's
  // connectivity regularizer + the credit matrix's sub-1 dominant
  // eigenvalue), so this story intentionally shows it as the largest single
  // line rather than a token remainder. Entries (0.002 + 0.00227 - 0.0004)
  // + this residual sum exactly to `rating` (0.00877), same as the footer
  // total this component renders.
  residual_contribution: 0.0049,
}

const meta = {
  title: 'components/EvidenceReceipts/RatingBreakdownDisclosure',
  component: RatingBreakdownDisclosure,
  tags: ['autodocs'],
  args: {
    teamName: 'Ohio State',
    rating: 0.00877,
    breakdown,
  },
  parameters: {
    // The trigger renders inline; give it some breathing room so the
    // popover/modal has somewhere to open into in the docs canvas.
    layout: 'centered',
  },
} satisfies Meta<typeof RatingBreakdownDisclosure>

export default meta

type Story = StoryObj<typeof meta>

/**
 * Default desktop rendering. Hover (or Tab to focus) the rating value to
 * open the popover; move the pointer away (or Tab off) to close it.
 */
export const Default: Story = {}

/**
 * Forces touch/coarse-pointer mode (no real touch device needed) -- click
 * the rating value here to see it render as a full tap-triggered modal
 * (with a close button and backdrop) instead of the desktop hover popover.
 */
/**
 * Covers the four representative `explanation` templates (issue #37) in one
 * panel, using the exact wording the engine layer produces: a blowout win, a
 * close win, a blowout loss, and a repeat matchup (two games against the same
 * opponent, each with its own margin bonus). Hover the rating value to see
 * each opponent row's own explanatory line beneath its numbers.
 */
export const ExplanationVariants: Story = {
  args: {
    teamName: 'Ohio State',
    rating: 0.0195,
    breakdown: {
      entries: [
        {
          opponent_team_id: 1,
          opponent_name: 'Rutgers',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.031,
          contribution: 0.006,
          explanation:
            "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
        },
        {
          opponent_team_id: 2,
          opponent_name: 'Penn State',
          games_played: 1,
          wins: 1,
          losses: 0,
          credit: 0.02,
          contribution: 0.0025,
          explanation:
            "Snuck out a 24-21 win — 53% of the points, barely above even. That's the flat 0.60 every win banks, plus just a 0.01 margin bonus.",
        },
        {
          opponent_team_id: 3,
          opponent_name: 'Michigan',
          games_played: 1,
          wins: 0,
          losses: 1,
          credit: -0.008,
          contribution: -0.001,
          explanation:
            'Got run over, 3-52 — 5% of the points, clamped at the 15% floor. Still banks the flat 0.05 every loss keeps, nobody walks away with zero, but no margin bonus at that end of the scale.',
        },
        {
          opponent_team_id: 4,
          opponent_name: 'Indiana',
          games_played: 2,
          wins: 2,
          losses: 0,
          credit: 0.028,
          contribution: 0.0037,
          explanation:
            "Swept them twice, 24-17 and 38-13 — the flat 0.60 win baseline both times, but the second game's bigger share (75% vs. 59%) earned a bigger margin bonus (0.07 vs. 0.03).",
        },
      ],
      residual_contribution: 0.0083,
    },
  },
}

export const TouchMode: Story = {
  decorators: [
    // Forces `window.matchMedia` to report a coarse/touch pointer for this
    // one story's initial render (`RatingBreakdownDisclosure` reads it at
    // mount time), then restores the original after this tick -- once React
    // has committed the mount and run its effects, which read `matchMedia`
    // again to subscribe to future changes. Calling `Story()` directly
    // (rather than rendering `<Story />` and restoring in an effect) keeps
    // the mock installed for that synchronous initial render; a plain
    // decorator function (not a capitalized component) also sidesteps
    // `react-hooks/immutability`, which otherwise forbids mutating an
    // outer-scope binding from inside a component's render body -- this is
    // Storybook-demo-only, never part of the shipped component.
    (Story) => {
      const original = window.matchMedia
      window.matchMedia = touchMatchMediaStub
      const rendered = Story()
      setTimeout(() => {
        window.matchMedia = original
      }, 0)
      return rendered
    },
  ],
}
