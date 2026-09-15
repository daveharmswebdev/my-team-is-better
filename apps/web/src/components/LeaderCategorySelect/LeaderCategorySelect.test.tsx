import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { LeaderCategorySelect } from './LeaderCategorySelect'

function renderSelect(value: 'passing' | 'rushing' = 'passing') {
  const onChange = vi.fn()
  render(<LeaderCategorySelect value={value} onChange={onChange} />)
  return {
    onChange,
    select: screen.getByRole('combobox', { name: 'Stat category' }),
  }
}

describe('LeaderCategorySelect (issue #312)', () => {
  it('is a dropdown whose accessible name comes from a real label', () => {
    const { select } = renderSelect()

    expect(select.tagName).toBe('SELECT')
    expect(select).toHaveAccessibleName('Stat category')
  })

  it('offers both categories, in the engine order, labelled for a reader', () => {
    const { select } = renderSelect()
    const options = within(select).getAllByRole('option')

    expect(options.map((option) => option.textContent)).toEqual([
      'Passing',
      'Rushing',
    ])
    expect(
      options.map((option) => (option as HTMLOptionElement).value),
    ).toEqual(['passing', 'rushing'])
  })

  it('shows the category it was given', () => {
    const { select } = renderSelect('rushing')

    expect(select).toHaveValue('rushing')
  })

  it('reports the category chosen, once', async () => {
    const user = userEvent.setup()
    const { select, onChange } = renderSelect()

    await user.selectOptions(select, 'rushing')

    expect(onChange.mock.calls).toEqual([['rushing']])
  })

  it('is reachable and operable from the keyboard', async () => {
    const user = userEvent.setup()
    const { select, onChange } = renderSelect()

    await user.tab()
    expect(select).toHaveFocus()
    await user.selectOptions(select, 'rushing')

    expect(onChange).toHaveBeenCalledWith('rushing')
  })
})
