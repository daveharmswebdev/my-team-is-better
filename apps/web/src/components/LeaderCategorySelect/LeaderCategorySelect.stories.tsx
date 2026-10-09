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

/** The receiving board (issue #314), chosen. */
export const Receiving: Story = {
  args: { value: 'receiving' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('receiving')
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

/** The kicking board (issue #315), chosen. */
export const Kicking: Story = {
  args: { value: 'kicking' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    const select = canvas.getByRole('combobox', { name: 'Stat category' })
    await expect(select).toHaveValue('kicking')
    await userEvent.selectOptions(select, 'punting')
    await expect(args.onChange).toHaveBeenCalledWith('punting')
  },
}

/** The punting board (issue #315), chosen. */
export const Punting: Story = {
  args: { value: 'punting' },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(
      canvas.getByRole('combobox', { name: 'Stat category' }),
    ).toHaveValue('punting')
  },
}

/** The defense board (issue #317), chosen from the dropdown. */
export const Defense: Story = {
  args: { value: 'defense' },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement)
    const select = canvas.getByRole('combobox', { name: 'Stat category' })
    await expect(select).toHaveValue('defense')
    await userEvent.selectOptions(select, 'kicking')
    await expect(args.onChange).toHaveBeenCalledWith('kicking')
  },
}
