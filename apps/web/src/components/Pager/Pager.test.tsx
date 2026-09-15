import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { Pager } from './Pager'

function renderPager(offset: number, shown: number, total: number) {
  const onPage = vi.fn()
  render(
    <Pager
      label="Leaders pages"
      offset={offset}
      limit={50}
      shown={shown}
      total={total}
      onPage={onPage}
    />,
  )
  return { onPage }
}

describe('Pager (issue #296)', () => {
  it('is a named navigation landmark', () => {
    renderPager(0, 50, 204)

    expect(
      screen.getByRole('navigation', { name: 'Leaders pages' }),
    ).toBeInTheDocument()
  })

  it.each([
    [0, 50, 204, '1–50 of 204'],
    [50, 50, 204, '51–100 of 204'],
    [200, 4, 204, '201–204 of 204'],
    [0, 50, 1234, '1–50 of 1,234'],
    [300, 0, 204, '0 of 204'],
  ])('at offset %i showing %i of %i, says %j', (offset, shown, total, text) => {
    renderPager(offset, shown, total)

    expect(screen.getByText(text)).toBeInTheDocument()
  })

  it('asks for the next page, and marks Previous unavailable on the first', async () => {
    const user = userEvent.setup()
    const { onPage } = renderPager(0, 50, 204)

    const previous = screen.getByRole('button', { name: 'Previous page' })
    expect(previous).toHaveAttribute('aria-disabled', 'true')
    await user.click(previous)
    expect(onPage).not.toHaveBeenCalled()

    const next = screen.getByRole('button', { name: 'Next page' })
    expect(next).toHaveAttribute('aria-disabled', 'false')
    await user.click(next)
    expect(onPage).toHaveBeenCalledWith(50)
  })

  it('asks for the previous page, never before the top', async () => {
    const user = userEvent.setup()
    const { onPage } = renderPager(30, 50, 204)

    await user.click(screen.getByRole('button', { name: 'Previous page' }))

    expect(onPage).toHaveBeenCalledWith(0)
  })

  it('marks Next unavailable on the last page', async () => {
    const user = userEvent.setup()
    const { onPage } = renderPager(200, 4, 204)

    const next = screen.getByRole('button', { name: 'Next page' })
    expect(next).toHaveAttribute('aria-disabled', 'true')
    await user.click(next)
    expect(onPage).not.toHaveBeenCalled()
    await user.click(screen.getByRole('button', { name: 'Previous page' }))
    expect(onPage).toHaveBeenCalledWith(150)
  })
})
