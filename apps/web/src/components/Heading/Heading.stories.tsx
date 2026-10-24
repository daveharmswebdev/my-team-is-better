import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, within } from 'storybook/test'
import { Heading } from './Heading'
import { nextHeadingLevel } from './headingLevel'

const meta = {
  title: 'components/Heading',
  component: Heading,
  tags: ['autodocs'],
  args: {
    level: 2,
    children: 'Quality wins',
  },
} satisfies Meta<typeof Heading>

export default meta

type Story = StoryObj<typeof meta>

/** One heading at the level its caller passes. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole('heading', {
        level: 2,
        name: 'Quality wins',
      }),
    ).toBeVisible()
  },
}

/**
 * A nested outline built with `nextHeadingLevel`: each level is one below
 * the heading it sits under, so axe's heading-order rule passes.
 */
export const NestedOutline: Story = {
  render: () => (
    <div>
      <Heading level={1}>Page title</Heading>
      <Heading level={2}>Section</Heading>
      <Heading level={nextHeadingLevel(2)}>Subsection</Heading>
      <Heading level={nextHeadingLevel(nextHeadingLevel(2))}>Detail</Heading>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const levels = within(canvasElement)
      .getAllByRole('heading')
      .map((heading) => heading.tagName)
    await expect(levels).toEqual(['H1', 'H2', 'H3', 'H4'])
  },
}
