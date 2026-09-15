import type { Meta, StoryObj } from '@storybook/react-vite'
import {
  HEAD_TO_HEAD_WITH_UNRECORDED_STATS,
  NEVER_MET_COMPARISON,
  WARNER_VS_MCNAIR,
} from '../../lib/playerFixtures'
import { PlayerHeadToHead } from './PlayerHeadToHead'

const meta = {
  title: 'components/PlayerHeadToHead',
  component: PlayerHeadToHead,
  tags: ['autodocs'],
  args: {
    aName: 'Kurt Warner',
    bName: 'Steve McNair',
    headToHead: WARNER_VS_MCNAIR.regular_season_head_to_head,
  },
} satisfies Meta<typeof PlayerHeadToHead>

export default meta

type Story = StoryObj<typeof meta>

/** 1999 week 8 on the committed fixture: Titans 24, Rams 21. */
export const RegularSeason: Story = {}

/** The 1999 season's Super Bowl, week 21: Rams 23, Titans 16. */
export const Playoffs: Story = {
  args: { headToHead: WARNER_VS_MCNAIR.postseason_head_to_head },
}

/** A missing stat line, a missing TD count, no week, no date, and a tie. */
export const UnrecordedStats: Story = {
  args: { headToHead: HEAD_TO_HEAD_WITH_UNRECORDED_STATS },
}

export const NeverMet: Story = {
  args: {
    bName: 'Unrecorded Player',
    headToHead: NEVER_MET_COMPARISON.regular_season_head_to_head,
  },
}
