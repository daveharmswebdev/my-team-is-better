import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, within } from 'storybook/test'
import type { PlayerLeadersOut } from '../../lib/api/types'
import {
  DATA_SOURCES,
  LEADERS_BY_RUSHING_TDS,
  LEADERS_BY_RUSHING_YARDS,
  LEADERS_BY_TDS,
  LEADERS_BY_YARDS,
  LEADERS_WITH_NULL_STATS,
} from '../../lib/playerFixtures'
import { PlayerLeadersPage } from './PlayerLeadersPage'

/**
 * Like AboutPage's stories, these drive the page through a stubbed
 * `window.fetch`: `/api/players/leaders` gets each story's handler, and
 * `/api/credits` the live data sources. Everything else falls through.
 */
function installFetch(leaders: (url: URL) => Promise<Response>) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input.toString())
    if (url.pathname === '/api/players/leaders') {
      return leaders(url)
    }
    if (url.pathname === '/api/credits') {
      return jsonResponse({ methodologies: [], data_sources: DATA_SOURCES })
    }
    return realFetch(input, init)
  }) as typeof fetch
}

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

/** Echoes the request's category, season type, sort and offset onto `page`, as the API does. */
function answering(page: PlayerLeadersOut) {
  return (url: URL) =>
    jsonResponse({
      ...page,
      category: url.searchParams.get('category') ?? page.category,
      season_type: url.searchParams.get('season_type') ?? page.season_type,
      sort: url.searchParams.get('sort') ?? page.sort,
      offset: Number(url.searchParams.get('offset') ?? page.offset),
    })
}

/**
 * The board each category asks for (issue #312): a different population and
 * different columns, which is why the page cannot just re-render the rows it
 * already has.
 */
function answeringByCategory(url: URL) {
  if (url.searchParams.get('category') === 'rushing') {
    const board =
      url.searchParams.get('sort') === 'rushing_tds'
        ? LEADERS_BY_RUSHING_TDS
        : LEADERS_BY_RUSHING_YARDS
    return answering(board)(url)
  }
  return answering(LEADERS_BY_YARDS)(url)
}

function atRoute(search = '') {
  return function RouterDecorator(Story: () => React.JSX.Element) {
    return (
      <MemoryRouter initialEntries={[`/nfl/leaders${search}`]}>
        <Routes>
          <Route path="/nfl/leaders" element={<Story />} />
        </Routes>
      </MemoryRouter>
    )
  }
}

const meta = {
  title: 'pages/PlayerLeadersPage',
  component: PlayerLeadersPage,
  tags: ['autodocs'],
} satisfies Meta<typeof PlayerLeadersPage>

export default meta

type Story = StoryObj<typeof meta>

export const Loaded: Story = {
  decorators: [
    (Story) => {
      installFetch(answering(LEADERS_BY_YARDS))
      return <Story />
    },
    atRoute(),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Tua Tagovailoa' })
    await canvas.findByRole('link', { name: /nflfastR/ })
  },
}

/** A real tie at rank 2, by passing TDs. */
export const TiedRanks: Story = {
  decorators: [
    (Story) => {
      installFetch(answering(LEADERS_BY_TDS))
      return <Story />
    },
    atRoute('?season_type=regular&sort=passing_tds&offset=0'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Steve Beuerlein' })
  },
}

export const NullStats: Story = {
  decorators: [
    (Story) => {
      installFetch(answering(LEADERS_WITH_NULL_STATS))
      return <Story />
    },
    atRoute(),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Unrecorded Player' })
  },
}

/** The playoffs switch, operated from the keyboard. */
export const Playoffs: Story = {
  decorators: [
    (Story) => {
      installFetch(answering(LEADERS_BY_YARDS))
      return <Story />
    },
    atRoute(),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Tua Tagovailoa' })
    canvas.getByRole('radio', { name: 'Regular season' }).focus()
    await userEvent.keyboard('{ArrowRight}')
    await canvas.findByRole('table', {
      name: 'NFL career leaders: playoffs, by passing yards',
    })
    await expect(canvas.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
  },
}

/** The rushing board, reached by its own URL (issue #312). */
export const Rushing: Story = {
  decorators: [
    (Story) => {
      installFetch(answeringByCategory)
      return <Story />
    },
    atRoute(
      '?category=rushing&season_type=regular&sort=rushing_yards&offset=0',
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Edgerrin James' })
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('rushing')
    await expect(
      canvas.queryByRole('columnheader', { name: 'Passing yards' }),
    ).toBeNull()
  },
}

/** Picking Rushing from the dropdown swaps the board, columns and all. */
export const CategorySwitch: Story = {
  decorators: [
    (Story) => {
      installFetch(answeringByCategory)
      return <Story />
    },
    atRoute(),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Tua Tagovailoa' })
    await userEvent.selectOptions(
      canvas.getByRole('combobox', { name: 'Stat category' }),
      'rushing',
    )
    await canvas.findByRole('table', {
      name: 'NFL career leaders: regular season, by rushing yards',
    })
    await canvas.findByRole('link', { name: 'Edgerrin James' })
  },
}

export const Loading: Story = {
  decorators: [
    (Story) => {
      installFetch(() => new Promise(() => {}))
      return <Story />
    },
    atRoute(),
  ],
}

export const Error: Story = {
  decorators: [
    (Story) => {
      installFetch(() => Promise.resolve(new Response(null, { status: 500 })))
      return <Story />
    },
    atRoute(),
  ],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('alert')
  },
}

export const Empty: Story = {
  decorators: [
    (Story) => {
      installFetch(answering({ ...LEADERS_BY_YARDS, total: 0, rows: [] }))
      return <Story />
    },
    atRoute(),
  ],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText(
      'No NFL player stats are loaded yet.',
    )
  },
}

export const PastTheEnd: Story = {
  decorators: [
    (Story) => {
      installFetch(answering({ ...LEADERS_BY_YARDS, rows: [] }))
      return <Story />
    },
    atRoute('?season_type=regular&sort=passing_yards&offset=500'),
  ],
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('button', {
      name: 'Back to the top',
    })
  },
}
