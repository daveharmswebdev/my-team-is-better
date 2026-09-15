import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
  PlayerApiError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
} from '../../lib/api/client'
import type { PlayerComparisonOut } from '../../lib/api/types'
import {
  BRADY_VS_MANNING,
  BRADY_VS_QUINN,
  DATA_SOURCES,
  KURT_WARNER_CAREER,
  NEVER_MET_COMPARISON,
  SEARCH_BRADY,
  SEARCH_MANNING,
  SEARCH_MCNAIR,
  WARNER_VS_MCNAIR,
} from '../../lib/playerFixtures'
import {
  HEAD_TO_HEAD_RULE,
  MARK_LEGEND,
  MARK_SCREEN_READER_TEXT,
  PICK_FROM_LIST_COPY,
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
const BRADY = 1002
const QUINN = 1003
const MANNING = 2153701690

/** Shows the URL's search, and goes Back/Forward through the router's history. */
function LocationProbe() {
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <>
      <output data-testid="location">{location.search}</output>
      <button type="button" onClick={() => void navigate(-1)}>
        Go back
      </button>
      <button type="button" onClick={() => void navigate(1)}>
        Go forward
      </button>
    </>
  )
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
const compareButton = () => screen.getByRole('button', { name: 'Compare' })

type User = ReturnType<typeof userEvent.setup>

/** Types into a field and clicks the suggestion matching `option`. */
async function pick(
  user: User,
  field: HTMLElement,
  text: string,
  option: RegExp,
) {
  await user.type(field, text)
  await user.click(await screen.findByRole('option', { name: option }))
}

/** Search answers by query; anything else finds nobody. */
function searchByQuery() {
  const answers = [SEARCH_BRADY, SEARCH_MANNING, SEARCH_MCNAIR]
  mockedSearch.mockImplementation((query) =>
    Promise.resolve(
      answers.find((answer) => answer.query === query) ?? {
        ...SEARCH_MCNAIR,
        query,
        rows: [],
      },
    ),
  )
}

/** The comparison answers by pair, rejecting any pair it wasn't given. */
function compareByPair(comparisons: PlayerComparisonOut[]) {
  mockedCompare.mockImplementation((a, b) => {
    const found = comparisons.find(
      (comparison) =>
        comparison.a.player_id === a && comparison.b.player_id === b,
    )
    return found === undefined
      ? Promise.reject(new Error(`no fixture for ${a}:${b}`))
      : Promise.resolve(found)
  })
}

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
    await user.click(compareButton())

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

describe('PlayerComparePage: changing a pick (issue #304)', () => {
  beforeEach(() => {
    mockedCompare.mockReset()
    mockedCareer.mockReset()
    mockedSearch.mockReset()
    mockedCredits.mockReset()
    mockedCredits.mockResolvedValue({
      methodologies: [],
      data_sources: DATA_SOURCES,
    })
    searchByQuery()
    compareByPair([BRADY_VS_QUINN, BRADY_VS_MANNING])
  })

  it("the founder's repro: Brady and Quinn, then Player B changed to Manning, compares Brady and Manning", async () => {
    const user = userEvent.setup()
    renderPage()

    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Brady Quinn/)
    await user.click(compareButton())

    const quinn = await screen.findByRole('dialog', {
      name: 'Tom Brady and Brady Quinn',
    })
    expect(
      within(quinn).getByRole('table', {
        name: 'Tom Brady and Brady Quinn, regular season',
      }),
    ).toBeInTheDocument()
    expect(mockedCompare).toHaveBeenLastCalledWith(BRADY, QUINN)

    // The comparison owns the screen while it is open, so changing a pick
    // starts by closing it (issue #310). Both fields keep the pair.
    await user.click(
      within(quinn).getByRole('button', { name: 'Close the comparison' }),
    )
    expect(playerA()).toHaveValue('Tom Brady')

    await user.clear(playerB())
    await pick(user, playerB(), 'Manning', /Peyton Manning/)
    expect(playerB()).toHaveValue('Peyton Manning')
    // Nothing is compared until the button is pressed.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(mockedCompare).toHaveBeenCalledTimes(1)

    await user.click(compareButton())

    const manning = await screen.findByRole('dialog', {
      name: 'Tom Brady and Peyton Manning',
    })
    expect(
      within(manning).getByRole('table', {
        name: 'Tom Brady and Peyton Manning, regular season',
      }),
    ).toBeInTheDocument()
    expect(mockedCompare).toHaveBeenLastCalledWith(BRADY, MANNING)
    expect(
      screen.queryByRole('table', {
        name: 'Tom Brady and Brady Quinn, regular season',
      }),
    ).not.toBeInTheDocument()
    const players = within(manning).getByRole('list', {
      name: 'Players compared',
    })
    expect(
      within(players).getByRole('link', { name: 'Tom Brady' }),
    ).toBeVisible()
    expect(
      within(players).getByRole('link', { name: 'Peyton Manning' }),
    ).toBeVisible()
    expect(screen.getByTestId('location')).toHaveTextContent(
      `?a=${BRADY}&b=${MANNING}`,
    )
  })

  it('typing over a pick clears it: Compare is disabled and says to pick from the list, until a new pick', async () => {
    const user = userEvent.setup()
    renderPage()

    expect(compareButton()).toBeDisabled()
    expect(screen.queryByText(PICK_FROM_LIST_COPY)).not.toBeInTheDocument()

    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Brady Quinn/)
    expect(compareButton()).toBeEnabled()
    expect(screen.queryByText(PICK_FROM_LIST_COPY)).not.toBeInTheDocument()

    await user.type(playerB(), 'x')

    expect(playerB()).toHaveValue('Brady Quinnx')
    expect(compareButton()).toBeDisabled()
    expect(screen.getByText(PICK_FROM_LIST_COPY)).toBeInTheDocument()
    expect(compareButton()).toHaveAccessibleDescription(PICK_FROM_LIST_COPY)

    await user.clear(playerB())
    await pick(user, playerB(), 'Manning', /Peyton Manning/)

    expect(compareButton()).toBeEnabled()
    expect(screen.queryByText(PICK_FROM_LIST_COPY)).not.toBeInTheDocument()
  })

  it('the clear control empties that field and disables Compare', async () => {
    const user = userEvent.setup()
    renderPage()

    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Brady Quinn/)
    expect(compareButton()).toBeEnabled()

    await user.click(screen.getByRole('button', { name: 'Clear Player B' }))

    expect(playerB()).toHaveValue('')
    expect(playerB()).toHaveFocus()
    expect(playerA()).toHaveValue('Tom Brady')
    expect(compareButton()).toBeDisabled()
    expect(
      screen.queryByRole('button', { name: 'Clear Player B' }),
    ).not.toBeInTheDocument()
  })

  it('pressing Compare twice on the pair already shown asks the API twice', async () => {
    const user = userEvent.setup()
    mockedCompare.mockReset()
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    await screen.findByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    })
    expect(mockedCompare).toHaveBeenCalledTimes(1)
    expect(compareButton()).toBeEnabled()

    await user.click(compareButton())

    await waitFor(() => {
      expect(mockedCompare).toHaveBeenCalledTimes(2)
    })
    expect(mockedCompare).toHaveBeenNthCalledWith(2, WARNER, MCNAIR)
    expect(
      await screen.findByRole('table', {
        name: 'Kurt Warner and Steve McNair, regular season',
      }),
    ).toBeInTheDocument()
  })

  it('picking suggestions alone changes neither the URL nor the comparison; Compare pushes ?a=&b=', async () => {
    const user = userEvent.setup()
    renderPage()

    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Brady Quinn/)
    await new Promise((resolve) => setTimeout(resolve, 50))

    expect(screen.getByTestId('location')).toBeEmptyDOMElement()
    expect(mockedCompare).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    await user.click(compareButton())

    expect(screen.getByTestId('location')).toHaveTextContent(
      `?a=${BRADY}&b=${QUINN}`,
    )
    expect(
      await screen.findByRole('table', {
        name: 'Tom Brady and Brady Quinn, regular season',
      }),
    ).toBeInTheDocument()
    expect(mockedCompare).toHaveBeenCalledWith(BRADY, QUINN)

    // A pushed entry: Back returns to nobody picked, and the fields follow.
    await user.click(screen.getByRole('button', { name: 'Go back' }))
    expect(screen.getByTestId('location')).toBeEmptyDOMElement()
    expect(playerA()).toHaveValue('')
    expect(playerB()).toHaveValue('')
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('the same player in both slots, on Compare, gets the same-player line without asking the API', async () => {
    const user = userEvent.setup()
    renderPage()

    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Tom Brady/)
    await user.click(compareButton())

    expect(await screen.findByRole('alert')).toHaveTextContent(SAME_PLAYER_COPY)
    expect(mockedCompare).not.toHaveBeenCalled()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })
})

/**
 * Issue #310: every answer to a committed pair shows in `VerdictModal` over
 * the form, so a shared link opens on the answer instead of the form. The
 * prompts that mean "you haven't asked yet" stay inline on the form.
 */
describe('PlayerComparePage: the comparison modal (issue #310)', () => {
  beforeEach(() => {
    mockedCompare.mockReset()
    mockedCareer.mockReset()
    mockedSearch.mockReset()
    mockedCredits.mockReset()
    mockedCredits.mockResolvedValue({
      methodologies: [],
      data_sources: DATA_SOURCES,
    })
    searchByQuery()
  })

  const shareButton = () => screen.queryByRole('button', { name: /^Share/ })

  it('a link to a pair opens the comparison over the form, with no click', async () => {
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    const dialog = await screen.findByRole('dialog', {
      name: 'Kurt Warner and Steve McNair',
    })
    expect(
      within(dialog).getByRole('table', {
        name: 'Kurt Warner and Steve McNair, regular season',
      }),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole('table', {
        name: 'Kurt Warner and Steve McNair, playoffs',
      }),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole('region', { name: 'Head to head' }),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Share this comparison' }),
    ).toBeInTheDocument()
    expect(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    ).toBeInTheDocument()
  })

  it('pressing Compare opens the comparison in the modal', async () => {
    const user = userEvent.setup()
    compareByPair([BRADY_VS_QUINN])

    renderPage()

    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Brady Quinn/)
    // Picking alone never opens it: nothing is asked until Compare.
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(compareButton())

    const dialog = await screen.findByRole('dialog', {
      name: 'Tom Brady and Brady Quinn',
    })
    expect(
      within(dialog).getByRole('table', {
        name: 'Tom Brady and Brady Quinn, regular season',
      }),
    ).toBeInTheDocument()
  })

  it('closing drops ?a&b from the URL, keeps both fields filled, and returns focus to Compare', async () => {
    const user = userEvent.setup()
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)
    const dialog = await screen.findByRole('dialog', {
      name: 'Kurt Warner and Steve McNair',
    })

    await user.click(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    )

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    // The address bar no longer names a comparison, so a reload comes back to
    // the form rather than to a comparison that was dismissed.
    expect(screen.getByTestId('location')).toBeEmptyDOMElement()
    // Dropping the query must not empty the fields: the pair is still there,
    // ready to be changed or compared again.
    expect(playerA()).toHaveValue('Kurt Warner')
    expect(playerB()).toHaveValue('Steve McNair')
    expect(compareButton()).toBeEnabled()
    expect(compareButton()).toHaveFocus()
  })

  it('shares an absolute link to the committed pair', async () => {
    const user = userEvent.setup()
    mockedCompare.mockResolvedValue(WARNER_VS_MCNAIR)

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)
    const dialog = await screen.findByRole('dialog', {
      name: 'Kurt Warner and Steve McNair',
    })

    // jsdom has no share sheet, and `userEvent.setup()` installs a clipboard
    // stub, so ShareButton takes its clipboard branch: what it copied is the
    // assertion.
    await user.click(
      within(dialog).getByRole('button', { name: 'Share this comparison' }),
    )

    expect(await within(dialog).findByRole('status')).toHaveTextContent(
      'Link copied',
    )
    expect(await navigator.clipboard.readText()).toBe(
      `${window.location.origin}/nfl/compare?a=${WARNER}&b=${MCNAIR}`,
    )
  })

  it('shows the narrator error state in the modal, with nothing to share', async () => {
    mockedCompare.mockRejectedValue(new VerdictNetworkError(NETWORK_ERROR_COPY))

    renderPage(`?a=${WARNER}&b=${MCNAIR}`)

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
    expect(shareButton()).not.toBeInTheDocument()
  })

  it('shows an unknown player in the modal, with nothing to share', async () => {
    mockedCompare.mockRejectedValue(
      new PlayerApiError(404, {
        error: 'unknown_player',
        player_id: 1,
        sport: 'nfl',
      }),
    )

    renderPage(`?a=${WARNER}&b=1`)

    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      PLAYER_NOT_FOUND_COPY,
    )
    expect(shareButton()).not.toBeInTheDocument()
  })

  it('shows the same player twice in the modal, with nothing to share', async () => {
    renderPage(`?a=${WARNER}&b=${WARNER}`)

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('alert')).toHaveTextContent(
      SAME_PLAYER_COPY,
    )
    expect(shareButton()).not.toBeInTheDocument()
    expect(mockedCompare).not.toHaveBeenCalled()
  })

  it('opens no modal for a lone ?a=<id> link, keeping the prompt on the form', async () => {
    mockedCareer.mockResolvedValue(KURT_WARNER_CAREER)

    renderPage(`?a=${WARNER}`)

    expect(
      await screen.findByText(pickOneMoreCopy('Kurt Warner')),
    ).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(playerA()).toHaveValue('Kurt Warner')
  })

  it('opens no modal with nobody picked', () => {
    renderPage()

    expect(screen.getByText(PICK_TWO_COPY)).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  /**
   * The close replaces the ?a&b entry, and keeping the fields is scoped to
   * that one arrival. Back and Forward onto the closed entry later are
   * ordinary navigations: they follow the URL, which names no comparison, so
   * the fields empty and the modal stays shut.
   */
  it('after closing, Back and Forward follow the URL and leave the modal closed', async () => {
    const user = userEvent.setup()
    compareByPair([BRADY_VS_QUINN])

    renderPage()
    await pick(user, playerA(), 'Brady', /Tom Brady/)
    await pick(user, playerB(), 'Brady', /Brady Quinn/)
    await user.click(compareButton())

    const dialog = await screen.findByRole('dialog', {
      name: 'Tom Brady and Brady Quinn',
    })
    await user.click(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    )
    expect(playerA()).toHaveValue('Tom Brady')

    await user.click(screen.getByRole('button', { name: 'Go back' }))

    expect(screen.getByTestId('location')).toBeEmptyDOMElement()
    expect(playerA()).toHaveValue('')
    expect(playerB()).toHaveValue('')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Go forward' }))

    expect(screen.getByTestId('location')).toBeEmptyDOMElement()
    expect(playerA()).toHaveValue('')
    expect(playerB()).toHaveValue('')
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })
})
