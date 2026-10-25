import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PlayerCareerTotalsOut } from '../../lib/api/types'
import {
  CAREER_WITH_NULL_STATS,
  FAULK_VS_FARMER,
  HILL_VS_LAMB,
  KURT_WARNER_CAREER,
  MARE_VS_GOWIN,
  SMITH_VS_PETERSON,
  STEVE_MCNAIR_CAREER,
  TJ_WATT_CAREER,
  fixtureCoverage,
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

/**
 * A career wholly inside the data, so the marking tests below see the
 * #301 rule alone; the #448 cut-off rule has its own tests.
 */
const IN_THE_BOOKS = fixtureCoverage(1999, 1999, 1999, 1999)

function renderTable(
  a: PlayerCareerTotalsOut | null = WARNER_REGULAR,
  b: PlayerCareerTotalsOut | null = MCNAIR_REGULAR,
  extra: Partial<PlayerComparisonTableProps> = {},
) {
  render(
    <PlayerComparisonTable
      caption="Kurt Warner and Steve McNair, regular season"
      a={{ name: 'Kurt Warner', totals: a, coverage: IN_THE_BOOKS }}
      b={{ name: 'Steve McNair', totals: b, coverage: IN_THE_BOOKS }}
      noTotalsCopy="No regular-season games on record."
      group="QB"
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
      { group: null },
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
   * Issue #438: the position group both players share decides the rows.
   * Two backs get rushing then receiving, whatever else they recorded.
   */
  it("compares two backs on rushing then receiving, with no passing or record row for Emmitt Smith's one pass", () => {
    const table = renderTable(
      SMITH_VS_PETERSON.a.regular_season,
      SMITH_VS_PETERSON.b.regular_season,
      { group: 'RB' },
    )

    const headers = within(table)
      .getAllByRole('rowheader')
      .map((header) => header.textContent)
    expect(headers).toEqual([
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
    for (const gone of [
      'Starter record',
      'Completions',
      'Attempts',
      'Passing yards',
      'Passing TDs',
      'Solo tackles',
    ]) {
      expect(
        within(table).queryByRole('rowheader', { name: gone }),
      ).not.toBeInTheDocument()
    }
    const [smith, peterson] = cellsOf(table, 'Rushing yards')
    expect(smith).toHaveTextContent('5,789')
    expect(isMarked(smith)).toBe(false)
    expect(peterson).toHaveTextContent('14,921')
    expect(isMarked(peterson)).toBe(true)
  })

  it('compares two receivers on receiving only', () => {
    const table = renderTable(
      HILL_VS_LAMB.a.regular_season,
      HILL_VS_LAMB.b.regular_season,
      { group: 'WR' },
    )

    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((header) => header.textContent),
    ).toEqual([
      'Seasons',
      'Games',
      'Receptions',
      'Receiving yards',
      'Receiving TDs',
    ])
  })

  /**
   * Issue #352: with no group the two share (unreachable on the page since
   * #436), the rows are the stat groups either player recorded.
   */
  it('compares a kicker and a punter on kicking and punting, a missing longest field goal read as "none"', () => {
    const table = renderTable(
      MARE_VS_GOWIN.a.regular_season,
      MARE_VS_GOWIN.b.regular_season,
      { group: null },
    )

    expect(
      within(table)
        .getAllByRole('rowheader')
        .map((header) => header.textContent),
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
    const [mare, gowin] = cellsOf(table, 'FG long')
    expect(mare).toHaveTextContent('54')
    expect(gowin).toHaveTextContent('none')
    expect(gowin).not.toHaveTextContent(/0|not recorded/)
    expect(isMarked(mare)).toBe(false)
    expect(isMarked(cellsOf(table, 'Punts')[1])).toBe(true)
  })

  it('describes each defense row a note covers by that note', () => {
    const watt = TJ_WATT_CAREER.regular_season!
    renderTable(
      watt,
      { ...watt, stats: { ...watt.stats, def_sacks: 17.5 } },
      { group: null },
    )

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

describe('PlayerComparisonTable and a career cut off by the data (#448)', () => {
  function renderPair(
    pair: typeof FAULK_VS_FARMER,
    seasonType: 'regular_season' | 'postseason' = 'regular_season',
  ) {
    const { a, b } = pair
    render(
      <PlayerComparisonTable
        caption="The pair"
        a={{
          name: a.display_name,
          totals: a[seasonType],
          coverage: a.coverage,
        }}
        b={{
          name: b.display_name,
          totals: b[seasonType],
          coverage: b.coverage,
        }}
        noTotalsCopy="No regular-season games on record."
        group={a.group}
      />,
    )
    return screen.getByRole('table', { name: 'The pair' })
  }

  it('marks no total when one side is cut off, and reads his seasons as a slice', () => {
    const table = renderPair(FAULK_VS_FARMER)

    expect(table).not.toHaveTextContent(MARK_SCREEN_READER_TEXT)
    const [faulk, farmer] = cellsOf(table, 'Seasons')
    expect(faulk).toHaveTextContent(/^1 of 13 \(1999\)$/)
    expect(farmer).toHaveTextContent(/^1$/)
  })

  it('marks no total when both are cut off', () => {
    const table = renderPair({
      ...FAULK_VS_FARMER,
      a: KURT_WARNER_CAREER,
      b: STEVE_MCNAIR_CAREER,
    })

    expect(table).not.toHaveTextContent(MARK_SCREEN_READER_TEXT)
    expect(cellsOf(table, 'Seasons').map((cell) => cell.textContent)).toEqual([
      '1 of 12 (1999)',
      '1 of 13 (1999)',
    ])
  })

  it('keeps the marks for careers that only run past the data', () => {
    const table = renderPair(HILL_VS_LAMB)

    expect(table).toHaveTextContent(MARK_SCREEN_READER_TEXT)
  })
})
