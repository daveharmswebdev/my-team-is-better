import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, waitFor, within } from 'storybook/test'
import {
  PICK_FROM_LIST_COPY,
  PICK_TWO_COPY,
  SAME_PLAYER_COPY,
  groupSingular,
  notComparableCopy,
  pickOneMoreCopy,
  restrictionCopy,
  uncomparableCopy,
} from '../../lib/playerCompare'
import {
  DATA_SOURCES,
  HILL_VS_LAMB,
  JEFF_WILKINS_CAREER,
  KURT_WARNER_CAREER,
  MARSHALL_FAULK_CAREER,
  NEVER_MET_COMPARISON,
  SEARCH_FARMER_RB,
  SEARCH_MCNAIR,
  WARNER_VS_MCNAIR,
} from '../../lib/playerFixtures'
import { NETWORK_ERROR_COPY } from '../../lib/api/client'
import { PLAYER_NOT_FOUND_COPY } from '../../lib/playerStats'
import { PlayerComparePage } from './PlayerComparePage'

type Handler = () => Promise<Response>

interface Handlers {
  compare?: Handler
  /** Gets the id asked for, for a story that looks up more than one. */
  career?: (playerId: number) => Promise<Response>
  /** `/api/players/search`; the fixture's McNair row when not given. */
  search?: (query: string, group: string | null) => Promise<Response>
}

/**
 * Like PlayerCareerPage's stories, these drive the page through a stubbed
 * `window.fetch`: `/api/players/compare` and `/api/players/{id}` get each
 * story's handlers, `/api/players/search` the fixture's McNair row, and
 * `/api/credits` the live data sources. Everything else falls through.
 */
function installFetch(handlers: Handlers) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input.toString())
    if (url.pathname === '/api/players/compare') {
      return (handlers.compare ?? never)()
    }
    if (url.pathname === '/api/players/search') {
      return handlers.search === undefined
        ? jsonResponse(200, SEARCH_MCNAIR)
        : handlers.search(
            url.searchParams.get('q') ?? '',
            url.searchParams.get('group'),
          )
    }
    if (url.pathname.startsWith('/api/players/')) {
      return (handlers.career ?? never)(
        Number(url.pathname.slice('/api/players/'.length)),
      )
    }
    if (url.pathname === '/api/credits') {
      return jsonResponse(200, {
        methodologies: [],
        data_sources: DATA_SOURCES,
      })
    }
    return realFetch(input, init)
  }) as typeof fetch
}

function never(): Promise<Response> {
  return new Promise(() => {})
}

function jsonResponse(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function atSearch(search: string, handlers: Handlers = {}) {
  return function RouterDecorator(Story: () => React.JSX.Element) {
    installFetch(handlers)
    return (
      <MemoryRouter initialEntries={[`/nfl/compare${search}`]}>
        <Routes>
          <Route path="/nfl/compare" element={<Story />} />
        </Routes>
      </MemoryRouter>
    )
  }
}

const WARNER = KURT_WARNER_CAREER.player_id
const MCNAIR = WARNER_VS_MCNAIR.b.player_id

/** The modal's name before the answer names both players (issue #310). */
const COMPARISON_TITLE = 'The comparison'
const WARNER_AND_MCNAIR = 'Kurt Warner and Steve McNair'

const playerB = (canvas: ReturnType<typeof within>) =>
  canvas.getByLabelText('Player B', { exact: true })

const meta = {
  title: 'pages/PlayerComparePage',
  component: PlayerComparePage,
  tags: ['autodocs'],
} satisfies Meta<typeof PlayerComparePage>

export default meta

type Story = StoryObj<typeof meta>

export const NothingPicked: Story = {
  decorators: [atSearch('')],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(PICK_TWO_COPY)
    // Nothing asked yet, so nothing opens over the form (issue #310).
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/** Opened from Kurt Warner's career page: a prompt, not an answer. */
export const OnePicked: Story = {
  decorators: [
    atSearch(`?a=${WARNER}`, {
      career: () => jsonResponse(200, KURT_WARNER_CAREER),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(pickOneMoreCopy('Kurt Warner'))
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/** Player B's typeahead open on "McNair", from the one-picked state. */
export const PickingPlayerB: Story = {
  decorators: [
    atSearch(`?a=${WARNER}`, {
      career: () => jsonResponse(200, KURT_WARNER_CAREER),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    // Player B opens once Warner's career says he is a quarterback (#436).
    await canvas.findByText(restrictionCopy('QB'))
    await userEvent.type(playerB(canvas), 'McNair')
    await expect(
      await canvas.findByRole('option', { name: /Steve McNair/ }),
    ).toBeVisible()
  },
}

/**
 * Text typed into Player B but nothing picked from the list (issue #304):
 * Compare stays disabled and says why.
 */
export const TypedNotPicked: Story = {
  decorators: [
    atSearch(`?a=${WARNER}`, {
      career: () => jsonResponse(200, KURT_WARNER_CAREER),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(pickOneMoreCopy('Kurt Warner'))
    await userEvent.type(playerB(canvas), 'McN')
    await expect(canvas.getByText(PICK_FROM_LIST_COPY)).toBeVisible()
    await expect(canvas.getByRole('button', { name: 'Compare' })).toBeDisabled()
  },
}

/**
 * Steve McNair picked into Player B, then Compare pressed (issue #304): the
 * comparison opens over the form (issue #310).
 */
export const PickedAndCompared: Story = {
  decorators: [
    atSearch(`?a=${WARNER}`, {
      career: () => jsonResponse(200, KURT_WARNER_CAREER),
      compare: () => jsonResponse(200, WARNER_VS_MCNAIR),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(pickOneMoreCopy('Kurt Warner'))
    await userEvent.type(playerB(canvas), 'McNair')
    await userEvent.click(
      await canvas.findByRole('option', { name: /Steve McNair/ }),
    )
    const compare = canvas.getByRole('button', { name: 'Compare' })
    await expect(compare).toBeEnabled()
    await expect(canvas.queryByRole('dialog')).toBeNull()

    await userEvent.click(compare)

    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    await within(dialog).findByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    })
  },
}

/**
 * A lone `?a=<id>` link whose career lookup couldn't be reached: the
 * narrator's line stays on the form while the fields hold only that pick.
 */
export const LoneLinkCareerFailed: Story = {
  decorators: [
    atSearch(`?a=${WARNER}`, {
      career: () => Promise.reject(new TypeError('Failed to fetch')),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/**
 * The same failed lone link, then Steve McNair picked over it into Player A
 * (issue #367): the failure was about the lone pick, so it goes. Player B
 * waits on Player A's group (#436), so he is the only other pick to make.
 */
export const LoneLinkCareerFailedThenPicked: Story = {
  decorators: [
    atSearch(`?a=${WARNER}`, {
      career: () => Promise.reject(new TypeError('Failed to fetch')),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('alert')
    await expect(playerB(canvas)).toBeDisabled()
    const playerA = canvas.getByLabelText('Player A', { exact: true })
    await userEvent.clear(playerA)
    await userEvent.type(playerA, 'McNair')
    await userEvent.click(
      await canvas.findByRole('option', { name: /Steve McNair/ }),
    )
    await expect(playerB(canvas)).toBeEnabled()
    await expect(canvas.queryByRole('alert')).toBeNull()
  },
}

export const SamePlayer: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${WARNER}`)],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(within(dialog).getByRole('alert')).toHaveTextContent(
      SAME_PLAYER_COPY,
    )
    // Nothing to share: there is no comparison.
    await expect(canvas.queryByRole('button', { name: /^Share/ })).toBeNull()
  },
}

export const Loading: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`, { compare: never })],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(within(dialog).getByRole('status')).toHaveTextContent(
      'Loading the comparison',
    )
  },
}

/** Kurt Warner and Steve McNair on the committed fixture, in the modal. */
export const Loaded: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=${MCNAIR}`, {
      compare: () => jsonResponse(200, WARNER_VS_MCNAIR),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    await modal.findByRole('table', {
      name: 'Kurt Warner and Steve McNair, playoffs',
    })
    await modal.findByRole('region', { name: 'Head to head' })
    // The credit travels with the numbers it credits.
    await modal.findByRole('link', { name: /nflfastR/ })
    await expect(
      modal.getByRole('button', { name: 'Share this comparison' }),
    ).toBeVisible()
  },
}

/**
 * Closing returns to the form with both fields still filled (issue #310), so
 * the pair can be changed or compared again.
 */
export const ClosedAfterComparing: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=${MCNAIR}`, {
      compare: () => jsonResponse(200, WARNER_VS_MCNAIR),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    )

    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(
      canvas.getByLabelText('Player A', { exact: true }),
    ).toHaveValue('Kurt Warner')
    await expect(playerB(canvas)).toHaveValue('Steve McNair')
    await expect(canvas.getByRole('button', { name: 'Compare' })).toBeEnabled()
    // The form holds two players, so it doesn't ask for two (issue #324).
    await expect(canvas.queryByText(PICK_TWO_COPY)).toBeNull()
  },
}

/**
 * A link whose comparison failed, closed (issue #308): the fields hold the
 * link's players by id, since nothing named them, and Compare -- focused --
 * asks for the same pair again without a reload.
 */
export const ClosedAfterFailedLink: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=${MCNAIR}`, {
      compare: () => Promise.reject(new TypeError('Failed to fetch')),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await within(dialog).findByRole('alert')

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    )

    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(
      canvas.getByLabelText('Player A', { exact: true }),
    ).toHaveValue(`Player #${WARNER}`)
    await expect(playerB(canvas)).toHaveValue(`Player #${MCNAIR}`)
    const compare = canvas.getByRole('button', { name: 'Compare' })
    await expect(compare).toBeEnabled()
    await expect(compare).toHaveFocus()
    await expect(canvas.queryByText(PICK_TWO_COPY)).toBeNull()
  },
}

/**
 * Never met, and one of them with null stats and no playoff games. Both
 * quarterbacks, since only they get a head-to-head (#436).
 */
export const NeverMet: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=1001`, {
      compare: () =>
        jsonResponse(200, {
          ...NEVER_MET_COMPARISON,
          b: { ...NEVER_MET_COMPARISON.b, position: 'QB', group: 'QB' },
        }),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: 'Kurt Warner and Unrecorded Player',
    })
    await within(dialog).findByText(
      'Kurt Warner and Unrecorded Player never started against each other in the playoffs.',
    )
  },
}

/** A 404 `unknown_player`, in the narrator's voice. */
export const UnknownPlayer: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=1`, {
      compare: () =>
        jsonResponse(404, {
          detail: { error: 'unknown_player', player_id: 1, sport: 'nfl' },
        }),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      PLAYER_NOT_FOUND_COPY,
    )
    await expect(canvas.queryByRole('button', { name: /^Share/ })).toBeNull()
  },
}

export const NetworkError: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=${MCNAIR}`, {
      compare: () => Promise.reject(new TypeError('Failed to fetch')),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
    await expect(canvas.queryByRole('button', { name: /^Share/ })).toBeNull()
  },
}

// ---------------------------------------------------------------------------
// Comparing like with like (issue #436). Everything below is copied from the
// API on the committed fixture db.
// ---------------------------------------------------------------------------

/**
 * Marshall Faulk as Player A: the page names the restriction, and Player B's
 * typeahead searches running backs only.
 */
export const RestrictedToRunningBacks: Story = {
  decorators: [
    atSearch(`?a=${MARSHALL_FAULK_CAREER.player_id}`, {
      career: () => jsonResponse(200, MARSHALL_FAULK_CAREER),
      search: (query, group) =>
        jsonResponse(
          200,
          group === 'RB' && query === 'farmer'
            ? SEARCH_FARMER_RB
            : { ...SEARCH_FARMER_RB, query, group, rows: [] },
        ),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByText(restrictionCopy('RB'))).toBeVisible()
    await userEvent.type(playerB(canvas), 'farmer')
    await expect(
      await canvas.findByRole('option', { name: /Robert Farmer/ }),
    ).toBeVisible()
  },
}

/**
 * A shared link to a quarterback and a running back: refused in the
 * narrator's voice, never shown. Kurt Warner stays as Player A; Player B is
 * empty and ready for another quarterback.
 */
export const MixedLinkRefused: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=2464876093`, {
      compare: () =>
        jsonResponse(400, {
          detail: {
            error: 'players_not_comparable',
            a_group: 'QB',
            b_group: 'RB',
          },
        }),
      career: () => jsonResponse(200, KURT_WARNER_CAREER),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByRole('alert')).toHaveTextContent(
      notComparableCopy('QB', groupSingular('RB')),
    )
    // The modal that showed "Loading" closes as the form takes the refusal.
    await waitFor(() => expect(canvas.queryByRole('dialog')).toBeNull())
    await expect(
      await canvas.findByDisplayValue('Kurt Warner'),
    ).toBeInTheDocument()
    await expect(playerB(canvas)).toHaveValue('')
    await expect(playerB(canvas)).toBeEnabled()
  },
}

/** Jeff Wilkins, a kicker, as Player A: no group, so nobody to compare yet. */
export const UncomparablePlayerA: Story = {
  decorators: [
    atSearch(`?a=${JEFF_WILKINS_CAREER.player_id}`, {
      career: () => jsonResponse(200, JEFF_WILKINS_CAREER),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByText(uncomparableCopy('K'))).toBeVisible()
    await expect(playerB(canvas)).toBeDisabled()
  },
}

/** Tyreek Hill and CeeDee Lamb: careers side by side, no head-to-head. */
export const ReceiversCompared: Story = {
  decorators: [
    atSearch(`?a=${HILL_VS_LAMB.a.player_id}&b=${HILL_VS_LAMB.b.player_id}`, {
      compare: () => jsonResponse(200, HILL_VS_LAMB),
    }),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: 'Tyreek Hill and CeeDee Lamb',
    })
    const modal = within(dialog)
    await modal.findByRole('table', {
      name: 'Tyreek Hill and CeeDee Lamb, regular season',
    })
    await expect(
      modal.queryByRole('region', { name: 'Head to head' }),
    ).toBeNull()
  },
}
