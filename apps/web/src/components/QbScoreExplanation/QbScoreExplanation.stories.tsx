import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import {
  BRADY_VS_BARKLEY_QB_SCORE,
  BRADY_VS_MANNING_QB_SCORE,
  WARNER_VS_MCNAIR_QB_SCORE,
} from '../../lib/qbScoreFixtures'
import { QbScoreExplanation } from './QbScoreExplanation'

/** How the QB score was got (issue #459), on real API payloads. */
const meta = {
  title: 'components/QbScoreExplanation',
  component: QbScoreExplanation,
  tags: ['autodocs'],
  args: {
    qbScore: BRADY_VS_MANNING_QB_SCORE,
    dataFirstSeason: 1999,
  },
} satisfies Meta<typeof QbScoreExplanation>

export default meta

type Story = StoryObj<typeof meta>

async function open(canvasElement: HTMLElement) {
  const canvas = within(canvasElement)
  const toggle = canvas.getByRole('button', { name: 'How the QB score works' })
  toggle.focus()
  await userEvent.keyboard('{Enter}')
  await expect(toggle).toHaveAttribute('aria-expanded', 'true')
  return canvas.getByRole('region', { name: 'How the QB score works' })
}

/** Shut: a single button. */
export const Closed: Story = {}

/** Brady and Manning, every season: Brady's 3-dropback 2000 greyed. */
export const Open: Story = {
  play: async ({ canvasElement }) => {
    const region = await open(canvasElement)
    await expect(region).toHaveTextContent(
      "Didn't count: 3 dropbacks, under 224",
    )
  },
}

/** One counting season each, peak slots filled with league average. */
export const OneSeasonEach: Story = {
  args: { qbScore: WARNER_VS_MCNAIR_QB_SCORE },
  play: async ({ canvasElement }) => {
    const region = await open(canvasElement)
    await expect(region).toHaveTextContent('with 4 of 5 slots filled with 0')
  },
}

/** A QB with no counting season at all (Matt Barkley). */
export const NoCountingSeason: Story = {
  args: { qbScore: BRADY_VS_BARKLEY_QB_SCORE },
  play: async ({ canvasElement }) => {
    const region = await open(canvasElement)
    await expect(region).toHaveTextContent(
      'Matt Barkley: no counting season, so no score.',
    )
  },
}
