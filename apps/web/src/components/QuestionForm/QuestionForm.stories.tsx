import type { Meta, StoryObj } from '@storybook/react-vite'
import { fn } from 'storybook/test'
import { QuestionForm } from './QuestionForm'

const meta = {
  title: 'components/QuestionForm',
  component: QuestionForm,
  tags: ['autodocs'],
  args: {
    onSubmit: fn(),
  },
} satisfies Meta<typeof QuestionForm>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

export const Submitting: Story = {
  args: {
    isSubmitting: true,
  },
}
