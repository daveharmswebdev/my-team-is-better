import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import {
  CAREER_WITH_NULL_STATS,
  KURT_WARNER_CAREER,
  WARNER_1999_POSTSEASON,
  WARNER_1999_REGULAR,
} from '../../lib/playerFixtures'
import { undercountNote } from '../../lib/playerStats'
import { PlayerCareerTable } from './PlayerCareerTable'

/** The cell of `row` under the column whose header reads `name`. */
function cellUnder(row: HTMLElement, name: string): HTMLElement {
  const headers = screen.getAllByRole('columnheader')
  const index = headers.findIndex((header) => header.textContent === name)
  expect(index, `no column named ${name}`).toBeGreaterThanOrEqual(0)
  const cell = row.querySelectorAll('th, td')[index]
  expect(cell).toBeDefined()
  return cell as HTMLElement
}

describe('PlayerCareerTable (issue #296)', () => {
  it('is named by its caption and has one body row per season line, in order', () => {
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[WARNER_1999_REGULAR, { ...WARNER_1999_REGULAR, season: 2000 }]}
        totals={KURT_WARNER_CAREER.regular_season}
      />,
    )

    const table = screen.getByRole('table', {
      name: 'Kurt Warner, regular season',
    })
    const [head, body, foot] = within(table).getAllByRole('rowgroup') as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ]
    expect(within(head).getAllByRole('row')).toHaveLength(1)
    const rows = within(body).getAllByRole('row')
    expect(
      rows.map((row) => within(row).getByRole('rowheader').textContent),
    ).toEqual(['1999', '2000'])
    expect(within(foot).getAllByRole('row')).toHaveLength(1)
  })

  it("prints a season line's teams, games, record and stats as sent", () => {
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[WARNER_1999_REGULAR]}
        totals={null}
      />,
    )

    const row = screen.getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(cellUnder(row, 'Teams')).toHaveTextContent('St. Louis Rams')
    expect(cellUnder(row, 'Games')).toHaveTextContent(/^15$/)
    expect(cellUnder(row, 'Starter record')).toHaveTextContent(/^13-3$/)
    expect(cellUnder(row, 'Starts')).toHaveTextContent(/^16$/)
    expect(cellUnder(row, 'Completions')).toHaveTextContent(/^297$/)
    expect(cellUnder(row, 'Attempts')).toHaveTextContent(/^455$/)
    expect(cellUnder(row, 'Passing yards')).toHaveTextContent(/^4,044$/)
    expect(cellUnder(row, 'Passing TDs')).toHaveTextContent(/^38$/)
    expect(cellUnder(row, 'Interceptions')).toHaveTextContent(/^11$/)
    expect(cellUnder(row, 'Rushing TDs')).toHaveTextContent(/^1$/)
  })

  it('joins several teams in the order sent', () => {
    render(
      <PlayerCareerTable
        caption="Two teams"
        lines={[
          {
            ...WARNER_1999_REGULAR,
            teams: ['New York Giants', 'Arizona Cardinals'],
          },
        ]}
        totals={null}
      />,
    )

    expect(
      screen.getByText('New York Giants, Arizona Cardinals'),
    ).toBeInTheDocument()
  })

  it('prints the career totals row from the API totals, naming how many seasons', () => {
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[WARNER_1999_REGULAR]}
        totals={{
          ...KURT_WARNER_CAREER.regular_season!,
          seasons: 3,
          games: 40,
        }}
      />,
    )

    const header = screen.getByRole('rowheader', { name: 'Career, 3 seasons' })
    const row = header.parentElement as HTMLElement
    expect(within(row).getByText('40')).toBeInTheDocument()
    expect(within(row).getByText('4,044')).toBeInTheDocument()
  })

  it('says "1 season" for a one-season career', () => {
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[WARNER_1999_REGULAR]}
        totals={KURT_WARNER_CAREER.regular_season}
      />,
    )

    expect(
      screen.getByRole('rowheader', { name: 'Career, 1 season' }),
    ).toBeInTheDocument()
  })

  it('discloses missing stat lines on the affected line only', () => {
    render(
      <PlayerCareerTable
        caption="Both"
        lines={[WARNER_1999_REGULAR, WARNER_1999_POSTSEASON]}
        totals={null}
      />,
    )

    const [affected, clean] = screen
      .getAllByRole('rowheader')
      .map((header) => header.parentElement as HTMLElement) as [
      HTMLElement,
      HTMLElement,
    ]
    expect(within(affected).getByText(undercountNote(1))).toBeInTheDocument()
    expect(within(clean).queryByText(/undercount/i)).not.toBeInTheDocument()
    expect(screen.getAllByText(/undercount/i)).toHaveLength(1)
  })

  it('shows null stats and null games as "not recorded"', () => {
    const [line] = CAREER_WITH_NULL_STATS.seasons
    render(
      <PlayerCareerTable
        caption="Unrecorded"
        lines={[line!]}
        totals={CAREER_WITH_NULL_STATS.regular_season}
      />,
    )

    const row = screen.getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(cellUnder(row, 'Games')).toHaveTextContent(/^not recorded$/)
    expect(cellUnder(row, 'Passing TDs')).toHaveTextContent(/^not recorded$/)
    expect(cellUnder(row, 'Passing yards')).toHaveTextContent(/^1,210$/)
    const totals = screen.getByRole('rowheader', { name: 'Career, 1 season' })
      .parentElement as HTMLElement
    expect(within(totals).getAllByText('not recorded').length).toBeGreaterThan(
      0,
    )
  })

  it('prints no totals row when the API sent none', () => {
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[WARNER_1999_REGULAR]}
        totals={null}
      />,
    )

    expect(
      screen.queryByRole('rowheader', { name: /career/i }),
    ).not.toBeInTheDocument()
  })

  it('shows no sack columns (#298)', () => {
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[WARNER_1999_REGULAR]}
        totals={KURT_WARNER_CAREER.regular_season}
      />,
    )

    for (const header of screen.getAllByRole('columnheader')) {
      expect(header.textContent).not.toMatch(/sack/i)
    }
    expect(screen.queryByText('-176')).not.toBeInTheDocument()
    expect(screen.queryByText('26')).not.toBeInTheDocument()
  })
})
