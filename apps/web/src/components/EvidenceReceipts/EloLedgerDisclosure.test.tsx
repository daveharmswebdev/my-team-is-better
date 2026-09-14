import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { EloLedgerOut } from '../../lib/api/types'
import { EloLedgerDisclosure } from './EloLedgerDisclosure'
import { TEXAS_ELO } from './eloLedgerFixture'

/** Stubs `window.matchMedia`: `true` is a coarse/touch pointer, `false` a hover-capable one. */
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

/**
 * What each Texas row must print, written out by hand from the fixture's own
 * fields at display precision (ratings/gap/shift 1 decimal, expectancy 3,
 * multiplier 2). Hard-coded on purpose: the test must not share the
 * component's formatting code, and nothing here is an Elo computation.
 */
const TEXAS_ROWS = [
  {
    header: 'Wk 2 · vs Ohio State · W 25–22',
    shift: '+22.8',
    total: 'now 1,522.8',
    work: '1,500.0 − 1,544.9 + 100 = gap +55.1 → win expectancy 0.579 → won by 3, multiplier 1.35 → 40 × 1.35 × (1 − 0.579) = +22.8',
  },
  {
    header: 'Wk 4 · at Texas Tech · W 52–17',
    shift: '+79.1',
    total: 'now 1,601.9',
    work: '1,522.8 − 1,453.6 − 100 = gap −30.8 → win expectancy 0.456 → won by 35, multiplier 3.63 → 40 × 3.63 × (1 − 0.456) = +79.1',
  },
  {
    header: 'Wk 5 · vs Oklahoma (neutral) · W 45–12',
    shift: '+48.2',
    total: 'now 1,650.1',
    work: '1,601.9 − 1,500.0 = gap +101.9 → win expectancy 0.643 → won by 33, multiplier 3.37 → 40 × 3.37 × (1 − 0.643) = +48.2',
  },
  {
    header: 'Wk 6 · at Baylor · T 21–21',
    shift: '−8.1',
    total: 'now 1,642.0',
    work: '1,650.1 − 1,455.1 − 100 = gap +95.0 → win expectancy 0.633 → tied, multiplier 1.52 → 40 × 1.52 × (½ − 0.633) = −8.1',
  },
  {
    header: 'Postseason · vs USC (neutral) · W 41–38',
    shift: '+19.4',
    total: 'now 1,661.4',
    work: '1,642.0 − 1,546.4 = gap +95.6 → win expectancy 0.634 → won by 3, multiplier 1.33 → 40 × 1.33 × (1 − 0.634) = +19.4',
  },
] as const

function renderTexas(ledger: EloLedgerOut = TEXAS_ELO.elo_ledger) {
  return render(
    <EloLedgerDisclosure
      teamName="Texas"
      rating={TEXAS_ELO.rating}
      ledger={ledger}
    />,
  )
}

async function openOnDesktop() {
  mockMatchMedia(false)
  const user = userEvent.setup()
  const trigger = screen.getByRole('button', { name: '1,661' })
  await user.hover(trigger)
  return { user, trigger, dialog: screen.getByRole('dialog') }
}

function gameItems(dialog: HTMLElement): HTMLElement[] {
  return within(
    within(dialog).getByRole('list', { name: 'Games, in order' }),
  ).getAllByRole('listitem')
}

describe('EloLedgerDisclosure', () => {
  it('(a) shows the rule, the start, every game in order with its own worked step, and a footer matching the trigger', async () => {
    mockMatchMedia(false)
    renderTexas()
    const { trigger, dialog } = await openOnDesktop()

    expect(trigger).toHaveTextContent('1,661')
    expect(dialog).toHaveAccessibleName('Texas Elo rating, game by game')
    expect(
      within(dialog).getByRole('heading', {
        name: 'Texas Elo rating, game by game',
      }),
    ).toBeInTheDocument()

    expect(
      within(dialog).getByText('The rule — same for every team'),
    ).toBeInTheDocument()
    for (const line of [
      'Gap = team rating − opponent rating, ± 100 for home field (0 at a neutral site)',
      'Win expectancy = 1 ÷ (10^(−gap ÷ 400) + 1)',
      "Margin multiplier = ln(max(margin, 1) + 1) × 2.2 ÷ (winner's gap × 0.001 + 2.2, floored at half of 2.2); a tie uses ln 2 × 2.2",
      'Rating change = 40 × multiplier × (result − win expectancy), where result is 1 for a win, ½ for a tie, 0 for a loss',
    ]) {
      expect(within(dialog).getByText(line)).toBeInTheDocument()
    }
    expect(
      within(dialog).getByRole('link', {
        name: "Arpad Elo's system, in the football form FiveThirtyEight published",
      }),
    ).toHaveAttribute('href', '/about')

    expect(
      within(dialog).getByText('Every team starts the season at 1,500'),
    ).toBeInTheDocument()

    const items = gameItems(dialog)
    expect(items).toHaveLength(TEXAS_ROWS.length)
    TEXAS_ROWS.forEach((row, index) => {
      const item = items[index] as HTMLElement
      expect(within(item).getByText(row.header)).toBeInTheDocument()
      expect(within(item).getByText(row.shift)).toBeInTheDocument()
      expect(within(item).getByText(row.total)).toBeInTheDocument()
      expect(within(item).getByText(row.work)).toBeInTheDocument()
    })

    expect(
      within(dialog).getByText('After 5 games: 1,661.4'),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(
        `The card rounds this to ${trigger.textContent}.`,
      ),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByText(
        "Figures are rounded for display; the engine keeps full precision, and every row's math checks out at full precision.",
      ),
    ).toBeInTheDocument()
  })

  it('(a) orders games by game_number, not by where they sit in the array', async () => {
    mockMatchMedia(false)
    renderTexas({
      ...TEXAS_ELO.elo_ledger,
      steps: [...TEXAS_ELO.elo_ledger.steps].reverse(),
    })
    const { dialog } = await openOnDesktop()

    const headers = gameItems(dialog).map(
      (item, index) =>
        within(item).getByText(TEXAS_ROWS[index]?.header ?? '').textContent,
    )
    expect(headers).toEqual(TEXAS_ROWS.map((row) => row.header))
  })

  it('(b) reads every constant from the response: k = 20 prints "20 ×"', async () => {
    mockMatchMedia(false)
    renderTexas({ ...TEXAS_ELO.elo_ledger, k: 20 })
    const { dialog } = await openOnDesktop()

    expect(
      within(dialog).getByText(
        'Rating change = 20 × multiplier × (result − win expectancy), where result is 1 for a win, ½ for a tie, 0 for a loss',
      ),
    ).toBeInTheDocument()
    expect(within(dialog).queryByText(/40 ×/)).not.toBeInTheDocument()
    expect(
      within(gameItems(dialog)[0] as HTMLElement).getByText(
        /→ 20 × 1\.35 × \(1 − 0\.579\) = \+22\.8$/,
      ),
    ).toBeInTheDocument()
  })

  it('(c) touch: a tap opens a modal, focus moves to its close button, and Escape closes it and refocuses the trigger', async () => {
    mockMatchMedia(true)
    const user = userEvent.setup()
    renderTexas()

    const trigger = screen.getByRole('button', { name: '1,661' })
    await user.click(trigger)

    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(within(dialog).getByRole('button', { name: /close/i })).toHaveFocus()

    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })

  it('(c) desktop: moving the pointer away closes the popover, and so does Escape', async () => {
    mockMatchMedia(false)
    renderTexas()
    const { user, trigger } = await openOnDesktop()

    await user.unhover(trigger)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.hover(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('desktop: tabbing from the trigger into the panel keeps it open, and tabbing out of the panel closes it', async () => {
    mockMatchMedia(false)
    const user = userEvent.setup()
    render(
      <>
        <EloLedgerDisclosure
          teamName="Texas"
          rating={TEXAS_ELO.rating}
          ledger={TEXAS_ELO.elo_ledger}
        />
        <button type="button">next field</button>
      </>,
    )

    await user.tab()
    const trigger = screen.getByRole('button', { name: '1,661' })
    expect(trigger).toHaveFocus()
    await user.keyboard('{Enter}')
    const dialog = screen.getByRole('dialog')

    await user.tab()
    expect(within(dialog).getByRole('link')).toHaveFocus()
    expect(screen.getByRole('dialog')).toBeInTheDocument()

    // The scrollable game list is itself focusable, so a keyboard user can scroll it.
    await user.tab()
    expect(
      within(dialog).getByRole('list', { name: 'Games, in order' }),
    ).toHaveFocus()

    await user.tab()
    expect(screen.getByRole('button', { name: 'next field' })).toHaveFocus()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('(d) row copy: neutral site, away tie and postseason each read the way they happened', async () => {
    mockMatchMedia(false)
    renderTexas()
    const { dialog } = await openOnDesktop()
    const items = gameItems(dialog)

    const neutral = items[2] as HTMLElement
    expect(within(neutral).getByText(/vs Oklahoma \(neutral\)/)).toBeVisible()
    const neutralWork = within(neutral).getByText(/= gap/).textContent ?? ''
    expect(neutralWork).not.toMatch(/[+−] 100/)
    expect(neutralWork.startsWith('1,601.9 − 1,500.0 = gap')).toBe(true)

    const awayTie = items[3] as HTMLElement
    expect(within(awayTie).getByText(/at Baylor/)).toBeInTheDocument()
    const awayTieWork = within(awayTie).getByText(/= gap/).textContent ?? ''
    expect(awayTieWork).toContain('− 100 = gap')
    expect(awayTieWork).toContain('→ tied, multiplier 1.52 →')

    const postseason = items[4] as HTMLElement
    expect(
      within(postseason).getByText(/^Postseason · vs USC \(neutral\)/),
    ).toBeInTheDocument()
    expect(within(postseason).queryByText(/Wk/)).not.toBeInTheDocument()

    expect(within(items[0] as HTMLElement).getByText(/won by 3/)).toBeVisible()
  })

  it('reads "lost by n" for a loss', async () => {
    mockMatchMedia(false)
    renderTexas({
      ...TEXAS_ELO.elo_ledger,
      steps: [
        {
          ...(TEXAS_ELO.elo_ledger.steps[0] as EloLedgerOut['steps'][number]),
          team_points: 17,
          opponent_points: 24,
          result: 'L',
        },
      ],
    })
    const { dialog } = await openOnDesktop()
    const item = gameItems(dialog)[0] as HTMLElement
    expect(within(item).getByText(/· L 17–24$/)).toBeInTheDocument()
    expect(
      within(item).getByText(/→ lost by 7, multiplier 1\.35 →/),
    ).toBeInTheDocument()
    expect(within(item).getByText(/× \(0 − 0\.579\)/)).toBeInTheDocument()
  })

  it('links the provenance line through the router when there is one', async () => {
    mockMatchMedia(false)
    render(
      <MemoryRouter>
        <EloLedgerDisclosure
          teamName="Texas"
          rating={TEXAS_ELO.rating}
          ledger={TEXAS_ELO.elo_ledger}
        />
      </MemoryRouter>,
    )
    const { dialog } = await openOnDesktop()
    expect(within(dialog).getByRole('link')).toHaveAttribute('href', '/about')
  })
})
