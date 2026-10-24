import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { VerdictModal } from '../VerdictModal/VerdictModal'
import { RatingDisclosureShell } from './RatingDisclosureShell'

function mockMatchMedia(matches: boolean) {
  const mql = {
    matches,
    media: '',
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }
  vi.stubGlobal('matchMedia', vi.fn().mockReturnValue(mql))
}

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderShell(scroll?: 'panel' | 'region') {
  return render(
    <RatingDisclosureShell
      headingLevel={3}
      triggerLabel="42"
      title="Example rating work"
      closeLabel="Close example"
      scroll={scroll}
    >
      <p>Panel body</p>
    </RatingDisclosureShell>,
  )
}

describe('RatingDisclosureShell', () => {
  it('desktop: hover opens a dialog named by the title, holding the children; unhover closes it', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    renderShell()

    const trigger = screen.getByRole('button', { name: '42' })
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')

    await user.hover(trigger)
    const dialog = screen.getByRole('dialog', { name: 'Example rating work' })
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(trigger).toHaveAttribute('aria-controls', dialog.id)
    expect(
      within(dialog).getByRole('heading', { name: 'Example rating work' }),
    ).toBeInTheDocument()
    expect(within(dialog).getByText('Panel body')).toBeInTheDocument()
    // No close button on desktop.
    expect(within(dialog).queryByRole('button')).not.toBeInTheDocument()

    await user.unhover(trigger)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('touch: tap opens a modal with a focused close button; the backdrop and the close button both close it', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    renderShell('region')

    const trigger = screen.getByRole('button', { name: '42' })
    await user.click(trigger)
    let dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    const close = within(dialog).getByRole('button', { name: 'Close example' })
    expect(close).toHaveFocus()

    await user.click(close)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()

    await user.click(trigger)
    dialog = screen.getByRole('dialog')
    // The backdrop is the <dialog> itself, around the panel box inside it.
    await user.click(dialog)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keyboard: Enter opens it and Escape closes it back onto the trigger', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    renderShell()

    await user.tab()
    const trigger = screen.getByRole('button', { name: '42' })
    await user.keyboard('{Enter}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('titles the panel at the heading level its caller passes (issue #219)', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    renderShell()

    await user.hover(screen.getByRole('button', { name: '42' }))

    expect(
      within(screen.getByRole('dialog')).getByRole('heading', {
        level: 3,
        name: 'Example rating work',
      }),
    ).toBeInTheDocument()
  })

  describe('touch: a real modal (issue #216)', () => {
    /** A shell with two focusables in its body, after a button outside it. */
    function renderTouchShell() {
      mockMatchMedia(true)
      render(
        <>
          <button type="button">Behind the panel</button>
          <RatingDisclosureShell
            headingLevel={3}
            triggerLabel="42"
            title="Example rating work"
            closeLabel="Close example"
          >
            <a href="#first-game">First game</a>
            <button type="button">Last game</button>
          </RatingDisclosureShell>
        </>,
      )
      return screen.getByRole('button', { name: '42' })
    }

    it('opens in a native modal <dialog> (showModal), named by its title', async () => {
      const user = userEvent.setup()
      const trigger = renderTouchShell()

      await user.click(trigger)

      const dialog = screen.getByRole('dialog', { name: 'Example rating work' })
      expect(dialog.tagName).toBe('DIALOG')
      expect(dialog).toHaveAttribute('open')
      expect(trigger).toHaveAttribute('aria-controls', dialog.id)
    })

    it('Tab from the last focusable and Shift+Tab from the first stay inside the panel', async () => {
      const user = userEvent.setup()
      const trigger = renderTouchShell()
      await user.click(trigger)
      const dialog = screen.getByRole('dialog')
      const close = within(dialog).getByRole('button', {
        name: 'Close example',
      })
      const last = within(dialog).getByRole('button', { name: 'Last game' })
      expect(close).toHaveFocus()

      await user.tab({ shift: true })
      expect(last).toHaveFocus()

      await user.tab()
      expect(close).toHaveFocus()

      await user.tab()
      expect(
        within(dialog).getByRole('link', { name: 'First game' }),
      ).toHaveFocus()
      await user.tab()
      expect(last).toHaveFocus()
      await user.tab()
      expect(close).toHaveFocus()
      expect(screen.getByRole('dialog')).toBeInTheDocument()
    })

    it('one Escape runs the close path exactly once and returns focus to the trigger', async () => {
      const user = userEvent.setup()
      const trigger = renderTouchShell()
      await user.click(trigger)
      // Closing always ends by focusing the trigger, once per close.
      const refocus = vi.spyOn(trigger, 'focus')

      await user.keyboard('{Escape}')

      expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
      expect(refocus).toHaveBeenCalledTimes(1)
      expect(trigger).toHaveFocus()
    })

    it('inside the verdict modal, Escape closes only the panel; the next one closes the verdict', async () => {
      mockMatchMedia(true)
      const user = userEvent.setup()
      const onClose = vi.fn()
      render(
        <VerdictModal
          open
          title="The verdict"
          closeLabel="Close the verdict"
          onClose={onClose}
        >
          <RatingDisclosureShell
            headingLevel={3}
            triggerLabel="42"
            title="Example rating work"
            closeLabel="Close example"
          >
            <p>Panel body</p>
          </RatingDisclosureShell>
        </VerdictModal>,
      )
      const verdict = screen.getByRole('dialog', { name: 'The verdict' })
      const trigger = within(verdict).getByRole('button', { name: '42' })
      await user.click(trigger)
      expect(
        within(verdict).getByRole('dialog', { name: 'Example rating work' }),
      ).toBeInTheDocument()

      await user.keyboard('{Escape}')

      expect(
        screen.queryByRole('dialog', { name: 'Example rating work' }),
      ).not.toBeInTheDocument()
      expect(onClose).not.toHaveBeenCalled()
      expect(verdict).toHaveAttribute('open')
      expect(trigger).toHaveFocus()

      await user.keyboard('{Escape}')
      expect(onClose).toHaveBeenCalledTimes(1)
    })

    it('closing the panel by its close button never closes the verdict around it', async () => {
      mockMatchMedia(true)
      const user = userEvent.setup()
      const onClose = vi.fn()
      render(
        <VerdictModal
          open
          title="The verdict"
          closeLabel="Close the verdict"
          onClose={onClose}
        >
          <RatingDisclosureShell
            headingLevel={3}
            triggerLabel="42"
            title="Example rating work"
            closeLabel="Close example"
          >
            <p>Panel body</p>
          </RatingDisclosureShell>
        </VerdictModal>,
      )
      await user.click(screen.getByRole('button', { name: '42' }))

      await user.click(screen.getByRole('button', { name: 'Close example' }))

      expect(
        screen.queryByRole('dialog', { name: 'Example rating work' }),
      ).not.toBeInTheDocument()
      expect(onClose).not.toHaveBeenCalled()
    })
  })
})
