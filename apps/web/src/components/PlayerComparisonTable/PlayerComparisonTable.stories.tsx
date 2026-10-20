import type { Meta, StoryObj } from '@storybook/react-vite'
import {
  CAREER_WITH_NULL_STATS,
  HARRISON_VS_JAMES,
  KURT_WARNER_CAREER,
  MARE_VS_GOWIN,
  STEVE_MCNAIR_CAREER,
  TJ_WATT_CAREER,
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

/** A receiver and a back (#352): rushing and receiving rows, no passing or record row. */
export const ReceiverAndBack: Story = {
  args: {
    caption: 'Marvin Harrison and Edgerrin James, regular season',
    a: {
      name: 'Marvin Harrison',
      totals: HARRISON_VS_JAMES.a.regular_season,
    },
    b: {
      name: 'Edgerrin James',
      totals: HARRISON_VS_JAMES.b.regular_season,
    },
  },
}

/** A kicker and a punter (#352): the punter's missing longest field goal is a dash, unmarked. */
export const KickerAndPunter: Story = {
  args: {
    caption: 'Olindo Mare and Toby Gowin, regular season',
    a: { name: 'Olindo Mare', totals: MARE_VS_GOWIN.a.regular_season },
    b: { name: 'Toby Gowin', totals: MARE_VS_GOWIN.b.regular_season },
  },
}

/** Two pass rushers (#352): the defense rows, with the founder's notes (#316) under the table. */
export const Defenders: Story = {
  args: {
    caption: 'T.J. Watt and a 17.5-sack season, regular season',
    a: { name: 'T.J. Watt', totals: TJ_WATT_CAREER.regular_season },
    b: {
      name: 'Another pass rusher',
      totals: {
        ...TJ_WATT_CAREER.regular_season!,
        stats: { ...TJ_WATT_CAREER.regular_season!.stats, def_sacks: 17.5 },
      },
    },
  },
}
