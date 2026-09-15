import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, within } from 'storybook/test'
import type { TeamDetail } from '../../lib/api/types'
import { QuestionForm } from './QuestionForm'

/**
 * `QuestionForm` fetches `/api/years` and `/api/teams` on mount (issue #56),
 * scoped to the selected sport (issue #60) and, for `/api/teams`, to the
 * entered year (issue #80) -- like `AboutPage.stories.tsx` for
 * `fetchCredits`, each story installs its own stubbed `window.fetch` before
 * rendering rather than mocking the module; only requests to those two
 * catalog endpoints are intercepted, everything else falls through to the
 * real `fetch`.
 */
function installCatalogFetch(
  handler: (
    path: '/api/years' | '/api/teams',
    params: URLSearchParams,
  ) => Promise<Response>,
) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const params = new URL(url, 'http://localhost').searchParams
    if (url.includes('/api/years')) {
      return handler('/api/years', params)
    }
    if (url.includes('/api/teams')) {
      return handler('/api/teams', params)
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

const mockYears = [2003, 2004, 2005, 2006, 2007]
const mockTeams: TeamDetail[] = [
  { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
  { name: 'Texas A&M', mascot: 'Aggies', aliases: ['TAMU'] },
  { name: 'Texas State', mascot: 'Bobcats', aliases: [] },
  { name: 'Ohio State', mascot: 'Buckeyes', aliases: ['OSU'] },
  { name: 'USC', mascot: 'Trojans', aliases: ['Southern California'] },
]

const mockNflYears = [2020, 2021, 2022, 2023]
const mockNflTeams: TeamDetail[] = [
  { name: 'Kansas City Chiefs', mascot: null, aliases: ['KC'] },
  { name: 'New York Giants', mascot: null, aliases: ['NYG'] },
  { name: 'New York Jets', mascot: null, aliases: ['NYJ'] },
  { name: 'Philadelphia Eagles', mascot: null, aliases: ['PHI'] },
]

function teamsBody(details: TeamDetail[]) {
  return {
    teams: details.map((detail) => detail.name),
    team_details: details,
  }
}

/** Serves sport-scoped catalog data -- `cfb` mocks by default, `nfl` mocks
 * once `QuestionForm`'s toggle switches the fetched `sport` param. */
function installSportScopedCatalogFetch() {
  installCatalogFetch((path, params) => {
    const isNfl = params.get('sport') === 'nfl'
    const years = isNfl ? mockNflYears : mockYears
    const teams = isNfl ? mockNflTeams : mockTeams
    return jsonResponse(path === '/api/years' ? { years } : teamsBody(teams))
  })
}

const meta = {
  title: 'components/QuestionForm',
  component: QuestionForm,
  tags: ['autodocs'],
  args: {
    onSubmit: fn(),
  },
  decorators: [
    (Story) => {
      installSportScopedCatalogFetch()
      return <Story />
    },
  ],
} satisfies Meta<typeof QuestionForm>

export default meta

type Story = StoryObj<typeof meta>

/**
 * Default College state, showing issue #52's guiding text: the real ingested
 * season range under the Year input, and a format example plus a
 * what-is-matchable hint on the (only) team field this question type shows.
 */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByRole('radio', { name: /college/i })).toBeChecked()
    await expect(
      await canvas.findByText(/seasons with data: 2003-2007/i),
    ).toBeVisible()
    // Issue #136: the Year defaults to the newest season with data, not the
    // calendar year.
    await expect(await canvas.findByDisplayValue('2007')).toBeVisible()
    // Issue #198: the best-team question names no team, so it has no
    // "Your team" field -- and none of that field's privacy note.
    await expect(canvas.queryByLabelText(/your team/i)).not.toBeInTheDocument()
  },
}

/**
 * The "your team" typeahead, open -- issue #80's headline fix. This field
 * had no suggestions at all before. It shows on the questions that name a
 * team; the best-team question has no "your team" field since issue #198.
 */
export const UserTeamSuggestionsOpen: Story = {
  args: { initialQuestionType: 'team_case' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    // Types as soon as the field is on screen, before `/api/teams` has
    // necessarily landed: the same `<input>` becomes the combobox when the
    // catalog arrives, keeping focus and keystrokes (issue #156).
    await userEvent.type(canvas.getByLabelText(/your team/i), 'Longhorns')
    const listbox = await canvas.findByRole('listbox')
    await expect(
      within(listbox).getByRole('option', { name: /Texas · Longhorns/ }),
    ).toBeVisible()
  },
}

/** The single-team question type, with its combobox open on a mascot match. */
export const TeamCaseSuggestionsOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.selectOptions(
      canvas.getByLabelText(/what do you want to know/i),
      'team_case',
    )
    await userEvent.type(canvas.getByLabelText(/^team$/i), 'Buckeyes')
    const listbox = await canvas.findByRole('listbox')
    await expect(
      within(listbox).getByRole('option', { name: /Ohio State/ }),
    ).toBeVisible()
  },
}

/** Both compare fields, each with its own guiding text. */
export const Compare: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.selectOptions(
      canvas.getByLabelText(/what do you want to know/i),
      'compare',
    )
    await expect(canvas.getByLabelText(/team a/i)).toBeVisible()
    await expect(canvas.getByLabelText(/team b/i)).toBeVisible()
  },
}

/** Switching the toggle to NFL re-fetches the catalog scoped to "nfl" --
 * including league-appropriate placeholder copy and suggestions. On a
 * question that names a team: the best-team one has no team field (#198). */
export const NflToggle: Story = {
  args: { initialQuestionType: 'team_case' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('radio', { name: /nfl/i }))
    await expect(canvas.getByRole('radio', { name: /nfl/i })).toBeChecked()
    await expect(
      canvas.getByRole('radio', { name: /college/i }),
    ).not.toBeChecked()
    // Team and "your team" both switch to NFL examples.
    const fields = canvas.getAllByPlaceholderText(/kansas city chiefs/i)
    await expect(fields).toHaveLength(2)
    await expect(fields[0]).toBeVisible()
  },
}

/**
 * Issue #154: the Engine toggle, switched to Elo. The catalogs refetch for the
 * new engine, and -- unlike a league switch -- the Year and the team stay put:
 * same season, same games. The choice applies to the next submission only.
 */
export const EloSelected: Story = {
  args: {
    initialQuestionType: 'team_case',
    initialYear: 2005,
    initialTeam: 'Texas',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const engine = canvas.getByRole('group', { name: 'Engine' })
    await expect(
      within(engine).getByRole('radio', { name: 'Keener (default)' }),
    ).toBeChecked()

    await userEvent.click(
      within(engine).getByRole('radio', { name: 'Elo (second opinion)' }),
    )

    await expect(
      within(engine).getByRole('radio', { name: 'Elo (second opinion)' }),
    ).toBeChecked()
    await expect(canvas.getByLabelText(/^team$/i)).toHaveValue('Texas')
    await expect(canvas.getByLabelText(/year/i)).toHaveValue(2005)
  },
}

/** A parent-applied correction (issue #38): `HomePage` remounts the form
 * with a changed `key` and these seed props, so the visible fields match
 * the question that was actually just asked. */
export const SeededByACorrection: Story = {
  args: {
    initialQuestionType: 'compare',
    initialYear: 2005,
    initialTeamA: 'Texas',
    initialTeamB: 'USC',
  },
}

/**
 * Issue #100(b): a team picked for one season, then left behind by a change
 * to a season whose catalog doesn't have it. The founder's call is to flag
 * it, not clear it -- the typed value survives, the submit button stays
 * enabled, and the user gets a one-click clear if they want one. Silently
 * discarding typed input is its own annoyance, and a freely-typed name has
 * to stay submittable for the same reason `CatalogError` below leaves a
 * usable plain input.
 *
 * Driven by a *year* change: a league change clears every team field
 * outright (issue #137 -- see `LeagueSwitchClearsTeams`), so it no longer
 * leaves anything behind to flag.
 */
export const StaleTeamAfterYearChange: Story = {
  args: {
    initialQuestionType: 'team_case',
    initialYear: 2005,
    initialTeam: 'Texas',
  },
  decorators: [
    (Story) => {
      // Year-scoped College teams: the 2003 catalog has no Texas.
      installCatalogFetch((path, params) =>
        jsonResponse(
          path === '/api/years'
            ? { years: mockYears }
            : teamsBody(
                params.get('year') === '2003'
                  ? mockTeams.filter((detail) => detail.name !== 'Texas')
                  : mockTeams,
              ),
        ),
      )
      return <Story />
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const yearInput = canvas.getByLabelText(/year/i)
    await userEvent.clear(yearInput)
    await userEvent.type(yearInput, '2003')

    await expect(
      await canvas.findByText(
        /isn't in the 2003 college football team list/i,
        {},
        { timeout: 3000 },
      ),
    ).toBeVisible()
    await expect(canvas.getByLabelText(/^team$/i)).toHaveValue('Texas')
    await expect(
      canvas.getByRole('button', { name: 'Clear the team' }),
    ).toBeVisible()
    await expect(
      canvas.getByRole('button', { name: /get the verdict/i }),
    ).not.toBeDisabled()
  },
}

/**
 * Issue #137: switching the league empties every team field, "your team"
 * included -- a College pick means nothing to an NFL question -- and leaves
 * no stale-team flag behind, because there is no longer anything to flag.
 */
export const LeagueSwitchClearsTeams: Story = {
  args: {
    initialQuestionType: 'compare',
    initialYear: 2005,
    initialTeamA: 'Texas',
    initialTeamB: 'USC',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByLabelText(/team a/i)).toHaveValue('Texas')

    await userEvent.click(canvas.getByRole('radio', { name: /nfl/i }))

    await expect(canvas.getByLabelText(/team a/i)).toHaveValue('')
    await expect(canvas.getByLabelText(/team b/i)).toHaveValue('')
    await expect(canvas.getByLabelText(/your team/i)).toHaveValue('')
    await expect(
      canvas.queryByText(/isn't in the .* team list/i),
    ).not.toBeInTheDocument()
  },
}

/**
 * Issue #136: a year the selected league has no data for. The field is
 * marked invalid (`aria-invalid`, described by the inline error), the error
 * names the league and the seasons to pick from, and "Get the verdict" stays
 * disabled until the year is one the league actually has.
 */
export const InvalidYear: Story = {
  args: {
    initialYear: 2010,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const error = await canvas.findByText(/no college football data for 2010/i)
    await expect(error).toBeVisible()
    await expect(error).toHaveTextContent(/2003-2007/)
    const yearInput = canvas.getByLabelText(/year/i)
    await expect(yearInput).toHaveAttribute('aria-invalid', 'true')
    await expect(yearInput).toHaveAttribute('aria-describedby', error.id)
    await expect(
      canvas.getByRole('button', { name: /get the verdict/i }),
    ).toBeDisabled()
  },
}

/** The same flag on a compare question, raised against one side only. */
export const StaleTeamOnOneSideOfACompare: Story = {
  args: {
    initialQuestionType: 'compare',
    initialSport: 'nfl',
    initialYear: 2021,
    initialTeamA: 'New York Giants',
    initialTeamB: 'Ohio State',
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      await canvas.findByText(/Ohio State.*isn't in the 2021 NFL team list/i),
    ).toBeVisible()
    await expect(
      canvas.queryByRole('button', { name: 'Clear the first team' }),
    ).not.toBeInTheDocument()
  },
}

export const Submitting: Story = {
  args: {
    isSubmitting: true,
  },
}

/** Catalog fetch still in flight -- the form renders immediately with
 * plain inputs rather than waiting on the suggestions. With no catalog there
 * is no default year yet, so the button waits for one to be typed; any
 * number will do until the catalog can range-check it (issue #136). */
export const CatalogLoading: Story = {
  decorators: [
    (Story) => {
      installCatalogFetch(() => new Promise(() => {}))
      return <Story />
    },
  ],
}

/** Catalog fetch fails -- the comboboxes degrade to plain typed inputs and
 * surface a small inline hint rather than blocking submission: any typed
 * year is accepted, since there is no range to check it against. Shown on a
 * question with team fields: the best-team one has none (issue #198). */
export const CatalogError: Story = {
  args: { initialQuestionType: 'team_case' },
  decorators: [
    (Story) => {
      installCatalogFetch(() =>
        Promise.resolve(new Response(null, { status: 500 })),
      )
      return <Story />
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const hints = await canvas.findAllByText(/couldn't load the team list/i)
    await expect(hints[0]).toBeVisible()
  },
}

/**
 * A *successful* year-scoped response with no teams in it -- an un-ingested
 * season. Distinct from `CatalogError` above and reads differently: there is
 * nothing wrong with the connection, the year just has no data. Shown on a
 * question with team fields: the best-team one has none (issue #198).
 */
export const EmptyYearScopedCatalog: Story = {
  args: { initialQuestionType: 'team_case' },
  decorators: [
    (Story) => {
      installCatalogFetch((path) =>
        jsonResponse(
          path === '/api/years' ? { years: mockYears } : teamsBody([]),
        ),
      )
      return <Story />
    },
  ],
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const notes = await canvas.findAllByText(/no teams found for/i)
    await expect(notes[0]).toBeVisible()
    await expect(
      canvas.queryByText(/couldn't load the team list/i),
    ).not.toBeInTheDocument()
  },
}
