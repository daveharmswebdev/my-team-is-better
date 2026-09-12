import type { Meta, StoryObj } from '@storybook/react-vite'
import type { CreditsOut } from '../../lib/api/types'
import { AboutPage } from './AboutPage'

/**
 * AboutPage owns its own data-fetching (`fetchCredits`, via `fetch`), so --
 * unlike the presentational components -- these stories drive it with a
 * stubbed `window.fetch` rather than props. Each story installs its own
 * handler before rendering; only requests to `/api/credits` are intercepted,
 * everything else falls through to the real `fetch`.
 */
const mockCredits: CreditsOut = {
  methodology: {
    name: 'Keener',
    citation:
      'Keener, J. P. (1993). The Perron-Frobenius theorem and the ranking of football teams. The American Mathematical Monthly, 100(1), 80-93.',
    url: 'https://www.jstor.org/stable/2324033',
    summary: 'Eigenvector-based strength-of-schedule ranking.',
  },
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
