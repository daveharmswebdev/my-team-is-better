import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DATA_SOURCES } from '../../lib/playerFixtures'
import { PlayerStatsCredit } from './PlayerStatsCredit'

const playerStats = DATA_SOURCES[2]!

describe('PlayerStatsCredit (issue #296)', () => {
  it('credits the source by the name, link and note the API sent', () => {
    render(
      <MemoryRouter>
        <PlayerStatsCredit credit={playerStats} />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole('link', { name: playerStats.name }),
    ).toHaveAttribute('href', 'https://github.com/nflverse/nflfastR')
    expect(screen.getByText(playerStats.note)).toBeInTheDocument()
  })

  it('points to the About page credits while the credit is unavailable', () => {
    render(
      <MemoryRouter>
        <PlayerStatsCredit credit={null} />
      </MemoryRouter>,
    )

    expect(
      screen.getByRole('link', { name: 'How This Works' }),
    ).toHaveAttribute('href', '/about#data')
  })
})
