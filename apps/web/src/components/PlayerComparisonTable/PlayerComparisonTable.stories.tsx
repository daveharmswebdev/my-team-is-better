import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, within } from 'storybook/test'
import {
  CAREER_WITH_NULL_STATS,
  FAULK_VS_FARMER,
  HILL_VS_LAMB,
  KURT_WARNER_CAREER,
  SMITH_VS_PETERSON,
  STEVE_MCNAIR_CAREER,
  TJ_WATT_CAREER,
  fixtureCoverage,
} from '../../lib/playerFixtures'
import { MARK_SCREEN_READER_TEXT } from '../../lib/playerCompare'
import { PlayerComparisonTable } from './PlayerComparisonTable'

/**
 * A career wholly inside the data, so a story shows the #301 marks alone.
 * The cut-off stories below use the fixtures' real coverage (#448).
 */
const IN_THE_BOOKS = fixtureCoverage(1999, 1999, 1999, 1999)

const meta = {
  title: 'components/PlayerComparisonTable',
  component: PlayerComparisonTable,
  tags: ['autodocs'],
  args: {
    caption: 'Kurt Warner and Steve McNair, regular season',
    a: {
      name: 'Kurt Warner',
      totals: KURT_WARNER_CAREER.regular_season,
      coverage: IN_THE_BOOKS,
    },
    b: {
      name: 'Steve McNair',
      totals: STEVE_MCNAIR_CAREER.regular_season,
      coverage: IN_THE_BOOKS,
    },
    noTotalsCopy: 'No regular-season games on record.',
    group: 'QB',
  },
} satisfies Meta<typeof PlayerComparisonTable>

export default meta

type Story = StoryObj<typeof meta>

/**
 * Neither career cut off by the data: Warner's 4,044 yards and 11
 * interceptions are both marked.
 */
export const RegularSeason: Story = {}

/** McNair's 4 playoff games are marked; 3-0 against 3-1 is equal wins, so unmarked. */
export const Playoffs: Story = {
  args: {
    caption: 'Kurt Warner and Steve McNair, playoffs',
    a: {
      name: 'Kurt Warner',
      totals: KURT_WARNER_CAREER.postseason,
      coverage: IN_THE_BOOKS,
    },
    b: {
      name: 'Steve McNair',
      totals: STEVE_MCNAIR_CAREER.postseason,
      coverage: IN_THE_BOOKS,
    },
    noTotalsCopy: 'No playoff games on record.',
  },
}

/**
 * Faulk's career began in 1994, before the data (#448): no total is
 * marked, and his seasons read "1 of 13 (1999)".
 */
export const OneCutOff: Story = {
  args: {
    caption: 'Marshall Faulk and Robert Farmer, regular season',
    a: {
      name: 'Marshall Faulk',
      totals: FAULK_VS_FARMER.a.regular_season,
      coverage: FAULK_VS_FARMER.a.coverage,
    },
    b: {
      name: 'Robert Farmer',
      totals: FAULK_VS_FARMER.b.regular_season,
      coverage: FAULK_VS_FARMER.b.coverage,
    },
    group: 'RB',
  },
  play: async ({ canvasElement }) => {
    const table = within(canvasElement).getByRole('table')
    await expect(table).not.toHaveTextContent(MARK_SCREEN_READER_TEXT)
    await expect(table).toHaveTextContent('1 of 13 (1999)')
  },
}

/** Warner (1998) and McNair (1995) both began before the data: nothing marked (#448). */
export const BothCutOff: Story = {
  args: {
    a: {
      name: 'Kurt Warner',
      totals: KURT_WARNER_CAREER.regular_season,
      coverage: KURT_WARNER_CAREER.coverage,
    },
    b: {
      name: 'Steve McNair',
      totals: STEVE_MCNAIR_CAREER.regular_season,
      coverage: STEVE_MCNAIR_CAREER.coverage,
    },
  },
  play: async ({ canvasElement }) => {
    const table = within(canvasElement).getByRole('table')
    await expect(table).not.toHaveTextContent(MARK_SCREEN_READER_TEXT)
    await expect(table).toHaveTextContent('1 of 12 (1999)')
    await expect(table).toHaveTextContent('1 of 13 (1999)')
  },
}

/**
 * Two receivers (#438): receiving only, not their handful of carries. Both
 * careers run past the data (`cut_off_after`), which is not a cut-off, so
 * the marks stay (#448).
 */
export const TwoReceivers: Story = {
  args: {
    caption: 'Tyreek Hill and CeeDee Lamb, regular season',
    a: {
      name: 'Tyreek Hill',
      totals: HILL_VS_LAMB.a.regular_season,
      coverage: HILL_VS_LAMB.a.coverage,
    },
    b: {
      name: 'CeeDee Lamb',
      totals: HILL_VS_LAMB.b.regular_season,
      coverage: HILL_VS_LAMB.b.coverage,
    },
    group: 'WR',
  },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole('table')).toHaveTextContent(
      MARK_SCREEN_READER_TEXT,
    )
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
      coverage: IN_THE_BOOKS,
    },
  },
}

/** One player has no playoff games: that player's column says so, and nothing is marked. */
export const NoTotalsForOne: Story = {
  args: {
    caption: 'Kurt Warner and Unrecorded Player, playoffs',
    a: {
      name: 'Kurt Warner',
      totals: KURT_WARNER_CAREER.postseason,
      coverage: IN_THE_BOOKS,
    },
    b: { name: 'Unrecorded Player', totals: null, coverage: IN_THE_BOOKS },
    noTotalsCopy: 'No playoff games on record.',
  },
}

/**
 * Two backs (#438): rushing then receiving. Emmitt Smith's one touchdown
 * pass brings no passing rows and no starter record. His career began in
 * 1990, before the data, so nothing is marked and his seasons read
 * "6 of 15 (1999–2004)" (#448).
 */
export const TwoBacks: Story = {
  args: {
    caption: 'Emmitt Smith and Adrian Peterson, regular season',
    a: {
      name: 'Emmitt Smith',
      totals: SMITH_VS_PETERSON.a.regular_season,
      coverage: SMITH_VS_PETERSON.a.coverage,
    },
    b: {
      name: 'Adrian Peterson',
      totals: SMITH_VS_PETERSON.b.regular_season,
      coverage: SMITH_VS_PETERSON.b.coverage,
    },
    group: 'RB',
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
    a: {
      name: 'T.J. Watt',
      totals: TJ_WATT_CAREER.regular_season,
      coverage: TJ_WATT_CAREER.coverage,
    },
    b: {
      name: 'Another pass rusher',
      totals: {
        ...TJ_WATT_CAREER.regular_season!,
        stats: { ...TJ_WATT_CAREER.regular_season!.stats, def_sacks: 17.5 },
      },
      coverage: TJ_WATT_CAREER.coverage,
    },
  },
}
