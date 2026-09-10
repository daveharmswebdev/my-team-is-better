import type { Meta, StoryObj } from '@storybook/react-vite'
import { Greeting } from './Greeting'

const meta = {
  title: 'components/Greeting',
  component: Greeting,
  tags: ['autodocs'],
} satisfies Meta<typeof Greeting>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {
  args: {
    name: 'Coach',
  },
}
