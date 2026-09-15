import { useEffect, useId, useState } from 'react'
import type { ReactNode } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
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

/** Text typed into a field, for the pick it was typed over. */
interface Draft {
  forPick: Pick
  text: string
}

/**
 * Two NFL players side by side (issue #301): career totals of each season
 * type in their own table, with the larger number in each row marked, and
 * their games against each other as opposing starting quarterbacks.
 *
 * The URL holds the picks (`?a=<id>&b=<id>`), so a link, a reload and Back
 * all show the same comparison. The same player twice, or an id that can't
 * be one, is answered here without asking the API.
 *
 * Pages own composition/data-fetching; components do not import from pages
 * (enforced by dependency-cruiser -- see .dependency-cruiser.cjs).
 */
export function PlayerComparePage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const pickA = parsePick(searchParams.get('a'))
  const pickB = parsePick(searchParams.get('b'))
  const picks: Record<Slot, Pick> = { a: pickA, b: pickB }

  const [names, setNames] = useState<Record<number, string>>({})
  const [drafts, setDrafts] = useState<Record<Slot, Draft | null>>({
    a: null,
    b: null,
  })
  const [comparisonAnswer, setComparisonAnswer] =
    useState<ComparisonAnswer | null>(null)
  const [careerAnswer, setCareerAnswer] = useState<CareerAnswer | null>(null)
  const credit = usePlayerStatsCredit()
  const noteId = useId()

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

  /** The text a slot's field is typing, or `''` when it shows the pick. */
  function draftText(slot: Slot): string | null {
    const draft = drafts[slot]
    return draft !== null && draft.forPick === picks[slot] ? draft.text : null
  }

  function fieldText(slot: Slot): string {
    const pick = picks[slot]
    return (
      draftText(slot) ?? (typeof pick === 'number' ? (names[pick] ?? '') : '')
    )
  }

  const searchA = usePlayerSearch(draftText('a') ?? '')
  const searchB = usePlayerSearch(draftText('b') ?? '')

  function handleType(slot: Slot, text: string) {
    setDrafts((current) => ({
      ...current,
      [slot]: { forPick: picks[slot], text },
    }))
  }

  /** Pushes a history entry, so Back returns to the picks before. */
  function handleSelect(slot: Slot, player: PlayerSearchRowOut) {
    setNames((known) => ({
      ...known,
      [player.player_id]: player.display_name,
    }))
    setDrafts((current) => ({ ...current, [slot]: null }))
    const values: Record<Slot, string | null> = {
      a: searchParams.get('a'),
      b: searchParams.get('b'),
    }
    values[slot] = String(player.player_id)
    const next = new URLSearchParams()
    for (const key of ['a', 'b'] as const) {
      const value = values[key]
      if (value !== null && value !== '') {
        next.set(key, value)
      }
    }
    setSearchParams(next)
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
          placeholder="Type a name"
        />
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
