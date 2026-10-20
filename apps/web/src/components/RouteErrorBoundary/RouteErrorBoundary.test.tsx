import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ROUTE_ERROR_COPY,
  ROUTE_ERROR_HEADING,
  RouteErrorBoundary,
} from './RouteErrorBoundary'

let shouldThrow = true

function MaybeThrows() {
  if (shouldThrow) {
    throw new Error('secret internal detail')
  }
  return <p>Recovered content</p>
}

function tree(resetKey: string) {
  return (
    <MemoryRouter>
      <RouteErrorBoundary resetKey={resetKey}>
        <MaybeThrows />
      </RouteErrorBoundary>
    </MemoryRouter>
  )
}

describe('RouteErrorBoundary (issue #268)', () => {
  beforeEach(() => {
    shouldThrow = true
    // React reports every caught error through console.error.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders its children when nothing throws', () => {
    shouldThrow = false
    render(tree('/a'))

    expect(screen.getByText('Recovered content')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('renders the narrator fallback, never the raw error, when a child throws', () => {
    render(tree('/a'))

    const alert = screen.getByRole('alert')
    expect(
      within(alert).getByRole('heading', { name: ROUTE_ERROR_HEADING }),
    ).toBeInTheDocument()
    expect(alert).toHaveTextContent(ROUTE_ERROR_COPY)
    expect(alert).not.toHaveTextContent('secret internal detail')
    expect(
      within(alert).getByRole('link', { name: /back to the start/i }),
    ).toHaveAttribute('href', '/')
  })

  it('keeps showing the fallback while the reset key is unchanged', () => {
    const { rerender } = render(tree('/a'))
    shouldThrow = false

    rerender(tree('/a'))

    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  it('clears the error and renders children again when the reset key changes', () => {
    const { rerender } = render(tree('/a'))
    expect(screen.getByRole('alert')).toBeInTheDocument()
    shouldThrow = false

    rerender(tree('/b'))

    expect(screen.getByText('Recovered content')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
