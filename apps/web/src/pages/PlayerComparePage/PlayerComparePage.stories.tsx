import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, within } from 'storybook/test'
import {
  PICK_FROM_LIST_COPY,
  PICK_TWO_COPY,
  SAME_PLAYER_COPY,
  pickOneMoreCopy,
} from '../../lib/playerCompare'
import {
  DATA_SOURCES,
  KURT_WARNER_CAREER,
  NEVER_MET_COMPARISON,
  SEARCH_MCNAIR,
  WARNER_VS_MCNAIR,
} from '../../lib/playerFixtures'
import { NETWORK_ERROR_COPY } from '../../lib/api/client'
import { PLAYER_NOT_FOUND_COPY } from '../../lib/playerStats'
import { PlayerComparePage } from './PlayerComparePage'

type Handler = () => Promise<Response>

interface Handlers {
  compare?: Handler
  career?: Handler
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
      return jsonResponse(200, SEARCH_MCNAIR)
    }
    if (url.pathname.startsWith('/api/players/')) {
      return (handlers.career ?? never)()
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
  },
}

/** Never met, and one of them with null stats and no playoff games. */
export const NeverMet: Story = {
  decorators: [
    atSearch(`?a=${WARNER}&b=1001`, {
      compare: () => jsonResponse(200, NEVER_MET_COMPARISON),
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
