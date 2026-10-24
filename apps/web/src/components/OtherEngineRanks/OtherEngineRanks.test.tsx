import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { OtherEngineRanks } from './OtherEngineRanks'

/**
 * Issue #155: where each other displayed engine ranks the verdict's team,
 * plus a control that re-asks the question under that engine.
 */
describe('OtherEngineRanks', () => {
  it("renders the other displayed engine's rank, by its Engine-toggle name", () => {
    render(
      <OtherEngineRanks
        rows={[{ ranks: [{ method: 'elo', rank: 6 }] }]}
        onSelectMethod={vi.fn()}
      />,
    )

    expect(screen.getByText('Elo (second opinion): #6')).toBeInTheDocument()
  })

  it('never shows elo_career, which no Engine radio offers', () => {
    const { container } = render(
      <OtherEngineRanks
        rows={[
          {
            ranks: [
              { method: 'elo', rank: 6 },
              { method: 'elo_career', rank: 8 },
            ],
          },
        ]}
        onSelectMethod={vi.fn()}
      />,
    )

    expect(container.textContent).not.toMatch(/career/i)
    expect(container.textContent).not.toMatch(/#8/)
    expect(screen.getAllByRole('button')).toHaveLength(1)
  })

  it.each([
    ['an empty list', []],
    ['a list of only elo_career', [{ method: 'elo_career', rank: 8 }]],
  ] as const)('renders nothing for %s', (_kind, ranks) => {
    const { container } = render(
      <OtherEngineRanks rows={[{ ranks }]} onSelectMethod={vi.fn()} />,
    )

    expect(container).toBeEmptyDOMElement()
  })

  it('renders a line per team, named, and one control per engine', () => {
    render(
      <OtherEngineRanks
        rows={[
          { teamName: 'Penn State', ranks: [{ method: 'elo', rank: 6 }] },
          { teamName: 'Texas', ranks: [{ method: 'elo', rank: 1 }] },
        ]}
        onSelectMethod={vi.fn()}
      />,
    )

    expect(
      screen.getByText('Penn State · Elo (second opinion): #6'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Texas · Elo (second opinion): #1'),
    ).toBeInTheDocument()
    expect(
      screen.getAllByRole('button', { name: 'Ask Elo (second opinion)' }),
    ).toHaveLength(1)
  })

  it('skips a team with no displayed rank but keeps the other', () => {
    render(
      <OtherEngineRanks
        rows={[
          { teamName: 'Penn State', ranks: [] },
          { teamName: 'Texas', ranks: [{ method: 'elo', rank: 1 }] },
        ]}
        onSelectMethod={vi.fn()}
      />,
    )

    expect(screen.queryByText(/Penn State/)).not.toBeInTheDocument()
    expect(
      screen.getByText('Texas · Elo (second opinion): #1'),
    ).toBeInTheDocument()
  })

  it('calls onSelectMethod with the other engine when its control is clicked', async () => {
    const onSelectMethod = vi.fn()
    render(
      <OtherEngineRanks
        rows={[{ ranks: [{ method: 'keener', rank: 3 }] }]}
        onSelectMethod={onSelectMethod}
      />,
    )

    await userEvent.click(
      screen.getByRole('button', { name: 'Ask Keener (default)' }),
    )

    expect(onSelectMethod).toHaveBeenCalledExactlyOnceWith('keener')
  })

  it('offers no control without onSelectMethod', () => {
    render(
      <OtherEngineRanks rows={[{ ranks: [{ method: 'elo', rank: 6 }] }]} />,
    )

    expect(screen.getByText('Elo (second opinion): #6')).toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  /**
   * Founder framing (2026-09-13): the engines have no mandate to agree, so a
   * rank that matches the answering engine's and one that doesn't render
   * with exactly the same markup, classes included.
   */
  it('renders a matching rank and a different rank with identical markup', () => {
    const markup = (rank: number) => {
      const { container, unmount } = render(
        <OtherEngineRanks
          rows={[{ ranks: [{ method: 'elo', rank }] }]}
          onSelectMethod={vi.fn()}
        />,
      )
      const html = container.innerHTML.replace(`#${rank}`, '#N')
      unmount()
      return html
    }

    expect(markup(1)).toBe(markup(6))
  })
})
