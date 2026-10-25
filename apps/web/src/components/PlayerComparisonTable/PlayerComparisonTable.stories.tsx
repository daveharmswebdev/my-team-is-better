import type { Meta, StoryObj } from '@storybook/react-vite'
import {
  CAREER_WITH_NULL_STATS,
  HILL_VS_LAMB,
  KURT_WARNER_CAREER,
  SMITH_VS_PETERSON,
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
    group: 'QB',
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

/**
 * Stats one side didn't record read "not recorded", and their rows stay
 * unmarked. The other player has no group, so the rows are the stats either
 * recorded (#352).
 */
export const NullStats: Story = {
  args: {
    group: null,
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

/**
 * Two backs (#438): rushing then receiving. Emmitt Smith's one touchdown
 * pass brings no passing rows and no starter record.
 */
export const TwoBacks: Story = {
  args: {
    caption: 'Emmitt Smith and Adrian Peterson, regular season',
    a: { name: 'Emmitt Smith', totals: SMITH_VS_PETERSON.a.regular_season },
    b: {
      name: 'Adrian Peterson',
      totals: SMITH_VS_PETERSON.b.regular_season,
    },
    group: 'RB',
  },
}

/** Two receivers (#438): receiving only, not their handful of carries. */
export const TwoReceivers: Story = {
  args: {
    caption: 'Tyreek Hill and CeeDee Lamb, regular season',
    a: { name: 'Tyreek Hill', totals: HILL_VS_LAMB.a.regular_season },
    b: { name: 'CeeDee Lamb', totals: HILL_VS_LAMB.b.regular_season },
    group: 'WR',
  },
}

/**
 * Two pass rushers, who have no position group yet: the rows are the stats
 * they recorded (#352), with the founder's defense notes (#316) under the
 * table. The page doesn't compare them yet (#436); the table still can.
 */
export const Defenders: Story = {
  args: {
    caption: 'T.J. Watt and a 17.5-sack season, regular season',
    group: null,
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
