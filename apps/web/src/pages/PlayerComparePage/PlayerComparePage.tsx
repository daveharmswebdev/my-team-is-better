import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { PlayerCombobox } from '../../components/PlayerCombobox/PlayerCombobox'
import { PlayerComparisonTable } from '../../components/PlayerComparisonTable/PlayerComparisonTable'
import { PlayerHeadToHead } from '../../components/PlayerHeadToHead/PlayerHeadToHead'
import { PlayerStatsCredit } from '../../components/PlayerStatsCredit/PlayerStatsCredit'
import {
  PlayerApiError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
  fetchPlayerCareer,
  fetchPlayerComparison,
} from '../../lib/api/client'
import type {
  PlayerCareerTotalsOut,
  PlayerComparisonOut,
  PlayerSearchRowOut,
  PlayerSeasonType,
} from '../../lib/api/types'
import {
  HEAD_TO_HEAD_RULE,
  MARK_GLYPH,
  MARK_LEGEND,
  NEITHER_TOTALS_COPY,
  NO_TOTALS_COPY,
  PICK_FROM_LIST_COPY,
  PICK_TWO_COPY,
  SAME_PLAYER_COPY,
  SEARCH_FAILED_COPY,
  compareUndercountNote,
  pickOneMoreCopy,
} from '../../lib/playerCompare'
import {
  PLAYER_NOT_FOUND_COPY,
  SEASON_TYPE_LABEL,
  STARTER_RECORD_NOTE,
} from '../../lib/playerStats'
import { usePlayerStatsCredit } from '../usePlayerStatsCredit'
import { usePlayerSearch } from './usePlayerSearch'
import styles from './PlayerComparePage.module.css'

type Slot = 'a' | 'b'

const SLOTS: readonly Slot[] = ['a', 'b']

/** One URL param: nobody picked, a player id, or something no id can be. */
type Pick = number | null | 'invalid'

function parsePick(raw: string | null): Pick {
  if (raw === null || raw === '') {
    return null
  }
  if (!/^\d+$/.test(raw)) {
    return 'invalid'
  }
  const id = Number(raw)
  return Number.isSafeInteger(id) ? id : 'invalid'
}

/** A failure as the page shows it: an unknown player, or narrator copy. */
type Failure = { status: 'not_found' } | { status: 'error'; message: string }

function failureOf(error: unknown): Failure {
  if (error instanceof PlayerApiError) {
    return { status: 'not_found' }
  }
  // Both carry plain narrator copy, never a raw status (issue #215).
  const message =
    error instanceof VerdictNetworkError || error instanceof VerdictHttpError
      ? error.message
      : SERVER_ERROR_COPY
  return { status: 'error', message }
}

/** The latest comparison answer, tagged with the pair it answers. */
type ComparisonAnswer = { key: string } & (
  { status: 'success'; comparison: PlayerComparisonOut } | Failure
)

/** The latest lone-player answer, tagged with the id it answers. */
type CareerAnswer = { id: number } & ({ status: 'success' } | Failure)

/**
 * A player in a slot. A pick seeded from the URL has no name until the API
 * names that player; until then the field is empty and it can't be compared.
 */
interface SlotPick {
  player_id: number
  display_name: string | null
}

/** A slot's field: a pick, or the text typed since. Typing clears the pick. */
interface SlotState {
  pick: SlotPick | null
  text: string
}

/** The slots, and the navigation (`location.key`) they were seeded from. */
interface Seeded {
  locationKey: string
  slots: Record<Slot, SlotState>
}

function seedSlots(
  picks: Record<Slot, Pick>,
  names: Record<number, string>,
): Record<Slot, SlotState> {
  const seed = (pick: Pick): SlotState => ({
    pick:
      typeof pick === 'number'
        ? { player_id: pick, display_name: names[pick] ?? null }
        : null,
    text: '',
  })
  return { a: seed(picks.a), b: seed(picks.b) }
}

/**
 * Two NFL players side by side (issue #301): career totals of each season
 * type in their own table, with the larger number in each row marked, and
 * their games against each other as opposing starting quarterbacks.
 *
 * Each field holds a pick or typed text, never both (issue #304): typing over
 * a pick clears it, and picking a suggestion changes only that field. The URL
 * (`?a=<id>&b=<id>`) is the comparison on screen, and only the Compare button
 * changes it, pushing a history entry, so a link, a reload and Back all show
 * the same comparison. Every press asks again, even for the pair on screen.
 * Any navigation re-seeds the fields from the URL. The same player twice, or
 * an id that can't be one, is answered here without asking the API.
 *
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function PlayerComparePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const pickA = parsePick(searchParams.get('a'))
  const pickB = parsePick(searchParams.get('b'))

  const [names, setNames] = useState<Record<number, string>>({})
  const [seeded, setSeeded] = useState<Seeded>(() => ({
    locationKey: location.key,
    slots: seedSlots({ a: pickA, b: pickB }, {}),
  }))
  /** Bumped by every Compare press on the pair already committed. */
  const [run, setRun] = useState(0)
  const [comparisonAnswer, setComparisonAnswer] =
    useState<ComparisonAnswer | null>(null)
  const [careerAnswer, setCareerAnswer] = useState<CareerAnswer | null>(null)
  const credit = usePlayerStatsCredit()
  const noteId = useId()
  const pickHintId = `${noteId}-pick-hint`

  // Back, Forward or a link moved the URL: the fields follow it.
  let slots = seeded.slots
  if (seeded.locationKey !== location.key) {
    slots = seedSlots({ a: pickA, b: pickB }, names)
    setSeeded({ locationKey: location.key, slots })
  }

  const comparisonKey =
    typeof pickA === 'number' && typeof pickB === 'number' && pickA !== pickB
      ? `${pickA}:${pickB}`
      : null
  // Exactly one player picked: that player's career gives the field a name.
  const loneId =
    typeof pickA === 'number' && pickB === null
      ? pickA
      : pickA === null && typeof pickB === 'number'
        ? pickB
        : null

  // `run` is a dependency on purpose: each press of Compare asks again.
  useEffect(() => {
    if (typeof pickA !== 'number' || typeof pickB !== 'number') {
      return
    }
    if (pickA === pickB) {
      return
    }
    let cancelled = false
    const key = `${pickA}:${pickB}`
    fetchPlayerComparison(pickA, pickB)
      .then((comparison) => {
        if (cancelled) {
          return
        }
        setComparisonAnswer({ key, status: 'success', comparison })
        setNames((known) => ({
          ...known,
          [comparison.a.player_id]: comparison.a.display_name,
          [comparison.b.player_id]: comparison.b.display_name,
        }))
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setComparisonAnswer({ key, ...failureOf(error) })
        }
      })
    return () => {
      cancelled = true
    }
  }, [pickA, pickB, run])

  useEffect(() => {
    if (loneId === null) {
      return
    }
    let cancelled = false
    fetchPlayerCareer(loneId)
      .then((career) => {
        if (cancelled) {
          return
        }
        setCareerAnswer({ id: loneId, status: 'success' })
        setNames((known) => ({
          ...known,
          [career.player_id]: career.display_name,
        }))
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          setCareerAnswer({ id: loneId, ...failureOf(error) })
        }
      })
    return () => {
      cancelled = true
    }
  }, [loneId])

  function pickName(pick: SlotPick): string | null {
    return pick.display_name ?? names[pick.player_id] ?? null
  }

  /**
   * A slot's player id once the field shows that player's name; `null`
   * otherwise, so an empty field is never compared.
   */
  function namedPick(slot: Slot): number | null {
    const { pick } = slots[slot]
    return pick !== null && pickName(pick) !== null ? pick.player_id : null
  }

  function fieldText(slot: Slot): string {
    const { pick, text } = slots[slot]
    return pick === null ? text : (pickName(pick) ?? '')
  }

  const searchA = usePlayerSearch(slots.a.pick === null ? slots.a.text : '')
  const searchB = usePlayerSearch(slots.b.pick === null ? slots.b.text : '')

  function updateSlot(slot: Slot, next: SlotState) {
    setSeeded((current) => ({
      ...current,
      slots: { ...current.slots, [slot]: next },
    }))
  }

  function handleType(slot: Slot, text: string) {
    updateSlot(slot, { pick: null, text })
  }

  /** Fills the field only: nothing is compared until Compare is pressed. */
  function handleSelect(slot: Slot, player: PlayerSearchRowOut) {
    setNames((known) => ({
      ...known,
      [player.player_id]: player.display_name,
    }))
    updateSlot(slot, {
      pick: { player_id: player.player_id, display_name: player.display_name },
      text: '',
    })
  }

  function handleClear(slot: Slot) {
    updateSlot(slot, { pick: null, text: '' })
  }

  const compareA = namedPick('a')
  const compareB = namedPick('b')
  const canCompare = compareA !== null && compareB !== null
  const typedNotPicked = SLOTS.some(
    (slot) => slots[slot].pick === null && slots[slot].text !== '',
  )

  /** Pushes a history entry for a new pair; the pair on screen asks again. */
  function handleCompare() {
    if (compareA === null || compareB === null) {
      return
    }
    if (compareA === pickA && compareB === pickB) {
      setRun((count) => count + 1)
      return
    }
    setSearchParams({ a: String(compareA), b: String(compareB) })
  }

  const currentComparison =
    comparisonKey !== null && comparisonAnswer?.key === comparisonKey
      ? comparisonAnswer
      : null
  const currentCareer =
    loneId !== null && careerAnswer?.id === loneId ? careerAnswer : null

  let body: ReactNode
  if (pickA === 'invalid' || pickB === 'invalid') {
    body = <NotFound />
  } else if (pickA !== null && pickA === pickB) {
    body = (
      <p role="alert" className={styles.error}>
        {SAME_PLAYER_COPY}
      </p>
    )
  } else if (comparisonKey !== null) {
    if (currentComparison === null) {
      body = (
        <p role="status" className={styles.status}>
          Loading the comparison&hellip;
        </p>
      )
    } else if (currentComparison.status === 'success') {
      body = (
        <Comparison comparison={currentComparison.comparison} noteId={noteId} />
      )
    } else if (currentComparison.status === 'not_found') {
      body = <NotFound />
    } else {
      body = (
        <p role="alert" className={styles.error}>
          {currentComparison.message}
        </p>
      )
    }
  } else if (loneId !== null && currentCareer?.status === 'not_found') {
    body = <NotFound />
  } else if (loneId !== null && currentCareer?.status === 'error') {
    body = (
      <p role="alert" className={styles.error}>
        {currentCareer.message}
      </p>
    )
  } else if (loneId !== null) {
    body = (
      <p className={styles.prompt}>{pickOneMoreCopy(names[loneId] ?? null)}</p>
    )
  } else {
    body = <p className={styles.prompt}>{PICK_TWO_COPY}</p>
  }

  return (
    <main className={styles.wrap}>
      <p className={styles.back}>
        <Link to="/nfl/leaders">
          <span aria-hidden="true">&larr; </span>NFL leaders
        </Link>
      </p>

      <h1 className={styles.title}>Compare NFL players</h1>
      <p className={styles.lede}>
        Two players&rsquo; career totals side by side, and every game they
        started at quarterback against each other.
      </p>

      <div className={styles.pickers}>
        <PlayerCombobox
          label="Player A"
          value={fieldText('a')}
          onChange={(text) => handleType('a', text)}
          options={searchA.rows}
          status={searchA.status}
          hint={searchA.status === 'error' ? SEARCH_FAILED_COPY : undefined}
          onSelect={(player) => handleSelect('a', player)}
          onClear={() => handleClear('a')}
          placeholder="Type a name"
        />
        <PlayerCombobox
          label="Player B"
          value={fieldText('b')}
          onChange={(text) => handleType('b', text)}
          options={searchB.rows}
          status={searchB.status}
          hint={searchB.status === 'error' ? SEARCH_FAILED_COPY : undefined}
          onSelect={(player) => handleSelect('b', player)}
          onClear={() => handleClear('b')}
          placeholder="Type a name"
        />
      </div>

      <div className={styles.actions}>
        <button
          type="button"
          className={styles.compare}
          disabled={!canCompare}
          aria-describedby={typedNotPicked ? pickHintId : undefined}
          onClick={handleCompare}
        >
          Compare
        </button>
        {typedNotPicked && (
          <p id={pickHintId} className={styles.pickHint}>
            {PICK_FROM_LIST_COPY}
          </p>
        )}
      </div>

      {body}

      <PlayerStatsCredit credit={credit} />
    </main>
  )
}

function NotFound() {
  return (
    <div role="alert" className={styles.error}>
      <p>
        {PLAYER_NOT_FOUND_COPY}{' '}
        <Link to="/nfl/leaders">Pick one off the leaders board.</Link>
      </p>
    </div>
  )
}

function Comparison({
  comparison,
  noteId,
}: {
  comparison: PlayerComparisonOut
  noteId: string
}) {
  const { a, b } = comparison
  const undercount = compareUndercountNote(a, b)
  const sections: [
    PlayerSeasonType,
    PlayerCareerTotalsOut | null,
    PlayerCareerTotalsOut | null,
  ][] = [
    ['regular', a.regular_season, b.regular_season],
    ['postseason', a.postseason, b.postseason],
  ]
  const headToHeads = [
    comparison.regular_season_head_to_head,
    comparison.postseason_head_to_head,
  ]
  const headToHeadId = `${noteId}-head-to-head`

  return (
    <>
      <ul className={styles.players} aria-label="Players compared">
        {[a, b].map((player) => (
          <li key={player.player_id} className={styles.player}>
            <Link
              to={`/nfl/players/${player.player_id}`}
              className={styles.playerName}
            >
              {player.display_name}
            </Link>
            <span className={styles.position}>
              {player.position ?? 'Position not recorded'}
            </span>
          </li>
        ))}
      </ul>

      <div className={styles.notes}>
        <p>
          <span aria-hidden="true" className={styles.glyph}>
            {MARK_GLYPH}
          </span>{' '}
          {MARK_LEGEND}
        </p>
        <p id={noteId}>{STARTER_RECORD_NOTE}</p>
        {undercount !== null && (
          <p className={styles.undercount}>{undercount}</p>
        )}
      </div>

      {sections.map(([seasonType, aTotals, bTotals]) => {
        const label = SEASON_TYPE_LABEL[seasonType]
        const headingId = `${noteId}-${seasonType}`
        return (
          <section
            key={seasonType}
            className={styles.section}
            aria-labelledby={headingId}
          >
            <h2 id={headingId} className={styles.heading}>
              {label}
            </h2>
            {aTotals === null && bTotals === null ? (
              <p className={styles.none}>{NEITHER_TOTALS_COPY[seasonType]}</p>
            ) : (
              <PlayerComparisonTable
                caption={`${a.display_name} and ${b.display_name}, ${label.toLowerCase()}`}
                a={{ name: a.display_name, totals: aTotals }}
                b={{ name: b.display_name, totals: bTotals }}
                noTotalsCopy={NO_TOTALS_COPY[seasonType]}
                describedBy={noteId}
              />
            )}
          </section>
        )
      })}

      <section className={styles.section} aria-labelledby={headToHeadId}>
        <h2 id={headToHeadId} className={styles.heading}>
          Head to head
        </h2>
        <p className={styles.rule}>{HEAD_TO_HEAD_RULE}</p>
        {headToHeads.map((headToHead) => (
          <div key={headToHead.season_type} className={styles.subsection}>
            <h3 className={styles.subheading}>
              {SEASON_TYPE_LABEL[headToHead.season_type]}
            </h3>
            <PlayerHeadToHead
              aName={a.display_name}
              bName={b.display_name}
              headToHead={headToHead}
            />
          </div>
        ))}
      </section>
    </>
  )
}
