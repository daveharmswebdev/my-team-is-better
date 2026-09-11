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
      games_played: 1,
      wins: 1,
      losses: 0,
      credit: 0.018,
      contribution: 0.002,
    },
    {
      opponent_team_id: 127,
      games_played: 1,
      wins: 1,
      losses: 0,
      credit: 0.021,
      contribution: 0.00227,
    },
    {
      opponent_team_id: 999,
      games_played: 1,
      wins: 0,
      losses: 1,
      credit: -0.004,
      contribution: -0.0004,
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
    opponentNames: { 84: 'Indiana', 127: 'Michigan State' },
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

/** Same data with no `opponentNames` supplied -- every row falls back to the visible numeric id. */
export const NoOpponentNamesResolved: Story = {
  args: {
    opponentNames: {},
  },
}

/**
 * Forces touch/coarse-pointer mode (no real touch device needed) -- click
 * the rating value here to see it render as a full tap-triggered modal
 * (with a close button and backdrop) instead of the desktop hover popover.
 */
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
