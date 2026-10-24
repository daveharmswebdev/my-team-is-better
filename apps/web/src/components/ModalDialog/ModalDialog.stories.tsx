import type { Meta, StoryObj } from '@storybook/react-vite'
import { useRef, useState } from 'react'
import { expect, fn, userEvent, waitFor, within } from 'storybook/test'
import { ModalDialog } from './ModalDialog'

const frame = {
  maxWidth: '22rem',
  margin: '20vh auto',
  padding: '1rem',
  background: 'var(--surface)',
  border: '1px solid var(--rule-strong)',
  borderRadius: 'var(--radius)',
}

/**
 * Story-only styles for the shared primitive: consumers pass their own
 * `className` (see `VerdictModal` and `RatingDisclosureShell`), so this one
 * only covers the viewport, dims the page and centres a plain frame.
 */
const css = `
  .storyModal {
    width: 100%;
    max-width: none;
    height: 100%;
    max-height: none;
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
  }
  .storyModal::backdrop { background: rgba(28, 26, 23, 0.45); }
`

function Demo({
  onClose,
  nested = false,
}: {
  onClose: () => void
  nested?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [innerOpen, setInnerOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const innerTriggerRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)
  const innerCloseRef = useRef<HTMLButtonElement>(null)

  function close() {
    onClose()
    setOpen(false)
    triggerRef.current?.focus()
  }
  function closeInner() {
    setInnerOpen(false)
    innerTriggerRef.current?.focus()
  }

  return (
    <>
      <style>{css}</style>
      <button ref={triggerRef} type="button" onClick={() => setOpen(true)}>
        Open the modal
      </button>
      <button type="button">Behind the modal</button>
      <ModalDialog
        open={open}
        onClose={close}
        initialFocusRef={closeRef}
        aria-label="Example modal"
        className="storyModal"
      >
        <div style={frame}>
          <button ref={closeRef} type="button" onClick={close}>
            Close
          </button>{' '}
          <a href="#example">A link</a>{' '}
          {nested ? (
            <button
              ref={innerTriggerRef}
              type="button"
              onClick={() => setInnerOpen(true)}
            >
              Open the inner modal
            </button>
          ) : (
            <button type="button">Last</button>
          )}
          {nested && (
            <ModalDialog
              open={innerOpen}
              onClose={closeInner}
              initialFocusRef={innerCloseRef}
              aria-label="Inner modal"
              className="storyModal"
            >
              <div style={frame}>
                <button ref={innerCloseRef} type="button" onClick={closeInner}>
                  Close inner
                </button>{' '}
                <button type="button">Inner last</button>
              </div>
            </ModalDialog>
          )}
        </div>
      </ModalDialog>
    </>
  )
}

const meta = {
  title: 'components/ModalDialog',
  component: Demo,
  tags: ['autodocs'],
  args: { onClose: fn() },
} satisfies Meta<typeof Demo>

export default meta

type Story = StoryObj<typeof meta>

/**
 * Open it, then Tab: focus wraps inside the modal and never reaches the page
 * behind. Escape closes it once and focus returns to the trigger.
 */
export const Default: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    const trigger = canvas.getByRole('button', { name: 'Open the modal' })
    const behind = canvas.getByRole('button', { name: 'Behind the modal' })
    await userEvent.click(trigger)
    const dialog = await canvas.findByRole('dialog', { name: 'Example modal' })
    const close = within(dialog).getByRole('button', { name: 'Close' })
    await waitFor(() => expect(close).toHaveFocus())
    // In the top layer, over a page made inert: nothing behind takes focus.
    await expect(dialog.matches(':modal')).toBe(true)
    behind.focus()
    await expect(behind).not.toHaveFocus()
    await expect(close).toHaveFocus()

    await userEvent.tab()
    await userEvent.tab()
    await expect(
      within(dialog).getByRole('button', { name: 'Last' }),
    ).toHaveFocus()
    await userEvent.tab()
    await expect(close).toHaveFocus()
    await userEvent.tab({ shift: true })
    await expect(
      within(dialog).getByRole('button', { name: 'Last' }),
    ).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(dialog).not.toHaveAttribute('open'))
    await expect(args.onClose).toHaveBeenCalledTimes(1)
    await expect(trigger).toHaveFocus()
  },
}

/**
 * A modal opened inside another stacks above it. Escape closes only the
 * inner one; the next Escape closes the outer one.
 */
export const Nested: Story = {
  args: { nested: true },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Open the modal' }),
    )
    const outer = await canvas.findByRole('dialog', { name: 'Example modal' })
    await userEvent.click(
      within(outer).getByRole('button', { name: 'Open the inner modal' }),
    )
    const inner = await within(outer).findByRole('dialog', {
      name: 'Inner modal',
    })
    await waitFor(() =>
      expect(
        within(inner).getByRole('button', { name: 'Close inner' }),
      ).toHaveFocus(),
    )

    await userEvent.tab()
    await userEvent.tab()
    await expect(
      within(inner).getByRole('button', { name: 'Close inner' }),
    ).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(inner).not.toHaveAttribute('open'))
    await expect(outer).toHaveAttribute('open')
    await expect(args.onClose).not.toHaveBeenCalled()
    await expect(
      within(outer).getByRole('button', { name: 'Open the inner modal' }),
    ).toHaveFocus()

    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(outer).not.toHaveAttribute('open'))
    await expect(args.onClose).toHaveBeenCalledTimes(1)
  },
}
