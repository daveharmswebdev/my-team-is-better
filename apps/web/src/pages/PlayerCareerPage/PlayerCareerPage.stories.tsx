import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, within } from 'storybook/test'
import {
  CAREER_WITH_NULL_STATS,
  DATA_SOURCES,
  KURT_WARNER_CAREER,
  SMITH_VS_PETERSON,
} from '../../lib/playerFixtures'
import {
  creditsHandler,
  hang,
  httpError,
  playerCareerHandler,
  typedError,
} from '../../mocks/handlers'
import { PlayerCareerPage } from './PlayerCareerPage'

/**
 * Like AboutPage's stories, these drive the page through the API, faked with
 * the shared MSW handlers (issue #221): the meta serves `/api/credits` the
 * live data sources, and each story answers `/api/players/{id}` itself.
 */
function career(answer: Parameters<typeof playerCareerHandler>[0]) {
  return { msw: { handlers: { career: playerCareerHandler(answer) } } }
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
} satisfies Meta<typeof PlayerCareerPage>

export default meta

type Story = StoryObj<typeof meta>

/** Kurt Warner on the committed fixture, with the one-game disclosure on 1999. */
export const Loaded: Story = {
  decorators: [atPlayer('2044124519')],
  parameters: career(() => KURT_WARNER_CAREER),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('table', { name: 'Kurt Warner, playoffs' })
    await canvas.findByRole('link', { name: /nflfastR/ })
  },
}

/**
 * Emmitt Smith played 1990 to 2004 and the data opens in 1999 (#448): the
 * narrator says so above the tables, and the totals read "Seasons in our
 * books: 6 of 15 (1999–2004)", not a career.
 */
export const CareerCutOff: Story = {
  decorators: [atPlayer('2249533020')],
  parameters: career(() => SMITH_VS_PETERSON.a),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const table = await canvas.findByRole('table', {
      name: 'Emmitt Smith, regular season',
    })
    const callout = canvas.getByText(/^Emmitt Smith played 1990 to 2004\./)
    await expect(callout).toHaveAttribute('role', 'status')
    await expect(table).toHaveAccessibleDescription(
      expect.stringContaining(callout.textContent ?? ''),
    )
    await expect(
      within(table).getByRole('rowheader', {
        name: 'Seasons in our books: 6 of 15 (1999–2004)',
      }),
    ).toBeVisible()
  },
}

/** Null games and stats, and no playoff games at all. */
export const NullStats: Story = {
  decorators: [atPlayer('1001')],
  parameters: career(() => CAREER_WITH_NULL_STATS),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByText('No playoff games on record.')
  },
}

export const Loading: Story = {
  decorators: [atPlayer('2044124519')],
  parameters: career(hang),
}

/** A 404 `unknown_player`, in the narrator's voice. */
export const NotFound: Story = {
  decorators: [atPlayer('1')],
  parameters: career(() =>
    typedError(404, { error: 'unknown_player', player_id: 1, sport: 'nfl' }),
  ),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('alert')
  },
}

export const Error: Story = {
  decorators: [atPlayer('2044124519')],
  parameters: career(() => httpError(503)),
  play: async ({ canvasElement }) => {
    await within(canvasElement).findByRole('alert')
  },
}
