import { useEffect, useId, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useLocation, useSearchParams } from 'react-router-dom'
import { PlayerCombobox } from '../../components/PlayerCombobox/PlayerCombobox'
import { PlayerComparisonTable } from '../../components/PlayerComparisonTable/PlayerComparisonTable'
import { PlayerHeadToHead } from '../../components/PlayerHeadToHead/PlayerHeadToHead'
import { PlayerStatsCredit } from '../../components/PlayerStatsCredit/PlayerStatsCredit'
import { ShareButton } from '../../components/ShareButton/ShareButton'
import { VerdictModal } from '../../components/VerdictModal/VerdictModal'
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
  showsStarterRecord,
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
 * A player in a slot. A pick seeded from the URL has no name until an API
 * answer about that player names it (`nameSlots`), and an answer that fails
 * never does. Named or not it is a pick: it counts for Compare, so a link
 * whose comparison failed can be asked again (issue #308), and its field
 * shows `unnamedPickText` rather than reading as blank.
 */
interface SlotPick {
  player_id: number
  display_name: string | null
}

/**
 * What a field shows for a pick no answer has named yet: the id the link
 * carried, which is all the page truthfully knows about that player.
 */
function unnamedPickText(playerId: number): string {
  return `Player #${playerId}`
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
 * Names the unnamed picks an API answer just named, by player id, and leaves
 * every other slot alone. This is the only way an unnamed pick gets a name
 * after seeding: a name picked into one field never reaches the other
 * (issue #308).
 */
function nameSlots(
  slots: Record<Slot, SlotState>,
  answered: Record<number, string>,
): Record<Slot, SlotState> {
  const name = (state: SlotState): SlotState => {
    const { pick } = state
    if (pick === null || pick.display_name !== null) {
      return state
    }
    const found = answered[pick.player_id]
    return found === undefined
      ? state
      : { ...state, pick: { ...pick, display_name: found } }
  }
  return { a: name(slots.a), b: name(slots.b) }
}

/**
 * The key of the entry a close navigated away from (issue #310), read off
 * `location.state`, which is `any` and can hold anything a browser restored.
 */
function closedFromKey(state: unknown): string | null {
  if (typeof state !== 'object' || state === null || !('closedFrom' in state)) {
    return null
  }
  const { closedFrom } = state as { closedFrom: unknown }
  return typeof closedFrom === 'string' ? closedFrom : null
}

/** The modal's name until the answer names both players. */
const COMPARISON_TITLE = 'The comparison'

/**
 * Two NFL players side by side (issue #301): career totals of each season
 * type in their own table, with the larger number in each row marked, and
 * their games against each other as opposing starting quarterbacks.
 *
 * Each field holds a pick or typed text, never both (issue #304): typing over
 * a pick clears it, and picking a suggestion changes only that field. The URL
 * (`?a=<id>&b=<id>`) is the comparison on screen, and only the Compare button
 * changes it, pushing a history entry, so a link, a reload and Back all show
 * the same comparison. Every press asks again, even for the pair just closed.
 * Any navigation re-seeds the fields from the URL. The same player twice, or
 * an id that can't be one, is answered here without asking the API.
 *
 * Every answer to a committed pair opens in `VerdictModal` over the form
 * (issue #310), the way a team verdict does since #198: a comparison rendered
 * below the whole form sat off-screen on a phone, which is where shared links
 * get opened. A successful comparison offers a share link that reopens it.
 * The prompts that mean "you haven't asked yet" -- pick two, or pick one more
 * next to the player a career page sent over -- stay inline on the form, so a
 * lone `?a=<id>` link never opens a modal.
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
  const [comparisonAnswer, setComparisonAnswer] =
    useState<ComparisonAnswer | null>(null)
  const [careerAnswer, setCareerAnswer] = useState<CareerAnswer | null>(null)
  const credit = usePlayerStatsCredit()
  const noteId = useId()
  const pickHintId = `${noteId}-pick-hint`
  /** Where focus goes when the comparison closes: the Compare button. */
  const compareButtonRef = useRef<HTMLButtonElement>(null)
  /** Holds the fields, for when Compare can't take focus after a close. */
  const pickersRef = useRef<HTMLDivElement>(null)
  /** Raised by a close, lowered once focus has actually moved (see below). */
  const focusCompareRef = useRef(false)

  // Back, Forward or a link moved the URL: the fields follow it. The one
  // exception is this page's own close (`closeComparison`), which drops ?a&b
  // from the address bar while the fields keep the pair that was compared --
  // seeding those from the now-empty URL would empty them. It navigates
  // carrying the key of the entry it closed, so only the arrival straight
  // from that entry keeps the fields; a later Back or Forward onto the closed
  // entry is an ordinary navigation and follows the URL like any other.
  let slots = seeded.slots
  if (seeded.locationKey !== location.key) {
    slots =
      closedFromKey(location.state) === seeded.locationKey
        ? seeded.slots
        : seedSlots({ a: pickA, b: pickB }, names)
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

  // The answer belongs to one ask, and an ask ends when the URL stops naming
  // a pair to fetch (a close, or Back to the form): drop it then, so the next
  // ask of the same pair shows loading until its own request settles rather
  // than the last ask's error or table (issue #308). Matching on the pair's
  // key alone can't tell two asks of the same pair apart.
  if (comparisonKey === null && comparisonAnswer !== null) {
    setComparisonAnswer(null)
  }

  // Asks whenever the URL's pair changes. Pressing Compare always changes
  // it: Compare can only be pressed with the modal shut (the form behind an
  // open modal is inert, issue #325), and the modal is shut exactly when the
  // URL names no pair, so every press pushes ?a&b and asks again -- and the
  // answer was dropped when the pair left the URL, so it shows loading.
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
        const answered = {
          [comparison.a.player_id]: comparison.a.display_name,
          [comparison.b.player_id]: comparison.b.display_name,
        }
        setComparisonAnswer({ key, status: 'success', comparison })
        setNames((known) => ({ ...known, ...answered }))
        setSeeded((current) => ({
          ...current,
          slots: nameSlots(current.slots, answered),
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
  }, [pickA, pickB])

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
        const answered = { [career.player_id]: career.display_name }
        setCareerAnswer({ id: loneId, status: 'success' })
        setNames((known) => ({ ...known, ...answered }))
        setSeeded((current) => ({
          ...current,
          slots: nameSlots(current.slots, answered),
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

  /**
   * A slot's player id whenever it holds a pick, named or not (issue #308);
   * `null` for typed text or an empty field, which are never compared.
   */
  function slotPick(slot: Slot): number | null {
    return slots[slot].pick?.player_id ?? null
  }

  /** A pick's own name, or the id it holds; never another slot's name. */
  function fieldText(slot: Slot): string {
    const { pick, text } = slots[slot]
    return pick === null
      ? text
      : (pick.display_name ?? unnamedPickText(pick.player_id))
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

  const compareA = slotPick('a')
  const compareB = slotPick('b')
  const canCompare = compareA !== null && compareB !== null
  const typedNotPicked = SLOTS.some(
    (slot) => slots[slot].pick === null && slots[slot].text !== '',
  )

  /**
   * Pushes the fields' pair to ?a&b, which asks for it. The button can only
   * be pressed while the URL names no pair (see the comparison effect), so
   * this is always a change of URL and always a fresh ask (issue #325).
   */
  function handleCompare() {
    if (compareA === null || compareB === null) {
      return
    }
    setSearchParams({ a: String(compareA), b: String(compareB) })
  }

  /**
   * Dismisses the comparison and returns to the form, which still holds the
   * pair it compared (issue #310). The address bar drops ?a&b -- `replace`,
   * so no history entry piles up -- because it is the share link of the
   * comparison on screen, and now there isn't one: a reload comes back to the
   * form rather than to a comparison that was dismissed.
   */
  function closeComparison() {
    focusCompareRef.current = true
    setSearchParams(new URLSearchParams(), {
      replace: true,
      state: { closedFrom: location.key },
    })
  }

  const currentComparison =
    comparisonKey !== null && comparisonAnswer?.key === comparisonKey
      ? comparisonAnswer
      : null
  const currentCareer =
    loneId !== null && careerAnswer?.id === loneId ? careerAnswer : null

  /**
   * Both slots named in the URL: the page has been asked about a pair, so
   * whatever it has to say -- loading, the comparison, an unknown player, the
   * narrator's error line, or the same player twice -- is an answer, and every
   * answer opens in the modal over the form (issue #310). Anything else is a
   * prompt meaning "you haven't asked yet", which belongs on the form itself.
   */
  const askedPair = pickA !== null && pickB !== null

  /**
   * Returns focus to the form after a close, once the modal is really gone:
   * to Compare, or -- when Compare is disabled, as after a link whose id
   * can't be a player, and so can't take focus -- to the first field that
   * still needs a pick. Never left on the page itself. It has to wait for that: what opens the modal is the URL,
   * and react-router applies a navigation in a transition, so the commit
   * right after `closeComparison` can still have it open -- and focusing
   * something outside an open modal only makes it pull focus back to its own
   * close button. Runs after every render, and the flag makes it once.
   */
  useEffect(() => {
    if (focusCompareRef.current && !askedPair) {
      focusCompareRef.current = false
      if (canCompare) {
        compareButtonRef.current?.focus()
      } else {
        const index = SLOTS.findIndex((slot) => slots[slot].pick === null)
        pickersRef.current
          ?.querySelectorAll('input')
          .item(Math.max(index, 0))
          ?.focus()
      }
    }
  })

  const comparison =
    currentComparison?.status === 'success'
      ? currentComparison.comparison
      : null
  /**
   * Built from the committed pair in the address bar, never from field state
   * nobody pressed Compare on, so the link always reopens what is on screen.
   */
  const shareUrl =
    comparison !== null &&
    typeof pickA === 'number' &&
    typeof pickB === 'number'
      ? `${window.location.origin}/nfl/compare?a=${pickA}&b=${pickB}`
      : undefined
  const nameA = typeof pickA === 'number' ? names[pickA] : undefined
  const nameB = typeof pickB === 'number' ? names[pickB] : undefined
  const modalTitle =
    comparison !== null
      ? `${comparison.a.display_name} and ${comparison.b.display_name}`
      : nameA !== undefined && nameB !== undefined && nameA !== nameB
        ? `${nameA} and ${nameB}`
        : COMPARISON_TITLE

  /** The answer to the committed pair, shown in the modal. */
  let answer: ReactNode = null
  /** What the form says while it has not been asked about a pair. */
  let prompt: ReactNode = null
  /** The players the fields hold, picked or seeded, typed text aside. */
  const held = SLOTS.flatMap((slot) => {
    const { pick } = slots[slot]
    return pick === null ? [] : [pick]
  })
  /**
   * A lone link's career failure is about that pick alone (issue #367): it
   * stands only while the fields hold just that player. Once they hold
   * anyone else, the prompt follows the fields like everywhere else (#324).
   */
  const loneCareerFailure =
    loneId !== null &&
    held.length === 1 &&
    held[0]?.player_id === loneId &&
    currentCareer !== null &&
    currentCareer.status !== 'success'
      ? currentCareer
      : null
  if (askedPair) {
    if (pickA === 'invalid' || pickB === 'invalid') {
      answer = <NotFound />
    } else if (pickA === pickB) {
      answer = (
        <p role="alert" className={styles.error}>
          {SAME_PLAYER_COPY}
        </p>
      )
    } else if (currentComparison === null) {
      answer = (
        <p role="status" className={styles.status}>
          Loading the comparison&hellip;
        </p>
      )
    } else if (currentComparison.status === 'success') {
      answer = (
        <div className={styles.answer}>
          <Comparison
            comparison={currentComparison.comparison}
            noteId={noteId}
          />
          {/* The credit travels with the numbers it credits (issue #296). */}
          <PlayerStatsCredit credit={credit} />
          {shareUrl !== undefined && (
            <ShareButton url={shareUrl} label="Share this comparison" />
          )}
        </div>
      )
    } else if (currentComparison.status === 'not_found') {
      answer = <NotFound />
    } else {
      answer = (
        <p role="alert" className={styles.error}>
          {currentComparison.message}
        </p>
      )
    }
  } else if (pickA === 'invalid' || pickB === 'invalid') {
    // A lone id that can't be one: still nothing asked, so still on the form.
    prompt = <NotFound />
  } else if (loneCareerFailure?.status === 'not_found') {
    prompt = <NotFound />
  } else if (loneCareerFailure?.status === 'error') {
    prompt = (
      <p role="alert" className={styles.error}>
        {loneCareerFailure.message}
      </p>
    )
  } else {
    // Otherwise the prompt follows the fields, not the URL (issue #324): a
    // close empties the URL while the fields keep the pair, and a field
    // holding a player must not be asked for one.
    if (held.length === 1) {
      prompt = (
        <p className={styles.prompt}>
          {pickOneMoreCopy(held[0]?.display_name ?? null)}
        </p>
      )
    } else if (held.length === 0) {
      prompt = <p className={styles.prompt}>{PICK_TWO_COPY}</p>
    }
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

      <div ref={pickersRef} className={styles.pickers}>
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
          ref={compareButtonRef}
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

      {prompt}

      {/* While a comparison is on screen the credit is inside the modal with
          it; otherwise it belongs here, under the form. */}
      {comparison === null && <PlayerStatsCredit credit={credit} />}

      <VerdictModal
        open={askedPair}
        title={modalTitle}
        closeLabel="Close the comparison"
        onClose={closeComparison}
      >
        {answer}
      </VerdictModal>
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
  // The note explains the starter record, so it shows only when a table can
  // show one: two receivers have no record row for it to describe (#352).
  const showsRecordNote = showsStarterRecord([...a.seasons, ...b.seasons])

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
        {showsRecordNote && <p id={noteId}>{STARTER_RECORD_NOTE}</p>}
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
                describedBy={showsRecordNote ? noteId : undefined}
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
