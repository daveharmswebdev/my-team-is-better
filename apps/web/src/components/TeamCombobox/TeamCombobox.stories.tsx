import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'
import { fn } from 'storybook/test'
import type { TeamDetail } from '../../lib/api/types'
import { TeamCombobox } from './TeamCombobox'
import type { TeamComboboxProps } from './TeamCombobox'

const CFB_TEAMS: TeamDetail[] = [
  { name: 'Texas', mascot: 'Longhorns', aliases: ['TEX'] },
  { name: 'Texas A&M', mascot: 'Aggies', aliases: ['TAMU'] },
  { name: 'TCU', mascot: 'Horned Frogs', aliases: ['Texas Christian', 'TCU'] },
  { name: 'North Texas', mascot: 'Mean Green', aliases: ['UNT'] },
  {
    name: 'NC State',
    mascot: 'Wolfpack',
    aliases: ['North Carolina St.', 'NCSU'],
  },
  { name: 'San José State', mascot: 'Spartans', aliases: ['SJSU'] },
  { name: 'Miami', mascot: 'Hurricanes', aliases: ['Miami (FL)', 'MIA'] },
  { name: 'Miami (OH)', mascot: 'RedHawks', aliases: [] },
  { name: 'Ohio State', mascot: 'Buckeyes', aliases: ['OSU'] },
  { name: 'USC', mascot: 'Trojans', aliases: ['Southern California'] },
  { name: 'Army', mascot: null, aliases: ['Army West Point'] },
]

const NFL_TEAMS: TeamDetail[] = [
  { name: 'New England Patriots', mascot: null, aliases: [] },
  { name: 'New York Giants', mascot: null, aliases: [] },
  { name: 'New York Jets', mascot: null, aliases: [] },
  { name: 'Dallas Cowboys', mascot: null, aliases: [] },
  { name: 'Green Bay Packers', mascot: null, aliases: [] },
  { name: 'Kansas City Chiefs', mascot: null, aliases: [] },
]

/** ~130 rows, roughly the real FBS catalog size, to exercise scrolling and the result cap. */
const LONG_LIST: TeamDetail[] = Array.from({ length: 130 }, (_, index) => {
  const base = CFB_TEAMS[index % CFB_TEAMS.length]
  return {
    name: index < CFB_TEAMS.length ? (base?.name ?? '') : `State U ${index}`,
    mascot: base?.mascot ?? null,
    aliases: base?.aliases ?? [],
  }
})

/**
 * `TeamCombobox` is controlled, so the stories own the value -- otherwise
 * typing in the Storybook canvas would never update the input.
 */
function ControlledTeamCombobox(props: TeamComboboxProps) {
  const { value: initialValue, onChange, ...rest } = props
  const [value, setValue] = useState(initialValue)
  return (
    <TeamCombobox
      {...rest}
      value={value}
      onChange={(next) => {
        setValue(next)
        onChange(next)
      }}
    />
  )
}

const meta = {
  title: 'components/TeamCombobox',
  component: TeamCombobox,
  tags: ['autodocs'],
  args: {
    label: 'Team',
    value: '',
    onChange: fn(),
  },
  render: (args) => <ControlledTeamCombobox {...args} />,
} satisfies Meta<typeof TeamCombobox>

export default meta

type Story = StoryObj<typeof meta>

/** Type "longhorn" (mascot) or "sjsu" (alias) -- both find their team. */
export const Default: Story = {
  args: {
    teams: CFB_TEAMS,
  },
}

/**
 * "New York" is genuinely ambiguous and stays that way: both the Giants and
 * the Jets are listed, neither is auto-selected.
 */
export const AmbiguousCity: Story = {
  args: {
    teams: NFL_TEAMS,
    value: 'New York',
  },
}

/** NFL rows have `mascot: null` -- the name renders alone, with no dangling separator. */
export const NoMascot: Story = {
  args: {
    teams: NFL_TEAMS,
    value: 'new',
  },
}

/** Catalog fetch failed or returned nothing: a plain, freely-typed input. */
export const EmptyList: Story = {
  args: {
    teams: [],
    hint: "Couldn't load the team list -- you can still type any name.",
  },
}

/** Full-catalog scale: the listbox scrolls and caps at `maxResults`. */
export const LongList: Story = {
  args: {
    teams: LONG_LIST,
  },
}
