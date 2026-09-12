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
      canvas.getByText(/seasons with data: 2003-2007/i),
    ).toBeVisible()
    await expect(canvas.getByText(/stays on this device only/i)).toBeVisible()
  },
}

/**
 * The "your team" typeahead, open -- issue #80's headline fix. This field
 * had no suggestions at all before, and on the `champion` question type it
 * is the *only* team input, which is why the form looked like it lost its
 * typeahead depending on the question selected.
 */
export const UserTeamSuggestionsOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
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
 * including league-appropriate placeholder copy and suggestions. */
export const NflToggle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('radio', { name: /nfl/i }))
    await expect(canvas.getByRole('radio', { name: /nfl/i })).toBeChecked()
    await expect(
      canvas.getByRole('radio', { name: /college/i }),
    ).not.toBeChecked()
    await expect(
      canvas.getByPlaceholderText(/kansas city chiefs/i),
    ).toBeVisible()
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

export const Submitting: Story = {
  args: {
    isSubmitting: true,
  },
}

/** Catalog fetch still in flight -- the form renders immediately with
 * plain, unvalidated inputs rather than waiting on the suggestions. */
export const CatalogLoading: Story = {
  decorators: [
    (Story) => {
      installCatalogFetch(() => new Promise(() => {}))
      return <Story />
    },
  ],
}

/** Catalog fetch fails -- the comboboxes degrade to plain typed inputs and
 * surface a small inline hint rather than blocking submission. */
export const CatalogError: Story = {
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
    await expect(
      await canvas.findByText(/couldn't load the team list/i),
    ).toBeVisible()
  },
}

/**
 * A *successful* year-scoped response with no teams in it -- an un-ingested
 * season. Distinct from `CatalogError` above and reads differently: there is
 * nothing wrong with the connection, the year just has no data.
 */
export const EmptyYearScopedCatalog: Story = {
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
    await expect(await canvas.findByText(/no teams found for/i)).toBeVisible()
    await expect(
      canvas.queryByText(/couldn't load the team list/i),
    ).not.toBeInTheDocument()
  },
}
