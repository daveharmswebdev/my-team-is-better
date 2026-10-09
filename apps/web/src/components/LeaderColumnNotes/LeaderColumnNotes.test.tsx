import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PlayerLeaderCategory } from '../../lib/api/types'
import {
  DEFENSE_EARLY_ERA_NOTE,
  DEFENSE_UNOFFICIAL_NOTE,
  LEADER_COLUMN_NOTES,
} from '../../lib/playerStats'
import { LeaderColumnNotes } from './LeaderColumnNotes'

/**
 * Issue #317: the founder's column notes (#316), rendered by the page in its
 * "About these numbers" box. Which notes a board shows comes from
 * `leaderColumnNotes`; each note's id is the one the table's headers point at.
 */
describe('LeaderColumnNotes (issue #317)', () => {
  it('shows both defense notes, exactly as written, in column order', () => {
    const { container } = render(
      <LeaderColumnNotes category="defense" idPrefix="notes" />,
    )

    const paragraphs = container.querySelectorAll('p')
    expect(paragraphs).toHaveLength(2)
    expect(paragraphs[0]).toHaveTextContent(DEFENSE_EARLY_ERA_NOTE)
    expect(paragraphs[1]).toHaveTextContent(DEFENSE_UNOFFICIAL_NOTE)
  })

  it('gives each note the id its headers are described by', () => {
    render(<LeaderColumnNotes category="defense" idPrefix="notes" />)

    expect(screen.getByText(DEFENSE_EARLY_ERA_NOTE)).toHaveAttribute(
      'id',
      'notes-early-era',
    )
    expect(screen.getByText(DEFENSE_UNOFFICIAL_NOTE)).toHaveAttribute(
      'id',
      'notes-unofficial',
    )
  })

  it("leads each note with its headers' marker, hidden from assistive tech", () => {
    render(<LeaderColumnNotes category="defense" idPrefix="notes" />)

    for (const [note, text] of [
      ['early-era', DEFENSE_EARLY_ERA_NOTE],
      ['unofficial', DEFENSE_UNOFFICIAL_NOTE],
    ] as const) {
      const paragraph = screen.getByText(text).closest('p') as HTMLElement
      const marker = paragraph.querySelector('[aria-hidden="true"]')
      expect(marker).toHaveTextContent(LEADER_COLUMN_NOTES[note].marker)
    }
  })

  it.each<PlayerLeaderCategory>([
    'passing',
    'rushing',
    'receiving',
    'kicking',
    'punting',
  ])('renders nothing on the %s board', (category) => {
    const { container } = render(
      <LeaderColumnNotes category={category} idPrefix="notes" />,
    )

    expect(container).toBeEmptyDOMElement()
  })
})
