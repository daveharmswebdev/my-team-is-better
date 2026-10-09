import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { PlayerLeadersOut } from '../../lib/api/types'
import {
  BRANDON_AUBREY,
  DEFENSE_WITH_NULL_STATS,
  LEADERS_BY_DEF_SACKS,
  LEADERS_BY_DEF_SACKS_TAIL,
  LEADERS_BY_FG_MADE,
  LEADERS_BY_FG_MADE_TAIL,
  LEADERS_BY_FG_PCT,
  LEADERS_BY_PT_YARDS,
  LEADERS_BY_RECEIVING_TDS,
  LEADERS_BY_RECEIVING_YARDS,
  LEADERS_BY_RECEPTIONS_TAIL,
  LEADERS_BY_RUSHING_TDS,
  LEADERS_BY_RUSHING_YARDS,
  LEADERS_BY_TDS,
  LEADERS_BY_YARDS,
  LEADERS_WITH_NULL_STATS,
  TUA_TAGOVAILOA,
  TYREEK_HILL,
} from '../../lib/playerFixtures'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
  LEADER_COLUMN_NOTES,
} from '../../lib/playerStats'
import { LeaderColumnNotes } from '../LeaderColumnNotes/LeaderColumnNotes'
import { PlayerLeadersTable } from './PlayerLeadersTable'

function renderTable(
  leaders: PlayerLeadersOut,
  extra: {
    busy?: boolean
    describedBy?: string
    columnNoteIdPrefix?: string
  } = {},
) {
  const onSort = vi.fn()
  render(
    <MemoryRouter>
      <PlayerLeadersTable leaders={leaders} onSort={onSort} {...extra} />
    </MemoryRouter>,
  )
  return { onSort }
}

/** The body rows, in order. */
function bodyRows(): HTMLElement[] {
  return screen.getAllByRole('row').slice(1)
}

/** The cell of `row` under the column whose header reads `name`. */
function cellUnder(row: HTMLElement, name: string): HTMLElement {
  const headers = screen.getAllByRole('columnheader')
  const index = headers.findIndex((header) => header.textContent === name)
  expect(index, `no column named ${name}`).toBeGreaterThanOrEqual(0)
  const cell = row.querySelectorAll('th, td')[index]
  expect(cell).toBeDefined()
  return cell as HTMLElement
}

describe('PlayerLeadersTable (issue #296)', () => {
  it('is named by its caption, which says the season type and the sort', () => {
    renderTable(LEADERS_BY_YARDS)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by passing yards',
      }),
    ).toBeInTheDocument()
  })

  it('sits in a focusable, named scroll region, so a keyboard can scroll it', () => {
    renderTable(LEADERS_BY_YARDS)

    const region = screen.getByRole('region', {
      name: 'NFL career leaders: regular season, by passing yards',
    })
    expect(region).toHaveAttribute('tabindex', '0')
    expect(within(region).getByRole('table')).toBeInTheDocument()
  })

  it('renders one row per API row, in the order sent, with each rank as sent', () => {
    renderTable(LEADERS_BY_YARDS)

    const rows = bodyRows()
    expect(rows).toHaveLength(4)
    expect(rows.map((row) => cellUnder(row, 'Rank').textContent)).toEqual([
      '1',
      '2',
      '3',
      '4',
    ])
    expect(rows.map((row) => cellUnder(row, 'Player').textContent)).toEqual([
      'Tua Tagovailoa',
      'Jared Goff',
      'Dak Prescott',
      'Steve Beuerlein',
    ])
    expect(
      cellUnder(rows[0] as HTMLElement, 'Passing yards'),
    ).toHaveTextContent('4,624')
    expect(
      cellUnder(rows[0] as HTMLElement, 'Starter record'),
    ).toHaveTextContent('11-6')
    expect(cellUnder(rows[0] as HTMLElement, 'Starts')).toHaveTextContent('17')
  })

  it('shows tied ranks exactly as the API sent them', () => {
    renderTable(LEADERS_BY_TDS)

    expect(bodyRows().map((row) => cellUnder(row, 'Rank').textContent)).toEqual(
      ['1', '2', '2', '4'],
    )
  })

  it('shows a null stat as "not recorded", and a recorded zero as 0', () => {
    renderTable(LEADERS_WITH_NULL_STATS)

    const [tua, goff, unrecorded] = bodyRows() as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ]
    expect(cellUnder(tua, 'Rushing TDs')).toHaveTextContent(/^0$/)
    expect(cellUnder(goff, 'Passing TDs')).toHaveTextContent(/^not recorded$/)
    expect(cellUnder(goff, 'Completions')).toHaveTextContent(/^not recorded$/)
    expect(cellUnder(goff, 'Passing yards')).toHaveTextContent('4,575')
    for (const column of [
      'Games',
      'Position',
      'Completions',
      'Attempts',
      'Passing yards',
      'Passing TDs',
      'Interceptions',
      'Carries',
      'Rushing yards',
      'Rushing TDs',
    ]) {
      expect(cellUnder(unrecorded, column)).toHaveTextContent(/^not recorded$/)
    }
    expect(cellUnder(unrecorded, 'Rank')).toHaveTextContent(/^not ranked$/)
  })

  it('keeps a negative stat negative', () => {
    renderTable({
      ...LEADERS_BY_YARDS,
      rows: [
        {
          ...TUA_TAGOVAILOA,
          stats: { ...TUA_TAGOVAILOA.stats, passing_yards: -7 },
        },
      ],
    })

    expect(
      cellUnder(bodyRows()[0] as HTMLElement, 'Passing yards'),
    ).toHaveTextContent(/^-7$/)
  })

  it("links each player's name to their career page", () => {
    renderTable(LEADERS_BY_YARDS)

    expect(
      screen.getByRole('link', { name: 'Tua Tagovailoa' }),
    ).toHaveAttribute('href', '/nfl/players/2186969283')
    expect(
      screen.getByRole('rowheader', { name: 'Steve Beuerlein' }),
    ).toBeInTheDocument()
  })

  it('makes each sortable header a button inside its th, with aria-sort on the th', () => {
    renderTable(LEADERS_BY_TDS)

    const expected: Record<string, string> = {
      'Starter record': 'none',
      'Passing yards': 'none',
      'Passing TDs': 'descending',
    }
    for (const [name, sort] of Object.entries(expected)) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).toHaveAttribute('aria-sort', sort)
      expect(within(header).getByRole('button', { name })).toBeInTheDocument()
    }
    for (const name of ['Rank', 'Player', 'Games', 'Rushing yards']) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).not.toHaveAttribute('aria-sort')
      expect(within(header).queryByRole('button')).not.toBeInTheDocument()
    }
  })

  it('asks for the sort a header names when it is clicked', async () => {
    const user = userEvent.setup()
    const { onSort } = renderTable(LEADERS_BY_YARDS)

    await user.click(screen.getByRole('button', { name: 'Passing TDs' }))
    await user.click(screen.getByRole('button', { name: 'Starter record' }))

    expect(onSort.mock.calls).toEqual([['passing_tds'], ['wins']])
  })

  it('shows no sack columns (#298)', () => {
    renderTable(LEADERS_BY_YARDS)

    for (const header of screen.getAllByRole('columnheader')) {
      expect(header.textContent).not.toMatch(/sack/i)
    }
  })

  it('marks the table busy while a new page is on its way (passing)', () => {
    renderTable(LEADERS_BY_YARDS, { busy: true })

    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true')
  })

  it('keeps the passing board exactly as it was when the category is passing (#312)', () => {
    renderTable(LEADERS_BY_YARDS)

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      'Rank',
      'Player',
      'Position',
      'Seasons',
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
    ])
  })

  it('points the table at the note that explains its records', () => {
    render(
      <MemoryRouter>
        <p id="record-note">A note.</p>
        <PlayerLeadersTable
          leaders={LEADERS_BY_YARDS}
          onSort={() => {}}
          describedBy="record-note"
        />
      </MemoryRouter>,
    )

    expect(screen.getByRole('table')).toHaveAccessibleDescription('A note.')
  })
})

/**
 * Issue #312: the same table, told by the API's `category` which board it is.
 * The rushing board ranks everyone with a carry -- quarterbacks included --
 * so it shows the rushing columns and none of the passing or starter ones.
 */
describe('PlayerLeadersTable, the rushing board (issue #312)', () => {
  it('names itself by the rushing sort in its caption', () => {
    renderTable(LEADERS_BY_RUSHING_YARDS)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by rushing yards',
      }),
    ).toBeInTheDocument()
  })

  it('shows the rushing columns only, in order, with no record or passing columns', () => {
    renderTable(LEADERS_BY_RUSHING_YARDS)

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      'Rank',
      'Player',
      'Position',
      'Seasons',
      'Games',
      'Carries',
      'Rushing yards',
      'Rushing TDs',
    ])
    for (const gone of [
      'Starter record',
      'Starts',
      'Completions',
      'Attempts',
      'Passing yards',
      'Passing TDs',
      'Interceptions',
    ]) {
      expect(
        screen.queryByRole('columnheader', { name: gone }),
      ).not.toBeInTheDocument()
    }
  })

  it('makes all three rushing columns sortable, with aria-sort on the active one', () => {
    renderTable(LEADERS_BY_RUSHING_YARDS)

    const expected: Record<string, string> = {
      Carries: 'none',
      'Rushing yards': 'descending',
      'Rushing TDs': 'none',
    }
    for (const [name, sort] of Object.entries(expected)) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).toHaveAttribute('aria-sort', sort)
      expect(within(header).getByRole('button', { name })).toBeInTheDocument()
    }
    for (const name of ['Rank', 'Player', 'Position', 'Seasons', 'Games']) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).not.toHaveAttribute('aria-sort')
      expect(within(header).queryByRole('button')).not.toBeInTheDocument()
    }
  })

  it('marks the pressed rushing column descending', () => {
    renderTable(LEADERS_BY_RUSHING_TDS)

    expect(
      screen.getByRole('columnheader', { name: 'Rushing TDs' }),
    ).toHaveAttribute('aria-sort', 'descending')
    expect(
      screen.getByRole('columnheader', { name: 'Rushing yards' }),
    ).toHaveAttribute('aria-sort', 'none')
  })

  it('asks for a rushing sort when its header is clicked', async () => {
    const user = userEvent.setup()
    const { onSort } = renderTable(LEADERS_BY_RUSHING_YARDS)

    await user.click(screen.getByRole('button', { name: 'Rushing TDs' }))
    await user.click(screen.getByRole('button', { name: 'Carries' }))

    expect(onSort.mock.calls).toEqual([['rushing_tds'], ['carries']])
  })

  it('ranks quarterbacks alongside the backs, showing each position', () => {
    renderTable(LEADERS_BY_RUSHING_TDS)

    const rows = bodyRows()
    expect(rows.map((row) => cellUnder(row, 'Rank').textContent)).toEqual([
      '1',
      '2',
      '3',
      '3',
    ])
    expect(rows.map((row) => cellUnder(row, 'Player').textContent)).toEqual([
      'Raheem Mostert',
      'Stephen Davis',
      'Jalen Hurts',
      'Josh Allen',
    ])
    expect(rows.map((row) => cellUnder(row, 'Position').textContent)).toEqual([
      'RB',
      'RB',
      'QB',
      'QB',
    ])
    expect(cellUnder(rows[0] as HTMLElement, 'Rushing TDs')).toHaveTextContent(
      /^18$/,
    )
  })

  it('groups the thousands of a rushing total', () => {
    renderTable(LEADERS_BY_RUSHING_YARDS)

    expect(
      cellUnder(bodyRows()[0] as HTMLElement, 'Rushing yards'),
    ).toHaveTextContent('1,553')
    expect(
      cellUnder(bodyRows()[0] as HTMLElement, 'Carries'),
    ).toHaveTextContent(/^369$/)
  })
})

/**
 * Issue #314: the receiving board. It ranks everyone with a target or a
 * reception -- a quarterback with one target included -- so, like the rushing
 * board, it shows its own three columns and no starter record. Targets are
 * published but never shown (#345: the source has them as 0 for 2003-2008).
 */
describe('PlayerLeadersTable, the receiving board (issue #314)', () => {
  it('names itself by the receiving sort in its caption', () => {
    renderTable(LEADERS_BY_RECEIVING_YARDS)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by receiving yards',
      }),
    ).toBeInTheDocument()
  })

  it('shows the receiving columns only, in order, with no record, passing, rushing or targets columns', () => {
    renderTable(LEADERS_BY_RECEIVING_YARDS)

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      'Rank',
      'Player',
      'Position',
      'Seasons',
      'Games',
      'Receptions',
      'Receiving yards',
      'Receiving TDs',
    ])
    for (const header of screen.getAllByRole('columnheader')) {
      expect(header.textContent).not.toMatch(/target|first down|fumble/i)
    }
  })

  it('renders the rows the API sent, receiving numbers grouped', () => {
    renderTable(LEADERS_BY_RECEIVING_YARDS)

    const rows = bodyRows()
    expect(rows.map((row) => cellUnder(row, 'Player').textContent)).toEqual([
      'Tyreek Hill',
      'CeeDee Lamb',
      'Marvin Harrison',
    ])
    const hill = rows[0] as HTMLElement
    expect(cellUnder(hill, 'Rank')).toHaveTextContent(/^1$/)
    expect(cellUnder(hill, 'Position')).toHaveTextContent(/^WR$/)
    expect(cellUnder(hill, 'Receiving yards')).toHaveTextContent(/^1,799$/)
    expect(cellUnder(hill, 'Receptions')).toHaveTextContent(/^119$/)
    expect(cellUnder(hill, 'Receiving TDs')).toHaveTextContent(/^13$/)
    // Hill's 171 targets are in the payload, and nowhere on the board.
    expect(hill).not.toHaveTextContent('171')
  })

  it('makes all three receiving columns sortable, with aria-sort on the active one', () => {
    renderTable(LEADERS_BY_RECEIVING_YARDS)

    const expected: Record<string, string> = {
      Receptions: 'none',
      'Receiving yards': 'descending',
      'Receiving TDs': 'none',
    }
    for (const [name, sort] of Object.entries(expected)) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).toHaveAttribute('aria-sort', sort)
      expect(within(header).getByRole('button', { name })).toBeInTheDocument()
    }
    for (const name of ['Rank', 'Player', 'Position', 'Seasons', 'Games']) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).not.toHaveAttribute('aria-sort')
      expect(within(header).queryByRole('button')).not.toBeInTheDocument()
    }
  })

  it('asks for each receiving column its own sort when clicked', async () => {
    const user = userEvent.setup()
    const { onSort } = renderTable(LEADERS_BY_RECEIVING_YARDS)

    await user.click(screen.getByRole('button', { name: 'Receiving TDs' }))
    await user.click(screen.getByRole('button', { name: 'Receptions' }))
    await user.click(screen.getByRole('button', { name: 'Receiving yards' }))

    expect(onSort.mock.calls).toEqual([
      ['receiving_tds'],
      ['receptions'],
      ['receiving_yards'],
    ])
  })

  it('shows the three-way tie at rank 1 by receiving TDs exactly as sent', () => {
    renderTable(LEADERS_BY_RECEIVING_TDS)

    expect(
      screen.getByRole('columnheader', { name: 'Receiving TDs' }),
    ).toHaveAttribute('aria-sort', 'descending')
    const rows = bodyRows()
    expect(rows.map((row) => cellUnder(row, 'Rank').textContent)).toEqual([
      '1',
      '1',
      '1',
      '4',
      '4',
    ])
    expect(
      rows.map((row) => cellUnder(row, 'Receiving TDs').textContent),
    ).toEqual(['13', '13', '13', '12', '12'])
  })

  it('shows a recorded 0 receptions as 0, not "not recorded", for a quarterback with a target', () => {
    renderTable(LEADERS_BY_RECEPTIONS_TAIL)

    expect(
      screen.getByRole('columnheader', { name: 'Receptions' }),
    ).toHaveAttribute('aria-sort', 'descending')
    const [tannehill, mckeon] = bodyRows() as [HTMLElement, HTMLElement]
    expect(cellUnder(tannehill, 'Rank')).toHaveTextContent(/^885$/)
    expect(cellUnder(tannehill, 'Position')).toHaveTextContent(/^QB$/)
    expect(cellUnder(mckeon, 'Rank')).toHaveTextContent(/^885$/)
    expect(cellUnder(mckeon, 'Position')).toHaveTextContent(/^TE$/)
    for (const row of [tannehill, mckeon]) {
      for (const column of ['Receptions', 'Receiving yards', 'Receiving TDs']) {
        expect(cellUnder(row, column)).toHaveTextContent(/^0$/)
      }
    }
    // A quarterback's starter record stays off a board with no record column.
    expect(
      screen.queryByRole('columnheader', { name: 'Starter record' }),
    ).not.toBeInTheDocument()
    expect(tannehill).not.toHaveTextContent('3-5')
  })

  it('shows a null receiving stat as "not recorded"', () => {
    renderTable({
      ...LEADERS_BY_RECEIVING_YARDS,
      rows: [
        {
          ...TYREEK_HILL,
          stats: { ...TYREEK_HILL.stats, receptions: null },
        },
      ],
    })

    expect(
      cellUnder(bodyRows()[0] as HTMLElement, 'Receptions'),
    ).toHaveTextContent(/^not recorded$/)
  })
})

/**
 * Issue #315: the kicking board. Like rushing and receiving it shows its own
 * columns and no starter record. Two of them -- FG% and 50+ -- are sorts the
 * engine computes and does not send, so the board derives their values from
 * the counts it was sent, and both still re-sort the board.
 */
describe('PlayerLeadersTable, the kicking board (issue #315)', () => {
  it('names itself by the kicking sort in its caption', () => {
    renderTable(LEADERS_BY_FG_MADE)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by field goals made',
      }),
    ).toBeInTheDocument()
  })

  it('shows the six kicking columns only, in order, with no record or other category', () => {
    renderTable(LEADERS_BY_FG_MADE)

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      'Rank',
      'Player',
      'Position',
      'Seasons',
      'Games',
      'FG made',
      'FG att',
      'FG%',
      '50+',
      'Long',
      'XP made',
    ])
  })

  it('renders the rows the API sent, with FG% and 50+ derived from the counts sent', () => {
    renderTable(LEADERS_BY_FG_MADE)

    const rows = bodyRows()
    expect(rows.map((row) => cellUnder(row, 'Player').textContent)).toEqual([
      'Olindo Mare',
      'Brandon Aubrey',
      'Cairo Santos',
      'Greg Zuerlein',
    ])
    expect(rows.map((row) => cellUnder(row, 'Rank').textContent)).toEqual([
      '1',
      '2',
      '3',
      '3',
    ])
    const [mare, aubrey] = rows as [HTMLElement, HTMLElement]
    expect(cellUnder(mare, 'Position')).toHaveTextContent(/^K$/)
    expect(cellUnder(mare, 'FG made')).toHaveTextContent(/^39$/)
    expect(cellUnder(mare, 'FG att')).toHaveTextContent(/^46$/)
    expect(cellUnder(mare, 'FG%')).toHaveTextContent(/^84\.8%$/)
    expect(cellUnder(mare, '50+')).toHaveTextContent(/^3$/)
    expect(cellUnder(mare, 'Long')).toHaveTextContent(/^54$/)
    expect(cellUnder(mare, 'XP made')).toHaveTextContent(/^27$/)
    // Aubrey's 50+ is 9 from 50-59 and 1 from 60+.
    expect(cellUnder(aubrey, 'FG%')).toHaveTextContent(/^94\.7%$/)
    expect(cellUnder(aubrey, '50+')).toHaveTextContent(/^10$/)
    expect(cellUnder(aubrey, 'Long')).toHaveTextContent(/^60$/)
    // His 52 extra-point attempts are in the payload, and nowhere on the board.
    expect(aubrey).not.toHaveTextContent('52')
  })

  it('makes all six kicking columns sortable, derived ones included, with aria-sort on the active one', () => {
    renderTable(LEADERS_BY_FG_MADE)

    const expected: Record<string, string> = {
      'FG made': 'descending',
      'FG att': 'none',
      'FG%': 'none',
      '50+': 'none',
      Long: 'none',
      'XP made': 'none',
    }
    for (const [name, sort] of Object.entries(expected)) {
      const header = screen.getByRole('columnheader', { name })
      expect(header).toHaveAttribute('aria-sort', sort)
      expect(within(header).getByRole('button', { name })).toBeInTheDocument()
    }
  })

  it('asks for each kicking column its own sort when clicked', async () => {
    const user = userEvent.setup()
    const { onSort } = renderTable(LEADERS_BY_FG_MADE)

    for (const name of ['FG%', '50+', 'Long', 'FG att', 'XP made']) {
      await user.click(screen.getByRole('button', { name }))
    }

    expect(onSort.mock.calls).toEqual([
      ['fg_pct'],
      ['fg_made_50_plus'],
      ['fg_long'],
      ['fg_att'],
      ['pat_made'],
    ])
  })

  it('marks FG% descending, and names it in the caption, on the FG% board', () => {
    renderTable(LEADERS_BY_FG_PCT)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by field-goal percentage',
      }),
    ).toBeInTheDocument()
    expect(screen.getByRole('columnheader', { name: 'FG%' })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
  })

  it('shows a null Long as a dash named "none" -- never 0, never "not recorded"', () => {
    renderTable(LEADERS_BY_FG_MADE_TAIL)

    const rows = bodyRows()
    expect(rows.map((row) => cellUnder(row, 'Rank').textContent)).toEqual([
      '79',
      '79',
      '79',
    ])
    for (const row of rows) {
      const long = cellUnder(row, 'Long')
      expect(long).toHaveAccessibleName('none')
      expect(long).toHaveTextContent(/^–none$/)
      expect(within(long).getByText('–')).toHaveAttribute('aria-hidden', 'true')
      expect(long).not.toHaveTextContent('0')
      expect(long).not.toHaveTextContent('not recorded')
    }
  })

  it('shows FG% as a dash named "none" with no attempts, and 0.0% for a miss', () => {
    renderTable(LEADERS_BY_FG_MADE_TAIL)

    const [wright, unutoa, gowin] = bodyRows() as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ]
    // Morris Unutoa, a center, is on the board on one extra point.
    expect(cellUnder(unutoa, 'Position')).toHaveTextContent(/^C$/)
    expect(cellUnder(unutoa, 'FG att')).toHaveTextContent(/^0$/)
    expect(cellUnder(unutoa, 'FG%')).toHaveAccessibleName('none')
    expect(cellUnder(unutoa, 'XP made')).toHaveTextContent(/^1$/)
    // Wright and Gowin each missed their one attempt: a real 0.0%.
    expect(cellUnder(wright, 'FG%')).toHaveTextContent(/^0\.0%$/)
    expect(cellUnder(gowin, 'FG%')).toHaveTextContent(/^0\.0%$/)
  })

  it('shows recorded kicking zeros as 0', () => {
    renderTable(LEADERS_BY_FG_MADE_TAIL)

    const wright = bodyRows()[0] as HTMLElement
    for (const column of ['FG made', '50+', 'XP made']) {
      expect(cellUnder(wright, column)).toHaveTextContent(/^0$/)
    }
  })

  it('shows a null kicking count as "not recorded", and 50+ too when a bucket is null', () => {
    renderTable({
      ...LEADERS_BY_FG_MADE,
      rows: [
        {
          ...BRANDON_AUBREY,
          stats: { ...BRANDON_AUBREY.stats, pat_made: null, fg_made_60_: null },
        },
      ],
    })

    const row = bodyRows()[0] as HTMLElement
    expect(cellUnder(row, 'XP made')).toHaveTextContent(/^not recorded$/)
    expect(cellUnder(row, '50+')).toHaveTextContent(/^not recorded$/)
  })
})

/** Issue #315: the punting board, the rushing board's shape. */
describe('PlayerLeadersTable, the punting board (issue #315)', () => {
  it('names itself by the punting sort in its caption', () => {
    renderTable(LEADERS_BY_PT_YARDS)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by punting yards',
      }),
    ).toBeInTheDocument()
  })

  it('shows the four punting columns only, in order, with no Long', () => {
    renderTable(LEADERS_BY_PT_YARDS)

    expect(
      screen.getAllByRole('columnheader').map((header) => header.textContent),
    ).toEqual([
      'Rank',
      'Player',
      'Position',
      'Seasons',
      'Games',
      'Punts',
      'Yards',
      'Net yards',
      'Inside 20',
    ])
  })

  it('renders the rows the API sent, yards grouped', () => {
    renderTable(LEADERS_BY_PT_YARDS)

    const rows = bodyRows()
    expect(rows.map((row) => cellUnder(row, 'Player').textContent)).toEqual([
      'Thomas Morstead',
      'Chris Gardocki',
      'Bryce Baringer',
    ])
    const morstead = rows[0] as HTMLElement
    expect(cellUnder(morstead, 'Rank')).toHaveTextContent(/^1$/)
    expect(cellUnder(morstead, 'Position')).toHaveTextContent(/^P$/)
    expect(cellUnder(morstead, 'Punts')).toHaveTextContent(/^99$/)
    expect(cellUnder(morstead, 'Yards')).toHaveTextContent(/^4,831$/)
    expect(cellUnder(morstead, 'Net yards')).toHaveTextContent(/^4,136$/)
    expect(cellUnder(morstead, 'Inside 20')).toHaveTextContent(/^36$/)
    // His 62-yard long punt is in the payload, and nowhere on the board.
    expect(morstead).not.toHaveTextContent('62')
  })

  it('makes all four punting columns sortable, and asks for each its own sort', async () => {
    const user = userEvent.setup()
    const { onSort } = renderTable(LEADERS_BY_PT_YARDS)

    expect(screen.getByRole('columnheader', { name: 'Yards' })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
    for (const name of ['Net yards', 'Punts', 'Inside 20']) {
      expect(screen.getByRole('columnheader', { name })).toHaveAttribute(
        'aria-sort',
        'none',
      )
      await user.click(screen.getByRole('button', { name }))
    }

    expect(onSort.mock.calls).toEqual([
      ['pt_net_yards'],
      ['pt_att'],
      ['pt_inside_20'],
    ])
  })
})

/**
 * Issue #317: the defense board. Sacks keep their half (17.5, never 17 or
 * 18), and the founder's two notes (#316) sit under the table, each tied to
 * the headers it covers: no sacks or forced-fumbles number without the
 * early-era note, no solo-tackle or passes-defended number without the
 * unofficial one. INT matched every official leader, so it has no note.
 */
describe('PlayerLeadersTable, the defense board (issue #317)', () => {
  /** The five defense headers' accessible names, in column order. */
  const DEFENSE_HEADERS = [
    'Sacks',
    'Interceptions',
    'Solo tackles',
    'Forced fumbles',
    'Passes defended',
  ]

  /**
   * The cell of `row` under the column whose accessible name is `name`: an
   * abbreviated header is named in full, and its marker is not in its name.
   */
  function cellAt(row: HTMLElement, name: string): HTMLElement {
    const index = screen
      .getAllByRole('columnheader')
      .indexOf(screen.getByRole('columnheader', { name }))
    return row.querySelectorAll('th, td')[index] as HTMLElement
  }

  it('names itself by the sacks sort in its caption', () => {
    renderTable(LEADERS_BY_DEF_SACKS)

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: regular season, by sacks',
      }),
    ).toBeInTheDocument()
  })

  it('shows the five defense columns only, in order, with no record or other category', () => {
    renderTable(LEADERS_BY_DEF_SACKS)

    const headers = screen.getAllByRole('columnheader')
    expect(headers).toHaveLength(10)
    expect(headers.slice(0, 5).map((header) => header.textContent)).toEqual([
      'Rank',
      'Player',
      'Position',
      'Seasons',
      'Games',
    ])
    expect(headers.slice(5)).toEqual(
      DEFENSE_HEADERS.map((name) => screen.getByRole('columnheader', { name })),
    )
    expect(
      screen.queryByRole('columnheader', { name: 'Starter record' }),
    ).not.toBeInTheDocument()
    expect(screen.getByRole('table')).not.toHaveTextContent(/EPA|QB hits/i)
  })

  it('gives each abbreviation a readable name, and a title for the mouse', () => {
    renderTable(LEADERS_BY_DEF_SACKS)

    for (const [abbreviation, name] of [
      ['INT', 'Interceptions'],
      ['FF', 'Forced fumbles'],
      ['PD', 'Passes defended'],
    ] as const) {
      const button = screen.getByRole('button', { name })
      expect(within(button).getByTitle(name)).toHaveTextContent(abbreviation)
    }
  })

  it('renders the rows the API sent, sacks to one decimal, the tie at 17.5 as sent', () => {
    renderTable(LEADERS_BY_DEF_SACKS)

    const rows = bodyRows()
    expect(
      rows.map((row) => within(row).getByRole('link').textContent),
    ).toEqual([
      'T.J. Watt',
      'Josh Hines-Allen',
      'Trey Hendrickson',
      'Khalil Mack',
      'Danielle Hunter',
    ])
    const [watt, hinesAllen, hendrickson, mack] = rows as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ]
    expect(cellAt(watt, 'Rank')).toHaveTextContent(/^1$/)
    expect(cellAt(watt, 'Position')).toHaveTextContent(/^OLB$/)
    expect(cellAt(watt, 'Sacks')).toHaveTextContent(/^19\.0$/)
    expect(cellAt(watt, 'Interceptions')).toHaveTextContent(/^1$/)
    expect(cellAt(watt, 'Solo tackles')).toHaveTextContent(/^38$/)
    expect(cellAt(watt, 'Forced fumbles')).toHaveTextContent(/^4$/)
    expect(cellAt(watt, 'Passes defended')).toHaveTextContent(/^8$/)
    expect(cellAt(hinesAllen, 'Rank')).toHaveTextContent(/^2$/)
    expect(cellAt(hinesAllen, 'Sacks')).toHaveTextContent(/^17\.5$/)
    expect(cellAt(hendrickson, 'Rank')).toHaveTextContent(/^2$/)
    expect(cellAt(hendrickson, 'Sacks')).toHaveTextContent(/^17\.5$/)
    expect(cellAt(mack, 'Sacks')).toHaveTextContent(/^17\.0$/)
  })

  it('shows a half sack as 0.5 and a null stat as "not recorded", never 0', () => {
    renderTable(DEFENSE_WITH_NULL_STATS)

    const [, half, unrecorded] = bodyRows() as [
      HTMLElement,
      HTMLElement,
      HTMLElement,
    ]
    expect(cellAt(half, 'Sacks')).toHaveTextContent(/^0\.5$/)
    expect(cellAt(half, 'Solo tackles')).toHaveTextContent(/^not recorded$/)
    expect(cellAt(unrecorded, 'Rank')).toHaveTextContent('not ranked')
    for (const name of DEFENSE_HEADERS) {
      expect(cellAt(unrecorded, name)).toHaveTextContent(/^not recorded$/)
    }
  })

  it('ranks a receiver with one solo tackle at the foot, showing his position and 0.0 sacks', () => {
    renderTable(LEADERS_BY_DEF_SACKS_TAIL)

    const davis = screen
      .getByRole('rowheader', { name: 'Zola Davis' })
      .closest('tr') as HTMLElement
    expect(cellAt(davis, 'Rank')).toHaveTextContent(/^812$/)
    expect(cellAt(davis, 'Position')).toHaveTextContent(/^WR$/)
    expect(cellAt(davis, 'Sacks')).toHaveTextContent(/^0\.0$/)
    expect(cellAt(davis, 'Solo tackles')).toHaveTextContent(/^1$/)
  })

  it('makes all five defense columns sortable, and asks for each its own sort', async () => {
    const user = userEvent.setup()
    const { onSort } = renderTable(LEADERS_BY_DEF_SACKS)

    expect(screen.getByRole('columnheader', { name: 'Sacks' })).toHaveAttribute(
      'aria-sort',
      'descending',
    )
    for (const name of DEFENSE_HEADERS.slice(1)) {
      expect(screen.getByRole('columnheader', { name })).toHaveAttribute(
        'aria-sort',
        'none',
      )
      await user.click(screen.getByRole('button', { name }))
    }
    await user.click(screen.getByRole('button', { name: 'Sacks' }))

    expect(onSort.mock.calls).toEqual([
      ['def_interceptions'],
      ['def_tackles_solo'],
      ['def_fumbles_forced'],
      ['def_pass_defended'],
      ['def_sacks'],
    ])
  })

  it('renders neither note itself: the page shows them above the table', () => {
    renderTable(LEADERS_BY_DEF_SACKS, { columnNoteIdPrefix: 'notes' })

    expect(screen.queryByText(DEFENSE_EARLY_ERA_NOTE)).not.toBeInTheDocument()
    expect(screen.queryByText(DEFENSE_UNOFFICIAL_NOTE)).not.toBeInTheDocument()
  })

  it('points each covered header at its note by the id built from the prefix', () => {
    renderTable(LEADERS_BY_DEF_SACKS, { columnNoteIdPrefix: 'notes' })

    for (const name of ['Sacks', 'Forced fumbles']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute(
        'aria-describedby',
        'notes-early-era',
      )
    }
    for (const name of ['Solo tackles', 'Passes defended']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute(
        'aria-describedby',
        'notes-unofficial',
      )
    }
    expect(
      screen.getByRole('button', { name: 'Interceptions' }),
    ).not.toHaveAttribute('aria-describedby')
  })

  it('describes no header when no note prefix is given, so no id dangles', () => {
    renderTable(LEADERS_BY_DEF_SACKS)

    for (const button of screen.getAllByRole('button')) {
      expect(button).not.toHaveAttribute('aria-describedby')
    }
  })

  it('ties each note the page renders to the headers it covers, and INT to neither', () => {
    render(
      <MemoryRouter>
        <LeaderColumnNotes category="defense" idPrefix="notes" />
        <PlayerLeadersTable
          leaders={LEADERS_BY_DEF_SACKS}
          onSort={() => {}}
          columnNoteIdPrefix="notes"
        />
      </MemoryRouter>,
    )

    for (const name of ['Sacks', 'Forced fumbles']) {
      expect(screen.getByRole('button', { name })).toHaveAccessibleDescription(
        DEFENSE_EARLY_ERA_NOTE,
      )
    }
    for (const name of ['Solo tackles', 'Passes defended']) {
      expect(screen.getByRole('button', { name })).toHaveAccessibleDescription(
        DEFENSE_UNOFFICIAL_NOTE,
      )
    }
    expect(
      screen.getByRole('button', { name: 'Interceptions' }),
    ).toHaveAccessibleDescription('')
  })

  it("marks each covered header with its note's marker, and the note with the same one", () => {
    render(
      <MemoryRouter>
        <LeaderColumnNotes category="defense" idPrefix="notes" />
        <PlayerLeadersTable
          leaders={LEADERS_BY_DEF_SACKS}
          onSort={() => {}}
          columnNoteIdPrefix="notes"
        />
      </MemoryRouter>,
    )

    const early = LEADER_COLUMN_NOTES['early-era'].marker
    const unofficial = LEADER_COLUMN_NOTES.unofficial.marker
    const marker = (name: string) =>
      screen.getByRole('button', { name }).textContent ?? ''
    expect(marker('Sacks')).toContain(early)
    expect(marker('Forced fumbles')).toContain(early)
    expect(marker('Solo tackles')).toContain(unofficial)
    expect(marker('Passes defended')).toContain(unofficial)
    expect(marker('Interceptions')).not.toContain(early)
    expect(marker('Interceptions')).not.toContain(unofficial)
    expect(
      screen.getByText(DEFENSE_EARLY_ERA_NOTE).closest('p'),
    ).toHaveTextContent(new RegExp(`^\\${early}`))
    expect(
      screen.getByText(DEFENSE_UNOFFICIAL_NOTE).closest('p'),
    ).toHaveTextContent(new RegExp(`^${unofficial}`))
  })

  it.each([
    ['passing', LEADERS_BY_YARDS],
    ['rushing', LEADERS_BY_RUSHING_YARDS],
    ['receiving', LEADERS_BY_RECEIVING_YARDS],
    ['kicking', LEADERS_BY_FG_MADE],
    ['kicking, by FG%', LEADERS_BY_FG_PCT],
    ['punting', LEADERS_BY_PT_YARDS],
  ])(
    'marks and describes no header by a note on the %s board',
    (_name, leaders) => {
      renderTable(leaders, { columnNoteIdPrefix: 'notes' })

      for (const button of screen.getAllByRole('button')) {
        expect(button).not.toHaveAttribute('aria-describedby')
        for (const { marker } of Object.values(LEADER_COLUMN_NOTES)) {
          expect(button.textContent).not.toContain(marker)
        }
      }
    },
  )
})
