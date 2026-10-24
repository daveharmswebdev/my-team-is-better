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
    headingLevel: 3,
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
    const trigger = canvas.getByRole('button', { name: '42' })

    /**
     * Opens the panel the way Safari and iOS do on a tap: the trigger is
     * clicked but never focused (issue #216). The browser's own focus
     * restore then has nothing to go back to, so the trigger only gets focus
     * back if the shell gives it, after the modal has closed.
     */
    async function openWithoutFocus() {
      trigger.blur()
      trigger.click()
      const dialog = await canvas.findByRole('dialog')
      await expect(trigger).not.toHaveFocus()
      return dialog
    }

    let dialog = await openWithoutFocus()
    await expect(dialog).toHaveAttribute('aria-modal', 'true')
    // A real modal (issue #216): top layer, Tab kept inside, one Escape.
    await expect(dialog.matches(':modal')).toBe(true)
    const close = within(dialog).getByRole('button', { name: 'Close example' })
    await expect(close).toHaveFocus()
    await userEvent.tab()
    await expect(close).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(trigger).toHaveFocus()

    dialog = await openWithoutFocus()
    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Close example' }),
    )
    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(trigger).toHaveFocus()

    dialog = await openWithoutFocus()
    // The backdrop: the <dialog> itself, around the panel.
    await userEvent.click(dialog)
    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(trigger).toHaveFocus()
  },
}
