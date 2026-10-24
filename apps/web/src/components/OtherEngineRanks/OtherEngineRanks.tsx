import type { Method, MethodRankOut } from '../../lib/api/types'
import type { DisplayedMethod } from '../../lib/methods'
import { DISPLAYED_METHODS, METHOD_RADIO_LABEL } from '../../lib/methods'
import styles from './OtherEngineRanks.module.css'

/** One team's ranks under the other engines, as the API sends them. */
export interface OtherEngineRanksRow {
  /** Names the team on a compare verdict; a team-case verdict has one team and needs no name. */
  teamName?: string
  ranks: readonly MethodRankOut[]
}

export interface OtherEngineRanksProps {
  rows: readonly OtherEngineRanksRow[]
  /**
   * Re-asks the same question under another engine. Without it the ranks
   * still show, with no control.
   */
  onSelectMethod?: (method: Method) => void
}

function isDisplayed(method: Method): method is DisplayedMethod {
  return (DISPLAYED_METHODS as readonly Method[]).includes(method)
}

/**
 * Where each other engine the Engine toggle offers ranks the verdict's team
 * (issue #155), named as the toggle names it, with one control per engine
 * that re-asks the same question under it.
 *
 * The API sends every other method with a ratings row, `elo_career`
 * included; only `DISPLAYED_METHODS` show here. Rank only, never a rating:
 * the engines' ratings are on different scales.
 *
 * The engines have no mandate to agree (founder, 2026-09-13), so the markup
 * is the same whatever the ranks are: no emphasis, no colour, no copy about
 * whether they match. Nothing renders when no displayed engine has a rank.
 */
export function OtherEngineRanks({
  rows,
  onSelectMethod,
}: OtherEngineRanksProps) {
  const shown = rows
    .map((row) => ({
      teamName: row.teamName,
      ranks: row.ranks.filter((entry) => isDisplayed(entry.method)),
    }))
    .filter((row) => row.ranks.length > 0)

  if (shown.length === 0) {
    return null
  }

  // Every engine any row names, in DISPLAYED_METHODS order: one control
  // each, since re-asking under an engine re-asks the whole question.
  const methods = DISPLAYED_METHODS.filter((method) =>
    shown.some((row) => row.ranks.some((entry) => entry.method === method)),
  )

  const controls =
    onSelectMethod === undefined
      ? null
      : methods.map((method) => (
          <button
            key={method}
            type="button"
            className={styles.ask}
            onClick={() => onSelectMethod(method)}
          >
            {`Ask ${METHOD_RADIO_LABEL[method]}`}
          </button>
        ))

  // One team (a team-case verdict): the controls sit on its one line. Two
  // (a compare verdict): they get a line of their own, since they re-ask
  // the comparison, not one side of it.
  const single = shown.length === 1

  return (
    <div className={styles.others}>
      {shown.map((row, index) => (
        <p key={row.teamName ?? index} className={styles.line}>
          <span>
            {(row.teamName === undefined ? '' : `${row.teamName} · `) +
              row.ranks
                .map(
                  (entry) =>
                    `${METHOD_RADIO_LABEL[entry.method]}: #${entry.rank}`,
                )
                .join(', ')}
          </span>
          {single && controls}
        </p>
      ))}
      {!single && controls !== null && (
        <p className={styles.line}>{controls}</p>
      )}
    </div>
  )
}
