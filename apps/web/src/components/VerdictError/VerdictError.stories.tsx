import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { VerdictError } from './VerdictError'

const meta = {
  title: 'components/VerdictError',
  component: VerdictError,
  tags: ['autodocs'],
  args: {
    onSelectYear: fn(),
    onSelectCandidate: fn(),
  },
} satisfies Meta<typeof VerdictError>

export default meta

type Story = StoryObj<typeof meta>

export const UnknownYear: Story = {
  args: {
    state: {
      kind: 'unknown_year',
      body: {
        error: 'unknown_year',
        year: 1899,
        available_years: [2003, 2004, 2005],
      },
    },
  },
}

export const AmbiguousTeam: Story = {
  args: {
    state: {
      kind: 'ambiguous_team',
      body: {
        error: 'ambiguous_team',
        query: 'Texas St',
        candidates: ['Texas', 'Texas State', 'Texas A&M'],
      },
    },
  },
}

export const SameTeamComparison: Story = {
  args: {
    state: {
      kind: 'same_team_comparison',
      body: { error: 'same_team_comparison', team_name: 'Texas' },
    },
  },
}

export const NetworkError: Story = {
  args: {
    state: {
      kind: 'network_error',
      message: 'Could not reach the API. Check your connection and try again.',
    },
  },
}
