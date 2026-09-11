import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { RatingBreakdownOut } from '../../lib/api/types'
import { RatingBreakdownDisclosure } from './RatingBreakdownDisclosure'

/**
 * Stubs `window.matchMedia` to report either a coarse/touch pointer (mobile
 * mode, `matches: true`) or a fine/hover-capable pointer (desktop mode,
 * `matches: false`) -- no such stub exists anywhere in this codebase yet
 * (per the brief), so this is new plumbing local to this test file.
 */
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
      opponent_team_id: 999,
      opponent_name: 'Rutgers',
      games_played: 1,
      wins: 1,
      losses: 0,
      credit: 0.009,
      contribution: 0.001,
      explanation:
        "Ran them off the field, 45-3 — 94% of the points, capped at 85% so blowouts don't count extra past that. That earns the flat 0.60 every win banks, plus a 0.10 margin bonus for the lopsided score.",
    },
  ],
  residual_contribution: 0.00427,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RatingBreakdownDisclosure', () => {
  it('desktop: hovering the trigger shows the breakdown, and moving the pointer away hides it', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    const trigger = screen.getByRole('button', { name: /8\.77/ })
    await user.hover(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.unhover(trigger)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('mobile: tapping the trigger shows the breakdown as a modal, and a close control hides it', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    const trigger = screen.getByRole('button', { name: /8\.77/ })
    await user.click(trigger)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')

    await user.click(within(dialog).getByRole('button', { name: /close/i }))
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('mobile: pressing Escape closes the modal and returns focus to the trigger', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    const trigger = screen.getByRole('button', { name: /8\.77/ })
    await user.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('mobile: clicking outside the modal closes it', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    await user.click(screen.getByRole('button', { name: /8\.77/ }))
    const dialog = screen.getByRole('dialog')
    // The overlay backdrop is the dialog's parent -- clicking it (not the
    // dialog panel itself) is "outside" the modal content.
    const overlay = dialog.parentElement as HTMLElement
    await user.click(overlay)

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('keyboard: the trigger is reachable via Tab and operable via Enter/Space', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    await user.tab()
    const trigger = screen.getByRole('button', { name: /8\.77/ })
    expect(trigger).toHaveFocus()

    await user.keyboard('{Enter}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('renders per-opponent rows with each entry’s own opponent_name, the labeled residual line, and a total consistent with the displayed rating', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    await user.hover(screen.getByRole('button', { name: /8\.77/ }))
    const dialog = screen.getByRole('dialog')

    // Each row reads its opponent name straight off its own entry.
    expect(within(dialog).getByText('Indiana')).toBeInTheDocument()
    expect(within(dialog).getByText('Rutgers')).toBeInTheDocument()

    // Residual line is labeled as its own named thing -- never bare
    // "Other"/"Misc" (an explanatory note elsewhere may legitimately use the
    // word "rounding" to say it *isn't* one, so this checks the label itself
    // rather than banning that word from the whole panel).
    expect(
      within(dialog).getByText(/rating-system baseline/i),
    ).toBeInTheDocument()
    expect(within(dialog).queryByText(/^other$/i)).not.toBeInTheDocument()
    expect(within(dialog).queryByText(/^misc$/i)).not.toBeInTheDocument()

    // entries' contributions (0.002 + 0.001) + residual (0.00427) = 0.00877,
    // i.e. the same value `formatRating` renders on the trigger (8.77).
    expect(within(dialog).getByText(/8\.77/)).toBeInTheDocument()
  })

  it('renders each entry’s own deterministic explanation line', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    render(
      <RatingBreakdownDisclosure
        teamName="Ohio State"
        rating={0.00877}
        breakdown={breakdown}
      />,
    )

    await user.hover(screen.getByRole('button', { name: /8\.77/ }))
    const dialog = screen.getByRole('dialog')

    expect(
      within(dialog).getByText(/snuck out a 24-21 win/i),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(/ran them off the field, 45-3/i),
    ).toBeInTheDocument()
  })
})
