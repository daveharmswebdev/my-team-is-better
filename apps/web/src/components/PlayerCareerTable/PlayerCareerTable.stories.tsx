import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, within } from 'storybook/test'
import {
  CAREER_WITH_NULL_STATS,
  EDGERRIN_JAMES_CAREER,
  KURT_WARNER_CAREER,
  MARVIN_HARRISON_CAREER,
  OLINDO_MARE_CAREER,
  SMITH_VS_PETERSON,
  TJ_WATT_CAREER,
  TOBY_GOWIN_CAREER,
  WARNER_1999_POSTSEASON,
  WARNER_1999_REGULAR,
} from '../../lib/playerFixtures'
import { PlayerCareerTable } from './PlayerCareerTable'

const meta = {
  title: 'components/PlayerCareerTable',
  component: PlayerCareerTable,
  tags: ['autodocs'],
  args: {
    caption: 'Kurt Warner, regular season',
    lines: [WARNER_1999_REGULAR],
    totals: KURT_WARNER_CAREER.regular_season,
  },
} satisfies Meta<typeof PlayerCareerTable>

export default meta

type Story = StoryObj<typeof meta>

/** 1999: one Rams game has no stat lines in the source, and the line says so. */
export const WithMissingStatLines: Story = {}

export const Playoffs: Story = {
  args: {
    caption: 'Kurt Warner, playoffs',
    lines: [WARNER_1999_POSTSEASON],
    totals: KURT_WARNER_CAREER.postseason,
  },
}

/**
 * A career that began before the data (#448): the totals row reads what's
 * in the books, "Seasons in our books: 6 of 15 (1999–2004)", not a career.
 */
export const CareerCutOff: Story = {
  args: {
    caption: 'Emmitt Smith, regular season',
    lines: SMITH_VS_PETERSON.a.seasons.filter(
      (line) => line.season_type === 'regular',
    ),
    totals: SMITH_VS_PETERSON.a.regular_season,
    coverage: SMITH_VS_PETERSON.a.coverage,
  },
}

/** Games and stats the source didn't track read "not recorded". */
export const NullStats: Story = {
  args: {
    caption: 'Unrecorded Player, regular season',
    lines: CAREER_WITH_NULL_STATS.seasons,
    totals: CAREER_WITH_NULL_STATS.regular_season,
  },
}

/** Several seasons, and more than one team in a season. */
export const SeveralSeasons: Story = {
  args: {
    lines: [
      WARNER_1999_REGULAR,
      {
        ...WARNER_1999_REGULAR,
        season: 2000,
        teams: ['St. Louis Rams', 'New York Giants'],
        games_without_stat_lines: 2,
      },
    ],
    totals: {
      ...KURT_WARNER_CAREER.regular_season!,
      seasons: 2,
    },
  },
}

/** A receiver (#352): receiving, and rushing for his one carry; no passing, no starter record. */
export const Receiver: Story = {
  args: {
    caption: 'Marvin Harrison, regular season',
    lines: MARVIN_HARRISON_CAREER.seasons.slice(0, 1),
    totals: MARVIN_HARRISON_CAREER.regular_season,
  },
}

/** A back (#352): rushing, with first downs and fumbles lost, then receiving. */
export const RunningBack: Story = {
  args: {
    caption: 'Edgerrin James, regular season',
    lines: EDGERRIN_JAMES_CAREER.seasons.slice(0, 1),
    totals: EDGERRIN_JAMES_CAREER.regular_season,
  },
}

/** A kicker who punted once (#352): kicking, then punting. */
export const Kicker: Story = {
  args: {
    caption: 'Olindo Mare, regular season',
    lines: OLINDO_MARE_CAREER.seasons.slice(0, 1),
    totals: OLINDO_MARE_CAREER.regular_season,
  },
}

/** A punter who never made a field goal (#352): his longest reads as a dash, "none" to assistive tech. */
export const Punter: Story = {
  args: {
    caption: 'Toby Gowin, regular season',
    lines: TOBY_GOWIN_CAREER.seasons.slice(0, 1),
    totals: TOBY_GOWIN_CAREER.regular_season,
  },
}

/**
 * A quarterback's EPA columns (#347): EPA per dropback closes the passing
 * columns and EPA per carry the rushing ones, derived for each line and the
 * totals. A second line with no carries shows a dash, read as "none".
 */
export const WithEpaColumns: Story = {
  args: {
    caption: 'Kurt Warner, regular season',
    lines: [
      WARNER_1999_REGULAR,
      {
        ...WARNER_1999_REGULAR,
        season: 2000,
        games_without_stat_lines: 0,
        stats: {
          ...WARNER_1999_REGULAR.stats,
          carries: 0,
          rushing_yards: 0,
          rushing_tds: 0,
          rushing_epa: null,
        },
      },
    ],
    totals: null,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('columnheader', { name: 'EPA per dropback' }),
    ).toBeInTheDocument()
    await expect(canvas.getByRole('cell', { name: '−0.183' })).toBeVisible()
    await expect(canvas.getByRole('cell', { name: 'none' })).toBeVisible()
  },
}

/** A defender (#352): the defense columns, with the founder's notes (#316) under the table. */
export const Defender: Story = {
  args: {
    caption: 'T.J. Watt, regular season',
    lines: TJ_WATT_CAREER.seasons,
    totals: TJ_WATT_CAREER.regular_season,
  },
}
