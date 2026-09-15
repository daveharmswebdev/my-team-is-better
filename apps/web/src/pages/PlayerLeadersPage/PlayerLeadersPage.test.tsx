import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode } from 'react'
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  NETWORK_ERROR_COPY,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
} from '../../lib/api/client'
import type { PlayerLeadersQuery } from '../../lib/api/client'
import type { PlayerLeaderRowOut, PlayerLeadersOut } from '../../lib/api/types'
import {
  DATA_SOURCES,
  LEADERS_BY_RUSHING_TDS,
  LEADERS_BY_RUSHING_YARDS,
  LEADERS_BY_TDS,
  LEADERS_BY_YARDS,
  LEADERS_WITH_NULL_STATS,
  TUA_TAGOVAILOA,
} from '../../lib/playerFixtures'
import { STARTER_RECORD_NOTE } from '../../lib/playerStats'
import { PlayerLeadersPage } from './PlayerLeadersPage'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchPlayerLeaders: vi.fn(),
    fetchCredits: vi.fn(),
  }
})

import { fetchCredits, fetchPlayerLeaders } from '../../lib/api/client'

const mockedFetchPlayerLeaders = vi.mocked(fetchPlayerLeaders)
const mockedFetchCredits = vi.mocked(fetchCredits)

/** 50 distinct rows, ranked from `offset + 1`: one full page of 204. */
function pageOf(query: PlayerLeadersQuery): PlayerLeadersOut {
  const rows: PlayerLeaderRowOut[] = Array.from(
    { length: Math.max(0, Math.min(query.limit, 204 - query.offset)) },
    (_unused, index) => ({
      ...TUA_TAGOVAILOA,
      rank: query.offset + index + 1,
      player_id: 5000 + query.offset + index,
      display_name: `Player ${query.offset + index + 1}`,
    }),
  )
  return { sport: 'nfl', ...query, total: 204, rows }
}

function LocationProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <div>
      <span data-testid="location-search">{location.search}</span>
      <button type="button" onClick={() => void navigate(-1)}>
        Browser back
      </button>
    </div>
  )
}

function renderPage(initialEntry = '/nfl/leaders', { strict = false } = {}) {
  const tree = (
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route
          path="/nfl/leaders"
          element={
            <>
              <PlayerLeadersPage />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  )
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree)
}

function lastQuery(): PlayerLeadersQuery {
  const calls = mockedFetchPlayerLeaders.mock.calls
  expect(calls.length).toBeGreaterThan(0)
  return calls[calls.length - 1]![0]
}

function search(): string {
  return screen.getByTestId('location-search').textContent ?? ''
}

describe('PlayerLeadersPage (issue #296)', () => {
  beforeEach(() => {
    mockedFetchPlayerLeaders.mockReset()
    mockedFetchCredits.mockReset()
    mockedFetchCredits.mockResolvedValue({
      methodologies: [],
      data_sources: DATA_SOURCES,
    })
  })

  it('asks for the regular season by passing yards, 50 from the top, and shows the table the API sent', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)

    renderPage()

    expect(
      screen.getByRole('heading', { level: 1, name: 'NFL Leaders' }),
    ).toBeInTheDocument()
    const table = await screen.findByRole('table', {
      name: 'NFL career leaders: regular season, by passing yards',
    })
    expect(lastQuery()).toEqual({
      category: 'passing',
      season_type: 'regular',
      sort: 'passing_yards',
      limit: 50,
      offset: 0,
    })
    const first = within(table).getAllByRole('row')[1] as HTMLElement
    expect(within(first).getByRole('link')).toHaveTextContent('Tua Tagovailoa')
    expect(within(first).getByText('4,624')).toBeInTheDocument()
  })

  it('shows a loading status while the first page is on its way', () => {
    mockedFetchPlayerLeaders.mockReturnValue(new Promise(() => {}))

    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent(/loading the leaders/i)
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('reads season type, sort and offset from the URL, so a reload shows the same table', async () => {
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(pageOf(query)),
    )

    renderPage('/nfl/leaders?season_type=postseason&sort=wins&offset=50')

    await screen.findByText('51–100 of 204')
    expect(lastQuery()).toEqual({
      category: 'passing',
      season_type: 'postseason',
      sort: 'wins',
      limit: 50,
      offset: 50,
    })
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
    expect(
      screen.getByRole('columnheader', { name: 'Starter record' }),
    ).toHaveAttribute('aria-sort', 'descending')
  })

  it('falls back to the defaults for URL values the API would refuse', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)

    renderPage(
      '/nfl/leaders?category=receiving&season_type=playoffs&sort=sacks&offset=-3',
    )

    await screen.findByRole('table')
    expect(lastQuery()).toEqual({
      category: 'passing',
      season_type: 'regular',
      sort: 'passing_yards',
      limit: 50,
      offset: 0,
    })
  })

  it('re-sorts through the API when a header is clicked, updating aria-sort and the URL', async () => {
    const user = userEvent.setup()
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(
        query.sort === 'passing_tds' ? LEADERS_BY_TDS : LEADERS_BY_YARDS,
      ),
    )

    renderPage()
    await screen.findByRole('table')
    expect(
      screen.getByRole('columnheader', { name: 'Passing yards' }),
    ).toHaveAttribute('aria-sort', 'descending')

    await user.click(screen.getByRole('button', { name: 'Passing TDs' }))

    expect(lastQuery()).toEqual({
      category: 'passing',
      season_type: 'regular',
      sort: 'passing_tds',
      limit: 50,
      offset: 0,
    })
    await waitFor(() => {
      expect(
        screen.getByRole('columnheader', { name: 'Passing TDs' }),
      ).toHaveAttribute('aria-sort', 'descending')
    })
    expect(
      screen.getByRole('columnheader', { name: 'Passing yards' }),
    ).toHaveAttribute('aria-sort', 'none')
    expect(search()).toBe(
      '?category=passing&season_type=regular&sort=passing_tds&offset=0',
    )
    // The button keeps focus across the reload, for a keyboard user.
    expect(screen.getByRole('button', { name: 'Passing TDs' })).toHaveFocus()
  })

  it('shows tied ranks exactly as the API sent them', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_TDS)

    renderPage('/nfl/leaders?sort=passing_tds')

    const table = await screen.findByRole('table')
    const ranks = within(table)
      .getAllByRole('row')
      .slice(1)
      .map((row) => row.querySelector('td')?.textContent)
    expect(ranks).toEqual(['1', '2', '2', '4'])
  })

  it('goes back to the top when the sort changes on a later page', async () => {
    const user = userEvent.setup()
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(pageOf(query)),
    )

    renderPage('/nfl/leaders?season_type=regular&sort=passing_yards&offset=100')
    await screen.findByText('101–150 of 204')

    await user.click(screen.getByRole('button', { name: 'Starter record' }))

    await screen.findByText('1–50 of 204')
    expect(lastQuery()).toMatchObject({ sort: 'wins', offset: 0 })
  })

  it('switches to the playoffs through the API, keeping the sort and going back to the top', async () => {
    const user = userEvent.setup()
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(pageOf(query)),
    )

    renderPage('/nfl/leaders?season_type=regular&sort=passing_tds&offset=50')
    await screen.findByText('51–100 of 204')

    await user.click(screen.getByRole('radio', { name: 'Playoffs' }))

    expect(lastQuery()).toEqual({
      category: 'passing',
      season_type: 'postseason',
      sort: 'passing_tds',
      limit: 50,
      offset: 0,
    })
    await screen.findByRole('table', {
      name: 'NFL career leaders: playoffs, by passing TDs',
    })
    expect(search()).toBe(
      '?category=passing&season_type=postseason&sort=passing_tds&offset=0',
    )
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
  })

  it('pages through the API with offset and limit, and Back restores the page before', async () => {
    const user = userEvent.setup()
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(pageOf(query)),
    )

    renderPage()
    await screen.findByText('1–50 of 204')
    expect(
      screen.getByRole('button', { name: 'Previous page' }),
    ).toHaveAttribute('aria-disabled', 'true')

    await user.click(screen.getByRole('button', { name: 'Next page' }))

    await screen.findByText('51–100 of 204')
    expect(lastQuery()).toMatchObject({ offset: 50, limit: 50 })
    expect(search()).toBe(
      '?category=passing&season_type=regular&sort=passing_yards&offset=50',
    )
    expect(screen.getByRole('link', { name: 'Player 51' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Browser back' }))

    await screen.findByText('1–50 of 204')
    expect(search()).toBe('')
    expect(lastQuery()).toMatchObject({ offset: 0 })
    expect(screen.getByRole('link', { name: 'Player 1' })).toBeInTheDocument()
  })

  it('never lets an older answer replace a newer one', async () => {
    const user = userEvent.setup()
    const answersToRegular: ((value: PlayerLeadersOut) => void)[] = []
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      query.season_type === 'regular'
        ? new Promise((resolve) => {
            answersToRegular.push(resolve)
          })
        : Promise.resolve({ ...LEADERS_BY_YARDS, season_type: 'postseason' }),
    )

    renderPage()
    expect(screen.getByRole('status')).toHaveTextContent(/loading/i)
    // The switch is usable before the first page arrives.
    await user.click(screen.getByRole('radio', { name: 'Playoffs' }))
    await screen.findByRole('table', {
      name: 'NFL career leaders: playoffs, by passing yards',
    })

    // The regular-season request answers late.
    expect(answersToRegular.length).toBeGreaterThan(0)
    await act(async () => {
      for (const answer of answersToRegular) {
        answer(LEADERS_BY_YARDS)
      }
      await Promise.resolve()
    })

    expect(
      screen.getByRole('table', {
        name: 'NFL career leaders: playoffs, by passing yards',
      }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('table', { name: /regular season/ }),
    ).not.toBeInTheDocument()
  })

  it('shows a null stat as "not recorded"', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_WITH_NULL_STATS)

    renderPage()

    const row = (
      await screen.findByRole('rowheader', {
        name: 'Unrecorded Player',
      })
    ).parentElement as HTMLElement
    // Games, position and all eight shown stats; `Starts` is a real 0 the API sent.
    expect(within(row).getAllByText('not recorded')).toHaveLength(10)
    expect(row.querySelector('td')).toHaveTextContent(/^not ranked$/)
  })

  it("links each player's name to their career page", async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)

    renderPage()

    expect(
      await screen.findByRole('link', { name: 'Jared Goff' }),
    ).toHaveAttribute('href', '/nfl/players/2454577150')
  })

  it('states the pulled-early starter note once, and describes the table with it', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)

    renderPage()

    const table = await screen.findByRole('table')
    expect(screen.getAllByText(STARTER_RECORD_NOTE)).toHaveLength(1)
    expect(table).toHaveAccessibleDescription(STARTER_RECORD_NOTE)
  })

  it('discloses that totals only count games with stat lines, and what "not recorded" means', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)

    renderPage()

    await screen.findByRole('table')
    expect(
      screen.getByText(/only count games the source has stat lines for/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/didn.t track that stat/i)).toBeInTheDocument()
  })

  it('credits the player data by the credit id, not its name', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)
    mockedFetchCredits.mockResolvedValue({
      methodologies: [],
      data_sources: [
        { ...DATA_SOURCES[2]!, name: 'A renamed player credit' },
        DATA_SOURCES[0]!,
        { ...DATA_SOURCES[1]!, name: DATA_SOURCES[2]!.name },
      ],
    })

    renderPage()

    expect(
      await screen.findByRole('link', { name: 'A renamed player credit' }),
    ).toHaveAttribute('href', 'https://github.com/nflverse/nflfastR')
    expect(
      screen.queryByRole('link', { name: DATA_SOURCES[2]!.name }),
    ).not.toBeInTheDocument()
  })

  it('still points to the credits when they fail to load', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)
    mockedFetchCredits.mockRejectedValue(
      new VerdictNetworkError(NETWORK_ERROR_COPY),
    )

    renderPage()

    await screen.findByRole('table')
    expect(
      await screen.findByRole('link', { name: 'How This Works' }),
    ).toHaveAttribute('href', '/about#data')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it("shows the narrator's network line when the leaders can't be reached", async () => {
    mockedFetchPlayerLeaders.mockRejectedValue(
      new VerdictNetworkError(NETWORK_ERROR_COPY),
    )

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it("shows the narrator's 5xx line for a server error, never the status", async () => {
    mockedFetchPlayerLeaders.mockRejectedValue(
      new VerdictHttpError(500, 'boom'),
    )

    renderPage()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(SERVER_ERROR_COPY)
    expect(alert).not.toHaveTextContent(/500/)
  })

  it('shows the 5xx line for an error nothing classified', async () => {
    mockedFetchPlayerLeaders.mockRejectedValue(new Error('odd'))

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      SERVER_ERROR_COPY,
    )
  })

  it('says so, and offers the top of the list, when a page is past the end', async () => {
    const user = userEvent.setup()
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(pageOf(query)),
    )

    renderPage('/nfl/leaders?offset=500')

    expect(
      await screen.findByText('Nobody this far down the list.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back to the top' }))

    await screen.findByText('1–50 of 204')
    expect(lastQuery()).toMatchObject({ offset: 0 })
  })

  it('says so when no player stats are loaded at all', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue({
      ...LEADERS_BY_YARDS,
      total: 0,
      rows: [],
    })

    renderPage()

    expect(
      await screen.findByText('No NFL player stats are loaded yet.'),
    ).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('asks once per URL under StrictMode and still shows the table', async () => {
    mockedFetchPlayerLeaders.mockResolvedValue(LEADERS_BY_YARDS)

    renderPage('/nfl/leaders', { strict: true })

    await screen.findByRole('table')
    for (const [query] of mockedFetchPlayerLeaders.mock.calls) {
      expect(query).toMatchObject({ sort: 'passing_yards', offset: 0 })
    }
  })
})

/**
 * Issue #312: the stat-category dropdown. Picking a category asks the API for
 * a different board -- different qualifiers, different columns, its own sorts
 * -- so the page resets the sort to that category's default rather than
 * sending a pair the API would 422.
 */
describe('PlayerLeadersPage, the stat category (issue #312)', () => {
  /** Answers each request with the board its category and sort name. */
  function boardFor(query: PlayerLeadersQuery): PlayerLeadersOut {
    const base =
      query.category === 'rushing'
        ? query.sort === 'rushing_tds'
          ? LEADERS_BY_RUSHING_TDS
          : LEADERS_BY_RUSHING_YARDS
        : LEADERS_BY_YARDS
    return {
      ...base,
      category: query.category,
      season_type: query.season_type,
      sort: query.sort,
      offset: query.offset,
    }
  }

  function categorySelect(): HTMLElement {
    return screen.getByRole('combobox', { name: 'Stat category' })
  }

  beforeEach(() => {
    mockedFetchPlayerLeaders.mockReset()
    mockedFetchCredits.mockReset()
    mockedFetchCredits.mockResolvedValue({
      methodologies: [],
      data_sources: DATA_SOURCES,
    })
    mockedFetchPlayerLeaders.mockImplementation((query) =>
      Promise.resolve(boardFor(query)),
    )
  })

  it('offers a labelled dropdown of both categories, set from the URL', async () => {
    renderPage('/nfl/leaders?category=rushing')

    await screen.findByRole('table')
    const select = categorySelect()
    expect(select).toHaveValue('rushing')
    expect(
      within(select)
        .getAllByRole('option')
        .map((option) => option.textContent),
    ).toEqual(['Passing', 'Rushing'])
  })

  it('starts on passing, and is the first control the keyboard reaches', async () => {
    const user = userEvent.setup()
    renderPage()

    await screen.findByRole('table')
    expect(categorySelect()).toHaveValue('passing')
    await user.tab()
    expect(categorySelect()).toHaveFocus()
  })

  it('switches to rushing, keeping the season type and resetting the sort and the page', async () => {
    const user = userEvent.setup()
    renderPage('/nfl/leaders?season_type=postseason&sort=wins&offset=50')
    await screen.findByRole('table')

    await user.selectOptions(categorySelect(), 'rushing')

    expect(lastQuery()).toEqual({
      category: 'rushing',
      season_type: 'postseason',
      sort: 'rushing_yards',
      limit: 50,
      offset: 0,
    })
    expect(search()).toBe(
      '?category=rushing&season_type=postseason&sort=rushing_yards&offset=0',
    )
    await screen.findByRole('table', {
      name: 'NFL career leaders: playoffs, by rushing yards',
    })
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
  })

  it('shows the rushing board the API sent, quarterbacks and all', async () => {
    renderPage('/nfl/leaders?category=rushing')

    const table = await screen.findByRole('table', {
      name: 'NFL career leaders: regular season, by rushing yards',
    })
    const first = within(table).getAllByRole('row')[1] as HTMLElement
    expect(within(first).getByRole('link')).toHaveTextContent('Edgerrin James')
    expect(within(first).getByText('1,553')).toBeInTheDocument()
    expect(
      within(table).queryByRole('columnheader', { name: 'Passing yards' }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('1–3 of 653')).toBeInTheDocument()
  })

  it('keeps the category when a rushing column is sorted', async () => {
    const user = userEvent.setup()
    renderPage('/nfl/leaders?category=rushing')
    await screen.findByRole('table')

    await user.click(screen.getByRole('button', { name: 'Rushing TDs' }))

    expect(lastQuery()).toEqual({
      category: 'rushing',
      season_type: 'regular',
      sort: 'rushing_tds',
      limit: 50,
      offset: 0,
    })
    expect(search()).toBe(
      '?category=rushing&season_type=regular&sort=rushing_tds&offset=0',
    )
    await screen.findByRole('table', {
      name: 'NFL career leaders: regular season, by rushing TDs',
    })
  })

  it('never asks for a sort the category does not own', async () => {
    renderPage('/nfl/leaders?category=rushing&sort=wins')

    await screen.findByRole('table')
    expect(lastQuery()).toEqual({
      category: 'rushing',
      season_type: 'regular',
      sort: 'rushing_yards',
      limit: 50,
      offset: 0,
    })
  })

  it('Back from the rushing board restores the passing board', async () => {
    const user = userEvent.setup()
    renderPage()
    await screen.findByRole('table', {
      name: 'NFL career leaders: regular season, by passing yards',
    })

    await user.selectOptions(categorySelect(), 'rushing')
    await screen.findByRole('table', {
      name: 'NFL career leaders: regular season, by rushing yards',
    })

    await user.click(screen.getByRole('button', { name: 'Browser back' }))

    await screen.findByRole('table', {
      name: 'NFL career leaders: regular season, by passing yards',
    })
    expect(search()).toBe('')
    expect(categorySelect()).toHaveValue('passing')
    expect(
      screen.getByRole('columnheader', { name: 'Starter record' }),
    ).toBeInTheDocument()
  })

  it('drops the starter-record note on a board with no records, keeping the other disclosures', async () => {
    renderPage('/nfl/leaders?category=rushing')

    const table = await screen.findByRole('table')
    expect(table).not.toHaveAccessibleDescription()
    expect(screen.queryByText(STARTER_RECORD_NOTE)).not.toBeInTheDocument()
    expect(
      screen.getByText(/only count games the source has stat lines for/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/didn.t track that stat/i)).toBeInTheDocument()
  })

  it('still describes the passing board by the starter-record note', async () => {
    renderPage()

    const table = await screen.findByRole('table')
    expect(table).toHaveAccessibleDescription(STARTER_RECORD_NOTE)
  })
})
