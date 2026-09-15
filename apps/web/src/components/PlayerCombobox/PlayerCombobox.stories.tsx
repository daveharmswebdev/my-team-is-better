import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'
import { expect, fn, userEvent, within } from 'storybook/test'
import { SEARCH_FAILED_COPY } from '../../lib/playerCompare'
import { SEARCH_MC, SEARCH_MCNAIR } from '../../lib/playerFixtures'
import { PlayerCombobox } from './PlayerCombobox'
import type { PlayerComboboxProps } from './PlayerCombobox'

/** The page owns the text; this stand-in keeps it so typing shows. */
function Harness(props: PlayerComboboxProps) {
  const [value, setValue] = useState(props.value)
  return (
    <div style={{ maxWidth: '24rem', minHeight: '22rem' }}>
      <PlayerCombobox
        {...props}
        value={value}
        onChange={(text) => {
          setValue(text)
          props.onChange(text)
        }}
        onSelect={(player) => {
          setValue(player.display_name)
          props.onSelect(player)
        }}
        onClear={() => {
          setValue('')
          props.onClear()
        }}
      />
    </div>
  )
}

const meta = {
  title: 'components/PlayerCombobox',
  component: PlayerCombobox,
  tags: ['autodocs'],
  args: {
    label: 'Player B',
    value: '',
    options: [],
    status: 'idle',
    placeholder: 'Type a name',
    onChange: fn(),
    onSelect: fn(),
    onClear: fn(),
  },
  render: (args) => <Harness {...args} />,
} satisfies Meta<typeof PlayerCombobox>

export default meta

type Story = StoryObj<typeof meta>

export const Empty: Story = {}

/** A picked player: the field shows the player's name. */
export const Picked: Story = {
  args: { label: 'Player A', value: 'Kurt Warner' },
}

/** `?q=mc` on the committed fixture: name, position and season span on each option. */
export const Suggestions: Story = {
  args: { options: SEARCH_MC.rows, status: 'done' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await userEvent.type(canvas.getByRole('combobox'), 'mc')
    await expect(canvas.getAllByRole('option')).toHaveLength(6)
    await userEvent.keyboard('{ArrowDown}')
    await expect(canvas.getByRole('combobox')).toHaveAttribute(
      'aria-activedescendant',
    )
    await userEvent.keyboard('{Enter}')
    await expect(args.onSelect).toHaveBeenCalledWith(SEARCH_MC.rows[0])
  },
}

/** Two players with one name, told apart by position and seasons. */
export const SameNames: Story = {
  args: {
    status: 'done',
    options: [
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
    ],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.type(canvas.getByRole('combobox'), 'smith')
    await expect(canvas.getAllByRole('option')).toHaveLength(2)
  },
}

export const Searching: Story = {
  args: { status: 'searching' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.type(canvas.getByRole('combobox'), 'mcn')
    await expect(canvas.getByRole('status')).toHaveTextContent('Searching')
  },
}

export const NoMatches: Story = {
  args: { status: 'done' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.type(canvas.getByRole('combobox'), 'zzzz')
    await expect(canvas.getByRole('status')).toHaveTextContent(
      'No players match',
    )
  },
}

/**
 * A picked player with the clear control (issue #304): pressing it empties
 * the field, hands the pick back to the page and puts focus in the field.
 */
export const Clearable: Story = {
  args: { label: 'Player A', value: 'Kurt Warner' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Clear Player A' }),
    )
    await expect(args.onClear).toHaveBeenCalledTimes(1)
    await expect(canvas.getByRole('combobox')).toHaveValue('')
    await expect(canvas.getByRole('combobox')).toHaveFocus()
    await expect(
      canvas.queryByRole('button', { name: 'Clear Player A' }),
    ).not.toBeInTheDocument()
  },
}

/** One suggestion left and nothing highlighted: Enter picks it (issue #304). */
export const EnterPicksOnlyMatch: Story = {
  args: { options: SEARCH_MCNAIR.rows, status: 'done' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await userEvent.type(canvas.getByRole('combobox'), 'McNair')
    await userEvent.keyboard('{Enter}')
    await expect(args.onSelect).toHaveBeenCalledWith(SEARCH_MCNAIR.rows[0])
    await expect(canvas.getByRole('combobox')).toHaveValue('Steve McNair')
  },
}

/** The search couldn't be had: the narrator says so under the field. */
export const SearchFailed: Story = {
  args: { status: 'error', hint: SEARCH_FAILED_COPY, value: 'McNair' },
}
