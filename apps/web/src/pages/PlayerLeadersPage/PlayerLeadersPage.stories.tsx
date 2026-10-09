import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, within } from 'storybook/test'
import type { PlayerLeadersOut } from '../../lib/api/types'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
  fgPctEmptyCopy,
  fgPctNote,
} from '../../lib/playerStats'
import {
  DATA_SOURCES,
  DEFENSE_WITH_NULL_STATS,
  LEADERS_BY_DEF_SACKS,
  LEADERS_BY_FG_MADE,
  LEADERS_BY_FG_PCT,
  LEADERS_BY_FG_PCT_EMPTY,
  LEADERS_BY_PT_YARDS,
  LEADERS_BY_RECEIVING_TDS,
  LEADERS_BY_RECEIVING_YARDS,
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
  if (url.searchParams.get('category') === 'receiving') {
    const board =
      url.searchParams.get('sort') === 'receiving_tds'
        ? LEADERS_BY_RECEIVING_TDS
        : LEADERS_BY_RECEIVING_YARDS
    return answering(board)(url)
  }
  if (url.searchParams.get('category') === 'kicking') {
    const board =
      url.searchParams.get('sort') === 'fg_pct'
        ? LEADERS_BY_FG_PCT
        : LEADERS_BY_FG_MADE
    return answering(board)(url)
  }
  if (url.searchParams.get('category') === 'punting') {
    return answering(LEADERS_BY_PT_YARDS)(url)
  }
  if (url.searchParams.get('category') === 'defense') {
    return answering(LEADERS_BY_DEF_SACKS)(url)
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

/** The receiving board, reached by its own URL (issue #314). */
export const Receiving: Story = {
  decorators: [
    (Story) => {
      installFetch(answeringByCategory)
      return <Story />
    },
    atRoute(
      '?category=receiving&season_type=regular&sort=receiving_yards&offset=0',
    ),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Tyreek Hill' })
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('receiving')
    await expect(
      canvas.getByRole('columnheader', { name: 'Receiving yards' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(
      canvas.queryByRole('columnheader', { name: 'Rushing yards' }),
    ).toBeNull()
  },
}

/** Picking Receiving, then sorting by Receiving TDs: the three-way tie at 1. */
export const ReceivingSwitch: Story = {
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
      'receiving',
    )
    await canvas.findByRole('table', {
      name: 'NFL career leaders: regular season, by receiving yards',
    })
    await userEvent.click(
      await canvas.findByRole('button', { name: 'Receiving TDs' }),
    )
    await canvas.findByRole('table', {
      name: 'NFL career leaders: regular season, by receiving TDs',
    })
    await canvas.findByRole('link', { name: 'Cris Carter' })
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

/** The kicking board, reached by its own URL (issue #315). */
export const Kicking: Story = {
  decorators: [
    (Story) => {
      installFetch(answeringByCategory)
      return <Story />
    },
    atRoute('?category=kicking&season_type=regular&sort=fg_made&offset=0'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Olindo Mare' })
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('kicking')
    await expect(
      canvas.getByRole('columnheader', { name: 'FG made' }),
    ).toHaveAttribute('aria-sort', 'descending')
    await expect(canvas.queryByText(fgPctNote('regular'))).toBeNull()
  },
}

/**
 * Sorting the kicking board by FG% (issue #315): the one sort with an attempts
 * minimum, so the page states it and describes the table with it.
 */
export const KickingByFieldGoalPercentage: Story = {
  decorators: [
    (Story) => {
      installFetch(answeringByCategory)
      return <Story />
    },
    atRoute('?category=kicking&season_type=regular&sort=fg_made&offset=0'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Olindo Mare' })
    await userEvent.click(canvas.getByRole('button', { name: 'FG%' }))
    const table = await canvas.findByRole('table', {
      name: 'NFL career leaders: regular season, by field-goal percentage',
    })
    await expect(table).toHaveAccessibleDescription(fgPctNote('regular'))
  },
}

/**
 * The FG% board when no kicker has reached the attempts minimum, as on the
 * committed two-season fixture: it says so, and offers the default sort.
 */
export const KickingFieldGoalPercentageEmpty: Story = {
  decorators: [
    (Story) => {
      installFetch(answering(LEADERS_BY_FG_PCT_EMPTY))
      return <Story />
    },
    atRoute('?category=kicking&season_type=postseason&sort=fg_pct&offset=0'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(fgPctEmptyCopy('postseason'))
    await expect(
      canvas.getByRole('button', { name: 'Rank by field goals made' }),
    ).toBeInTheDocument()
    await expect(canvas.getByText(fgPctNote('postseason'))).toBeInTheDocument()
  },
}

/** The punting board, reached by its own URL (issue #315). */
export const Punting: Story = {
  decorators: [
    (Story) => {
      installFetch(answeringByCategory)
      return <Story />
    },
    atRoute('?category=punting&season_type=regular&sort=pt_yards&offset=0'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Thomas Morstead' })
    await expect(
      canvas.getByRole('columnheader', { name: 'Yards' }),
    ).toHaveAttribute('aria-sort', 'descending')
  },
}

/**
 * The defense board (issue #317), with a half sack and stats the source
 * didn't track, and the founder's two notes (#316) in the box above the
 * table, each describing the headers it covers.
 */
export const Defense: Story = {
  decorators: [
    (Story) => {
      installFetch(answering(DEFENSE_WITH_NULL_STATS))
      return <Story />
    },
    atRoute('?category=defense&season_type=regular&sort=def_sacks&offset=0'),
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'T.J. Watt' })
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('defense')
    await expect(canvas.getByText('19.0')).toBeInTheDocument()
    await expect(canvas.getByText('0.5')).toBeInTheDocument()
    const about = canvas.getByRole('region', { name: 'About these numbers' })
    await expect(within(about).getByText(DEFENSE_EARLY_ERA_NOTE)).toBeVisible()
    await expect(within(about).getByText(DEFENSE_UNOFFICIAL_NOTE)).toBeVisible()
    await expect(
      canvas.getByRole('button', { name: 'Passes defended' }),
    ).toHaveAccessibleDescription(DEFENSE_UNOFFICIAL_NOTE)
  },
}

/** Defense, chosen from the dropdown: the board and both notes arrive together. */
export const DefenseChosen: Story = {
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
      'defense',
    )
    await canvas.findByRole('table', {
      name: 'NFL career leaders: regular season, by sacks',
    })
    await expect(canvas.getAllByText('17.5')).toHaveLength(2)
    await expect(canvas.getByText(DEFENSE_EARLY_ERA_NOTE)).toBeVisible()
    await expect(canvas.getByText(DEFENSE_UNOFFICIAL_NOTE)).toBeVisible()
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
