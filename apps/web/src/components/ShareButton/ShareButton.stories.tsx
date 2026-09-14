import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, fn, userEvent, within } from 'storybook/test'
import { ShareButton } from './ShareButton'

/** A real share link, with the `&` in "Texas A&M" encoded as the app writes it. */
const SHARE_URL =
  'https://my-team-is-better.lol/?q=compare&sport=cfb&year=2012&engine=keener&a=Texas+A%26M&b=Ole+Miss&for=Texas+A%26M'

const share = fn<(data: ShareData) => Promise<void>>(() => Promise.resolve())
const copyToClipboard = fn<(text: string) => Promise<void>>(() =>
  Promise.resolve(),
)

/**
 * A `beforeEach` that gives the story exactly the `navigator` capabilities it
 * is about -- own properties shadowing the browser's, removed again by the
 * returned cleanup -- so each branch renders the same in every browser.
 */
function withNavigator(capabilities: { share?: unknown; clipboard?: unknown }) {
  return () => {
    share.mockClear()
    copyToClipboard.mockClear()
    for (const [key, value] of Object.entries(capabilities)) {
      Object.defineProperty(navigator, key, {
        value,
        configurable: true,
        writable: true,
      })
    }
    return () => {
      for (const key of Object.keys(capabilities)) {
        Reflect.deleteProperty(navigator, key)
      }
    }
  }
}

const meta = {
  title: 'components/ShareButton',
  component: ShareButton,
  tags: ['autodocs'],
  args: { url: SHARE_URL },
} satisfies Meta<typeof ShareButton>

export default meta

type Story = StoryObj<typeof meta>

export const Default: Story = {}

/** Where the browser has a share sheet, the link goes to it, and nothing else shows. */
export const NativeShareSheet: Story = {
  beforeEach: withNavigator({
    share,
    clipboard: { writeText: copyToClipboard },
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Share this verdict' }),
    )
    await expect(share).toHaveBeenCalledWith({
      title: 'My Team Is Better',
      url: SHARE_URL,
    })
    await expect(copyToClipboard).not.toHaveBeenCalled()
    await expect(canvas.queryByText('Link copied')).toBeNull()
  },
}

/** No share sheet: the link is copied, and a status message says so. */
export const CopiedToClipboard: Story = {
  beforeEach: withNavigator({
    share: undefined,
    clipboard: { writeText: copyToClipboard },
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Share this verdict' }),
    )
    await expect(await canvas.findByRole('status')).toHaveTextContent(
      'Link copied',
    )
    await expect(copyToClipboard).toHaveBeenCalledWith(SHARE_URL)
  },
}

/** The clipboard refuses: the link is shown in a field to copy by hand. */
export const ManualCopyFallback: Story = {
  beforeEach: withNavigator({
    share: undefined,
    clipboard: {
      writeText: () => Promise.reject(new Error('Clipboard blocked')),
    },
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await userEvent.click(
      canvas.getByRole('button', { name: 'Share this verdict' }),
    )
    const field = await canvas.findByRole('textbox', {
      name: 'Copy this link',
    })
    await expect(field).toHaveValue(SHARE_URL)
    await expect(canvas.queryByText('Link copied')).toBeNull()
  },
}
