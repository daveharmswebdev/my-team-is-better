import type { Meta, StoryObj } from '@storybook/react-vite'
import type { CreditsOut } from '../../lib/api/types'
import { AboutPage } from './AboutPage'

/**
 * AboutPage owns its own data-fetching (`fetchCredits`, via `fetch`), so --
 * unlike the presentational components -- these stories drive it with a
 * stubbed `window.fetch` rather than props. Each story installs its own
 * handler before rendering; only requests to `/api/credits` are intercepted,
 * everything else falls through to the real `fetch`.
 *
 * `mockCredits` mirrors the live payload's shape and ordering: `methodologies`
 * is a list, Keener's method first and Elo second, and the page renders them
 * in that order.
 */
const mockCredits: CreditsOut = {
  methodologies: [
    {
      name: "Keener's method",
      citation:
        'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking of Football Teams," SIAM Review, 35(1), 1993.',
      url: 'https://dl.acm.org/doi/10.1137/1035004',
      summary:
        "A team's rating depends recursively on the strength of the teams it beat, whose strength depends on the strength of their opponents -- the same Perron-Frobenius eigenvector idea behind PageRank, applied to a win graph. This is stock Keener, with win/loss as the dominant signal: this method does not weight margin of victory, so running up the score doesn't move the needle. It is the default, and the only method checked against the golden dataset of undisputed champions.",
    },
    {
      name: 'Elo',
      citation:
        'Arpad E. Elo, The Rating of Chessplayers, Past and Present, Arco, 1978 -- as adapted for professional football by FiveThirtyEight (fivethirtyeight/nfl-elo-game).',
      url: 'https://github.com/fivethirtyeight/nfl-elo-game',
      summary:
        'Every team starts even and they trade points after each game: beat someone better than you and you take more from them than you would from a team you were supposed to beat. Arpad Elo built it for chess; FiveThirtyEight published the football adaptation implemented here -- including the margin-of-victory multiplier, so unlike Keener above, blowouts do count. Offered as a second opinion, not a replacement -- two different methods will naturally rank teams differently from time to time.',
    },
  ],
  data_sources: [
    {
      name: 'CollegeFootballData.com (CFBD)',
      url: 'https://collegefootballdata.com',
      note: 'All game results are ingested from the CFBD API. This project performs no independent data collection and claims no ownership of the underlying game data.',
    },
    {
      name: 'nflverse (Lee Sharpe)',
      url: 'https://github.com/nflverse/nflverse-data',
      note: 'NFL game results are ingested from nflverse, built on play-by-play data originated by Lee Sharpe.',
    },
  ],
}

function installCreditsFetch(handler: () => Promise<Response>) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/api/credits')) {
      return handler()
    }
    return realFetch(input, init)
  }) as typeof fetch
}

function jsonResponse(body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

const meta = {
  title: 'pages/AboutPage',
  component: AboutPage,
  tags: ['autodocs'],
} satisfies Meta<typeof AboutPage>

export default meta

type Story = StoryObj<typeof meta>

export const Loaded: Story = {
  decorators: [
    (Story) => {
      installCreditsFetch(() => jsonResponse(mockCredits))
      return <Story />
    },
  ],
}

export const Loading: Story = {
  decorators: [
    (Story) => {
      installCreditsFetch(() => new Promise(() => {}))
      return <Story />
    },
  ],
}

export const Error: Story = {
  decorators: [
    (Story) => {
      installCreditsFetch(() =>
        Promise.resolve(new Response(null, { status: 500 })),
      )
      return <Story />
    },
  ],
}
