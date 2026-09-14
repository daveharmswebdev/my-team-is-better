import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import type { EloLedgerOut } from '../../lib/api/types'
import { EloLedgerDisclosure } from './EloLedgerDisclosure'
import { TEXAS_ELO } from './eloLedgerFixture'

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

/**
 * Layout-only: Texas's real steps repeated three times and renumbered
 * 1..15, so the game list is long enough to scroll. The chain of ratings
 * does not continue across repeats -- this exists to show that only the list
 * scrolls, never as data.
 */
const longSeason: EloLedgerOut = {
  ...TEXAS_ELO.elo_ledger,
  steps: [0, 1, 2].flatMap((repeat) =>
    TEXAS_ELO.elo_ledger.steps.map((step, index) => ({
      ...step,
      game_number: repeat * TEXAS_ELO.elo_ledger.steps.length + index + 1,
    })),
  ),
}

/**
 * The long-season layout contract: the game list is the scroll container and
 * really overflows, the dialog itself does not scroll, and the rule heading
 * and the footer sit inside the dialog's visible box.
 */
async function expectOnlyTheListScrolls(dialog: HTMLElement) {
  const list = within(dialog).getByRole('list', { name: 'Games, in order' })
  await expect(getComputedStyle(list).overflowY).toBe('auto')
  await expect(list.scrollHeight).toBeGreaterThan(list.clientHeight)
  await expect(dialog.scrollHeight).toBeLessThanOrEqual(dialog.clientHeight)
  const box = dialog.getBoundingClientRect()
  for (const el of [
    within(dialog).getByText('The rule — same for every team'),
    within(dialog).getByText('After 15 games: 1,661.4'),
  ]) {
    const rect = el.getBoundingClientRect()
    await expect(rect.top).toBeGreaterThanOrEqual(box.top)
    await expect(rect.bottom).toBeLessThanOrEqual(box.bottom)
  }
}

const meta = {
  title: 'components/EvidenceReceipts/EloLedgerDisclosure',
  component: EloLedgerDisclosure,
  tags: ['autodocs'],
  args: {
    teamName: TEXAS_ELO.team_name,
    rating: TEXAS_ELO.rating,
    ledger: TEXAS_ELO.elo_ledger,
  },
  parameters: {
    layout: 'padded',
  },
} satisfies Meta<typeof EloLedgerDisclosure>

export default meta

type Story = StoryObj<typeof meta>

/** Forces a coarse/touch pointer for the initial render (see RatingBreakdownDisclosure's TouchMode). */
function touchDecorator(Story: () => ReturnType<NonNullable<Story['render']>>) {
  const original = window.matchMedia
  window.matchMedia = touchMatchMediaStub
  const rendered = Story()
  setTimeout(() => {
    window.matchMedia = original
  }, 0)
  return rendered
}

/**
 * Texas 2005, engine-true: hover the rating to see the rule, the start, all
 * five games (home, away, neutral, an away tie, a bowl) with each game's own
 * numbers plugged in, and the rating the card rounds.
 */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.hover(canvas.getByRole('button', { name: '1,661' }))
    const dialog = await canvas.findByRole('dialog', {
      name: 'Texas Elo rating, game by game',
    })
    await expect(
      within(dialog).getByText('The card rounds this to 1,661.'),
    ).toBeVisible()
  },
}

/**
 * A long season: the rule at the top and the footer at the bottom stay in
 * view, and only the game list scrolls.
 */
export const LongSeason: Story = {
  args: { ledger: longSeason },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.hover(canvas.getByRole('button', { name: '1,661' }))
    const dialog = await canvas.findByRole('dialog')
    await expect(
      within(dialog).getByText('The rule — same for every team'),
    ).toBeVisible()
    await expectOnlyTheListScrolls(dialog)
  },
}

/** Touch: tap the rating for a modal with a close button and a backdrop. */
export const TouchMode: Story = {
  decorators: [touchDecorator],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('button', { name: '1,661' }))
    const dialog = await canvas.findByRole('dialog')
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    await expect(
      within(dialog).getByRole('button', { name: /close/i }),
    ).toHaveFocus()
  },
}

/** Touch with a long season: in the modal too, only the game list scrolls. */
export const TouchModeLongSeason: Story = {
  args: { ledger: longSeason },
  decorators: [touchDecorator],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('button', { name: '1,661' }))
    const dialog = await canvas.findByRole('dialog')
    await expectOnlyTheListScrolls(dialog)
  },
}
