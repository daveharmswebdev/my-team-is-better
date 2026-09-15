import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  NETWORK_ERROR_COPY,
  PlayerApiError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
} from '../../lib/api/client'
import {
  DATA_SOURCES,
  KURT_WARNER_CAREER,
  NEVER_MET_COMPARISON,
  SEARCH_MCNAIR,
  WARNER_VS_MCNAIR,
} from '../../lib/playerFixtures'
import {
  HEAD_TO_HEAD_RULE,
  MARK_LEGEND,
  MARK_SCREEN_READER_TEXT,
  PICK_TWO_COPY,
  SAME_PLAYER_COPY,
  pickOneMoreCopy,
} from '../../lib/playerCompare'
import { PLAYER_NOT_FOUND_COPY } from '../../lib/playerStats'
import { PlayerComparePage } from './PlayerComparePage'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchPlayerComparison: vi.fn(),
    fetchPlayerCareer: vi.fn(),
    searchPlayers: vi.fn(),
    fetchCredits: vi.fn(),
  }
})

import {
  fetchCredits,
  fetchPlayerCareer,
  fetchPlayerComparison,
  searchPlayers,
} from '../../lib/api/client'

const mockedCompare = vi.mocked(fetchPlayerComparison)
const mockedCareer = vi.mocked(fetchPlayerCareer)
const mockedSearch = vi.mocked(searchPlayers)
const mockedCredits = vi.mocked(fetchCredits)

const WARNER = 2044124519
const MCNAIR = 2385180619

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.search}</output>
}

function renderPage(search = '') {
  return render(
    <MemoryRouter initialEntries={[`/nfl/compare${search}`]}>
      <Routes>
        <Route
          path="/nfl/compare"
          element={
            <>
              <PlayerComparePage />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
}

const playerA = () => screen.getByLabelText('Player A', { exact: true })
const playerB = () => screen.getByLabelText('Player B', { exact: true })

function cellsOf(table: HTMLElement, label: string): HTMLElement[] {
  const row = within(table).getByRole('rowheader', { name: label })
    .parentElement as HTMLElement
  return within(row).getAllByRole('cell')
}

const marked = (cell: HTMLElement | undefined) =>
  (cell?.textContent ?? '').includes(MARK_SCREEN_READER_TEXT)

describe('PlayerComparePage (issue #301)', () => {
  beforeEach(() => {
    mockedCompare.mockReset()
    mockedCareer.mockReset()
    mockedSearch.mockReset()
    mockedCredits.mockReset()
    mockedCredits.mockResolvedValue({
      methodologies: [],
      data_sources: DATA_SOURCES,
    })
  })

  it('with nobody picked, prompts for two players and asks the API nothing', () => {
    renderPage()

    expect(
      screen.getByRole('heading', { level: 1, name: 'Compare NFL players' }),
    ).toBeInTheDocument()
    expect(screen.getByText(PICK_TWO_COPY)).toBeInTheDocument()
    expect(playerA()).toHaveValue('')
    expect(playerB()).toHaveValue('')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(mockedCompare).not.toHaveBeenCalled()
    expect(mockedCareer).not.toHaveBeenCalled()
  })

  it('with one player picked, names that player in the field and prompts for the other', async () => {
    mockedCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage(`?a=${WARNER}`)

    await waitFor(() => {
      expect(playerA()).toHaveValue('Kurt Warner')
    })
    expect(mockedCareer).toHaveBeenCalledWith(WARNER)
    expect(screen.getByText(pickOneMoreCopy('Kurt Warner'))).toBeInTheDocument()
    expect(playerB()).toHaveValue('')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(mockedCompare).not.toHaveBeenCalled()
  })

  it('catches the same player picked twice before asking the API', () => {
    renderPage(`?a=${WARNER}&b=${WARNER}`)

    expect(screen.getByRole('alert')).toHaveTextContent(SAME_PLAYER_COPY)
    expect(mockedCompare).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('puts Warner and McNair side by side, marking the larger number in each row', async () => {
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    const regular = await screen.findByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    })
    expect(mockedCompare).toHaveBeenCalledWith(WARNER, MCNAIR)
    expect(playerA()).toHaveValue('Kurt Warner')
    expect(playerB()).toHaveValue('Steve McNair')

    const [warnerYards, mcnairYards] = cellsOf(regular, 'Passing yards')
    expect(warnerYards).toHaveTextContent('4,044')
    expect(marked(warnerYards)).toBe(true)
    expect(mcnairYards).toHaveTextContent('2,179')
    expect(marked(mcnairYards)).toBe(false)
    expect(marked(cellsOf(regular, 'Interceptions')[0])).toBe(true)

    const playoffs = screen.getByRole('table', {
      name: 'Kurt Warner and Steve McNair, playoffs',
    })
    const [warnerGames, mcnairGames] = cellsOf(playoffs, 'Games')
    expect(marked(warnerGames)).toBe(false)
    expect(mcnairGames).toHaveTextContent('4')
    expect(marked(mcnairGames)).toBe(true)

    expect(screen.getByText(MARK_LEGEND)).toBeInTheDocument()
    expect(
      screen.queryByText(/\b(leads?|winner|tally|wins the row)\b/i),
    ).not.toBeInTheDocument()
  })

  it("links each player to the player's career page and discloses Warner's undercounted game", async () => {
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    expect(
      await screen.findByRole('link', { name: 'Kurt Warner' }),
    ).toHaveAttribute('href', `/nfl/players/${WARNER}`)
    expect(screen.getByRole('link', { name: 'Steve McNair' })).toHaveAttribute(
      'href',
      `/nfl/players/${MCNAIR}`,
    )
    expect(
      screen.getByText(
        'These totals undercount games the source has no stat lines for. Kurt Warner, 1999 regular season: 1 game.',
      ),
    ).toBeInTheDocument()
    expect(
      await screen.findByRole('link', { name: DATA_SOURCES[2]!.name }),
    ).toHaveAttribute('href', 'https://github.com/nflverse/nflfastR')
  })

  it('shows both head-to-heads with the rule for which games count', async () => {
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    const headToHead = await screen.findByRole('region', {
      name: 'Head to head',
    })
    expect(within(headToHead).getByText(HEAD_TO_HEAD_RULE)).toBeInTheDocument()
    expect(
      within(headToHead).getByText(
        "Kurt Warner's record against Steve McNair: 0-1",
      ),
    ).toBeInTheDocument()
    expect(
      within(headToHead).getByText('St. Louis Rams 21, Tennessee Titans 24'),
    ).toBeInTheDocument()
    expect(
      within(headToHead).getByText(
        "Kurt Warner's record against Steve McNair: 1-0",
      ),
    ).toBeInTheDocument()
    expect(
      within(headToHead).getByText('St. Louis Rams 23, Tennessee Titans 16'),
    ).toBeInTheDocument()
  })

  it('says plainly when the two never met, and when one has no playoff games', async () => {
    mockedCompare.mockResolvedValue(NEVER_MET_COMPARISON)

    renderPage(`?a=${WARNER}&b=1001`)

    expect(
      await screen.findByText(
        'Kurt Warner and Unrecorded Player never started against each other in the regular season.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        'Kurt Warner and Unrecorded Player never started against each other in the playoffs.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('No playoff games on record.')).toBeInTheDocument()
  })

  it("answers an unknown player in the narrator's voice, with a way back to the leaders", async () => {
    mockedCompare.mockRejectedValue(
      new PlayerApiError(404, {
        error: 'unknown_player',
        player_id: 1,
        sport: 'nfl',
      }),
    )

    renderPage(`?a=${WARNER}&b=1`)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(PLAYER_NOT_FOUND_COPY)
    expect(alert).not.toHaveTextContent(/404|unknown_player/)
    expect(
      within(alert).getByRole('link', { name: /leaders board/ }),
    ).toHaveAttribute('href', '/nfl/leaders')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('answers an id that is not a number the same way, without asking the API', async () => {
    renderPage(`?a=kurt&b=${MCNAIR}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      PLAYER_NOT_FOUND_COPY,
    )
    expect(mockedCompare).not.toHaveBeenCalled()
    expect(mockedCareer).not.toHaveBeenCalled()
  })

  it("shows the narrator's network line when the comparison can't be reached", async () => {
    mockedCompare.mockRejectedValue(new VerdictNetworkError(NETWORK_ERROR_COPY))

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
  })

  it("shows the narrator's 5xx line, never the status", async () => {
    mockedCompare.mockRejectedValue(new VerdictHttpError(503, ''))

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(SERVER_ERROR_COPY)
    expect(alert).not.toHaveTextContent(/503/)
  })

  it('picking Player B through the typeahead puts both players in the URL', async () => {
    const user = userEvent.setup()
    mockedCareer.mockResolvedValue(KURT_WARNER_CAREER)
    mockedSearch.mockResolvedValue(SEARCH_MCNAIR)
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}`)

    await user.type(playerB(), 'McNair')
    await user.click(
      await screen.findByRole('option', { name: /Steve McNair/ }),
    )

    expect(mockedSearch).toHaveBeenCalledWith('McNair')
    expect(screen.getByTestId('location')).toHaveTextContent(
      `?a=${WARNER}&b=${MCNAIR}`,
    )
    expect(
      await screen.findByRole('table', {
        name: 'Kurt Warner and Steve McNair, regular season',
      }),
    ).toBeInTheDocument()
    expect(mockedCompare).toHaveBeenCalledWith(WARNER, MCNAIR)
  })

  it('searches only once there are two non-space characters', async () => {
    const user = userEvent.setup()
    mockedSearch.mockResolvedValue({ ...SEARCH_MCNAIR, rows: [] })

    renderPage()

    await user.type(playerA(), ' m ')
    await new Promise((resolve) => setTimeout(resolve, 500))
    expect(mockedSearch).not.toHaveBeenCalled()

    await user.type(playerA(), 'c')
    await waitFor(() => {
      expect(mockedSearch).toHaveBeenCalledWith('m c')
    })
    expect(mockedSearch).toHaveBeenCalledTimes(1)
  })
})
