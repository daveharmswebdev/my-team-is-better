import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Greeting } from './Greeting'

describe('Greeting', () => {
  it('renders a greeting addressed to the given name', () => {
    render(<Greeting name="Coach" />)

    expect(
      screen.getByRole('heading', { name: 'Hello, Coach!' }),
    ).toBeInTheDocument()
  })
})
