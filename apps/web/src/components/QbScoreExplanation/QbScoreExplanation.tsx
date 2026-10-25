import { useId, useState } from 'react'
import type {
  PlayerQbMetricValueOut,
  PlayerQbScoreComparisonOut,
  PlayerQbScoreOut,
  PlayerQbScoreSeasonOut,
} from '../../lib/api/types'
import {
  QB_WEIGHT_FIT_COPY,
  formatQbAnyA,
  formatQbEpa,
  formatQbScore,
  formatQbWeight,
  formatQbZ,
} from '../../lib/qbScore'
import styles from './QbScoreExplanation.module.css'

export interface QbScoreExplanationProps {
  qbScore: PlayerQbScoreComparisonOut
  /** The db's first season of player stats (1999): the score's floor. */
  dataFirstSeason: number | null
}

const TOGGLE_LABEL = 'How the QB score works'

/**
 * How the engine got the QB score (issue #459, to #183's bar: the working,
 * not vibes). A disclosure: a real `<button>` with `aria-expanded` and
 * `aria-controls` opens a labelled region, so it is reachable by keyboard and
 * screen reader, not only by hover. The region is left out of the DOM while
 * shut, so it is never read out of turn.
 *
 * Every rule's number -- the weights, `min_dropbacks`, `peak_seasons` -- is
 * read from the response. Only how the weights were fitted is static copy.
 */
export function QbScoreExplanation({
  qbScore,
  dataFirstSeason,
}: QbScoreExplanationProps) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const regionId = `${id}-region`
  const toggleId = `${id}-toggle`
  const { weights, min_dropbacks: minDropbacks, peak_seasons: peak } = qbScore

  return (
    <div className={styles.wrap}>
      <button
        id={toggleId}
        type="button"
        className={styles.toggle}
        aria-expanded={open}
        aria-controls={regionId}
        onClick={() => setOpen((current) => !current)}
      >
        <span aria-hidden="true" className={styles.chevron}>
          {open ? '▾' : '▸'}
        </span>{' '}
        {TOGGLE_LABEL}
      </button>
      {open && (
        <section
          id={regionId}
          aria-labelledby={toggleId}
          className={styles.region}
        >
          <ul className={styles.rules}>
            <li>
              A season counts at {minDropbacks} or more dropbacks (pass attempts
              plus sacks). Under that it&apos;s shown greyed, and doesn&apos;t
              count.
            </li>
            <li>
              Each counting season is measured against the quarterbacks of that
              same season: z is how many standard deviations he was above (or
              below) their average.
            </li>
            <li>
              <span className={styles.formula}>
                Season score = {formatQbWeight(weights.epa_per_dropback)}{' '}
                &times; passing EPA per dropback z +{' '}
                {formatQbWeight(weights.rush_epa_per_play)} &times; rushing EPA
                per play z
              </span>
              . Those weights come from {QB_WEIGHT_FIT_COPY}.
            </li>
            <li>
              ANY/A (adjusted net yards per attempt) is there for context.
              It&apos;s not scored.
            </li>
            <li>
              Career = the sum of every counting season&apos;s score:
              above-average years add, below-average years subtract.
            </li>
            <li>
              Peak = the average of his best {peak} season scores. With fewer
              than {peak} counting seasons, the empty slots are filled with 0, a
              league-average season.
            </li>
            {dataFirstSeason !== null && (
              <li>
                The play-by-play starts in {dataFirstSeason}, so nothing before{' '}
                {dataFirstSeason} is scored.
              </li>
            )}
          </ul>
          {[qbScore.a, qbScore.b].map((player) => (
            <PlayerSeasons
              key={player.player_id}
              player={player}
              minDropbacks={minDropbacks}
              peakSeasons={peak}
            />
          ))}
        </section>
      )}
    </div>
  )
}

/** "Kurt Warner: 1 counting season. Career 2.25. Peak 0.45, with 4 of 5 ..." */
function summaryOf(player: PlayerQbScoreOut, peakSeasons: number): string {
  const { display_name: name, qualifying_seasons: counted } = player
  if (counted === 0 || player.career === null || player.peak === null) {
    return `${name}: no counting season, so no score.`
  }
  const seasons = `${counted} counting ${counted === 1 ? 'season' : 'seasons'}`
  const filled = player.peak_filled_with_average
  const fill =
    filled > 0 ? `, with ${filled} of ${peakSeasons} slots filled with 0` : ''
  return `${name}: ${seasons}. Career ${formatQbScore(player.career)}. Peak ${formatQbScore(player.peak)}${fill}.`
}

function PlayerSeasons({
  player,
  minDropbacks,
  peakSeasons,
}: {
  player: PlayerQbScoreOut
  minDropbacks: number
  peakSeasons: number
}) {
  return (
    <div className={styles.player}>
      <h3 className={styles.playerName}>{player.display_name}</h3>
      <p className={styles.summary}>{summaryOf(player, peakSeasons)}</p>
      <table className={styles.table}>
        <caption className={styles.caption}>
          {player.display_name}, season by season
        </caption>
        <thead>
          <tr>
            <th scope="col">Season</th>
            <th scope="col">Passing EPA per dropback</th>
            <th scope="col">Rushing EPA per play</th>
            <th scope="col">ANY/A (not scored)</th>
            <th scope="col">Season score</th>
          </tr>
        </thead>
        <tbody>
          {player.seasons.map((season) => (
            <SeasonRow
              key={season.season}
              season={season}
              minDropbacks={minDropbacks}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SeasonRow({
  season,
  minDropbacks,
}: {
  season: PlayerQbScoreSeasonOut
  minDropbacks: number
}) {
  const counted = season.qualifies
  return (
    <tr
      data-counted={counted ? 'true' : 'false'}
      className={counted ? undefined : styles.notCounted}
    >
      <th scope="row" className={styles.seasonCell}>
        <span className={styles.season}>{season.season}</span>{' '}
        <span className={styles.sub}>
          {season.dropbacks.toLocaleString('en-US')} dropbacks
        </span>
        {season.in_peak && (
          <>
            {' '}
            <span className={styles.peak}>Peak</span>
          </>
        )}
      </th>
      <MetricCell metric={season.epa_per_dropback} format={formatQbEpa} />
      <MetricCell metric={season.rush_epa_per_play} format={formatQbEpa} />
      <MetricCell metric={season.any_a} format={formatQbAnyA} />
      <td className={styles.score}>
        {season.composite !== null ? (
          formatQbScore(season.composite)
        ) : (
          <span className={styles.sub}>
            Didn&apos;t count: {season.dropbacks.toLocaleString('en-US')}{' '}
            dropbacks, under {minDropbacks}
          </span>
        )}
      </td>
    </tr>
  )
}

/** A metric's raw value, and -- for a counting season -- its era and z. */
function MetricCell({
  metric,
  format,
}: {
  metric: PlayerQbMetricValueOut | null
  format: (value: number) => string
}) {
  if (metric === null) {
    return <td className={styles.sub}>None</td>
  }
  const { value, season_mean: mean, season_sd: sd, z } = metric
  return (
    <td>
      <span className={styles.value}>{format(value)}</span>
      {mean !== null && sd !== null && z !== null && (
        <>
          {' '}
          <span className={styles.era}>
            <span>avg {format(mean)}</span> <span>SD {format(sd)}</span>{' '}
            <span className={styles.z}>z {formatQbZ(z)}</span>
          </span>
        </>
      )}
    </td>
  )
}
