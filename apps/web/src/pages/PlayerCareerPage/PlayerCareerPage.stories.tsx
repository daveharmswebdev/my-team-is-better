import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { within } from 'storybook/test'
import {
  CAREER_WITH_NULL_STATS,
  DATA_SOURCES,
  KURT_WARNER_CAREER,
} from '../../lib/playerFixtures'
import { PlayerCareerPage } from './PlayerCareerPage'

/**
 * Like AboutPage's stories, these drive the page through a stubbed
 * `window.fetch`: `/api/players/{id}` gets each story's handler, and
 * `/api/credits` the live data sources. Everything else falls through.
 */
function installFetch(career: () => Promise<Response>) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input.toString())
    if (url.pathname.startsWith('/api/players/')) {
      return career()
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

function jsonResponse(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function atPlayer(id: string) {
  return function RouterDecorator(Story: () => React.JSX.Element) {
    return (
      <MemoryRouter initialEntries={[`/nfl/players/${id}`]}>
        <Routes>
          <Route path="/nfl/players/:playerId" element={<Story />} />
        </Routes>
      </MemoryRouter>
    )
  }
}

const meta = {
  title: 'pages/PlayerCareerPage',
  component: PlayerCareerPage,
  tags: ['autodocs'],
} satisfies Meta<typeof PlayerCareerPage>

export default meta

type Story = StoryObj<typeof meta>

/** Kurt Warner on the committed fixture, with the one-game disclosure on 1999. */
export const Loaded: Story = {
  decorators: [
    (Story) => {
      installFetch(() => jsonResponse(200, KURT_WARNER_CAREER))
      return <Story />
    },
    atPlayer('2044124519'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('table', { name: 'Kurt Warner, playoffs' })
    await canvas.findByRole('link', { name: /nflfastR/ })
  },
}

/** Null games and stats, and no playoff games at all. */
export const NullStats: Story = {
  decorators: [
    (Story) => {
      installFetch(() => jsonResponse(200, CAREER_WITH_NULL_STATS))
      return <Story />
    },
    atPlayer('1001'),
  ],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText('No playoff games on record.')
  },
}

export const Loading: Story = {
  decorators: [
    (Story) => {
      installFetch(() => new Promise(() => {}))
      return <Story />
    },
    atPlayer('2044124519'),
  ],
}

/** A 404 `unknown_player`, in the narrator's voice. */
export const NotFound: Story = {
  decorators: [
    (Story) => {
      installFetch(() =>
        jsonResponse(404, {
          detail: { error: 'unknown_player', player_id: 1, sport: 'nfl' },
        }),
      )
      return <Story />
    },
    atPlayer('1'),
  ],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('alert')
  },
}

export const Error: Story = {
  decorators: [
    (Story) => {
      installFetch(() => Promise.resolve(new Response(null, { status: 503 })))
      return <Story />
    },
    atPlayer('2044124519'),
  ],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('alert')
  },
}
