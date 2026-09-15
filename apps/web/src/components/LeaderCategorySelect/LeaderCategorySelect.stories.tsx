import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, within } from 'storybook/test'
import { LeaderCategorySelect } from './LeaderCategorySelect'

const meta = {
  title: 'components/LeaderCategorySelect',
  component: LeaderCategorySelect,
  tags: ['autodocs'],
  args: {
    value: 'passing',
    onChange: fn(),
  },
} satisfies Meta<typeof LeaderCategorySelect>

export default meta

type Story = StoryObj<typeof meta>

/** The default board: passing. */
export const Passing: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    const select = canvas.getByRole('combobox', { name: 'Stat category' })
    await expect(select).toHaveValue('passing')
    await userEvent.selectOptions(select, 'rushing')
    await expect(args.onChange).toHaveBeenCalledWith('rushing')
  },
}

/** The rushing board, chosen. */
export const Rushing: Story = {
  args: { value: 'rushing' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('rushing')
  },
}
