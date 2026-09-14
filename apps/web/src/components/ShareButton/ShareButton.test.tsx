import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ShareButton } from './ShareButton'

const URL_TO_SHARE =
  'https://my-team-is-better.lol/?q=compare&sport=cfb&year=2012&engine=keener&a=Texas+A%26M&b=Ole+Miss'

/**
 * jsdom has neither `navigator.share` nor `navigator.clipboard`, so each test
 * installs exactly the capabilities it is about. Own properties on the
 * `navigator` instance, removed again after every test.
 */
function stubNavigator(key: 'share' | 'clipboard', value: unknown) {
  Object.defineProperty(window.navigator, key, {
    value,
    configurable: true,
    writable: true,
  })
}

afterEach(() => {
  Reflect.deleteProperty(window.navigator, 'share')
  Reflect.deleteProperty(window.navigator, 'clipboard')
})

function clickShare() {
  fireEvent.click(screen.getByRole('button', { name: 'Share this verdict' }))
}

/** Lets the click handler's awaited promise chain settle. */
async function flush() {
  await act(async () => {
    await new Promise((resolveWait) => setTimeout(resolveWait, 0))
  })
}

describe('ShareButton (issue #184)', () => {
  it('renders a "Share this verdict" button and nothing else yet', () => {
    render(<ShareButton url={URL_TO_SHARE} />)

    expect(
      screen.getByRole('button', { name: 'Share this verdict' }),
    ).toBeInTheDocument()
    expect(screen.queryByText('Link copied')).not.toBeInTheDocument()
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument()
  })

  it('uses the native share sheet with the title and url when it exists', async () => {
    const share = vi.fn().mockResolvedValue(undefined)
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigator('share', share)
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()
    await flush()

    expect(share).toHaveBeenCalledTimes(1)
    expect(share).toHaveBeenCalledWith({
      title: 'My Team Is Better',
      url: URL_TO_SHARE,
    })
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.queryByText('Link copied')).not.toBeInTheDocument()
  })

  it('treats a cancelled share sheet (AbortError) as a silent no-op', async () => {
    const share = vi
      .fn()
      .mockRejectedValue(new DOMException('Share canceled', 'AbortError'))
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigator('share', share)
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()
    await flush()

    expect(share).toHaveBeenCalledTimes(1)
    expect(writeText).not.toHaveBeenCalled()
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    expect(screen.queryByText('Link copied')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('textbox', { name: 'Copy this link' }),
    ).not.toBeInTheDocument()
  })

  it('falls through to the clipboard when the share sheet fails for another reason', async () => {
    stubNavigator(
      'share',
      vi.fn().mockRejectedValue(new DOMException('No', 'NotAllowedError')),
    )
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(URL_TO_SHARE))
    expect(await screen.findByRole('status')).toHaveTextContent('Link copied')
  })

  it('copies the url and says so in a status message when there is no share sheet', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()

    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Link copied'),
    )
    expect(writeText).toHaveBeenCalledTimes(1)
    expect(writeText).toHaveBeenCalledWith(URL_TO_SHARE)
    expect(
      screen.queryByRole('textbox', { name: 'Copy this link' }),
    ).not.toBeInTheDocument()
  })

  it('shows the url in a read-only "Copy this link" field, and says so in the status, when the clipboard rejects', async () => {
    stubNavigator('clipboard', {
      writeText: vi.fn().mockRejectedValue(new Error('denied')),
    })
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()

    const field = await screen.findByRole('textbox', { name: 'Copy this link' })
    expect(field).toHaveValue(URL_TO_SHARE)
    expect(field).toHaveAttribute('readonly')
    expect(screen.getByRole('status')).toHaveTextContent(
      "Couldn't copy automatically -- the link is in the field below.",
    )
    expect(screen.queryByText('Link copied')).not.toBeInTheDocument()
  })

  it('shows the manual-copy field and the status message when there is no clipboard at all', async () => {
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()

    expect(
      await screen.findByRole('textbox', { name: 'Copy this link' }),
    ).toHaveValue(URL_TO_SHARE)
    expect(screen.getByRole('status')).toHaveTextContent(
      "Couldn't copy automatically -- the link is in the field below.",
    )
  })

  it('clears the status before each attempt, so a second copy re-announces "Link copied"', async () => {
    let releaseSecondCopy = () => {}
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockResolvedValueOnce(undefined)
      .mockImplementationOnce(
        () =>
          new Promise<void>((resolveCopy) => {
            releaseSecondCopy = () => resolveCopy()
          }),
      )
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} />)

    clickShare()
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Link copied'),
    )

    clickShare()
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('status')).toBeEmptyDOMElement()

    await act(async () => {
      releaseSecondCopy()
    })
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Link copied'),
    )
  })
})
