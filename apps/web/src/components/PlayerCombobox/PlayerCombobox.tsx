import { useEffect, useId, useRef, useState } from 'react'
import type { ChangeEvent, KeyboardEvent } from 'react'
import type { PlayerSearchRowOut } from '../../lib/api/types'
import { formatSeasonSpan } from '../../lib/playerStats'
import styles from './PlayerCombobox.module.css'

/** Where the parent's search for the typed text stands. */
export type PlayerSearchStatus = 'idle' | 'searching' | 'done' | 'error'

export interface PlayerComboboxProps {
  /** Visible field label, rendered as this component's own `<label>`. */
  label: string
  /** Controlled text in the field. */
  value: string
  /** Called with every keystroke's text. */
  onChange: (text: string) => void
  /** The parent's search results for the typed text, in the API's order. */
  options: PlayerSearchRowOut[]
  /** Called with the picked player. */
  onSelect: (player: PlayerSearchRowOut) => void
  status: PlayerSearchStatus
  /** Secondary text under the field, e.g. a search that failed. */
  hint?: string
  placeholder?: string
}

const SEPARATOR = ' · '

/** The longest query `GET /api/players/search` accepts. */
const MAX_QUERY_LENGTH = 100

function statusText(
  expanded: boolean,
  status: PlayerSearchStatus,
  count: number,
): string {
  if (!expanded) {
    return ''
  }
  if (count > 0) {
    return count === 1 ? '1 player matches' : `${count} players match`
  }
  if (status === 'searching') {
    return 'Searching…'
  }
  return status === 'done' ? 'No players match' : ''
}

/**
 * Player typeahead for the comparison (issue #301), following
 * `TeamCombobox`'s ARIA 1.2 combobox-with-listbox pattern. It fetches
 * nothing: the page searches `GET /api/players/search` for the typed text and
 * passes the rows in, so this component never imports a page or the client.
 *
 * Each option shows the name, position and season span, so two players with
 * the same name can be told apart. Picking one hands the whole row back; the
 * field's text is only ever what the parent sets.
 */
export function PlayerCombobox({
  label,
  value,
  onChange,
  options,
  onSelect,
  status,
  hint,
  placeholder,
}: PlayerComboboxProps) {
  const generatedId = useId()
  const inputId = `${generatedId}-input`
  const listboxId = `${generatedId}-listbox`
  const hintId = `${generatedId}-hint`
  const optionId = (index: number) => `${generatedId}-option-${index}`

  const [isExpanded, setIsExpanded] = useState(false)
  /** -1 means nothing active: typing never picks a player by itself. */
  const [activeIndex, setActiveIndex] = useState(-1)
  const activeOptionRef = useRef<HTMLLIElement | null>(null)

  const isOpen = isExpanded && options.length > 0
  const activePlayer = activeIndex < 0 ? undefined : options[activeIndex]
  const activeDescendant =
    isOpen && activePlayer !== undefined ? optionId(activeIndex) : undefined

  // `scrollIntoView` is feature-detected: jsdom doesn't implement it.
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

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    setIsExpanded(true)
    setActiveIndex(-1)
    onChange(event.target.value)
  }

  function select(player: PlayerSearchRowOut) {
    close()
    onSelect(player)
  }

  function moveActive(delta: number) {
    if (options.length === 0) {
      return
    }
    if (!isOpen || activeIndex < 0) {
      setIsExpanded(true)
      setActiveIndex(delta > 0 ? 0 : options.length - 1)
      return
    }
    setActiveIndex((activeIndex + delta + options.length) % options.length)
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
        if (isOpen && activePlayer !== undefined) {
          event.preventDefault()
          select(activePlayer)
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

  const noMatches = isExpanded && status === 'done' && options.length === 0

  return (
    <div className={styles.field}>
      <label htmlFor={inputId}>{label}</label>
      <div className={styles.combo}>
        <input
          id={inputId}
          className={styles.input}
          type="text"
          value={value}
          placeholder={placeholder}
          autoComplete="off"
          spellCheck={false}
          maxLength={MAX_QUERY_LENGTH}
          role="combobox"
          aria-expanded={isOpen}
          aria-controls={listboxId}
          aria-autocomplete="list"
          aria-activedescendant={activeDescendant}
          aria-describedby={hint === undefined ? undefined : hintId}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onClick={() => setIsExpanded(true)}
          onBlur={close}
        />
        {isOpen && (
          <ul
            className={styles.listbox}
            id={listboxId}
            role="listbox"
            aria-label={`${label} suggestions`}
          >
            {options.map((player, index) => (
              <li
                key={player.player_id}
                ref={index === activeIndex ? activeOptionRef : null}
                id={optionId(index)}
                role="option"
                aria-selected={index === activeIndex}
                className={
                  index === activeIndex
                    ? `${styles.option} ${styles.optionActive}`
                    : styles.option
                }
                // Keeps focus on the input so the click lands on a mounted option.
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => select(player)}
              >
                <span className={styles.optionName}>{player.display_name}</span>
                <span className={styles.optionMeta}>
                  {SEPARATOR}
                  {player.position ?? 'position not recorded'},{' '}
                  {formatSeasonSpan(player.first_season, player.last_season)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div role="status" className={styles.srOnly}>
        {statusText(isExpanded, status, options.length)}
      </div>
      {noMatches && (
        <p className={styles.empty} aria-hidden="true">
          Nobody by that name.
        </p>
      )}
      {hint !== undefined && (
        <p id={hintId} className={styles.hint}>
          {hint}
        </p>
      )}
    </div>
  )
}
