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

  it('renders a non-default label as the button text and accessible name (issue #310)', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} label="Share this comparison" />)

    const button = screen.getByRole('button', { name: 'Share this comparison' })
    expect(button).toHaveTextContent('Share this comparison')
    expect(
      screen.queryByRole('button', { name: 'Share this verdict' }),
    ).not.toBeInTheDocument()

    // The label changes the wording only: the link still goes out the same way.
    fireEvent.click(button)
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Link copied'),
    )
    expect(writeText).toHaveBeenCalledWith(URL_TO_SHARE)
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

/**
 * Issue #474: on a phone, the button floats bottom-right over the scrolling
 * view (a FAB), labelled "Share" on screen but keeping the full accessible
 * name, so screen readers and the e2e selectors read it the same.
 */
describe('ShareButton, floating (issue #474)', () => {
  it('shows "Share" and keeps the full label as its accessible name', () => {
    render(
      <ShareButton
        url={URL_TO_SHARE}
        label="Share this comparison"
        layout="floating"
      />,
    )

    const button = screen.getByRole('button', { name: 'Share this comparison' })
    expect(button).toHaveTextContent(/^Share$/)
    expect(screen.getAllByRole('button')).toHaveLength(1)
  })

  it('confirms a copy and falls back to a manual-copy field, like the inline button', async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('Clipboard blocked'))
    stubNavigator('clipboard', { writeText })
    render(<ShareButton url={URL_TO_SHARE} layout="floating" />)

    clickShare()
    await waitFor(() =>
      expect(screen.getByRole('status')).toHaveTextContent('Link copied'),
    )
    clickShare()
    expect(
      await screen.findByRole('textbox', { name: 'Copy this link' }),
    ).toHaveValue(URL_TO_SHARE)
  })

  it('sits in an in-flow slot that reserves its space at the end of the content', () => {
    const { container } = render(
      <ShareButton url={URL_TO_SHARE} layout="floating" />,
    )
    const slot = container.firstElementChild
    expect(slot).toHaveAttribute('data-layout', 'floating')
    expect(slot).toContainElement(
      screen.getByRole('button', { name: 'Share this verdict' }),
    )
  })

  it('reserves room for its overlay as well as the button, measured as it changes', async () => {
    // jsdom lays nothing out: a ResizeObserver stub reports the stack's height.
    let report: () => void = () => {}
    class FakeResizeObserver {
      constructor(callback: () => void) {
        report = callback
      }
      observe() {}
      disconnect() {}
    }
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    const height = vi
      .spyOn(HTMLElement.prototype, 'offsetHeight', 'get')
      .mockReturnValue(200)
    try {
      const { container } = render(
        <ShareButton url={URL_TO_SHARE} layout="floating" />,
      )
      act(() => report())
      const slot = container.firstElementChild as HTMLElement
      // The stack's 200px, plus the gap below it and a little air.
      expect(slot.style.height).toBe(
        'calc(200px + var(--fab-gap) + var(--sp-2))',
      )
    } finally {
      height.mockRestore()
      vi.unstubAllGlobals()
    }
  })

  it('is inline by default, its text the full label', () => {
    const { container } = render(<ShareButton url={URL_TO_SHARE} />)
    expect(container.firstElementChild).toHaveAttribute('data-layout', 'inline')
    expect(
      screen.getByRole('button', { name: 'Share this verdict' }),
    ).toHaveTextContent('Share this verdict')
  })
})

/**
 * Issue #474, round 2: on a phone the toast and the manual-copy box float
 * over the content, so neither may stay there forever.
 */
describe.each(['inline', 'floating'] as const)(
  'ShareButton, transient messages (%s)',
  (layout) => {
    afterEach(() => {
      vi.useRealTimers()
    })

    it('has its status live region in the accessibility tree before any click', () => {
      render(<ShareButton url={URL_TO_SHARE} layout={layout} />)
      const status = screen.getByRole('status')
      expect(status).toBeEmptyDOMElement()
      expect(status).toBeVisible()
    })

    it('clears "Link copied" after about four seconds', async () => {
      vi.useFakeTimers()
      stubNavigator('clipboard', {
        writeText: vi.fn().mockResolvedValue(undefined),
      })
      render(<ShareButton url={URL_TO_SHARE} layout={layout} />)

      clickShare()
      await act(async () => {
        await Promise.resolve()
      })
      expect(screen.getByRole('status')).toHaveTextContent('Link copied')

      act(() => {
        vi.advanceTimersByTime(3500)
      })
      expect(screen.getByRole('status')).toHaveTextContent('Link copied')
      act(() => {
        vi.advanceTimersByTime(1000)
      })
      expect(screen.getByRole('status')).toBeEmptyDOMElement()
    })

    it('drops its pending clear on unmount', async () => {
      vi.useFakeTimers()
      stubNavigator('clipboard', {
        writeText: vi.fn().mockResolvedValue(undefined),
      })
      const { unmount } = render(
        <ShareButton url={URL_TO_SHARE} layout={layout} />,
      )
      clickShare()
      await act(async () => {
        await Promise.resolve()
      })
      expect(vi.getTimerCount()).toBe(1)
      unmount()
      expect(vi.getTimerCount()).toBe(0)
    })

    it('lets the manual-copy box be dismissed, and puts focus back on Share', async () => {
      stubNavigator('clipboard', {
        writeText: () => Promise.reject(new Error('Clipboard blocked')),
      })
      render(<ShareButton url={URL_TO_SHARE} layout={layout} />)
      clickShare()
      const field = await screen.findByRole('textbox', {
        name: 'Copy this link',
      })
      expect(field).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: 'Dismiss the link' }))

      expect(
        screen.queryByRole('textbox', { name: 'Copy this link' }),
      ).not.toBeInTheDocument()
      expect(screen.getByRole('status')).toBeEmptyDOMElement()
      expect(
        screen.getByRole('button', { name: 'Share this verdict' }),
      ).toHaveFocus()
    })
  },
)
