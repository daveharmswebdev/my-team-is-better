import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import { RatingDisclosureShell } from './RatingDisclosureShell'

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

const meta = {
  title: 'components/EvidenceReceipts/RatingDisclosureShell',
  component: RatingDisclosureShell,
  tags: ['autodocs'],
  args: {
    triggerLabel: '42',
    title: 'Example rating work',
    closeLabel: 'Close example',
    children: (
      <p>
        Any method&rsquo;s panel content goes here; the shell only owns the
        trigger, popover, modal and close rules.
      </p>
    ),
  },
  parameters: {
    layout: 'centered',
  },
} satisfies Meta<typeof RatingDisclosureShell>

export default meta

type Story = StoryObj<typeof meta>

/** Desktop: hover (or Tab + Enter) the value to open the popover. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.hover(canvas.getByRole('button', { name: '42' }))
    await expect(
      await canvas.findByRole('dialog', { name: 'Example rating work' }),
    ).toBeVisible()
  },
}

/** Touch: tap the value for a modal with a close button and a backdrop. */
export const TouchMode: Story = {
  decorators: [
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
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('button', { name: '42' }))
    const dialog = await canvas.findByRole('dialog')
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
  },
}
