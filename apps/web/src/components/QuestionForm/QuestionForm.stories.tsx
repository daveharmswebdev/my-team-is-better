import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, within } from 'storybook/test'
import { QuestionForm } from './QuestionForm'

/**
 * `QuestionForm` fetches `/api/years` and `/api/teams` on mount (issue #56),
 * scoped to the selected sport (issue #60), to back its year/team datalist
 * suggestions -- like `AboutPage.stories.tsx` for `fetchCredits`, each story
 * installs its own stubbed `window.fetch` before rendering rather than
 * mocking the module; only requests to those two catalog endpoints are
 * intercepted, everything else falls through to the real `fetch`.
 */
function installCatalogFetch(
  handler: (
    path: '/api/years' | '/api/teams',
    sport: string | null,
  ) => Promise<Response>,
) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    const sport = new URL(url, 'http://localhost').searchParams.get('sport')
    if (url.includes('/api/years')) {
      return handler('/api/years', sport)
    }
    if (url.includes('/api/teams')) {
      return handler('/api/teams', sport)
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
const mockTeams = ['Texas', 'USC', 'Ohio State', 'Texas State']

const mockNflYears = [2020, 2021, 2022, 2023]
const mockNflTeams = ['Chiefs', 'Bills', 'Eagles', '49ers']

/** Serves sport-scoped catalog data -- `cfb` mocks by default, `nfl` mocks
 * once `QuestionForm`'s toggle switches the fetched `sport` param. */
function installSportScopedCatalogFetch() {
  installCatalogFetch((path, sport) => {
    const isNfl = sport === 'nfl'
    const years = isNfl ? mockNflYears : mockYears
    const teams = isNfl ? mockNflTeams : mockTeams
    return jsonResponse(path === '/api/years' ? { years } : { teams })
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

/** Default College state -- untouched behavior from before issue #60's toggle. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.getByRole('radio', { name: /college/i })).toBeChecked()
  },
}

/** Switching the toggle to NFL re-fetches the catalog scoped to "nfl". */
export const NflToggle: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(canvas.getByRole('radio', { name: /nfl/i }))
    await expect(canvas.getByRole('radio', { name: /nfl/i })).toBeChecked()
    await expect(
      canvas.getByRole('radio', { name: /college/i }),
    ).not.toBeChecked()
  },
}

export const Submitting: Story = {
  args: {
    isSubmitting: true,
  },
}

/** Catalog fetch still in flight -- the form renders immediately with
 * plain, unvalidated inputs rather than waiting on the datalists. */
export const CatalogLoading: Story = {
  decorators: [
    (Story) => {
      installCatalogFetch(() => new Promise(() => {}))
      return <Story />
    },
  ],
}

/** Catalog fetch fails -- the form degrades to today's unvalidated-input
 * behavior and surfaces a small inline hint rather than blocking. */
export const CatalogError: Story = {
  decorators: [
    (Story) => {
      installCatalogFetch(() =>
        Promise.resolve(new Response(null, { status: 500 })),
      )
      return <Story />
    },
  ],
}
