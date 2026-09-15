import { act, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  CATALOG_TIMEOUT_MS,
  NETWORK_ERROR_COPY,
  SERVER_ERROR_COPY,
  VerdictNetworkError,
} from '../../lib/api/client'
import type { CreditsMethodologyOut, CreditsOut } from '../../lib/api/types'
import { AboutPage } from './AboutPage'

vi.mock('../../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../../lib/api/client')>(
    '../../lib/api/client',
  )
  return {
    ...actual,
    fetchCredits: vi.fn(),
  }
})

import { fetchCredits } from '../../lib/api/client'

const mockedFetchCredits = vi.mocked(fetchCredits)

/**
 * Mirrors the live `/api/credits` payload: `methodologies` is a list, and the
 * order is deliberate -- Keener (the validated default) first, Elo (the second
 * opinion) after. The page renders in the order received and must not sort.
 */
const keener = {
  name: "Keener's method",
  citation:
    'J. P. Keener, "The Perron-Frobenius Theorem and the Ranking of Football Teams," SIAM Review, 35(1), 1993.',
  url: 'https://dl.acm.org/doi/10.1137/1035004',
  summary:
    "A team's rating depends recursively on the strength of the teams it beat, the same eigenvector idea behind PageRank applied to a win graph.",
  methods: ['keener'],
} as const satisfies CreditsMethodologyOut

const elo = {
  name: 'Elo',
  citation:
    'Arpad E. Elo, The Rating of Chessplayers, Past and Present, Arco, 1978 -- as adapted for professional football by FiveThirtyEight (fivethirtyeight/nfl-elo-game).',
  url: 'https://github.com/fivethirtyeight/nfl-elo-game',
  summary:
    'Every team starts even and they trade points after each game: beat someone better than you and you take more from them than you would from a team you were supposed to beat.',
  methods: ['elo', 'elo_career'],
} as const satisfies CreditsMethodologyOut

const credits: CreditsOut = {
  methodologies: [keener, elo],
  data_sources: [
    {
      id: 'cfbd',
      name: 'CollegeFootballData.com (CFBD)',
      url: 'https://collegefootballdata.com/test-mock',
      note: 'All game results are ingested from the CFBD API. This project performs no independent data collection and claims no ownership of the underlying game data.',
    },
    {
      id: 'nflverse_games',
      name: 'nflverse (Lee Sharpe)',
      url: 'https://github.com/nflverse/nflverse-data/test-mock',
      note: 'NFL game results are ingested from nflverse, built on play-by-play data originated by Lee Sharpe.',
    },
    {
      id: 'nflverse_player_stats',
      name: 'nflverse player stats (nflfastR, by Sebastian Carl and Ben Baldwin)',
      url: 'https://github.com/nflverse/nflfastR/test-mock',
      note: 'NFL player stats are ingested from nflverse, built with nflfastR.',
    },
  ],
}

/** The paragraph that credits the source whose link is named `name`. */
async function creditParagraph(name: string): Promise<HTMLElement> {
  const link = await screen.findByRole('link', { name })
  const paragraph = link.closest('p')
  expect(paragraph).not.toBeNull()
  return paragraph as HTMLElement
}

describe('AboutPage', () => {
  beforeEach(() => {
    mockedFetchCredits.mockReset()
  })

  it('renders the "How This Works" headline', () => {
    mockedFetchCredits.mockReturnValue(new Promise(() => {}))

    render(<AboutPage />)

    expect(
      screen.getByRole('heading', { name: /how this works/i }),
    ).toBeInTheDocument()
  })

  it('shows a loading state while the credits request is in flight', () => {
    mockedFetchCredits.mockReturnValue(new Promise(() => {}))

    render(<AboutPage />)

    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('renders every methodology name, summary, and citation link from the fetched credits, not hardcoded', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    // Awaited once so the fetch has resolved before the synchronous loop.
    await screen.findByRole('heading', { name: keener.name })

    for (const methodology of credits.methodologies) {
      const heading = screen.getByRole('heading', { name: methodology.name })
      const article = heading.closest('article')
      expect(article).not.toBeNull()
      const scope = within(article as HTMLElement)

      expect(scope.getByText(methodology.summary)).toBeInTheDocument()

      const link = scope.getByRole('link', { name: methodology.citation })
      expect(link).toHaveAttribute('href', methodology.url)
    }
  })

  it('credits Arpad Elo by name on the Elo methodology (PRD §5.6)', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    const heading = await screen.findByRole('heading', { name: 'Elo' })
    const scope = within(heading.closest('article') as HTMLElement)

    expect(scope.getByRole('link', { name: /arpad e\. elo/i })).toHaveAttribute(
      'href',
      'https://github.com/fivethirtyeight/nfl-elo-game',
    )
  })

  it('renders the methodologies in the order received, without sorting', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    await screen.findByRole('heading', { name: 'Elo' })

    const rendered = screen
      .getAllByRole('heading', { level: 3 })
      .map((heading) => heading.textContent)
    expect(rendered).toEqual([keener.name, elo.name])
  })

  it('renders no Keener-specific prose outside the fetched credits', async () => {
    mockedFetchCredits.mockResolvedValue({
      ...credits,
      methodologies: [
        {
          name: 'Only method',
          citation: 'Some citation.',
          url: 'https://example.com/only',
          summary: 'The only summary.',
          methods: ['elo'],
        },
      ],
    })

    render(<AboutPage />)

    await screen.findByRole('heading', { name: 'Only method' })

    expect(screen.queryByText(/keener/i)).not.toBeInTheDocument()
  })

  it('renders every data source name, link, and note from the fetched credits, not hardcoded', async () => {
    mockedFetchCredits.mockResolvedValue(credits)

    render(<AboutPage />)

    for (const source of credits.data_sources) {
      const link = await screen.findByRole('link', {
        name: source.name,
      })
      expect(link).toHaveAttribute('href', source.url)
      expect(
        screen.getByText(source.note, { exact: false }),
      ).toBeInTheDocument()
    }
  })

  /**
   * Issue #296: a third credit (the player stats) made "Every game result
   * behind these rankings comes from ..." false for one of them, so each
   * source's lead-in is chosen by its `id`, never by its position or name.
   */
  describe('data-source copy per credit id (issue #296)', () => {
    const [cfbd, nflGames, playerStats] = credits.data_sources as [
      (typeof credits.data_sources)[number],
      (typeof credits.data_sources)[number],
      (typeof credits.data_sources)[number],
    ]

    async function expectCopyPerId() {
      expect(await creditParagraph(cfbd.name)).toHaveTextContent(
        `Every college game result behind these rankings comes from ${cfbd.name}. ${cfbd.note}`,
      )
      expect(await creditParagraph(nflGames.name)).toHaveTextContent(
        `Every NFL game result behind these rankings comes from ${nflGames.name}. ${nflGames.note}`,
      )
      const players = await creditParagraph(playerStats.name)
      expect(players).toHaveTextContent(
        `The NFL player stats on the leaders and player pages come from ${playerStats.name}. ${playerStats.note}`,
      )
      expect(players).not.toHaveTextContent(/every game result/i)
    }

    it('gives each source the lead-in that fits it', async () => {
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      await expectCopyPerId()
    })

    it('keeps each lead-in with its id when the API reorders the sources', async () => {
      mockedFetchCredits.mockResolvedValue({
        ...credits,
        data_sources: [playerStats, cfbd, nflGames],
      })

      render(<AboutPage />)

      await expectCopyPerId()
    })

    it('never claims every game result for a source it does not know', async () => {
      mockedFetchCredits.mockResolvedValue({
        ...credits,
        data_sources: [
          {
            id: 'some_future_source',
            name: 'A future source',
            url: 'https://example.com/future',
            note: 'Its note.',
          },
        ],
      })

      render(<AboutPage />)

      const paragraph = await creditParagraph('A future source')
      expect(paragraph).toHaveTextContent('A future source. Its note.')
      expect(paragraph).not.toHaveTextContent(/every .*game result/i)
    })

    it('gives The Data section the id "data", for the player pages\' fallback link', async () => {
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      await creditParagraph(cfbd.name)
      expect(
        screen.getByRole('heading', { name: 'The Data' }).closest('section'),
      ).toHaveAttribute('id', 'data')
    })
  })

  it('shows an error state when the credits request fails', async () => {
    mockedFetchCredits.mockRejectedValue(
      new VerdictNetworkError(NETWORK_ERROR_COPY),
    )

    render(<AboutPage />)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
  })

  /** Issue #215, through the real client: only `fetch` is faked. */
  describe('an HTTP error from /api/credits (issue #215)', () => {
    afterEach(() => {
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
    })

    it('shows the 5xx copy for a 500, and never the status', async () => {
      vi.spyOn(console, 'error').mockImplementation(() => {})
      const actual = await vi.importActual<
        typeof import('../../lib/api/client')
      >('../../lib/api/client')
      mockedFetchCredits.mockImplementation(actual.fetchCredits)
      vi.stubGlobal(
        'fetch',
        vi
          .fn()
          .mockResolvedValue(
            new Response(JSON.stringify({ detail: 'boom' }), { status: 500 }),
          ),
      )

      render(<AboutPage />)

      expect(await screen.findByRole('alert')).toHaveTextContent(
        SERVER_ERROR_COPY,
      )
      expect(screen.getByRole('main')).not.toHaveTextContent(/status/i)
    })

    it('shows the 5xx copy for an error the client never classified', async () => {
      mockedFetchCredits.mockRejectedValue(new Error('something odd'))

      render(<AboutPage />)

      expect(await screen.findByRole('alert')).toHaveTextContent(
        SERVER_ERROR_COPY,
      )
    })
  })

  /** Issue #237, through the real client: only `fetch` and the clock are faked. */
  describe('a hung /api/credits (issue #237)', () => {
    afterEach(() => {
      vi.useRealTimers()
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
    })

    /** Moves the fake clock, then lets the rejection chain and React settle. */
    async function advance(ms: number) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(ms)
        for (let i = 0; i < 20; i += 1) {
          await Promise.resolve()
        }
      })
    }

    it('replaces "Loading methods" with the network copy once CATALOG_TIMEOUT_MS passes', async () => {
      const actual = await vi.importActual<
        typeof import('../../lib/api/client')
      >('../../lib/api/client')
      mockedFetchCredits.mockImplementation(actual.fetchCredits)
      // Never answers; gives up only when its request's signal aborts.
      vi.stubGlobal(
        'fetch',
        vi.fn(
          (_url: string, init?: RequestInit) =>
            new Promise<Response>((_resolve, reject) => {
              init?.signal?.addEventListener('abort', () => {
                reject(new DOMException('aborted', 'AbortError'))
              })
            }),
        ),
      )
      vi.useFakeTimers()

      render(<AboutPage />)

      await advance(CATALOG_TIMEOUT_MS - 1)
      expect(screen.getByRole('status')).toHaveTextContent(/loading methods/i)
      expect(screen.queryByRole('alert')).not.toBeInTheDocument()

      await advance(1)
      expect(screen.getByRole('alert')).toHaveTextContent(NETWORK_ERROR_COPY)
      expect(screen.queryByText(/loading methods/i)).not.toBeInTheDocument()
      expect(screen.queryByRole('status')).not.toBeInTheDocument()
    })
  })

  /**
   * Issue #227: the Elo ledger's provenance link is `/about#elo`. Each
   * article's id is the first entry of the credit's `methods` (issue #144:
   * the API guarantees `methods[0]` is unique across credits), never the
   * display name, and because the articles only exist once the credits
   * resolve, the page has to do the hash scroll itself -- the browser and
   * React Router both gave up long before the element was there.
   */
  describe('landing on a method by hash (issue #227)', () => {
    /** The elements `scrollIntoView` was called on, in order. */
    let scrolledInto: Element[]

    beforeEach(() => {
      scrolledInto = []
      // jsdom has no `scrollIntoView`; the page feature-detects it.
      Element.prototype.scrollIntoView = function scrollIntoView(
        this: Element,
      ) {
        scrolledInto.push(this)
      }
    })

    afterEach(() => {
      // Cast: the DOM lib types the method as required, but here it is our
      // own stand-in, and removing it restores jsdom's state.
      delete (Element.prototype as Partial<Element>).scrollIntoView
      window.history.replaceState(null, '', '/')
    })

    it('gives each method article the id of its first `methods` entry, and the section the id "methods"', async () => {
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      const eloHeading = await screen.findByRole('heading', { name: 'Elo' })
      expect(eloHeading.closest('article')).toHaveAttribute('id', 'elo')
      expect(
        screen
          .getByRole('heading', { name: "Keener's method" })
          .closest('article'),
      ).toHaveAttribute('id', 'keener')
      expect(
        screen.getByRole('heading', { name: 'The Methods' }).closest('section'),
      ).toHaveAttribute('id', 'methods')
    })

    it('takes the id from `methods[0]`, not the display name', async () => {
      mockedFetchCredits.mockResolvedValue({
        ...credits,
        methodologies: [
          { ...keener, name: 'Elo' },
          { ...elo, name: 'Keener' },
        ],
      })

      render(<AboutPage />)

      const first = await screen.findByRole('heading', { name: 'Elo' })
      expect(first.closest('article')).toHaveAttribute('id', 'keener')
      expect(
        screen.getByRole('heading', { name: 'Keener' }).closest('article'),
      ).toHaveAttribute('id', 'elo')
    })

    it('scrolls the Elo article into view once the credits resolve when the hash is #elo', async () => {
      window.location.hash = '#elo'
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      // Nothing to scroll to while the request is in flight.
      expect(screen.getByRole('status')).toBeInTheDocument()
      expect(scrolledInto).toEqual([])

      const eloHeading = await screen.findByRole('heading', { name: 'Elo' })
      expect(scrolledInto).toEqual([eloHeading.closest('article')])
    })

    it('scrolls the Keener article into view once the credits resolve when the hash is #keener', async () => {
      window.location.hash = '#keener'
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      expect(screen.getByRole('status')).toBeInTheDocument()
      expect(scrolledInto).toEqual([])

      const keenerHeading = await screen.findByRole('heading', {
        name: "Keener's method",
      })
      expect(scrolledInto).toEqual([keenerHeading.closest('article')])
    })

    it('scrolls nothing when there is no hash', async () => {
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      await screen.findByRole('heading', { name: 'Elo' })
      expect(scrolledInto).toEqual([])
    })

    it('scrolls nothing, and does not throw, when the hash names no element', async () => {
      window.location.hash = '#colley'
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      await screen.findByRole('heading', { name: 'Elo' })
      expect(scrolledInto).toEqual([])
    })

    it('keeps the page mounted, and scrolls nothing, when the hash is not valid percent-encoding', async () => {
      // `decodeURIComponent('100%')` throws URIError; with no error boundary
      // in the app, an effect that let it escape would unmount the page.
      window.location.hash = '#100%'
      mockedFetchCredits.mockResolvedValue(credits)

      render(<AboutPage />)

      await screen.findByRole('heading', { name: 'Elo' })
      expect(screen.getByRole('heading', { name: 'Elo' })).toBeInTheDocument()
      expect(scrolledInto).toEqual([])
    })
  })
})
