import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { PlayerLeadersOut } from '../../lib/api/types'
import {
  LEADERS_BY_TDS,
  LEADERS_BY_YARDS,
  LEADERS_WITH_NULL_STATS,
  TUA_TAGOVAILOA,
} from '../../lib/playerFixtures'
import { PlayerLeadersTable } from './PlayerLeadersTable'

function renderTable(
  leaders: PlayerLeadersOut,
  extra: { busy?: boolean; describedBy?: string } = {},
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

  it('marks the table busy while a new page is on its way', () => {
    renderTable(LEADERS_BY_YARDS, { busy: true })

    expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true')
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
