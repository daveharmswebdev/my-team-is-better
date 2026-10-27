import type { Meta, StoryObj } from '@storybook/react-vite'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { expect, userEvent, waitFor, within } from 'storybook/test'
import type { queries } from 'storybook/test'
import {
  MARK_SCREEN_READER_TEXT,
  PICK_FROM_LIST_COPY,
  PICK_TWO_COPY,
  SAME_PLAYER_COPY,
  groupSingular,
  notComparableCopy,
  pickOneMoreCopy,
  restrictionCopy,
  uncomparableCopy,
} from '../../lib/playerCompare'
import {
  DATA_SOURCES,
  FAULK_VS_FARMER,
  HILL_VS_LAMB,
  JEFF_WILKINS_CAREER,
  KURT_WARNER_CAREER,
  MARSHALL_FAULK_CAREER,
  NEVER_MET_COMPARISON,
  SEARCH_FARMER_RB,
  SEARCH_MCNAIR,
  WARNER_VS_MCNAIR,
  fixtureCoverage,
} from '../../lib/playerFixtures'
import { NETWORK_ERROR_COPY } from '../../lib/api/client'
import { WARNER_VS_MCNAIR_VERDICT } from '../../lib/qbScoreFixtures'
import { PLAYER_NOT_FOUND_COPY } from '../../lib/playerStats'
import type {
  PlayerPositionGroup,
  PlayerSearchOut,
  QbVerdictEnvelope,
} from '../../lib/api/types'
import {
  creditsHandler,
  hang,
  httpError,
  networkError,
  playerCareerHandler,
  playerComparisonHandler,
  playerSearchHandler,
  qbVerdictHandler,
  typedError,
  type Answer,
} from '../../mocks/handlers'
import { PlayerComparePage } from './PlayerComparePage'

interface Handlers {
  compare?: Parameters<typeof playerComparisonHandler>[0]
  /** `POST /api/players/compare/verdict` (#459); never answers when not given. */
  verdict?: (a: number, b: number) => Answer<QbVerdictEnvelope>
  /** Gets the id asked for, for a story that looks up more than one. */
  career?: Parameters<typeof playerCareerHandler>[0]
  /** `/api/players/search`; the fixture's McNair row when not given. */
  search?: (
    query: string,
    group: PlayerPositionGroup | null,
  ) => Answer<PlayerSearchOut>
}

/**
 * Like PlayerCareerPage's stories, these drive the page through the API,
 * faked with the shared MSW handlers (issue #221). The meta's `parameters.msw`
 * leaves `/api/players/compare`, its verdict and `/api/players/{id}` hanging,
 * answers `/api/players/search` with the fixture's McNair row and
 * `/api/credits` with the live data sources; `api()` gives a story its own
 * handlers, which replace the meta's by name.
 */
function api(handlers: Handlers) {
  const { compare, verdict, career, search } = handlers
  return {
    msw: {
      handlers: {
        ...(compare && { compare: playerComparisonHandler(compare) }),
        ...(verdict && {
          verdict: qbVerdictHandler(verdict),
        }),
        ...(career && { career: playerCareerHandler(career) }),
        ...(search && {
          search: playerSearchHandler((query, options) =>
            search(query, options.group ?? null),
          ),
        }),
      },
    },
  }
}

function atSearch(search: string) {
  return function RouterDecorator(Story: () => React.JSX.Element) {
    return (
      <MemoryRouter initialEntries={[`/nfl/compare${search}`]}>
        <Routes>
          <Route path="/nfl/compare" element={<Story />} />
        </Routes>
      </MemoryRouter>
    )
  }
}

const WARNER = KURT_WARNER_CAREER.player_id
const MCNAIR = WARNER_VS_MCNAIR.b.player_id

/** The modal's name before the answer names both players (issue #310). */
/** A career wholly inside the data (#448), for the story with no cut-off. */
const IN_THE_BOOKS = fixtureCoverage(1999, 1999, 1999, 1999)
const COMPARISON_TITLE = 'The comparison'
const WARNER_AND_MCNAIR = 'Kurt Warner and Steve McNair'

// `ReturnType<typeof within>` alone resolves `within`'s generic to its
// constraint, whose queries are `any`; pin it to the default query set.
const playerB = (canvas: ReturnType<typeof within<typeof queries>>) =>
  canvas.getByLabelText('Player B', { exact: true })

const meta = {
  title: 'pages/PlayerComparePage',
  component: PlayerComparePage,
  tags: ['autodocs'],
  parameters: {
    msw: {
      handlers: {
        compare: playerComparisonHandler(hang),
        verdict: qbVerdictHandler(hang),
        career: playerCareerHandler(hang),
        search: playerSearchHandler(() => SEARCH_MCNAIR),
        credits: creditsHandler(() => ({
          methodologies: [],
          data_sources: DATA_SOURCES,
        })),
      },
    },
  },
} satisfies Meta<typeof PlayerComparePage>

export default meta

type Story = StoryObj<typeof meta>

export const NothingPicked: Story = {
  decorators: [atSearch('')],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(PICK_TWO_COPY)
    // Nothing asked yet, so nothing opens over the form (issue #310).
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/** Opened from Kurt Warner's career page: a prompt, not an answer. */
export const OnePicked: Story = {
  decorators: [atSearch(`?a=${WARNER}`)],
  parameters: api({
    career: () => KURT_WARNER_CAREER,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(pickOneMoreCopy('Kurt Warner'))
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/** Player B's typeahead open on "McNair", from the one-picked state. */
export const PickingPlayerB: Story = {
  decorators: [atSearch(`?a=${WARNER}`)],
  parameters: api({
    career: () => KURT_WARNER_CAREER,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    // Player B opens once Warner's career says he is a quarterback (#436).
    await canvas.findByText(restrictionCopy('QB'))
    await userEvent.type(playerB(canvas), 'McNair')
    await expect(
      await canvas.findByRole('option', { name: /Steve McNair/ }),
    ).toBeVisible()
  },
}

/**
 * Text typed into Player B but nothing picked from the list (issue #304):
 * Compare stays disabled and says why.
 */
export const TypedNotPicked: Story = {
  decorators: [atSearch(`?a=${WARNER}`)],
  parameters: api({
    career: () => KURT_WARNER_CAREER,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(pickOneMoreCopy('Kurt Warner'))
    await userEvent.type(playerB(canvas), 'McN')
    await expect(canvas.getByText(PICK_FROM_LIST_COPY)).toBeVisible()
    await expect(canvas.getByRole('button', { name: 'Compare' })).toBeDisabled()
  },
}

/**
 * Steve McNair picked into Player B, then Compare pressed (issue #304): the
 * comparison opens over the form (issue #310).
 */
export const PickedAndCompared: Story = {
  decorators: [atSearch(`?a=${WARNER}`)],
  parameters: api({
    career: () => KURT_WARNER_CAREER,
    compare: () => WARNER_VS_MCNAIR,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByText(pickOneMoreCopy('Kurt Warner'))
    await userEvent.type(playerB(canvas), 'McNair')
    await userEvent.click(
      await canvas.findByRole('option', { name: /Steve McNair/ }),
    )
    const compare = canvas.getByRole('button', { name: 'Compare' })
    await expect(compare).toBeEnabled()
    await expect(canvas.queryByRole('dialog')).toBeNull()

    await userEvent.click(compare)

    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    await within(dialog).findByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    })
  },
}

/**
 * A lone `?a=<id>` link whose career lookup couldn't be reached: the
 * narrator's line stays on the form while the fields hold only that pick.
 */
export const LoneLinkCareerFailed: Story = {
  decorators: [atSearch(`?a=${WARNER}`)],
  parameters: api({
    career: networkError,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
    await expect(canvas.queryByRole('dialog')).toBeNull()
  },
}

/**
 * The same failed lone link, then Steve McNair picked over it into Player A
 * (issue #367): the failure was about the lone pick, so it goes. Player B
 * waits on Player A's group (#436), so he is the only other pick to make.
 */
export const LoneLinkCareerFailedThenPicked: Story = {
  decorators: [atSearch(`?a=${WARNER}`)],
  parameters: api({
    career: networkError,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await canvas.findByRole('alert')
    await expect(playerB(canvas)).toBeDisabled()
    const playerA = canvas.getByLabelText('Player A', { exact: true })
    await userEvent.clear(playerA)
    await userEvent.type(playerA, 'McNair')
    await userEvent.click(
      await canvas.findByRole('option', { name: /Steve McNair/ }),
    )
    await expect(playerB(canvas)).toBeEnabled()
    await expect(canvas.queryByRole('alert')).toBeNull()
  },
}

export const SamePlayer: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${WARNER}`)],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(within(dialog).getByRole('alert')).toHaveTextContent(
      SAME_PLAYER_COPY,
    )
    // Nothing to share: there is no comparison.
    await expect(canvas.queryByRole('button', { name: /^Share/ })).toBeNull()
  },
}

export const Loading: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({ compare: hang }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(within(dialog).getByRole('status')).toHaveTextContent(
      'Loading the comparison',
    )
  },
}

/** Kurt Warner and Steve McNair on the committed fixture, in the modal. */
export const Loaded: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: () => WARNER_VS_MCNAIR,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    await modal.findByRole('table', {
      name: 'Kurt Warner and Steve McNair, playoffs',
    })
    await modal.findByRole('region', { name: 'Head to head' })
    // The credit travels with the numbers it credits.
    await modal.findByRole('link', { name: /nflfastR/ })
    await expect(
      modal.getByRole('button', { name: 'Share this comparison' }),
    ).toBeVisible()
  },
}

/**
 * Closing returns to the form with both fields still filled (issue #310), so
 * the pair can be changed or compared again.
 */
export const ClosedAfterComparing: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: () => WARNER_VS_MCNAIR,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    )

    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(
      canvas.getByLabelText('Player A', { exact: true }),
    ).toHaveValue('Kurt Warner')
    await expect(playerB(canvas)).toHaveValue('Steve McNair')
    await expect(canvas.getByRole('button', { name: 'Compare' })).toBeEnabled()
    // The form holds two players, so it doesn't ask for two (issue #324).
    await expect(canvas.queryByText(PICK_TWO_COPY)).toBeNull()
  },
}

/**
 * A link whose comparison failed, closed (issue #308): the fields hold the
 * link's players by id, since nothing named them, and Compare -- focused --
 * asks for the same pair again without a reload.
 */
export const ClosedAfterFailedLink: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: networkError,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await within(dialog).findByRole('alert')

    await userEvent.click(
      within(dialog).getByRole('button', { name: 'Close the comparison' }),
    )

    await expect(canvas.queryByRole('dialog')).toBeNull()
    await expect(
      canvas.getByLabelText('Player A', { exact: true }),
    ).toHaveValue(`Player #${WARNER}`)
    await expect(playerB(canvas)).toHaveValue(`Player #${MCNAIR}`)
    const compare = canvas.getByRole('button', { name: 'Compare' })
    await expect(compare).toBeEnabled()
    await expect(compare).toHaveFocus()
    await expect(canvas.queryByText(PICK_TWO_COPY)).toBeNull()
  },
}

/**
 * Never met, and one of them with null stats and no playoff games. Both
 * quarterbacks, since only they get a head-to-head (#436).
 */
export const NeverMet: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=1001`)],
  parameters: api({
    compare: () => ({
      ...NEVER_MET_COMPARISON,
      b: { ...NEVER_MET_COMPARISON.b, position: 'QB', group: 'QB' },
    }),
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: 'Kurt Warner and Unrecorded Player',
    })
    await within(dialog).findByText(
      'Kurt Warner and Unrecorded Player never started against each other in the playoffs.',
    )
  },
}

/** A 404 `unknown_player`, in the narrator's voice. */
export const UnknownPlayer: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=1`)],
  parameters: api({
    compare: () =>
      typedError(404, { error: 'unknown_player', player_id: 1, sport: 'nfl' }),
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      PLAYER_NOT_FOUND_COPY,
    )
    await expect(canvas.queryByRole('button', { name: /^Share/ })).toBeNull()
  },
}

export const NetworkError: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: networkError,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: COMPARISON_TITLE,
    })
    await expect(await within(dialog).findByRole('alert')).toHaveTextContent(
      NETWORK_ERROR_COPY,
    )
    await expect(canvas.queryByRole('button', { name: /^Share/ })).toBeNull()
  },
}

// ---------------------------------------------------------------------------
// Comparing like with like (issue #436). Everything below is copied from the
// API on the committed fixture db.
// ---------------------------------------------------------------------------

/**
 * Marshall Faulk as Player A: the page names the restriction, and Player B's
 * typeahead searches running backs only.
 */
export const RestrictedToRunningBacks: Story = {
  decorators: [atSearch(`?a=${MARSHALL_FAULK_CAREER.player_id}`)],
  parameters: api({
    career: () => MARSHALL_FAULK_CAREER,
    search: (query, group) =>
      group === 'RB' && query === 'farmer'
        ? SEARCH_FARMER_RB
        : { ...SEARCH_FARMER_RB, query, group, rows: [] },
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByText(restrictionCopy('RB'))).toBeVisible()
    await userEvent.type(playerB(canvas), 'farmer')
    await expect(
      await canvas.findByRole('option', { name: /Robert Farmer/ }),
    ).toBeVisible()
  },
}

/**
 * A shared link to a quarterback and a running back: refused in the
 * narrator's voice, never shown. Kurt Warner stays as Player A; Player B is
 * empty and ready for another quarterback.
 */
export const MixedLinkRefused: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=2464876093`)],
  parameters: api({
    compare: () =>
      typedError(400, {
        error: 'players_not_comparable',
        a_group: 'QB',
        b_group: 'RB',
      }),
    career: () => KURT_WARNER_CAREER,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByRole('alert')).toHaveTextContent(
      notComparableCopy('QB', groupSingular('RB')),
    )
    // The modal that showed "Loading" closes as the form takes the refusal.
    await waitFor(() => expect(canvas.queryByRole('dialog')).toBeNull())
    await expect(
      await canvas.findByDisplayValue('Kurt Warner'),
    ).toBeInTheDocument()
    await expect(playerB(canvas)).toHaveValue('')
    await expect(playerB(canvas)).toBeEnabled()
  },
}

/** Jeff Wilkins, a kicker, as Player A: no group, so nobody to compare yet. */
export const UncomparablePlayerA: Story = {
  decorators: [atSearch(`?a=${JEFF_WILKINS_CAREER.player_id}`)],
  parameters: api({
    career: () => JEFF_WILKINS_CAREER,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(await canvas.findByText(uncomparableCopy('K'))).toBeVisible()
    await expect(playerB(canvas)).toBeDisabled()
  },
}

/** Tyreek Hill and CeeDee Lamb: careers side by side, no head-to-head. */
export const ReceiversCompared: Story = {
  decorators: [
    atSearch(`?a=${HILL_VS_LAMB.a.player_id}&b=${HILL_VS_LAMB.b.player_id}`),
  ],
  parameters: api({
    compare: () => HILL_VS_LAMB,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: 'Tyreek Hill and CeeDee Lamb',
    })
    const modal = within(dialog)
    const table = await modal.findByRole('table', {
      name: 'Tyreek Hill and CeeDee Lamb, regular season',
    })
    await expect(
      modal.queryByRole('region', { name: 'Head to head' }),
    ).toBeNull()
    // Both run past the data (#448): a plain line, no callout, marks kept.
    await expect(
      modal.getByText(
        "Stats through 2023. This season isn't in our books yet.",
      ),
    ).toBeVisible()
    await expect(modal.queryByText(/^Hold on\./)).toBeNull()
    await expect(table).toHaveTextContent(MARK_SCREEN_READER_TEXT)
  },
}

/**
 * Marshall Faulk's career began in 1994, before the data (#448): the
 * narrator says so above the tables, which it describes, and no total is
 * marked.
 */
export const OneCareerCutOff: Story = {
  decorators: [
    atSearch(
      `?a=${FAULK_VS_FARMER.a.player_id}&b=${FAULK_VS_FARMER.b.player_id}`,
    ),
  ],
  parameters: api({ compare: () => FAULK_VS_FARMER }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: 'Marshall Faulk and Robert Farmer',
    })
    const modal = within(dialog)
    const table = await modal.findByRole('table', {
      name: 'Marshall Faulk and Robert Farmer, regular season',
    })
    const callout = modal.getByText(/^Hold on\. Marshall Faulk played 1994/)
    await expect(callout).toHaveAttribute('role', 'status')
    await expect(table).toHaveAccessibleDescription(callout.textContent ?? '')
    await expect(table).not.toHaveTextContent(MARK_SCREEN_READER_TEXT)
  },
}

/** Warner (1998) and McNair (1995) both began before the data: one callout for both (#448). */
export const BothCareersCutOff: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: () => WARNER_VS_MCNAIR,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    await modal.findByRole('table', {
      name: 'Kurt Warner and Steve McNair, playoffs',
    })
    await expect(modal.getByText(/^Hold on\. Both of these guys/)).toBeVisible()
  },
}

/**
 * Two quarterbacks (#459): the QB score from the comparison, the narration
 * after it, and the EP model's credit beside the stats credit. The narration
 * is the fixture db's, as the e2e run serves it.
 */
export const QuarterbacksScored: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: () => WARNER_VS_MCNAIR,
    verdict: () => WARNER_VS_MCNAIR_VERDICT,
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    const panel = await modal.findByRole('region', { name: 'QB score' })
    await expect(
      within(panel).getByRole('table', { name: /QB score/ }),
    ).toHaveTextContent('Kurt Warner by 1.65')
    await waitFor(() =>
      expect(
        within(panel).getByRole('region', { name: 'The take' }),
      ).toHaveTextContent(WARNER_VS_MCNAIR_VERDICT.narration.text),
    )
    await expect(modal.getByText(/nflfastR's EP model/)).toBeVisible()
  },
}

/**
 * Issue #474 on a phone: who's compared, then the verdict (the winning line
 * and the take), then the numbers -- and one Share button, floating
 * bottom-right over the scrolling comparison, never over its last line.
 */
export const ShareOnPhone: Story = {
  globals: { viewport: { value: 'mobile2', isRotated: false } },
  decorators: QuarterbacksScored.decorators,
  parameters: QuarterbacksScored.parameters,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    await modal.findByRole('region', { name: 'QB score' })
    const shares = modal.getAllByRole('button', { name: /^Share/ })
    await expect(shares).toHaveLength(1)
    const share = modal.getByRole('button', { name: 'Share this comparison' })
    await expect(share).toHaveTextContent(/^Share$/)

    const box = share.getBoundingClientRect()
    await expect(box.width).toBeGreaterThanOrEqual(56)
    await expect(box.height).toBeGreaterThanOrEqual(56)
    await expect(box.bottom).toBeLessThanOrEqual(window.innerHeight)

    // Scrolled to the bottom, it is still on screen, below the last line.
    dialog.scrollTop = dialog.scrollHeight
    const slot = dialog.querySelector('[data-layout="floating"]')
    const lastLine = slot?.previousElementSibling
    await expect(lastLine).toBeTruthy()
    await waitFor(() =>
      expect(lastLine?.getBoundingClientRect().bottom).toBeLessThanOrEqual(
        share.getBoundingClientRect().top,
      ),
    )
    await expect(share.getBoundingClientRect().bottom).toBeLessThanOrEqual(
      window.innerHeight,
    )
  },
}

/**
 * Issue #474 on a desktop: one inline Share button, the primary action,
 * first in the panel -- before the players and the verdict.
 */
export const ShareOnDesktop: Story = {
  globals: { viewport: { value: 'desktop', isRotated: false } },
  decorators: QuarterbacksScored.decorators,
  parameters: QuarterbacksScored.parameters,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    const panel = await modal.findByRole('region', { name: 'QB score' })
    const shares = modal.getAllByRole('button', { name: /^Share/ })
    await expect(shares).toHaveLength(1)
    const share = modal.getByRole('button', { name: 'Share this comparison' })
    await expect(share).toHaveTextContent('Share this comparison')
    const players = modal.getByRole('list', { name: 'Players compared' })
    await expect(
      share.compareDocumentPosition(players) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    await expect(
      players.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy()
    await expect(dialog.querySelector('[data-layout="floating"]')).toBeNull()
  },
}

/** The narration can't be had (#459): the narrator says so, and the score stays. */
export const QuarterbackNarrationFailed: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: () => WARNER_VS_MCNAIR,
    verdict: () =>
      httpError(503, JSON.stringify({ detail: { error: 'stale_database' } })),
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const panel = await within(dialog).findByRole('region', {
      name: 'QB score',
    })
    await waitFor(() =>
      expect(
        within(panel).getByRole('region', { name: 'The take' }),
      ).toHaveTextContent(/Something broke in the back/),
    )
    await expect(
      within(panel).getByRole('table', { name: /QB score/ }),
    ).toBeVisible()
  },
}

/**
 * Neither career cut off (here Warner and McNair as if both began in the
 * data): no callout, and the larger numbers marked (#301).
 */
export const NeitherCareerCutOff: Story = {
  decorators: [atSearch(`?a=${WARNER}&b=${MCNAIR}`)],
  parameters: api({
    compare: () => ({
      ...WARNER_VS_MCNAIR,
      a: { ...WARNER_VS_MCNAIR.a, coverage: IN_THE_BOOKS },
      b: { ...WARNER_VS_MCNAIR.b, coverage: IN_THE_BOOKS },
    }),
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const dialog = await canvas.findByRole('dialog', {
      name: WARNER_AND_MCNAIR,
    })
    const modal = within(dialog)
    const table = await modal.findByRole('table', {
      name: 'Kurt Warner and Steve McNair, regular season',
    })
    await expect(modal.queryByText(/^Hold on\./)).toBeNull()
    await expect(table).toHaveTextContent(MARK_SCREEN_READER_TEXT)
  },
}
