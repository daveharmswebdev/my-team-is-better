import { render, screen, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  NETWORK_ERROR_COPY,
  PlayerApiError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
} from '../../lib/api/client'
import {
  CAREER_WITH_NULL_STATS,
  DATA_SOURCES,
  KURT_WARNER_CAREER,
} from '../../lib/playerFixtures'
import {
  PLAYER_NOT_FOUND_COPY,
  STARTER_RECORD_NOTE,
  undercountNote,
} from '../../lib/playerStats'
import { PlayerCareerPage } from './PlayerCareerPage'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchPlayerCareer: vi.fn(),
    fetchCredits: vi.fn(),
  }
})

import { fetchCredits, fetchPlayerCareer } from '../../lib/api/client'

const mockedFetchPlayerCareer = vi.mocked(fetchPlayerCareer)
const mockedFetchCredits = vi.mocked(fetchCredits)

function renderPage(path = '/nfl/players/2044124519') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/nfl/players/:playerId" element={<PlayerCareerPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('PlayerCareerPage (issue #296)', () => {
  beforeEach(() => {
    mockedFetchPlayerCareer.mockReset()
    mockedFetchCredits.mockReset()
    mockedFetchCredits.mockResolvedValue({
      methodologies: [],
      data_sources: DATA_SOURCES,
    })
  })

  it('asks for the player in the URL and names them with their position', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    expect(screen.getByRole('status')).toHaveTextContent(/loading the player/i)
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Kurt Warner' }),
    ).toBeInTheDocument()
    expect(mockedFetchPlayerCareer).toHaveBeenCalledWith(2044124519)
    expect(screen.getByText('QB')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /nfl leaders/i })).toHaveAttribute(
      'href',
      '/nfl/leaders',
    )
  })

  it('shows each regular-season line and the regular-season career totals', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    const table = await screen.findByRole('table', {
      name: 'Kurt Warner, regular season',
    })
    const line = within(table).getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    for (const text of [
      'St. Louis Rams',
      '4,044',
      '38',
      '297',
      '455',
      '13-3',
    ]) {
      expect(within(line).getByText(text)).toBeInTheDocument()
    }
    expect(
      within(table).getByRole('rowheader', { name: 'Career, 1 season' }),
    ).toBeInTheDocument()
  })

  it('shows each playoff line and the playoff career totals in their own table', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    const table = await screen.findByRole('table', {
      name: 'Kurt Warner, playoffs',
    })
    const line = within(table).getByRole('rowheader', { name: '1999' })
      .parentElement as HTMLElement
    expect(within(line).getByText('1,063')).toBeInTheDocument()
    expect(within(line).getByText('3-0')).toBeInTheDocument()
    expect(
      within(table).getByRole('rowheader', { name: 'Career, 1 season' }),
    ).toBeInTheDocument()
  })

  it('discloses missing stat lines on the affected line only', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    const regular = await screen.findByRole('table', {
      name: 'Kurt Warner, regular season',
    })
    const playoffs = screen.getByRole('table', {
      name: 'Kurt Warner, playoffs',
    })
    expect(within(regular).getByText(undercountNote(1))).toBeInTheDocument()
    expect(within(playoffs).queryByText(/undercount/i)).not.toBeInTheDocument()
    expect(screen.getAllByText(/undercount/i)).toHaveLength(1)
  })

  it('states the pulled-early starter note once, describing both tables', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    const regular = await screen.findByRole('table', {
      name: 'Kurt Warner, regular season',
    })
    expect(screen.getAllByText(STARTER_RECORD_NOTE)).toHaveLength(1)
    expect(regular).toHaveAccessibleDescription(STARTER_RECORD_NOTE)
    expect(
      screen.getByRole('table', { name: 'Kurt Warner, playoffs' }),
    ).toHaveAccessibleDescription(STARTER_RECORD_NOTE)
  })

  it('shows no sack columns (#298)', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    await screen.findAllByRole('table')
    for (const header of screen.getAllByRole('columnheader')) {
      expect(header.textContent).not.toMatch(/sack/i)
    }
    expect(screen.queryByText('-176')).not.toBeInTheDocument()
  })

  it('shows null stats as "not recorded", and says when there are no playoff games', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(CAREER_WITH_NULL_STATS)

    renderPage('/nfl/players/1001')

    const table = await screen.findByRole('table', {
      name: 'Unrecorded Player, regular season',
    })
    expect(within(table).getAllByText('not recorded').length).toBeGreaterThan(5)
    expect(screen.getByText('Position not recorded')).toBeInTheDocument()
    expect(
      screen.queryByRole('table', { name: /playoffs/i }),
    ).not.toBeInTheDocument()
    expect(screen.getByText('No playoff games on record.')).toBeInTheDocument()
  })

  it("answers an unknown player in the narrator's voice, with a way back to the leaders", async () => {
    mockedFetchPlayerCareer.mockRejectedValue(
      new PlayerApiError(404, {
        error: 'unknown_player',
        player_id: 1,
        sport: 'nfl',
      }),
    )

    renderPage('/nfl/players/1')

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(PLAYER_NOT_FOUND_COPY)
    expect(alert).not.toHaveTextContent(/404|unknown_player/)
    expect(
      within(alert).getByRole('link', { name: /leaders/i }),
    ).toHaveAttribute('href', '/nfl/leaders')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('answers an id that is not a number the same way, without asking the API', async () => {
    renderPage('/nfl/players/kurt-warner')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      PLAYER_NOT_FOUND_COPY,
    )
    expect(mockedFetchPlayerCareer).not.toHaveBeenCalled()
  })

  it("shows the narrator's network line when the player can't be reached", async () => {
    mockedFetchPlayerCareer.mockRejectedValue(
      new VerdictNetworkError(NETWORK_ERROR_COPY),
    )

    renderPage()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
  })

  it("shows the narrator's 5xx line for a server error, never the status", async () => {
    mockedFetchPlayerCareer.mockRejectedValue(new VerdictHttpError(503, ''))

    renderPage()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(SERVER_ERROR_COPY)
    expect(alert).not.toHaveTextContent(/503/)
  })

  it('credits the player data by id', async () => {
    mockedFetchPlayerCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage()

    expect(
      await screen.findByRole('link', { name: DATA_SOURCES[2]!.name }),
    ).toHaveAttribute('href', 'https://github.com/nflverse/nflfastR')
  })
})
