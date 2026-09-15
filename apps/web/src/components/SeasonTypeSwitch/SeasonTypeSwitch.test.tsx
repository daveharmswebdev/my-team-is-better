import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { PlayerSeasonType } from '../../lib/api/types'
import { SeasonTypeSwitch } from './SeasonTypeSwitch'

function Controlled({
  initial,
  onChange,
}: {
  initial: PlayerSeasonType
  onChange: (value: PlayerSeasonType) => void
}) {
  const [value, setValue] = useState(initial)
  return (
    <SeasonTypeSwitch
      value={value}
      onChange={(next) => {
        onChange(next)
        setValue(next)
      }}
    />
  )
}

describe('SeasonTypeSwitch (issue #296)', () => {
  it('is a named group of two radios exposing which one is on', () => {
    render(<SeasonTypeSwitch value="postseason" onChange={() => {}} />)

    const group = screen.getByRole('group', { name: 'Season type' })
    expect(group).toBeInTheDocument()
    expect(screen.getAllByRole('radio')).toHaveLength(2)
    expect(
      screen.getByRole('radio', { name: 'Regular season' }),
    ).not.toBeChecked()
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
  })

  it('asks for the playoffs when Playoffs is clicked', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Controlled initial="regular" onChange={onChange} />)

    await user.click(screen.getByRole('radio', { name: 'Playoffs' }))

    expect(onChange).toHaveBeenCalledWith('postseason')
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
  })

  it('moves between season types with the arrow keys', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Controlled initial="regular" onChange={onChange} />)

    await user.tab()
    expect(screen.getByRole('radio', { name: 'Regular season' })).toHaveFocus()
    await user.keyboard('{ArrowRight}')

    expect(onChange).toHaveBeenLastCalledWith('postseason')
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toBeChecked()
    expect(screen.getByRole('radio', { name: 'Playoffs' })).toHaveFocus()
  })

  it('does not ask again for the season type already on', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<SeasonTypeSwitch value="regular" onChange={onChange} />)

    await user.click(screen.getByRole('radio', { name: 'Regular season' }))

    expect(onChange).not.toHaveBeenCalled()
  })
})
