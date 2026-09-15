import type { Meta, StoryObj } from '@storybook/react-vite'
import {
  CAREER_WITH_NULL_STATS,
  KURT_WARNER_CAREER,
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
