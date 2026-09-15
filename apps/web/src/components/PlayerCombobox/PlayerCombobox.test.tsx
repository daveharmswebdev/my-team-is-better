import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { PlayerSearchRowOut } from '../../lib/api/types'
import { SEARCH_MC, SEARCH_MCNAIR } from '../../lib/playerFixtures'
import { PlayerCombobox } from './PlayerCombobox'
import type { PlayerSearchStatus } from './PlayerCombobox'

interface HarnessProps {
  options: PlayerSearchRowOut[]
  status?: PlayerSearchStatus
  hint?: string
  onChange?: (text: string) => void
  onSelect?: (player: PlayerSearchRowOut) => void
}

/** A controlled parent: the page owns the text and the search results. */
function Harness({
  options,
  status = 'done',
  hint,
  onChange,
  onSelect,
}: HarnessProps) {
  const [value, setValue] = useState('')
  return (
    <PlayerCombobox
      label="Player B"
      value={value}
      options={options}
      status={status}
      hint={hint}
      onChange={(text) => {
        setValue(text)
        onChange?.(text)
      }}
      onSelect={(player) => {
        setValue(player.display_name)
        onSelect?.(player)
      }}
    />
  )
}

function optionLabels(): string[] {
  return screen
    .getAllByRole('option')
    .map((option) => (option.textContent ?? '').replace(/\s+/g, ' ').trim())
}

describe('PlayerCombobox (issue #301)', () => {
  it('is a labelled combobox wired to its listbox', async () => {
    const user = userEvent.setup()
    render(<Harness options={SEARCH_MC.rows} />)

    const input = screen.getByLabelText('Player B', { exact: true })
    expect(input).toHaveAttribute('role', 'combobox')
    expect(input).toHaveAttribute('aria-autocomplete', 'list')
    expect(input).toHaveAttribute('aria-expanded', 'false')

    await user.type(input, 'mc')

    const listbox = screen.getByRole('listbox')
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-controls', listbox.id)
  })

  it('reports every keystroke to the parent', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness options={[]} onChange={onChange} />)

    await user.type(screen.getByRole('combobox'), 'Mc')

    expect(onChange).toHaveBeenLastCalledWith('Mc')
  })

  it('shows each option with position and season span, in the order given', async () => {
    const user = userEvent.setup()
    render(<Harness options={SEARCH_MC.rows} />)

    await user.type(screen.getByRole('combobox'), 'mc')

    expect(optionLabels()).toEqual([
      'Steve McNair · QB, 1999',
      'Mike Tomczak · QB, 1999',
      'Cade McNown · QB, 1999',
      'Donovan McNabb · QB, 1999',
      'AJ McCarron · QB, 2023',
      'Jerick McKinnon · RB, 2023',
    ])
  })

  it('tells same-named players apart', async () => {
    const user = userEvent.setup()
    render(
      <Harness
        options={[
          {
            player_id: 1,
            display_name: 'Mike Smith',
            position: 'QB',
            first_season: 1999,
            last_season: 2004,
          },
          {
            player_id: 2,
            display_name: 'Mike Smith',
            position: null,
            first_season: 2023,
            last_season: 2023,
          },
        ]}
      />,
    )

    await user.type(screen.getByRole('combobox'), 'smith')

    expect(optionLabels()).toEqual([
      'Mike Smith · QB, 1999–2004',
      'Mike Smith · position not recorded, 2023',
    ])
  })

  it('selects a clicked option and closes the list', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<Harness options={SEARCH_MCNAIR.rows} onSelect={onSelect} />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'McNair')
    await user.click(screen.getByRole('option', { name: /Steve McNair/ }))

    expect(onSelect).toHaveBeenCalledWith(SEARCH_MCNAIR.rows[0])
    expect(input).toHaveValue('Steve McNair')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('moves through options with the arrow keys and selects with Enter', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<Harness options={SEARCH_MC.rows} onSelect={onSelect} />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'mc')
    expect(input).not.toHaveAttribute('aria-activedescendant')

    await user.keyboard('{ArrowDown}{ArrowDown}')
    const second = screen.getAllByRole('option')[1]
    expect(input).toHaveAttribute('aria-activedescendant', second?.id)
    expect(second).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{ArrowUp}{Enter}')
    expect(onSelect).toHaveBeenCalledWith(SEARCH_MC.rows[0])
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('closes on Escape and keeps the typed text', async () => {
    const user = userEvent.setup()
    const onSelect = vi.fn()
    render(<Harness options={SEARCH_MC.rows} onSelect={onSelect} />)

    const input = screen.getByRole('combobox')
    await user.type(input, 'mc')
    await user.keyboard('{ArrowDown}{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).not.toHaveAttribute('aria-activedescendant')
    expect(input).toHaveValue('mc')
    expect(onSelect).not.toHaveBeenCalled()
  })

  it('announces how many players match', async () => {
    const user = userEvent.setup()
    render(<Harness options={SEARCH_MC.rows} />)

    await user.type(screen.getByRole('combobox'), 'mc')

    expect(screen.getByRole('status')).toHaveTextContent('6 players match')
  })

  it('announces a search in flight, and a search that found nobody', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<Harness options={[]} status="searching" />)

    await user.type(screen.getByRole('combobox'), 'zz')
    expect(screen.getByRole('status')).toHaveTextContent('Searching')

    rerender(<Harness options={[]} status="done" />)
    expect(screen.getByRole('status')).toHaveTextContent('No players match')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('shows a hint under the field', () => {
    render(<Harness options={[]} hint="Search is down." status="error" />)

    expect(screen.getByText('Search is down.')).toBeInTheDocument()
  })
})
