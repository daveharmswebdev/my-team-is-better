import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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
    await user.click(dialog.parentElement as HTMLElement)
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
})
