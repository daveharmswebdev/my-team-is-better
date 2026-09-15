import type { Meta, StoryObj } from '@storybook/react-vite'
import {
  CAREER_WITH_NULL_STATS,
  KURT_WARNER_CAREER,
  STEVE_MCNAIR_CAREER,
} from '../../lib/playerFixtures'
import { PlayerComparisonTable } from './PlayerComparisonTable'

const meta = {
  title: 'components/PlayerComparisonTable',
  component: PlayerComparisonTable,
  tags: ['autodocs'],
  args: {
    caption: 'Kurt Warner and Steve McNair, regular season',
    a: { name: 'Kurt Warner', totals: KURT_WARNER_CAREER.regular_season },
    b: { name: 'Steve McNair', totals: STEVE_MCNAIR_CAREER.regular_season },
    noTotalsCopy: 'No regular-season games on record.',
  },
} satisfies Meta<typeof PlayerComparisonTable>

export default meta

type Story = StoryObj<typeof meta>

/** The committed fixture: Warner's 4,044 yards and 11 interceptions are both marked. */
export const RegularSeason: Story = {}

/** McNair's 4 playoff games are marked; 3-0 against 3-1 is equal wins, so unmarked. */
export const Playoffs: Story = {
  args: {
    caption: 'Kurt Warner and Steve McNair, playoffs',
    a: { name: 'Kurt Warner', totals: KURT_WARNER_CAREER.postseason },
    b: { name: 'Steve McNair', totals: STEVE_MCNAIR_CAREER.postseason },
    noTotalsCopy: 'No playoff games on record.',
  },
}

/** Stats one side didn't record read "not recorded", and their rows stay unmarked. */
export const NullStats: Story = {
  args: {
    caption: 'Kurt Warner and Unrecorded Player, regular season',
    b: {
      name: 'Unrecorded Player',
      totals: CAREER_WITH_NULL_STATS.regular_season,
    },
  },
}

/** One player has no playoff games: that player's column says so, and nothing is marked. */
export const NoTotalsForOne: Story = {
  args: {
    caption: 'Kurt Warner and Unrecorded Player, playoffs',
    a: { name: 'Kurt Warner', totals: KURT_WARNER_CAREER.postseason },
    b: { name: 'Unrecorded Player', totals: null },
    noTotalsCopy: 'No playoff games on record.',
  },
}
