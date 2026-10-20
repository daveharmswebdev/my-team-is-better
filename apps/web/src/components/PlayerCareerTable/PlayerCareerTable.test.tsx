import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PlayerStatsOut } from '../../lib/api/types'
import {
  CAREER_WITH_NULL_STATS,
  EDGERRIN_JAMES_CAREER,
  KURT_WARNER_CAREER,
  MARVIN_HARRISON_CAREER,
  OLINDO_MARE_CAREER,
  TJ_WATT_CAREER,
  TOBY_GOWIN_CAREER,
  WARNER_1999_POSTSEASON,
  WARNER_1999_REGULAR,
} from '../../lib/playerFixtures'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
  undercountNote,
} from '../../lib/playerStats'
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

  /**
   * Issue #352: the columns are the stat groups the player recorded. A
   * quarterback keeps passing and rushing, now with rushing first downs and
   * fumbles lost; one who also caught a pass gets receiving too.
   */
  it('gives a quarterback passing and rushing, and receiving when he caught a pass', () => {
    const line = {
      ...WARNER_1999_REGULAR,
      stats: {
        ...WARNER_1999_REGULAR.stats,
        receptions: 1,
        receiving_yards: 9,
      },
    }
    render(
      <PlayerCareerTable
        caption="Kurt Warner, regular season"
        lines={[line]}
        totals={{ ...KURT_WARNER_CAREER.regular_season!, stats: line.stats }}
      />,
    )

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      'Season',
      'Teams',
      'Games',
      'Starter record',
      'Starts',
      'Completions',
      'Attempts',
      'Passing yards',
      'Passing TDs',
      'Interceptions',
      'Carries',
      'Rushing yards',
      'Rushing TDs',
      'Rushing first downs',
      'Rushing fumbles lost',
      'Receptions',
      'Receiving yards',
      'Receiving TDs',
    ])
    const row = screen.getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(cellUnder(row, 'Rushing first downs')).toHaveTextContent(/^5$/)
    expect(cellUnder(row, 'Rushing fumbles lost')).toHaveTextContent(/^2$/)
  })

  it('gives a receiver his rushing, receiving and defense columns, and no passing column or starter record', () => {
    const [regular] = MARVIN_HARRISON_CAREER.seasons
    render(
      <PlayerCareerTable
        caption="Marvin Harrison, regular season"
        lines={[regular!]}
        totals={MARVIN_HARRISON_CAREER.regular_season}
      />,
    )

    expect(
      screen
        .getAllByRole('columnheader')
        .map((header) => header.textContent)
        .slice(0, 11),
    ).toEqual([
      'Season',
      'Teams',
      'Games',
      'Carries',
      'Rushing yards',
      'Rushing TDs',
      'Rushing first downs',
      'Rushing fumbles lost',
      'Receptions',
      'Receiving yards',
      'Receiving TDs',
    ])
    // His solo tackles put him on the defense board, so defense follows.
    expect(
      screen.getByRole('columnheader', { name: 'Solo tackles' }),
    ).toBeInTheDocument()
    const row = screen.getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(cellUnder(row, 'Receptions')).toHaveTextContent(/^115$/)
    expect(cellUnder(row, 'Receiving yards')).toHaveTextContent(/^1,663$/)
    expect(cellUnder(row, 'Receiving TDs')).toHaveTextContent(/^12$/)
    expect(cellUnder(row, 'Carries')).toHaveTextContent(/^1$/)
  })

  it('gives a kicker his kicking columns, punting when he punted, and defense for his solo tackles', () => {
    const [, postseason] = OLINDO_MARE_CAREER.seasons
    render(
      <PlayerCareerTable
        caption="Olindo Mare"
        lines={OLINDO_MARE_CAREER.seasons}
        totals={null}
      />,
    )

    expect(
      screen
        .getAllByRole('columnheader')
        .map((header) => header.textContent)
        .slice(0, 11),
    ).toEqual([
      'Season',
      'Teams',
      'Games',
      'FG made',
      'FG att',
      'FG long',
      'XP made',
      'Punts',
      'Punt yards',
      'Net punt yards',
      'Inside 20',
    ])
    // His solo tackles put him on the defense board, so defense follows.
    expect(
      screen.getByRole('columnheader', { name: 'Solo tackles' }),
    ).toBeInTheDocument()
    const [regularRow, postseasonRow] = screen
      .getAllByRole('rowheader')
      .map((header) => header.parentElement as HTMLElement) as [
      HTMLElement,
      HTMLElement,
    ]
    expect(cellUnder(regularRow, 'FG made')).toHaveTextContent(/^39$/)
    expect(cellUnder(regularRow, 'FG long')).toHaveTextContent(/^54$/)
    expect(cellUnder(regularRow, 'Punts')).toHaveTextContent(/^1$/)
    expect(postseason!.stats.pt_att).toBe(0)
    expect(cellUnder(postseasonRow, 'Punts')).toHaveTextContent(/^0$/)
  })

  it('names each kicking and punting column unambiguously when both share the table', () => {
    render(
      <PlayerCareerTable
        caption="Olindo Mare"
        lines={OLINDO_MARE_CAREER.seasons}
        totals={null}
      />,
    )

    const headers = screen
      .getAllByRole('columnheader')
      .map((header) => header.textContent)
    expect(headers).toEqual(
      expect.arrayContaining(['FG long', 'Punt yards', 'Net punt yards']),
    )
    for (const bare of ['Long', 'Yards', 'Net yards']) {
      expect(headers).not.toContain(bare)
    }
    expect(new Set(headers).size).toBe(headers.length)
  })

  it('renders a line whose payload lacks the two new rushing fields, reading them "not recorded"', () => {
    const [regular] = EDGERRIN_JAMES_CAREER.seasons
    // An API that hasn't deployed the two #352 fields yet sends neither key.
    const stats: Partial<PlayerStatsOut> = { ...regular!.stats }
    delete stats.rushing_first_downs
    delete stats.rushing_fumbles_lost
    const line = { ...regular!, stats: stats as PlayerStatsOut }
    render(
      <PlayerCareerTable
        caption="Edgerrin James"
        lines={[line]}
        totals={null}
      />,
    )

    const row = screen.getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(cellUnder(row, 'Rushing first downs')).toHaveTextContent(
      /^not recorded$/,
    )
    expect(cellUnder(row, 'Rushing fumbles lost')).toHaveTextContent(
      /^not recorded$/,
    )
    expect(cellUnder(row, 'Carries')).toHaveTextContent(/^369$/)
  })

  it('reads a missing longest field goal as "none", not 0 and not "not recorded"', () => {
    render(
      <PlayerCareerTable
        caption="Toby Gowin"
        lines={TOBY_GOWIN_CAREER.seasons}
        totals={null}
      />,
    )

    const [row] = screen
      .getAllByRole('rowheader')
      .map((header) => header.parentElement as HTMLElement)
    const long = cellUnder(row!, 'FG long')
    expect(long).toHaveTextContent('none')
    expect(long).not.toHaveTextContent(/0|not recorded/)
  })

  it('gives a defender the defense columns, each covered header described by its note', () => {
    render(
      <PlayerCareerTable
        caption="T.J. Watt, regular season"
        lines={TJ_WATT_CAREER.seasons}
        totals={TJ_WATT_CAREER.regular_season}
      />,
    )

    expect(
      screen.getByRole('columnheader', { name: 'Sacks' }),
    ).toHaveAccessibleDescription(DEFENSE_EARLY_ERA_NOTE)
    expect(
      screen.getByRole('columnheader', { name: 'Solo tackles' }),
    ).toHaveAccessibleDescription(DEFENSE_UNOFFICIAL_NOTE)
    expect(
      screen.getByRole('columnheader', { name: 'Interceptions' }),
    ).not.toHaveAccessibleDescription()
    const row = screen.getByRole('rowheader', { name: '2023' })
      .parentElement as HTMLElement
    expect(within(row).getByText('19.0')).toBeInTheDocument()
    expect(
      screen.queryByRole('columnheader', { name: /passing|carries/i }),
    ).not.toBeInTheDocument()
  })

  it('reads a stat an era didn\'t track as "not recorded" in a shown column, never 0', () => {
    const [regular] = EDGERRIN_JAMES_CAREER.seasons
    const line = {
      ...regular!,
      stats: { ...regular!.stats, rushing_fumbles_lost: null },
    }
    render(
      <PlayerCareerTable
        caption="Edgerrin James"
        lines={[line]}
        totals={null}
      />,
    )

    const row = screen.getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(cellUnder(row, 'Rushing fumbles lost')).toHaveTextContent(
      /^not recorded$/,
    )
    expect(cellUnder(row, 'Rushing first downs')).toHaveTextContent(/^80$/)
  })
})
