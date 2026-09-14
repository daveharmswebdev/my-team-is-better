import { fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { VerdictModal } from './VerdictModal'

/**
 * jsdom has no `showModal()` (see `src/test/setup.ts`), so these tests cover
 * what the component itself decides: what renders, its name, and which close
 * requests reach `onClose`. The top layer, the inert page and the focus trap
 * are the browser's, and are checked in Storybook and the e2e specs.
 */
function renderModal({
  open = true,
  onClose = vi.fn(),
  strict = false,
}: { open?: boolean; onClose?: () => void; strict?: boolean } = {}) {
  const tree = (
    <VerdictModal
      open={open}
      title="The verdict"
      closeLabel="Close the verdict"
      onClose={onClose}
    >
      <p>Texas, full stop.</p>
      <button type="button">Share this verdict</button>
    </VerdictModal>
  )
  const view = render(strict ? <StrictMode>{tree}</StrictMode> : tree)
  return { ...view, onClose }
}

describe('VerdictModal (issue #198)', () => {
  it('renders its children inside a dialog named by its title when open', () => {
    renderModal()

    const dialog = screen.getByRole('dialog', { name: 'The verdict' })
    expect(within(dialog).getByText('Texas, full stop.')).toBeInTheDocument()
    expect(dialog).toHaveAttribute('open')
  })

  it('renders no dialog and none of its children when closed', () => {
    renderModal({ open: false })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.queryByText('Texas, full stop.')).not.toBeInTheDocument()
  })

  it('moves focus to its close button on open, even under StrictMode', () => {
    renderModal({ strict: true })

    expect(
      screen.getByRole('button', { name: 'Close the verdict' }),
    ).toHaveFocus()
  })

  it('shows "Close" as the close button\'s visible text, inside its accessible name', () => {
    renderModal()

    const close = screen.getByRole('button', { name: 'Close the verdict' })
    expect(close).toHaveTextContent('Close')
  })

  it('calls onClose once when the close button is clicked', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.click(screen.getByRole('button', { name: 'Close the verdict' }))

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('calls onClose once on Escape', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal()

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not call onClose on Escape while it is closed', async () => {
    const user = userEvent.setup()
    const { onClose } = renderModal({ open: false })

    await user.keyboard('{Escape}')

    expect(onClose).not.toHaveBeenCalled()
  })

  /**
   * A rating's show-your-work panel (`RatingDisclosureShell`) opens as its
   * own `role="dialog"` inside the verdict, and closes itself on Escape. That
   * Escape belongs to the panel: it must not close the verdict too (#216).
   */
  it('leaves Escape to a dialog open inside it, without closing', () => {
    const onClose = vi.fn()
    render(
      <VerdictModal
        open
        title="The verdict"
        closeLabel="Close the verdict"
        onClose={onClose}
      >
        <div role="dialog" aria-label="Texas rating breakdown">
          <button type="button">Inside the panel</button>
        </div>
      </VerdictModal>,
    )

    fireEvent.keyDown(
      screen.getByRole('button', { name: 'Inside the panel' }),
      { key: 'Escape' },
    )

    expect(onClose).not.toHaveBeenCalled()
  })

  it('calls onClose for a close request that is not a key press (the "cancel" event)', () => {
    const { onClose } = renderModal()

    const cancel = new Event('cancel', { cancelable: true })
    screen.getByRole('dialog').dispatchEvent(cancel)

    expect(onClose).toHaveBeenCalledTimes(1)
    // The parent's `open` prop decides; the browser must not close it itself.
    expect(cancel.defaultPrevented).toBe(true)
  })

  it('calls onClose if the browser closes it on its own', () => {
    const { onClose } = renderModal()

    ;(screen.getByRole('dialog') as HTMLDialogElement).close()

    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('does not call onClose when the parent closes it', () => {
    const { onClose, rerender } = renderModal()

    rerender(
      <VerdictModal
        open={false}
        title="The verdict"
        closeLabel="Close the verdict"
        onClose={onClose}
      >
        <p>Texas, full stop.</p>
      </VerdictModal>,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(onClose).not.toHaveBeenCalled()
  })
})
