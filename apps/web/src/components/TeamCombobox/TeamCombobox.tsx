import { useEffect, useId, useMemo, useRef, useState } from 'react'
import type { ChangeEvent, KeyboardEvent } from 'react'
import type { TeamDetail } from '../../lib/api/types'
import styles from './TeamCombobox.module.css'
import { matchTeams } from './teamMatching'

export interface TeamComboboxProps {
  /** Visible field label, rendered as this component's own `<label>`. */
  label: string
  /**
   * The pick-from universe (`/api/teams` detail rows). An empty array is a
   * supported state, not an error: the component degrades to a plain,
   * freely-typed input (see the component doc comment).
   */
  teams: TeamDetail[]
  /** Controlled value -- the string that will actually be submitted. */
  value: string
  /**
   * Called with the user's raw keystrokes while typing and with the
   * **canonical team name** (`TeamDetail.name`, byte-identical) when a
   * suggestion is picked. Never the display label, never the mascot.
   */
  onChange: (value: string) => void
  /** Overrides the generated input `id` (e.g. to match an external `<label htmlFor>`). */
  id?: string
  required?: boolean
  disabled?: boolean
  placeholder?: string
  /** Secondary text under the input -- e.g. a catalog-fetch-failed note. */
  hint?: string
  /** Caps how many suggestions render at once. Defaults to 50. */
  maxResults?: number
}

/** Separator between canonical name and mascot: "Texas · Longhorns". */
const SEPARATOR = ' · '

const DEFAULT_MAX_RESULTS = 50

/**
 * Accessible team typeahead (ARIA 1.2 combobox-with-listbox, hand-rolled --
 * no combobox dependency), replacing the native `<input list>` +
 * `<datalist>` this app started with. A `<datalist>` `<option>` renders
 * exactly one string, so it physically cannot show "Texas · Longhorns"
 * while submitting "Texas"; it also can't do substring highlighting and
 * behaves inconsistently across browsers and on mobile.
 *
 * Two invariants matter more than anything else here:
 *
 * 1. **Display the mascot, submit the canonical name.** The option reads
 *    "Texas · Longhorns"; `onChange` receives exactly `"Texas"`. The
 *    canonical string is the only thing that ever leaves this component,
 *    byte-identical, because the API's verdict lookup, the persona
 *    grounding check, the golden dataset, and every cached narration key
 *    are keyed on it.
 * 2. **Suggestions never gate submission.** An empty `teams` list (the
 *    catalog fetch failed, or hasn't landed) leaves a plain, freely-typed
 *    input with no combobox semantics at all; a typed value that matches
 *    nothing is still the value. `apps/api`'s mapped error responses (see
 *    `VerdictError`) remain the correction mechanism for a genuinely
 *    mistyped name -- matching here is substring-only, deliberately not
 *    typo-tolerant.
 */
export function TeamCombobox({
  label,
  teams,
  value,
  onChange,
  id,
  required = false,
  disabled = false,
  placeholder,
  hint,
  maxResults = DEFAULT_MAX_RESULTS,
}: TeamComboboxProps) {
  const generatedId = useId()
  const inputId = id ?? `${generatedId}-input`
  const listboxId = `${generatedId}-listbox`
  const optionId = (index: number) => `${generatedId}-option-${index}`

  const [isExpanded, setIsExpanded] = useState(false)
  /** -1 means "nothing active" -- an ambiguous match must never auto-select. */
  const [activeIndex, setActiveIndex] = useState(-1)

  const matches = useMemo(
    () => matchTeams(teams, value, maxResults),
    [teams, value, maxResults],
  )

  const activeOptionRef = useRef<HTMLLIElement | null>(null)

  const isOpen = isExpanded && matches.length > 0
  const activeTeam = activeIndex < 0 ? undefined : matches[activeIndex]
  const activeDescendant =
    isOpen && activeTeam !== undefined ? optionId(activeIndex) : undefined

  // The listbox scrolls at full-catalog scale, so arrow-key navigation has
  // to drag the viewport along with it. `scrollIntoView` is feature-detected
  // because jsdom (the Vitest environment) does not implement it.
  useEffect(() => {
    const node = activeOptionRef.current
    if (node !== null && typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' })
    }
  }, [activeIndex])

  function close() {
    setIsExpanded(false)
    setActiveIndex(-1)
  }

  function handleInputChange(event: ChangeEvent<HTMLInputElement>) {
    setIsExpanded(true)
    setActiveIndex(-1)
    onChange(event.target.value)
  }

  function selectTeam(team: TeamDetail) {
    close()
    // Canonical name only -- not the display label, not the mascot.
    onChange(team.name)
  }

  function moveActive(delta: number) {
    if (matches.length === 0) {
      return
    }
    const firstOrLast = delta > 0 ? 0 : matches.length - 1
    if (!isOpen || activeIndex < 0) {
      setIsExpanded(true)
      setActiveIndex(firstOrLast)
      return
    }
    setActiveIndex((activeIndex + delta + matches.length) % matches.length)
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault()
        moveActive(1)
        return
      case 'ArrowUp':
        event.preventDefault()
        moveActive(-1)
        return
      case 'Enter':
        // With no active option, Enter is left alone so the surrounding
        // form still submits the typed value.
        if (isOpen && activeTeam !== undefined) {
          event.preventDefault()
          selectTeam(activeTeam)
        }
        return
      case 'Escape':
        if (isOpen) {
          event.preventDefault()
        }
        close()
        return
      default:
        return
    }
  }

  // No suggestions to offer: a plain input, with none of the combobox
  // semantics a screen reader would then have to reconcile with an
  // always-empty listbox.
  if (teams.length === 0) {
    return (
      <div className={styles.field}>
        <label htmlFor={inputId}>{label}</label>
        <input
          id={inputId}
          className={styles.input}
          type="text"
          value={value}
          onChange={(event) => onChange(event.target.value)}
          required={required}
          disabled={disabled}
          placeholder={placeholder}
          autoComplete="off"
        />
        {hint !== undefined && <p className={styles.hint}>{hint}</p>}
      </div>
    )
  }

  return (
    <div className={styles.field}>
      <label htmlFor={inputId}>{label}</label>
      <div className={styles.combo}>
        <input
          id={inputId}
          className={styles.input}
          type="text"
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeDescendant}
          value={value}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onClick={() => setIsExpanded(true)}
          onBlur={close}
          required={required}
          disabled={disabled}
          placeholder={placeholder}
          autoComplete="off"
        />
        {isOpen && (
          <ul
            className={styles.listbox}
            id={listboxId}
            role="listbox"
            aria-label={`${label} suggestions`}
          >
            {matches.map((team, index) => (
              <li
                key={team.name}
                ref={index === activeIndex ? activeOptionRef : null}
                id={optionId(index)}
                role="option"
                aria-selected={index === activeIndex}
                className={
                  index === activeIndex
                    ? `${styles.option} ${styles.optionActive}`
                    : styles.option
                }
                // Keeps focus (and therefore the open listbox) on the input
                // so the click below actually lands on a mounted option.
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectTeam(team)}
              >
                <span className={styles.optionName}>{team.name}</span>
                {team.mascot !== null && (
                  <span className={styles.optionMascot}>
                    {SEPARATOR}
                    {team.mascot}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
      <div role="status" className={styles.srOnly}>
        {isOpen
          ? `${matches.length} ${matches.length === 1 ? 'team' : 'teams'} match`
          : ''}
      </div>
      {hint !== undefined && <p className={styles.hint}>{hint}</p>}
    </div>
  )
}
