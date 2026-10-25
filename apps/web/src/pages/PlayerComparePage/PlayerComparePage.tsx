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
  PlayersNotComparableError,
  SERVER_ERROR_COPY,
  VerdictHttpError,
  VerdictNetworkError,
  fetchPlayerCareer,
  fetchPlayerComparison,
} from '../../lib/api/client'
import { isPlayerPositionGroup } from '../../lib/api/types'
import type {
  PlayerCareerTotalsOut,
  PlayerComparisonOut,
  PlayerPositionGroup,
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
  comparisonGroup,
  comparisonShowsRecord,
  groupSingular,
  notComparableCopy,
  pickOneMoreCopy,
  positionSingular,
  restrictionCopy,
  showsHeadToHead,
  uncomparableCopy,
} from '../../lib/playerCompare'
import {
  careerSpanText,
  compareCallout,
  dataSpanLine,
  statsThroughLine,
} from '../../lib/playerCoverage'
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

/**
 * Why a pair was refused (issue #436): the API's two groups, and -- only for
 * a Player B with no group next to a Player A with one -- Player B's
 * position label, which the refusal names him by instead (`null` when it is
 * missing or couldn't be fetched).
 */
interface Refusal {
  aGroup: PlayerPositionGroup | null
  bGroup: PlayerPositionGroup | null
  bPosition: string | null
}

/** The latest comparison answer, tagged with the pair it answers. */
type ComparisonAnswer = { key: string } & (
  | { status: 'success'; comparison: PlayerComparisonOut }
  | ({ status: 'not_comparable' } & Refusal)
  | Failure
)

/**
 * What the page has learned about a player's position, from any API answer
 * or search row naming him. A missing key is "not known yet"; `null` is the
 * API's "none".
 */
interface Profile {
  group?: PlayerPositionGroup | null
  position?: string | null
}

/** A state update adding what an answer just said about some players. */
function learned(
  answered: Record<number, Profile>,
): (known: Record<number, Profile>) => Record<number, Profile> {
  return (known) => {
    const next = { ...known }
    for (const [id, profile] of Object.entries(answered)) {
      next[Number(id)] = { ...known[Number(id)], ...profile }
    }
    return next
  }
}

/**
 * The refusal a mixed link navigated with (issue #436), read off
 * `location.state`, which is `any` and can hold anything a browser restored.
 */
function refusalOf(state: unknown): Refusal | null {
  if (typeof state !== 'object' || state === null || !('refused' in state)) {
    return null
  }
  const { refused } = state
  if (typeof refused !== 'object' || refused === null) {
    return null
  }
  const { aGroup, bGroup, bPosition } = refused as Record<string, unknown>
  const groupOrNull = (value: unknown): value is PlayerPositionGroup | null =>
    value === null || isPlayerPositionGroup(value)
  if (
    !groupOrNull(aGroup) ||
    !groupOrNull(bGroup) ||
    !(bPosition === null || typeof bPosition === 'string')
  ) {
    return null
  }
  return { aGroup, bGroup, bPosition }
}

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

const EMPTY: SlotState = { pick: null, text: '' }

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
  const { closedFrom } = state
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
  const [profiles, setProfiles] = useState<Record<number, Profile>>({})
  /** The entry whose refusal a slot change has since dismissed. */
  const [dismissedRefusalKey, setDismissedRefusalKey] = useState<string | null>(
    null,
  )
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
  /** Raised by a refusal: focus goes to the field that needs a new pick. */
  const focusPickerRef = useRef(false)

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
        setProfiles(
          learned({
            [comparison.a.player_id]: {
              group: comparison.a.group,
              position: comparison.a.position,
            },
            [comparison.b.player_id]: {
              group: comparison.b.group,
              position: comparison.b.position,
            },
          }),
        )
        setSeeded((current) => ({
          ...current,
          slots: nameSlots(current.slots, answered),
        }))
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return
        }
        if (!(error instanceof PlayersNotComparableError)) {
          setComparisonAnswer({ key, ...failureOf(error) })
          return
        }
        // A mixed pair (issue #436). The 400 names both groups but no
        // position, so a Player B with no group next to a Player A with one
        // is looked up: the refusal names him by his position instead.
        const { a_group: aGroup, b_group: bGroup } = error.body
        setProfiles(
          learned({ [pickA]: { group: aGroup }, [pickB]: { group: bGroup } }),
        )
        const refuse = (bPosition: string | null) => {
          setComparisonAnswer({
            key,
            status: 'not_comparable',
            aGroup,
            bGroup,
            bPosition,
          })
        }
        if (aGroup === null || bGroup !== null) {
          refuse(null)
          return
        }
        fetchPlayerCareer(pickB).then(
          (career) => {
            if (!cancelled) {
              setProfiles(
                learned({
                  [career.player_id]: {
                    group: career.group,
                    position: career.position,
                  },
                }),
              )
              refuse(career.position)
            }
          },
          () => {
            if (!cancelled) {
              refuse(null)
            }
          },
        )
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
        setProfiles(
          learned({
            [career.player_id]: {
              group: career.group,
              position: career.position,
            },
          }),
        )
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

  /**
   * Player A's profile once he is picked (issue #436): his group decides who
   * Player B can be. `undefined` until an answer has said.
   */
  const aProfile =
    slots.a.pick === null ? undefined : profiles[slots.a.pick.player_id]
  const aGroup = aProfile?.group
  /** Player B searches only within Player A's known group. */
  const bGroup = aGroup ?? undefined
  /**
   * Player B waits for a Player A whose group is known, and for a Player A
   * with no group, for good: there is nobody to compare him with yet. But a
   * Player B already holding a pick or text -- a failed link's, say -- stays
   * live, so it can always be cleared or typed over (round 3).
   */
  /**
   * The line under the fields: the restriction once Player A has a group,
   * the uncomparable line once he has none (his label arrives with his
   * career or search row; until then there is nothing true to say).
   */
  const bLine =
    aGroup === undefined
      ? null
      : aGroup !== null
        ? restrictionCopy(aGroup)
        : aProfile?.position === undefined
          ? null
          : uncomparableCopy(aProfile.position)
  const bLineId = `${noteId}-b-line`
  const bHolds = slots.b.pick !== null || slots.b.text !== ''
  const bDisabled = bGroup === undefined && !bHolds

  const searchA = usePlayerSearch(slots.a.pick === null ? slots.a.text : '')
  const searchB = usePlayerSearch(
    bGroup !== undefined && slots.b.pick === null ? slots.b.text : '',
    bGroup,
  )

  /**
   * A Player A whose group nobody has said yet, on the form with no pair
   * asked: a failed link's (a 404, a network error, a 5xx, the same player
   * twice), whose answer never named him. His career says, so Player B can
   * be picked again (round 3). A lone link's own lookup above covers that
   * case; each player is looked up once.
   */
  const pairInUrl = pickA !== null && pickB !== null
  const aLookupId =
    !pairInUrl &&
    slots.a.pick !== null &&
    aGroup === undefined &&
    slots.a.pick.player_id !== loneId
      ? slots.a.pick.player_id
      : null
  const lookedUpRef = useRef(new Set<number>())
  useEffect(() => {
    if (aLookupId === null || lookedUpRef.current.has(aLookupId)) {
      return
    }
    lookedUpRef.current.add(aLookupId)
    fetchPlayerCareer(aLookupId).then(
      (career) => {
        const answered = { [career.player_id]: career.display_name }
        setNames((known) => ({ ...known, ...answered }))
        setProfiles(
          learned({
            [career.player_id]: {
              group: career.group,
              position: career.position,
            },
          }),
        )
        setSeeded((current) => ({
          ...current,
          slots: nameSlots(current.slots, answered),
        }))
      },
      () => {
        // Nothing learned: Player B can still be cleared, and a new
        // Player A picked from the list brings his group with him.
      },
    )
  }, [aLookupId])

  /**
   * Sets one field. Player B is picked against Player A's group, so whatever
   * empties Player A -- typing over him, or the clear button -- empties
   * Player B too (issue #436). Any change dismisses a refusal.
   */
  function updateSlot(slot: Slot, next: SlotState) {
    setDismissedRefusalKey(location.key)
    if (refusalOf(location.state) !== null) {
      // The refusal is dismissed for good: drop it from the entry's state,
      // so a reload doesn't bring it back. Same URL, `replace`, and the
      // `closedFrom` mark keeps the fields as they are rather than
      // re-seeding them from the URL (see `closedFromKey`).
      setSearchParams(searchParams, {
        replace: true,
        state: { closedFrom: location.key },
      })
    }
    setSeeded((current) => ({
      ...current,
      slots:
        slot === 'a' && next.pick === null
          ? { a: next, b: EMPTY }
          : { ...current.slots, [slot]: next },
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
    setProfiles(
      learned({
        [player.player_id]: { group: player.group, position: player.position },
      }),
    )
    updateSlot(slot, {
      pick: { player_id: player.player_id, display_name: player.display_name },
      text: '',
    })
  }

  function handleClear(slot: Slot) {
    updateSlot(slot, EMPTY)
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
    // After a refusal, the same wait: then Player B, ready for a new pick,
    // or Player A when Player B can't take one.
    if (focusPickerRef.current && !askedPair) {
      focusPickerRef.current = false
      const [inputA, inputB] = Array.from(
        pickersRef.current?.querySelectorAll('input') ?? [],
      )
      if (inputB !== undefined && !inputB.disabled) {
        inputB.focus()
      } else {
        inputA?.focus()
      }
    }
  })

  /**
   * A mixed pair was refused (issue #436): back to the form, never showing
   * the pair. The address bar drops Player B -- it names no pair until one
   * is committed (#325) -- with `replace`, so Back skips the refused link,
   * and the fields follow it as on any navigation: Player A stays, Player B
   * is empty. The refusal rides along in the entry's state.
   */
  const refused =
    currentComparison?.status === 'not_comparable' ? currentComparison : null
  useEffect(() => {
    if (refused === null || typeof pickA !== 'number') {
      return
    }
    focusPickerRef.current = true
    const { aGroup: a, bGroup: b, bPosition } = refused
    setSearchParams(
      { a: String(pickA) },
      {
        replace: true,
        state: { refused: { aGroup: a, bGroup: b, bPosition } },
      },
    )
  }, [refused, pickA, setSearchParams])

  /**
   * The refusal's line, while the form is as the refusal left it: Player A
   * its link's player, Player B empty, and nothing changed since. A Player A
   * with no group gets the uncomparable line instead (below).
   */
  const refusal = refusalOf(location.state)
  const refusalCopy =
    refusal !== null &&
    refusal.aGroup !== null &&
    !askedPair &&
    dismissedRefusalKey !== location.key &&
    typeof pickA === 'number' &&
    slots.a.pick?.player_id === pickA &&
    slots.b.pick === null
      ? notComparableCopy(
          refusal.aGroup,
          refusal.bGroup !== null
            ? groupSingular(refusal.bGroup)
            : positionSingular(refusal.bPosition),
        )
      : null

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
    } else if (
      currentComparison === null ||
      // Refused: on its way back to the form (the effect above), never shown.
      currentComparison.status === 'not_comparable'
    ) {
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
  } else if (refusalCopy !== null) {
    prompt = (
      <p role="alert" className={styles.error}>
        {refusalCopy}
      </p>
    )
  } else if (aGroup === null) {
    // A Player A with no group (issue #436): the uncomparable line under the
    // fields (`bLine`) says it all, so no pick-one-more prompt.
    prompt = null
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
        Two players at the same position, career totals side by side. Two
        quarterbacks get every game they started against each other too.
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
          disabled={bDisabled}
          describedBy={bLine === null ? undefined : bLineId}
        />
      </div>

      {/* Who Player B can be, or why nobody can be yet (issue #436). Always
          in the page, so a polite live region announces the line when it
          appears or changes; Player B is described by it. */}
      <div aria-live="polite" className={styles.bLine}>
        {bLine !== null && (
          <p id={bLineId} className={styles.restriction}>
            {bLine}
          </p>
        )}
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
  const showsRecordNote = comparisonShowsRecord(a, b)
  const group = comparisonGroup(a, b)
  // How much of each career the data holds (#448).
  const callout = compareCallout(
    { name: a.display_name, coverage: a.coverage },
    { name: b.display_name, coverage: b.coverage },
  )
  const calloutId = `${noteId}-coverage`
  const statsThrough = statsThroughLine([a.coverage, b.coverage])
  const dataSpan = dataSpanLine(
    a.coverage.data_first_season,
    a.coverage.data_last_season,
  )
  const describedBy =
    [callout === null ? null : calloutId, showsRecordNote ? noteId : null]
      .filter((id) => id !== null)
      .join(' ') || undefined

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
            {careerSpanText(player.coverage) !== null && (
              <span className={styles.span}>
                {careerSpanText(player.coverage)}
              </span>
            )}
          </li>
        ))}
      </ul>

      {/* Above the numbers, not a footnote (#448): the tables are described by it. */}
      {callout !== null && (
        <p id={calloutId} role="status" className={styles.callout}>
          {callout}
        </p>
      )}

      <div className={styles.notes}>
        {/* With a cut-off career nothing is marked, so there's no mark to explain. */}
        {callout === null && (
          <p>
            <span aria-hidden="true" className={styles.glyph}>
              {MARK_GLYPH}
            </span>{' '}
            {MARK_LEGEND}
          </p>
        )}
        {statsThrough !== null && <p>{statsThrough}</p>}
        {dataSpan !== null && <p>{dataSpan}</p>}
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
                a={{
                  name: a.display_name,
                  totals: aTotals,
                  coverage: a.coverage,
                }}
                b={{
                  name: b.display_name,
                  totals: bTotals,
                  coverage: b.coverage,
                }}
                group={group}
                noTotalsCopy={NO_TOTALS_COPY[seasonType]}
                describedBy={describedBy}
              />
            )}
          </section>
        )
      })}

      {/* Starts at quarterback against each other: two quarterbacks only
          (#372). The API still sends it for any pair; this only hides it. */}
      {showsHeadToHead(comparison) && (
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
      )}
    </>
  )
}
