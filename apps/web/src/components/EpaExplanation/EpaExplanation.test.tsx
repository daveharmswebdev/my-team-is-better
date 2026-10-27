import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { EPA_EXPLANATION } from '../../lib/playerStats'
import { EpaExplanation } from './EpaExplanation'

/**
 * Issue #347: what EPA is and how each rate was computed, behind a
 * disclosure button a keyboard reaches and a screen reader names.
 */
describe('EpaExplanation (issue #347)', () => {
  it('starts closed: a named button, collapsed, with the explanation hidden', () => {
    render(<EpaExplanation />)

    const button = screen.getByRole('button', { name: 'What is EPA?' })
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(EPA_EXPLANATION)).not.toBeVisible()
    expect(
      screen.queryByRole('region', { name: 'What is EPA?' }),
    ).not.toBeInTheDocument()
  })

  it('opens from the keyboard into a region named by its button', async () => {
    const user = userEvent.setup()
    render(<EpaExplanation />)

    await user.tab()
    const button = screen.getByRole('button', { name: 'What is EPA?' })
    expect(button).toHaveFocus()
    await user.keyboard('{Enter}')

    expect(button).toHaveAttribute('aria-expanded', 'true')
    const region = screen.getByRole('region', { name: 'What is EPA?' })
    expect(button).toHaveAttribute('aria-controls', region.id)
    expect(region).toHaveTextContent(EPA_EXPLANATION)
    expect(screen.getByText(EPA_EXPLANATION)).toBeVisible()
  })

  it('says how each rate is computed, and that rushing EPA per carry is usually negative', async () => {
    const user = userEvent.setup()
    render(<EpaExplanation />)
    await user.click(screen.getByRole('button', { name: 'What is EPA?' }))

    const region = screen.getByRole('region', { name: 'What is EPA?' })
    expect(region).toHaveTextContent(
      'EPA per dropback is passing EPA divided by dropbacks (pass attempts plus sacks).',
    )
    expect(region).toHaveTextContent(
      'EPA per carry is rushing EPA divided by carries.',
    )
    expect(region).toHaveTextContent(
      'Rushing EPA per carry is usually negative',
    )
  })

  it('closes again on a second press', async () => {
    const user = userEvent.setup()
    render(<EpaExplanation defaultOpen />)

    const button = screen.getByRole('button', { name: 'What is EPA?' })
    expect(button).toHaveAttribute('aria-expanded', 'true')
    await user.click(button)
    expect(button).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByText(EPA_EXPLANATION)).not.toBeVisible()
  })
})
