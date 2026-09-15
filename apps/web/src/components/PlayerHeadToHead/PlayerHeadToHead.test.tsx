import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PlayerHeadToHeadOut } from '../../lib/api/types'
import {
  HEAD_TO_HEAD_WITH_UNRECORDED_STATS,
  NEVER_MET_COMPARISON,
  WARNER_VS_MCNAIR,
} from '../../lib/playerFixtures'
import { PlayerHeadToHead } from './PlayerHeadToHead'

function renderHeadToHead(headToHead: PlayerHeadToHeadOut) {
  render(
    <PlayerHeadToHead
      aName="Kurt Warner"
      bName="Steve McNair"
      headToHead={headToHead}
    />,
  )
}

describe('PlayerHeadToHead (issue #301)', () => {
  it("states a's record against b, naming both players", () => {
    renderHeadToHead(WARNER_VS_MCNAIR.regular_season_head_to_head)

    expect(
      screen.getByText("Kurt Warner's record against Steve McNair: 0-1"),
    ).toBeInTheDocument()
  })

  it('lists each game with its season, week and date, both teams and points, and each passing line', () => {
    renderHeadToHead(WARNER_VS_MCNAIR.regular_season_head_to_head)

    const list = screen.getByRole('list', { name: 'Regular-season games' })
    const [game] = within(list).getAllByRole('listitem')
    expect(game).toBeDefined()
    const item = within(game!)
    expect(
      item.getByText('1999 season · week 8 · Oct 31, 1999'),
    ).toBeInTheDocument()
    expect(
      item.getByText('St. Louis Rams 21, Tennessee Titans 24'),
    ).toBeInTheDocument()
    expect(
      item.getByText('Kurt Warner: 328 passing yards, 3 TDs, 0 INTs'),
    ).toBeInTheDocument()
    expect(
      item.getByText('Steve McNair: 186 passing yards, 2 TDs, 0 INTs'),
    ).toBeInTheDocument()
  })

  it('shows the playoff record and game', () => {
    renderHeadToHead(WARNER_VS_MCNAIR.postseason_head_to_head)

    expect(
      screen.getByText("Kurt Warner's record against Steve McNair: 1-0"),
    ).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Playoff games' })
    expect(
      within(list).getByText('St. Louis Rams 23, Tennessee Titans 16'),
    ).toBeInTheDocument()
    expect(
      within(list).getByText('Steve McNair: 214 passing yards, 0 TDs, 0 INTs'),
    ).toBeInTheDocument()
  })

  it('reads a missing stat line as "not recorded", never 0', () => {
    renderHeadToHead(HEAD_TO_HEAD_WITH_UNRECORDED_STATS)

    const [first, second] = screen.getAllByRole('listitem')
    expect(
      within(first!).getByText('Kurt Warner: not recorded'),
    ).toBeInTheDocument()
    expect(first).not.toHaveTextContent(/Kurt Warner: 0/)
    expect(
      within(second!).getByText(
        'Steve McNair: 186 passing yards, TDs not recorded, 0 INTs',
      ),
    ).toBeInTheDocument()
  })

  it('falls back to the date, or the season alone, when the week is missing; and shows ties', () => {
    renderHeadToHead(HEAD_TO_HEAD_WITH_UNRECORDED_STATS)

    const [first, second] = screen.getAllByRole('listitem')
    expect(
      within(first!).getByText('1999 season · Oct 31, 1999'),
    ).toBeInTheDocument()
    expect(within(second!).getByText('2000 season')).toBeInTheDocument()
    expect(
      screen.getByText("Kurt Warner's record against Steve McNair: 1-0-1"),
    ).toBeInTheDocument()
  })

  it('says plainly when the two never started against each other', () => {
    renderHeadToHead(NEVER_MET_COMPARISON.postseason_head_to_head)

    expect(
      screen.getByText(
        'Kurt Warner and Steve McNair never started against each other in the playoffs.',
      ),
    ).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.queryByText(/record against/)).not.toBeInTheDocument()
  })
})
