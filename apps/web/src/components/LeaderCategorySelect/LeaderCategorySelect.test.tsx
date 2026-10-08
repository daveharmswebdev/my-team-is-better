import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { PlayerLeaderCategory } from '../../lib/api/types'
import { LeaderCategorySelect } from './LeaderCategorySelect'

function renderSelect(value: PlayerLeaderCategory = 'passing') {
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

  it('offers every category, in the engine order, labelled for a reader', () => {
    const { select } = renderSelect()
    const options = within(select).getAllByRole('option')

    expect(options.map((option) => option.textContent)).toEqual([
      'Passing',
      'Rushing',
      'Receiving',
      'Kicking',
      'Punting',
    ])
    expect(
      options.map((option) => (option as HTMLOptionElement).value),
    ).toEqual(['passing', 'rushing', 'receiving', 'kicking', 'punting'])
  })

  it('shows the category it was given', () => {
    const { select } = renderSelect('rushing')

    expect(select).toHaveValue('rushing')
  })

  it('offers Receiving, and reports it when chosen (issue #314)', async () => {
    const user = userEvent.setup()
    const { select, onChange } = renderSelect('rushing')

    expect(
      within(select).getByRole('option', { name: 'Receiving' }),
    ).toHaveValue('receiving')
    await user.selectOptions(select, 'Receiving')

    expect(onChange.mock.calls).toEqual([['receiving']])
  })

  it('shows the receiving category when given it', () => {
    const { select } = renderSelect('receiving')

    expect(select).toHaveValue('receiving')
  })

  it('offers Kicking and Punting, and reports each when chosen (issue #315)', async () => {
    const user = userEvent.setup()
    const { select, onChange } = renderSelect('receiving')

    expect(within(select).getByRole('option', { name: 'Kicking' })).toHaveValue(
      'kicking',
    )
    expect(within(select).getByRole('option', { name: 'Punting' })).toHaveValue(
      'punting',
    )
    await user.selectOptions(select, 'Kicking')
    await user.selectOptions(select, 'Punting')

    expect(onChange.mock.calls).toEqual([['kicking'], ['punting']])
  })

  it('shows the kicking category when given it', () => {
    const { select } = renderSelect('kicking')
    expect(select).toHaveValue('kicking')
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
