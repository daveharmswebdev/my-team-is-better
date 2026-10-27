import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, within } from 'storybook/test'
import type { PlayerLeadersQuery } from '../../lib/api/client'
import type { PlayerLeadersOut } from '../../lib/api/types'
import {
  creditsHandler,
  hang,
  httpError,
  playerLeadersHandler,
} from '../../mocks/handlers'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
  EPA_EXPLANATION,
  STARTER_RECORD_NOTE,
  fgPctEmptyCopy,
  fgPctNote,
  rateMinimumEmptyCopy,
  rateMinimumNote,
} from '../../lib/playerStats'
import {
  DATA_SOURCES,
  DEFENSE_WITH_NULL_STATS,
  LEADERS_BY_DEF_SACKS,
  LEADERS_BY_EPA_PER_CARRY,
  LEADERS_BY_EPA_PER_CARRY_EMPTY,
  LEADERS_BY_EPA_PER_DROPBACK,
  LEADERS_BY_EPA_PER_DROPBACK_EMPTY,
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
 * Like AboutPage's stories, these drive the page through the API, faked with
 * the shared MSW handlers (issue #221): the meta serves `/api/credits` the
 * live data sources, and each story answers `/api/players/leaders` itself.
 */
function leaders(answer: Parameters<typeof playerLeadersHandler>[0]) {
  return { msw: { handlers: { leaders: playerLeadersHandler(answer) } } }
}

/** Echoes the request's category, season type, sort and offset onto `page`, as the API does. */
function answering(page: PlayerLeadersOut) {
  return (query: PlayerLeadersQuery): PlayerLeadersOut => ({
    ...page,
    category: query.category,
    season_type: query.season_type,
    sort: query.sort,
    offset: query.offset,
  })
}

/**
 * The board each category asks for (issue #312): a different population and
 * different columns, which is why the page cannot just re-render the rows it
 * already has.
 */
function answeringByCategory(query: PlayerLeadersQuery) {
  if (query.category === 'rushing') {
    const board =
      query.sort === 'rushing_tds'
        ? LEADERS_BY_RUSHING_TDS
        : LEADERS_BY_RUSHING_YARDS
    return answering(board)(query)
  }
  if (query.category === 'receiving') {
    const board =
      query.sort === 'receiving_tds'
        ? LEADERS_BY_RECEIVING_TDS
        : LEADERS_BY_RECEIVING_YARDS
    return answering(board)(query)
  }
  if (query.category === 'kicking') {
    const board =
      query.sort === 'fg_pct' ? LEADERS_BY_FG_PCT : LEADERS_BY_FG_MADE
    return answering(board)(query)
  }
  if (query.category === 'punting') {
    return answering(LEADERS_BY_PT_YARDS)(query)
  }
  if (query.category === 'defense') {
    return answering(LEADERS_BY_DEF_SACKS)(query)
  }
  return answering(LEADERS_BY_YARDS)(query)
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
  parameters: {
    msw: {
      handlers: {
        credits: creditsHandler(() => ({
          methodologies: [],
          data_sources: DATA_SOURCES,
        })),
      },
    },
  },
} satisfies Meta<typeof PlayerLeadersPage>

export default meta

type Story = StoryObj<typeof meta>

export const Loaded: Story = {
  decorators: [atRoute()],
  parameters: leaders(answering(LEADERS_BY_YARDS)),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Tua Tagovailoa' })
    await canvas.findByRole('link', { name: /nflfastR/ })
  },
}

/** A real tie at rank 2, by passing TDs. */
export const TiedRanks: Story = {
  decorators: [atRoute('?season_type=regular&sort=passing_tds&offset=0')],
  parameters: leaders(answering(LEADERS_BY_TDS)),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Steve Beuerlein' })
  },
}

export const NullStats: Story = {
  decorators: [atRoute()],
  parameters: leaders(answering(LEADERS_WITH_NULL_STATS)),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Unrecorded Player' })
  },
}

/** The playoffs switch, operated from the keyboard. */
export const Playoffs: Story = {
  decorators: [atRoute()],
  parameters: leaders(answering(LEADERS_BY_YARDS)),
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
    atRoute(
      '?category=rushing&season_type=regular&sort=rushing_yards&offset=0',
    ),
  ],
  parameters: leaders(answeringByCategory),
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
    atRoute(
      '?category=receiving&season_type=regular&sort=receiving_yards&offset=0',
    ),
  ],
  parameters: leaders(answeringByCategory),
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
  decorators: [atRoute()],
  parameters: leaders(answeringByCategory),
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
  decorators: [atRoute()],
  parameters: leaders(answeringByCategory),
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
    atRoute('?category=kicking&season_type=regular&sort=fg_made&offset=0'),
  ],
  parameters: leaders(answeringByCategory),
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
    atRoute('?category=kicking&season_type=regular&sort=fg_made&offset=0'),
  ],
  parameters: leaders(answeringByCategory),
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
    atRoute('?category=kicking&season_type=postseason&sort=fg_pct&offset=0'),
  ],
  parameters: leaders(answering(LEADERS_BY_FG_PCT_EMPTY)),
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
    atRoute('?category=punting&season_type=regular&sort=pt_yards&offset=0'),
  ],
  parameters: leaders(answeringByCategory),
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
    atRoute('?category=defense&season_type=regular&sort=def_sacks&offset=0'),
  ],
  parameters: leaders(answering(DEFENSE_WITH_NULL_STATS)),
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
  decorators: [atRoute()],
  parameters: leaders(answeringByCategory),
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
  decorators: [atRoute()],
  parameters: leaders(hang),
}

export const Error: Story = {
  decorators: [atRoute()],
  parameters: leaders(() => httpError(500)),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('alert')
  },
}

export const Empty: Story = {
  decorators: [atRoute()],
  parameters: leaders(answering({ ...LEADERS_BY_YARDS, total: 0, rows: [] })),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText(
      'No NFL player stats are loaded yet.',
    )
  },
}

export const PastTheEnd: Story = {
  decorators: [atRoute('?season_type=regular&sort=passing_yards&offset=500')],
  parameters: leaders(answering({ ...LEADERS_BY_YARDS, rows: [] })),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('button', {
      name: 'Back to the top',
    })
  },
}

/** Any board with an EPA rate on it: the passing board by default, or the rushing one (#347). */
function answeringEpa(query: PlayerLeadersQuery) {
  if (query.sort === 'epa_per_dropback') {
    return answering(LEADERS_BY_EPA_PER_DROPBACK)(query)
  }
  if (query.sort === 'epa_per_carry') {
    return answering(LEADERS_BY_EPA_PER_CARRY)(query)
  }
  return answeringByCategory(query)
}

/**
 * Sorting Passing by EPA per dropback (#347), invented rows at the full
 * build's rates: the minimum is stated and describes the table, beside the
 * starter-record note, and the EP model is credited.
 */
export const PassingByEpaPerDropback: Story = {
  decorators: [atRoute()],
  parameters: leaders(answeringEpa),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Tua Tagovailoa' })
    await userEvent.click(
      canvas.getByRole('button', { name: 'EPA per dropback' }),
    )
    const table = await canvas.findByRole('table', {
      name: 'NFL career leaders: regular season, by EPA per dropback',
    })
    await canvas.findByRole('link', { name: 'Peyton Manning' })
    await expect(table).toHaveAccessibleDescription(
      `${STARTER_RECORD_NOTE} ${rateMinimumNote('epa_per_dropback', 'regular') ?? ''}`,
    )
    await expect(canvas.getByText(/nflfastR's EP model/)).toBeInTheDocument()
  },
}

/** The rushing board by EPA per carry (#347), with the explanation opened. */
export const RushingByEpaPerCarryExplained: Story = {
  decorators: [
    atRoute('?category=rushing&season_type=regular&sort=epa_per_carry'),
  ],
  parameters: leaders(answeringEpa),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('link', { name: 'Josh Allen' })
    await expect(
      canvas.getByText(rateMinimumNote('epa_per_carry', 'regular') ?? ''),
    ).toBeInTheDocument()
    await userEvent.click(canvas.getByRole('button', { name: 'What is EPA?' }))
    await expect(
      canvas.getByRole('region', { name: 'What is EPA?' }),
    ).toHaveTextContent(EPA_EXPLANATION)
  },
}

/**
 * The EPA per dropback board when nobody has reached the minimum, as on
 * the committed two-season fixture (#347): it says so, and offers the
 * default sort.
 */
export const PassingEpaPerDropbackEmpty: Story = {
  decorators: [
    atRoute('?category=passing&season_type=regular&sort=epa_per_dropback'),
  ],
  parameters: leaders(answering(LEADERS_BY_EPA_PER_DROPBACK_EMPTY)),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(
      rateMinimumEmptyCopy('epa_per_dropback', 'regular') ?? '',
    )
    await expect(
      canvas.getByRole('button', { name: 'Rank by passing yards' }),
    ).toBeInTheDocument()
  },
}

/** The playoff EPA per carry board, empty: nobody has 110 playoff carries here (#347). */
export const RushingEpaPerCarryEmpty: Story = {
  decorators: [
    atRoute('?category=rushing&season_type=postseason&sort=epa_per_carry'),
  ],
  parameters: leaders(answering(LEADERS_BY_EPA_PER_CARRY_EMPTY)),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(
      rateMinimumEmptyCopy('epa_per_carry', 'postseason') ?? '',
    )
    await expect(
      canvas.getByText(rateMinimumNote('epa_per_carry', 'postseason') ?? ''),
    ).toBeInTheDocument()
  },
}
