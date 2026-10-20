import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PlayerCareerTotalsOut } from '../../lib/api/types'
import {
  CAREER_WITH_NULL_STATS,
  HARRISON_VS_JAMES,
  KURT_WARNER_CAREER,
  MARE_VS_GOWIN,
  STEVE_MCNAIR_CAREER,
  TJ_WATT_CAREER,
} from '../../lib/playerFixtures'
import { MARK_SCREEN_READER_TEXT } from '../../lib/playerCompare'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
} from '../../lib/playerStats'
import { PlayerComparisonTable } from './PlayerComparisonTable'
import type { PlayerComparisonTableProps } from './PlayerComparisonTable'

const WARNER_REGULAR = KURT_WARNER_CAREER.regular_season!
const MCNAIR_REGULAR = STEVE_MCNAIR_CAREER.regular_season!

function renderTable(
  a: PlayerCareerTotalsOut | null = WARNER_REGULAR,
  b: PlayerCareerTotalsOut | null = MCNAIR_REGULAR,
  extra: Partial<PlayerComparisonTableProps> = {},
) {
  render(
    <PlayerComparisonTable
      caption="Kurt Warner and Steve McNair, regular season"
      a={{ name: 'Kurt Warner', totals: a }}
      b={{ name: 'Steve McNair', totals: b }}
      noTotalsCopy="No regular-season games on record."
      {...extra}
    />,
  )
  return screen.getByRole('table', {
    name: 'Kurt Warner and Steve McNair, regular season',
  })
}

/** The row's two value cells, player A's first. */
function cellsOf(table: HTMLElement, label: string): HTMLElement[] {
  const row = within(table).getByRole('rowheader', { name: label })
    .parentElement as HTMLElement
  return within(row).getAllByRole('cell')
}

function isMarked(cell: HTMLElement | undefined): boolean {
  return (cell?.textContent ?? '').includes(MARK_SCREEN_READER_TEXT)
}

describe('PlayerComparisonTable (issue #301)', () => {
  it('has a column per player and a row per total, with no sack rows', () => {
    const table = renderTable()

    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((header) => header.textContent),
    ).toEqual(['Total', 'Kurt Warner', 'Steve McNair'])
    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((header) => header.textContent),
    ).toEqual([
      'Seasons',
      'Games',
      'Starter record',
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
    ])
    expect(table).not.toHaveTextContent(/sack/i)
  })

  it('marks the larger number with text a screen reader announces', () => {
    const table = renderTable()

    const [warner, mcnair] = cellsOf(table, 'Passing yards')
    expect(warner).toHaveTextContent('4,044')
    expect(isMarked(warner)).toBe(true)
    expect(mcnair).toHaveTextContent('2,179')
    expect(isMarked(mcnair)).toBe(false)
  })

  it('marks the larger interceptions too', () => {
    const table = renderTable()

    const [warner, mcnair] = cellsOf(table, 'Interceptions')
    expect(isMarked(warner)).toBe(true)
    expect(isMarked(mcnair)).toBe(false)
  })

  it('marks neither of two equal numbers', () => {
    const table = renderTable()

    const [warner, mcnair] = cellsOf(table, 'Seasons')
    expect(warner).toHaveTextContent('1')
    expect(isMarked(warner)).toBe(false)
    expect(isMarked(mcnair)).toBe(false)
  })

  it('compares starter records by wins', () => {
    const table = renderTable()
    const [warner, mcnair] = cellsOf(table, 'Starter record')
    expect(warner).toHaveTextContent('13-3')
    expect(isMarked(warner)).toBe(true)
    expect(mcnair).toHaveTextContent('9-2')
    expect(isMarked(mcnair)).toBe(false)
  })

  it('marks nothing on equal wins, even with different losses', () => {
    const table = renderTable(
      KURT_WARNER_CAREER.postseason,
      STEVE_MCNAIR_CAREER.postseason,
    )
    const [warner, mcnair] = cellsOf(table, 'Starter record')
    expect(warner).toHaveTextContent('3-0')
    expect(mcnair).toHaveTextContent('3-1')
    expect(isMarked(warner)).toBe(false)
    expect(isMarked(mcnair)).toBe(false)
    expect(isMarked(cellsOf(table, 'Games')[1])).toBe(true)
  })

  it('reads a null stat as "not recorded" and marks neither side of its row', () => {
    const table = renderTable(
      WARNER_REGULAR,
      CAREER_WITH_NULL_STATS.regular_season,
    )

    const [warner, other] = cellsOf(table, 'Passing TDs')
    expect(other).toHaveTextContent('not recorded')
    expect(other).not.toHaveTextContent('0')
    expect(isMarked(warner)).toBe(false)
    expect(isMarked(other)).toBe(false)
  })

  it('says so in plain copy when a player has no totals of the type, and marks nothing', () => {
    const table = renderTable(KURT_WARNER_CAREER.postseason, null, {
      noTotalsCopy: 'No playoff games on record.',
    })

    expect(
      within(table).getAllByText('No playoff games on record.'),
    ).toHaveLength(1)
    expect(within(table).getByText('1,063')).toBeInTheDocument()
    expect(table).not.toHaveTextContent(MARK_SCREEN_READER_TEXT)
  })

  /**
   * Issue #352: the rows are the stat groups either player recorded, so two
   * receivers, or a kicker and a punter, are compared on their own stats.
   */
  it('compares a receiver and a back on rushing, receiving and defense, with no passing or record row', () => {
    const table = renderTable(
      HARRISON_VS_JAMES.a.regular_season,
      HARRISON_VS_JAMES.b.regular_season,
    )

    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((header) => header.textContent)
        .slice(0, 10),
    ).toEqual([
      'Seasons',
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
    // Their solo tackles put both on the defense board, so the defense rows follow.
    for (const name of ['Sacks', 'Interceptions', 'Solo tackles']) {
      expect(within(table).getByRole('rowheader', { name })).toBeInTheDocument()
    }
    const [harrison, james] = cellsOf(table, 'Receptions')
    expect(harrison).toHaveTextContent('115')
    expect(isMarked(harrison)).toBe(true)
    expect(james).toHaveTextContent('62')
    expect(isMarked(james)).toBe(false)
  })

  it('compares a kicker and a punter on kicking and punting, a missing longest field goal read as "none"', () => {
    const table = renderTable(
      MARE_VS_GOWIN.a.regular_season,
      MARE_VS_GOWIN.b.regular_season,
    )

    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((header) => header.textContent)
        .slice(0, 10),
    ).toEqual([
      'Seasons',
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
    // Their solo tackles put both on the defense board, so the defense rows follow.
    for (const name of ['Sacks', 'Interceptions', 'Solo tackles']) {
      expect(within(table).getByRole('rowheader', { name })).toBeInTheDocument()
    }
    const [mare, gowin] = cellsOf(table, 'FG long')
    expect(mare).toHaveTextContent('54')
    expect(gowin).toHaveTextContent('none')
    expect(gowin).not.toHaveTextContent(/0|not recorded/)
    expect(isMarked(mare)).toBe(false)
    expect(isMarked(cellsOf(table, 'Punts')[1])).toBe(true)
  })

  it('describes each defense row a note covers by that note', () => {
    const watt = TJ_WATT_CAREER.regular_season!
    renderTable(watt, {
      ...watt,
      stats: { ...watt.stats, def_sacks: 17.5 },
    })

    expect(
      screen.getByRole('rowheader', { name: 'Sacks' }),
    ).toHaveAccessibleDescription(DEFENSE_EARLY_ERA_NOTE)
    expect(
      screen.getByRole('rowheader', { name: 'Passes defended' }),
    ).toHaveAccessibleDescription(DEFENSE_UNOFFICIAL_NOTE)
    const [a, b] = cellsOf(screen.getByRole('table'), 'Sacks')
    expect(a).toHaveTextContent('19.0')
    expect(b).toHaveTextContent('17.5')
  })

  it('sits in its own focusable scroll region', () => {
    renderTable()

    const region = screen.getByRole('region', {
      name: 'Kurt Warner and Steve McNair, regular season',
    })
    expect(region).toHaveAttribute('tabindex', '0')
  })
})
