import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'
import { expect, fn, userEvent, within } from 'storybook/test'
import type { PlayerSeasonType } from '../../lib/api/types'
import { SeasonTypeSwitch } from './SeasonTypeSwitch'

const meta = {
  title: 'components/SeasonTypeSwitch',
  component: SeasonTypeSwitch,
  tags: ['autodocs'],
  args: {
    value: 'regular',
    onChange: fn(),
  },
} satisfies Meta<typeof SeasonTypeSwitch>

export default meta

type Story = StoryObj<typeof meta>

export const RegularSeason: Story = {}

export const Playoffs: Story = {
  args: { value: 'postseason' },
}

function StatefulSwitch({
  onChange,
}: {
  onChange: (value: PlayerSeasonType) => void
}) {
  const [value, setValue] = useState<PlayerSeasonType>('regular')
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

/** Tab in, then an arrow key moves to Playoffs, in a real browser. */
export const KeyboardOperable: Story = {
  render: (args) => <StatefulSwitch onChange={args.onChange} />,
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    await userEvent.tab()
    await expect(
      canvas.getByRole('radio', { name: 'Regular season' }),
    ).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}')
    const playoffs = canvas.getByRole('radio', { name: 'Playoffs' })
    await expect(playoffs).toBeChecked()
    await expect(playoffs).toHaveFocus()
    await expect(args.onChange).toHaveBeenCalledWith('postseason')
  },
}
