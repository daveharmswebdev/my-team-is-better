import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { Pager } from './Pager'

const meta = {
  title: 'components/Pager',
  component: Pager,
  tags: ['autodocs'],
  args: {
    label: 'Leaders pages',
    offset: 0,
    limit: 50,
    shown: 50,
    total: 204,
    onPage: fn(),
  },
} satisfies Meta<typeof Pager>

export default meta

type Story = StoryObj<typeof meta>

/** Previous is unavailable on the first page. */
export const FirstPage: Story = {}

export const MiddlePage: Story = {
  args: { offset: 50 },
}

/** The committed fixture's last regular-season page: 4 rows, Next unavailable. */
export const LastPage: Story = {
  args: { offset: 200, shown: 4 },
}
