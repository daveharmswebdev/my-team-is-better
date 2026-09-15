import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { TeamDetail } from '../../lib/api/types'
import { TeamCombobox } from './TeamCombobox'
import { isTeamInCatalog } from './teamMatching'

/**
 * Calibrated against the real `/api/teams` detail rows quoted in issue #79:
 * accented canonical names, empty and multi-entry alias lists, and the
 * `Miami` / `Miami (OH)` pair that makes ranking order observable.
 */
const CFB_TEAMS: TeamDetail[] = [
  { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
  { name: 'Texas A&M', mascot: 'Aggies', aliases: ['TAMU'] },
  { name: 'TCU', mascot: 'Horned Frogs', aliases: ['Texas Christian'] },
  { name: 'North Texas', mascot: 'Mean Green', aliases: [] },
  {
    name: 'NC State',
    mascot: 'Wolfpack',
    aliases: ['North Carolina St.', 'NCSU'],
  },
  { name: 'San José State', mascot: 'Spartans', aliases: ['SJSU'] },
  { name: 'Miami', mascot: 'Hurricanes', aliases: ['Miami (FL)', 'MIA'] },
  { name: 'Miami (OH)', mascot: 'RedHawks', aliases: [] },
]

/** NFL rows carry `mascot: null` -- the canonical name already holds city + nickname. */
const NFL_TEAMS: TeamDetail[] = [
  { name: 'New England Patriots', mascot: null, aliases: [] },
  { name: 'New York Giants', mascot: null, aliases: [] },
  { name: 'New York Jets', mascot: null, aliases: [] },
  { name: 'Dallas Cowboys', mascot: null, aliases: [] },
]

interface HarnessProps {
  teams: TeamDetail[]
  onChange?: (value: string) => void
  initialValue?: string
}

/** Controlled-parent stand-in: `TeamCombobox` owns no value state of its own. */
function Harness({ teams, onChange, initialValue = '' }: HarnessProps) {
  const [value, setValue] = useState(initialValue)
  return (
    <TeamCombobox
      label="Team"
      teams={teams}
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange?.(next)
      }}
    />
  )
}

function squash(text: string | null): string {
  return (text ?? '').replace(/\s+/g, ' ').trim()
}

function optionLabels(): string[] {
  return screen
    .getAllByRole('option')
    .map((option) => squash(option.textContent))
}

function optionByLabel(label: string): HTMLElement {
  const match = screen
    .getAllByRole('option')
    .find((option) => squash(option.textContent) === label)
  if (match === undefined) {
    throw new Error(
      `no option labelled "${label}"; visible options: ${optionLabels().join(' | ')}`,
    )
  }
  return match
}

function getInput(): HTMLInputElement {
  return screen.getByRole('combobox', { name: /team/i })
}

describe('TeamCombobox', () => {
  it('test_substring_match_on_mascot: typing "longhorn" surfaces Texas', async () => {
    const user = userEvent.setup()
    render(<Harness teams={CFB_TEAMS} />)

    await user.type(getInput(), 'longhorn')

    expect(optionLabels()).toEqual(['Texas · Longhorns'])
  })

  it('test_substring_match_on_city: typing "New England" surfaces the Patriots', async () => {
    const user = userEvent.setup()
    render(<Harness teams={NFL_TEAMS} />)

    await user.type(getInput(), 'New England')

    expect(optionLabels()).toEqual(['New England Patriots'])
  })

  it('test_ambiguous_city_lists_both: "New York" yields Giants and Jets, nothing auto-selected', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness teams={NFL_TEAMS} onChange={onChange} />)

    const input = getInput()
    await user.type(input, 'New York')

    expect(optionLabels()).toEqual(['New York Giants', 'New York Jets'])
    // Nothing auto-selected: no active descendant, no option marked selected.
    expect(input).not.toHaveAttribute('aria-activedescendant')
    for (const option of screen.getAllByRole('option')) {
      expect(option).toHaveAttribute('aria-selected', 'false')
    }
    // The only values emitted so far are the user's own keystrokes.
    expect(onChange).toHaveBeenLastCalledWith('New York')
  })

  it('test_selection_emits_canonical_name_not_display_label', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness teams={CFB_TEAMS} onChange={onChange} />)

    const input = getInput()
    await user.type(input, 'longhorn')
    await user.click(optionByLabel('Texas · Longhorns'))

    expect(onChange).toHaveBeenLastCalledWith('Texas')
    expect(onChange).not.toHaveBeenCalledWith('Texas · Longhorns')
    expect(onChange).not.toHaveBeenCalledWith('Longhorns')
    expect(input).toHaveValue('Texas')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
  })

  it('test_keyboard_navigation_and_escape', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness teams={NFL_TEAMS} onChange={onChange} />)

    const input = getInput()
    await user.type(input, 'new york')

    const [giants, jets] = screen.getAllByRole('option')
    expect(giants).toBeDefined()
    expect(jets).toBeDefined()

    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', giants?.id)
    expect(giants).toHaveAttribute('aria-selected', 'true')

    await user.keyboard('{ArrowDown}')
    expect(input).toHaveAttribute('aria-activedescendant', jets?.id)

    await user.keyboard('{ArrowUp}')
    expect(input).toHaveAttribute('aria-activedescendant', giants?.id)

    await user.keyboard('{Enter}')
    expect(onChange).toHaveBeenLastCalledWith('New York Giants')
    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-expanded', 'false')

    // Escape closes the reopened list without discarding the typed value.
    await user.clear(input)
    await user.type(input, 'new york')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    await user.keyboard('{ArrowDown}')
    await user.keyboard('{Escape}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(input).not.toHaveAttribute('aria-activedescendant')
    expect(input).toHaveValue('new york')
  })

  it('test_empty_team_list_degrades_to_plain_input', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness teams={[]} onChange={onChange} />)

    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    const input = screen.getByRole('textbox', { name: /team/i })
    // None of the combobox semantics a screen reader would then have to
    // reconcile with an always-empty listbox: no role, no popup wiring, no
    // status region announcing match counts.
    for (const attribute of [
      'role',
      'aria-expanded',
      'aria-controls',
      'aria-autocomplete',
      'aria-activedescendant',
    ]) {
      expect(input).not.toHaveAttribute(attribute)
    }
    expect(screen.queryByRole('status')).not.toBeInTheDocument()

    await user.type(input, 'Texs')
    await user.keyboard('{ArrowDown}')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(onChange).toHaveBeenLastCalledWith('Texs')
    expect(input).toHaveValue('Texs')
  })

  it('test_catalog_arrival_keeps_the_focused_input_and_its_value (issue #156)', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    const { rerender } = render(<Harness teams={[]} onChange={onChange} />)

    const input = screen.getByRole('textbox', { name: /team/i })
    await user.click(input)
    await user.type(input, 'Tex')
    expect(document.activeElement).toBe(input)

    // `/api/teams` resolves mid-keystroke.
    rerender(<Harness teams={CFB_TEAMS} onChange={onChange} />)

    // The very same element (identity, not just role) is still focused,
    // still holds what was typed, and has become the combobox.
    expect(document.activeElement).toBe(input)
    expect(screen.getByRole('combobox', { name: /team/i })).toBe(input)
    expect(input).toHaveValue('Tex')

    await user.keyboard('as')

    expect(input).toHaveValue('Texas')
    expect(onChange).toHaveBeenLastCalledWith('Texas')
    expect(screen.getByRole('listbox')).toBeInTheDocument()
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(optionLabels()[0]).toBe('Texas · Longhorns')
  })

  it('matches diacritics insensitively: "san jose" finds San José State', async () => {
    const user = userEvent.setup()
    render(<Harness teams={CFB_TEAMS} />)

    await user.type(getInput(), 'san jose')

    expect(optionLabels()).toEqual(['San José State · Spartans'])
  })

  it('matches on an alias: "NCSU" finds NC State', async () => {
    const user = userEvent.setup()
    render(<Harness teams={CFB_TEAMS} />)

    await user.type(getInput(), 'NCSU')

    expect(optionLabels()).toEqual(['NC State · Wolfpack'])
  })

  it('ranks exact match, then name prefix, then mascot/alias, then substring anywhere', async () => {
    const user = userEvent.setup()
    render(<Harness teams={CFB_TEAMS} />)

    await user.type(getInput(), 'texas')

    expect(optionLabels()).toEqual([
      'Texas · Longhorns', // exact canonical match
      'Texas A&M · Aggies', // canonical-name prefix
      'TCU · Horned Frogs', // alias match ("Texas Christian")
      'North Texas · Mean Green', // substring anywhere
    ])
  })

  it('renders a mascot-less team with no dangling separator', async () => {
    const user = userEvent.setup()
    render(<Harness teams={NFL_TEAMS} />)

    await user.type(getInput(), 'patriots')

    const option = screen.getByRole('option')
    expect(squash(option.textContent)).toBe('New England Patriots')
    expect(option.textContent).not.toContain('·')
  })

  it('exposes full ARIA combobox wiring', async () => {
    const user = userEvent.setup()
    render(<Harness teams={CFB_TEAMS} />)

    const input = getInput()
    expect(input).toHaveAttribute('aria-expanded', 'false')

    await user.type(input, 'miami')

    const listbox = screen.getByRole('listbox')
    expect(input).toHaveAttribute('aria-expanded', 'true')
    expect(input).toHaveAttribute('aria-controls', listbox.id)
    expect(optionLabels()).toEqual([
      'Miami · Hurricanes',
      'Miami (OH) · RedHawks',
    ])
  })

  it('shows no listbox when nothing matches, and never blocks the typed value', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Harness teams={CFB_TEAMS} onChange={onChange} />)

    const input = getInput()
    await user.type(input, 'Longhrons')

    expect(screen.queryByRole('listbox')).not.toBeInTheDocument()
    expect(input).toHaveAttribute('aria-expanded', 'false')
    expect(onChange).toHaveBeenLastCalledWith('Longhrons')
    expect(input).toHaveValue('Longhrons')
  })
})

/**
 * The exported membership check behind `QuestionForm`'s stale-value flag
 * (issue #100). It is the *submittable-name* test, not the suggestion test:
 * a partial query or a mascot ranks as a typeahead match but is not a name
 * the API resolves, so flagging must not treat either as "in scope".
 */
describe('isTeamInCatalog', () => {
  it.each([
    ['an exact canonical name', 'Texas'],
    ['a differently-cased name', 'texas'],
    ['a name with the accent dropped', 'San Jose State'],
    ['an alias the API resolves', 'TEX'],
    ['a value with surrounding whitespace', '  Texas  '],
  ])('accepts %s', (_case, value) => {
    expect(isTeamInCatalog(CFB_TEAMS, value)).toBe(true)
  })

  it.each([
    ['a partial name the typeahead would still offer', 'Texa'],
    ['a mascot, which is displayed but never submitted', 'Longhorns'],
    ['a team from another league or season', 'Kansas City Chiefs'],
    ['an empty value', ''],
    ['a whitespace-only value', '   '],
  ])('rejects %s', (_case, value) => {
    expect(isTeamInCatalog(CFB_TEAMS, value)).toBe(false)
  })

  it('is false for every value when the catalog is empty', () => {
    expect(isTeamInCatalog([], 'Texas')).toBe(false)
  })
})
