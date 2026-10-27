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

  describe('the EP model credit (issues #459, #347)', () => {
    // Broadened by #347: it covers the EPA boards and career columns, not
    // only the QB score.
    const EP_CREDIT =
      "The expected points behind every EPA number here, the QB score's included, come from nflfastR's EP model, by Ben Baldwin & Sebastian Carl."

    it('credits the EP model next to the stats credit when EPA is shown', () => {
      render(
        <MemoryRouter>
          <PlayerStatsCredit credit={playerStats} epModel />
        </MemoryRouter>,
      )
      expect(screen.getByText(EP_CREDIT)).toBeInTheDocument()
      expect(
        screen.getByRole('link', { name: playerStats.name }),
      ).toBeInTheDocument()
    })

    it('credits it while the stats credit is unavailable too', () => {
      render(
        <MemoryRouter>
          <PlayerStatsCredit credit={null} epModel />
        </MemoryRouter>,
      )
      expect(screen.getByText(EP_CREDIT)).toBeInTheDocument()
    })

    it('says nothing of it without a QB score', () => {
      render(
        <MemoryRouter>
          <PlayerStatsCredit credit={playerStats} />
        </MemoryRouter>,
      )
      expect(screen.queryByText(/EP model/)).toBeNull()
    })
  })
})
