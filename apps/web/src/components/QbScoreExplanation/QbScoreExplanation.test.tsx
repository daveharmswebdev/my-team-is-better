import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { PlayerQbScoreComparisonOut } from '../../lib/api/types'
import {
  BRADY_VS_BARKLEY_QB_SCORE,
  BRADY_VS_MANNING_QB_SCORE,
  WARNER_VS_MCNAIR_QB_SCORE,
} from '../../lib/qbScoreFixtures'
import { QbScoreExplanation } from './QbScoreExplanation'

function renderExplanation(
  qbScore: PlayerQbScoreComparisonOut = BRADY_VS_MANNING_QB_SCORE,
) {
  return render(<QbScoreExplanation qbScore={qbScore} dataFirstSeason={1999} />)
}

/** Opens the explanation from the keyboard alone, and returns its region. */
async function openByKeyboard() {
  const user = userEvent.setup()
  const toggle = screen.getByRole('button', { name: 'How the QB score works' })
  await user.tab()
  expect(toggle).toHaveFocus()
  await user.keyboard('{Enter}')
  return screen.getByRole('region', { name: 'How the QB score works' })
}

/** One season's row in a player's season table. */
function seasonRow(region: HTMLElement, player: string, season: number) {
  const table = within(region).getByRole('table', {
    name: `${player}, season by season`,
  })
  const header = within(table).getByRole('rowheader', {
    name: new RegExp(`^${season}\\b`),
  })
  const row = header.closest('tr')
  if (row === null) throw new Error('no row')
  return row
}

describe('QbScoreExplanation (issue #459)', () => {
  it('starts closed, controlling a hidden region', () => {
    renderExplanation()
    const toggle = screen.getByRole('button', {
      name: 'How the QB score works',
    })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('opens from the keyboard, and closes again', async () => {
    renderExplanation()
    const region = await openByKeyboard()
    const toggle = screen.getByRole('button', {
      name: 'How the QB score works',
    })
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(toggle).toHaveAttribute('aria-controls', region.id)

    await userEvent.setup().keyboard(' ')
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region')).toBeNull()
  })

  it('shows the weights from the response, never typed in', async () => {
    renderExplanation()
    const region = await openByKeyboard()
    expect(region).toHaveTextContent(
      'Season score = 0.826 × passing EPA per dropback z + 0.174 × rushing EPA per play z',
    )
  })

  it('says how the weights were fitted', async () => {
    renderExplanation()
    const region = await openByKeyboard()
    expect(region).toHaveTextContent(
      "an OLS fit of next season's EPA per play on this season's two z-scores, 629 consecutive QB-season pairs, 1999–2025",
    )
  })

  it('states the qualifying rule, career, peak with its fill, and the 1999 floor, from the response', async () => {
    renderExplanation()
    const region = await openByKeyboard()
    expect(region).toHaveTextContent(
      'A season counts at 224 or more dropbacks (pass attempts plus sacks).',
    )
    expect(region).toHaveTextContent(
      "Career = the sum of every counting season's score",
    )
    expect(region).toHaveTextContent(
      'Peak = the average of his best 5 season scores. With fewer than 5 counting seasons, the empty slots are filled with 0, a league-average season.',
    )
    expect(region).toHaveTextContent(
      'The play-by-play starts in 1999, so nothing before 1999 is scored.',
    )
  })

  it("lists a qualifying season's z-scores, its score and its peak mark", async () => {
    renderExplanation()
    const region = await openByKeyboard()

    // Manning 1999: z 1.74 passing, -0.03 rushing, composite 1.43, not peak.
    const row = seasonRow(region, 'Peyton Manning', 1999)
    const cells = within(row).getAllByRole('cell')
    expect(cells[0]).toHaveTextContent('0.212')
    expect(cells[0]).toHaveTextContent('z 1.74')
    expect(cells[0]).toHaveTextContent('avg −0.006')
    expect(cells[0]).toHaveTextContent('SD 0.125')
    expect(cells[1]).toHaveTextContent('z −0.03')
    expect(cells[3]).toHaveTextContent('1.43')
    expect(within(row).getByRole('rowheader')).toHaveTextContent(
      '1999 546 dropbacks',
    )
  })

  it('marks the peak seasons', async () => {
    renderExplanation(WARNER_VS_MCNAIR_QB_SCORE)
    const region = await openByKeyboard()
    expect(
      within(seasonRow(region, 'Kurt Warner', 1999)).getByRole('rowheader'),
    ).toHaveTextContent('Peak')
    expect(region).toHaveTextContent(
      'Kurt Warner: 1 counting season. Career 2.25. Peak 0.45, with 4 of 5 slots filled with 0.',
    )
  })

  it('greys a non-qualifying season and says why', async () => {
    renderExplanation()
    const region = await openByKeyboard()
    // Brady 2000: 3 dropbacks.
    const row = seasonRow(region, 'Tom Brady', 2000)
    expect(row).toHaveAttribute('data-counted', 'false')
    expect(within(row).getAllByRole('cell')[3]).toHaveTextContent(
      "Didn't count: 3 dropbacks, under 224",
    )
    // No era numbers for a season that isn't judged.
    expect(within(row).getAllByRole('cell')[0]).not.toHaveTextContent('z ')
  })

  it('marks ANY/A as not scored', async () => {
    renderExplanation()
    const region = await openByKeyboard()
    const table = within(region).getByRole('table', {
      name: 'Tom Brady, season by season',
    })
    expect(
      within(table).getByRole('columnheader', { name: /ANY\/A/ }),
    ).toHaveTextContent('ANY/A (not scored)')
    expect(region).toHaveTextContent(
      "ANY/A (adjusted net yards per attempt) is there for context. It's not scored.",
    )
  })

  it('a QB with no counting season says so', async () => {
    renderExplanation(BRADY_VS_BARKLEY_QB_SCORE)
    const region = await openByKeyboard()
    expect(region).toHaveTextContent(
      'Matt Barkley: no counting season, so no score.',
    )
  })
})
