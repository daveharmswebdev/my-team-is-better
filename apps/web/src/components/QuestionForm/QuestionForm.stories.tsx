import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { QuestionForm } from './QuestionForm'

/**
 * `QuestionForm` fetches `/api/years` and `/api/teams` on mount (issue #56)
 * to back its year/team datalist suggestions -- like `AboutPage.stories.tsx`
 * for `fetchCredits`, each story installs its own stubbed `window.fetch`
 * before rendering rather than mocking the module; only requests to those
 * two catalog endpoints are intercepted, everything else falls through to
 * the real `fetch`.
 */
function installCatalogFetch(
  handler: (path: '/api/years' | '/api/teams') => Promise<Response>,
) {
  const realFetch = globalThis.fetch
  globalThis.fetch = ((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString()
    if (url.includes('/api/years')) {
      return handler('/api/years')
    }
    if (url.includes('/api/teams')) {
      return handler('/api/teams')
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

const meta = {
  title: 'components/QuestionForm',
  component: QuestionForm,
  tags: ['autodocs'],
  args: {
    onSubmit: fn(),
  },
  decorators: [
    (Story) => {
      installCatalogFetch((path) =>
        jsonResponse(
          path === '/api/years' ? { years: mockYears } : { teams: mockTeams },
        ),
      )
      return <Story />
    },
  ],
} satisfies Meta<typeof QuestionForm>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

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
