import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Heading } from './Heading'
import { nextHeadingLevel } from './headingLevel'

describe('Heading', () => {
  it.each([1, 2, 3, 4, 5, 6] as const)(
    'renders an h%i, keeping its id and class',
    (level) => {
      render(
        <Heading level={level} id="the-id" className="the-class">
          Quality wins
        </Heading>,
      )

      const heading = screen.getByRole('heading', {
        level,
        name: 'Quality wins',
      })
      expect(heading.tagName).toBe(`H${level}`)
      expect(heading).toHaveAttribute('id', 'the-id')
      expect(heading).toHaveClass('the-class')
    },
  )
})

describe('nextHeadingLevel', () => {
  it('is one level below, so a section under a heading never skips one', () => {
    expect(nextHeadingLevel(1)).toBe(2)
    expect(nextHeadingLevel(2)).toBe(3)
    expect(nextHeadingLevel(5)).toBe(6)
  })

  it('stays at h6, the deepest level HTML has', () => {
    expect(nextHeadingLevel(6)).toBe(6)
  })
})
