import { Link, useInRouterContext } from 'react-router-dom'
import type {
  EloGameStepOut,
  EloLedgerOut,
  GameResult,
} from '../../lib/api/types'
import { formatRating } from '../../lib/formatRating'
import { RatingDisclosureShell } from './RatingDisclosureShell'
import styles from './EloLedgerDisclosure.module.css'

export interface EloLedgerDisclosureProps {
  /** Team the ledger belongs to (panel title and dialog name). */
  teamName: string
  /** The Elo rating the card prints; the trigger shows it via `formatRating`. */
  rating: number
  /** The engine's own game-by-game work, straight from the response. */
  ledger: EloLedgerOut
}

const MINUS = '−'

const RATING = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
})
const SIGNED = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
  signDisplay: 'exceptZero',
})
const CONSTANT = new Intl.NumberFormat('en-US', { maximumFractionDigits: 6 })

/** A typeset minus, so a negative number matches the formula's operators. */
function withMinus(text: string): string {
  return text.replace('-', MINUS)
}

/** Ratings, the gap and the shift: 1 decimal. */
function oneDecimal(value: number): string {
  return withMinus(RATING.format(value))
}

function signedOneDecimal(value: number): string {
  return withMinus(SIGNED.format(value))
}

/** The engine's constants, as it sent them ("40", "2.2", "0.001", "1,500"). */
function constant(value: number): string {
  return withMinus(CONSTANT.format(value))
}

const RESULT_VALUE: Record<GameResult, string> = { W: '1', T: '½', L: '0' }

/**
 * One game, as a fan would name it: "Wk 2 · vs Ohio State · W 25–22",
 * "at X" away, "vs X (neutral)" at a neutral site, and "Postseason" in place
 * of the week for a postseason game.
 */
function gameLabel(step: EloGameStepOut): string {
  const when =
    step.season_type === 'postseason'
      ? 'Postseason'
      : step.week !== null
        ? `Wk ${step.week}`
        : null
  const where =
    step.venue === 'away'
      ? `at ${step.opponent_name}`
      : step.venue === 'neutral'
        ? `vs ${step.opponent_name} (neutral)`
        : `vs ${step.opponent_name}`
  const score = `${step.result} ${step.team_points}–${step.opponent_points}`
  return [when, where, score].filter((part) => part !== null).join(' · ')
}

/** "won by 3" / "lost by 7" / "tied": the final score's margin, not an Elo value. */
function marginPhrase(step: EloGameStepOut): string {
  switch (step.result) {
    case 'W':
      return `won by ${step.team_points - step.opponent_points}`
    case 'L':
      return `lost by ${step.opponent_points - step.team_points}`
    case 'T':
      return 'tied'
  }
}

/** " + 100" at home, " − 100" away, nothing at a neutral site: the step's own adjustment. */
function homeFieldTerm(adjustment: number): string {
  if (adjustment > 0) {
    return ` + ${constant(adjustment)}`
  }
  if (adjustment < 0) {
    return ` ${MINUS} ${constant(-adjustment)}`
  }
  return ''
}

/**
 * The rule with this game's own values plugged in, every one read from the
 * response and only rounded for display. Nothing here computes Elo: the gap,
 * expectancy, multiplier and shift are the engine's.
 */
function workedStep(k: number, step: EloGameStepOut): string {
  // Named with the rule lines' own words ("gap", "win expectancy",
  // "multiplier"), so every number maps to the line it came from. Expectancy
  // at 4 decimals and multiplier at 3, so a fan multiplying the printed
  // operands almost always lands on the printed shift (issue #183).
  const winExpectancy = step.win_expectancy.toFixed(4)
  const multiplier = step.mov_multiplier.toFixed(3)
  return (
    `${oneDecimal(step.rating_before)} ${MINUS} ${oneDecimal(step.opponent_rating_before)}` +
    `${homeFieldTerm(step.home_field_adjustment)} = gap ${signedOneDecimal(step.rating_gap)}` +
    ` → win expectancy ${winExpectancy} → ${marginPhrase(step)}, multiplier ${multiplier}` +
    ` → ${constant(k)} × ${multiplier} × (${RESULT_VALUE[step.result]} ${MINUS} ${winExpectancy})` +
    ` = ${signedOneDecimal(step.shift)}`
  )
}

/**
 * The Elo article on the About page, not the top of it (issue #227). The
 * fragment is the id `AboutPage` slugs from the methodology's name.
 */
const ABOUT_ELO = '/about#elo'

/** Client-side navigation inside the app; a plain link where there is no router (a story, a test). */
function AboutLink({ children }: { children: string }) {
  const inRouter = useInRouterContext()
  return inRouter ? (
    <Link to={ABOUT_ELO} className={styles.link}>
      {children}
    </Link>
  ) : (
    <a href={ABOUT_ELO} className={styles.link}>
      {children}
    </a>
  )
}

/**
 * Hover popover (desktop) / tap modal (mobile) on an Elo rating that answers
 * "how did the engine arrive at this value?" (issue #183): the rule with the
 * engine's constants, the starting rating, every game in order with that
 * game's own numbers plugged into the rule, and the final rating the card
 * rounds. A fan with a calculator can re-derive any row.
 *
 * Every number comes from `ledger` and is only formatted here; this component
 * never computes an expectancy, multiplier, shift or running total. On a long
 * season only the game list scrolls, so the rule and the footer stay in view.
 */
export function EloLedgerDisclosure({
  teamName,
  rating,
  ledger,
}: EloLedgerDisclosureProps) {
  const steps = [...ledger.steps].sort((a, b) => a.game_number - b.game_number)
  const last = steps.at(-1)
  const games = `${steps.length} game${steps.length === 1 ? '' : 's'}`
  const finalRating = oneDecimal(
    last === undefined ? ledger.starting_rating : last.rating_after,
  )

  return (
    <RatingDisclosureShell
      triggerLabel={formatRating(rating, 'elo')}
      title={`${teamName} Elo rating, game by game`}
      closeLabel="Close Elo rating, game by game"
      scroll="region"
    >
      <div className={styles.rule}>
        <h6 className={styles.sectionLabel}>The rule — same for every team</h6>
        <ul className={styles.ruleLines}>
          <li>{`Gap = team rating ${MINUS} opponent rating, ± ${constant(ledger.hfa)} for home field (0 at a neutral site)`}</li>
          <li>{`Win expectancy = 1 ÷ (10^(${MINUS}gap ÷ ${constant(ledger.scale)}) + 1)`}</li>
          <li>{`Margin multiplier = ln(max(margin, 1) + 1) × ${constant(ledger.mov_scale)} ÷ (winner's gap × ${constant(ledger.mov_autocorr)} + ${constant(ledger.mov_scale)}, floored at ${constant(ledger.mov_denom_floor_fraction)} × ${constant(ledger.mov_scale)} = ${constant(ledger.mov_denom_floor_fraction * ledger.mov_scale)}); a tie uses ln 2 × ${constant(ledger.mov_scale)}`}</li>
          <li>{`Rating change = ${constant(ledger.k)} × multiplier × (result ${MINUS} win expectancy), where result is 1 for a win, ½ for a tie, 0 for a loss`}</li>
        </ul>
        <p className={styles.provenance}>
          <AboutLink>
            Arpad Elo&apos;s system, in the football form FiveThirtyEight
            published
          </AboutLink>
        </p>
      </div>

      <p className={styles.start}>
        {`Every team starts the season at ${constant(ledger.starting_rating)}`}
      </p>

      {steps.length > 0 ? (
        // Focusable so a keyboard user can scroll it (it's the one region
        // that scrolls on a long season). The desktop popover grows until at
        // least four whole games show at once.
        <ol
          className={styles.steps}
          aria-label="Games, in order"
          tabIndex={0}
          data-min-visible-items={4}
        >
          {steps.map((step) => (
            <li key={step.game_number} className={styles.step}>
              <span className={styles.stepGame}>{gameLabel(step)}</span>
              <span className={styles.stepNumbers}>
                <span className={styles.stepShift}>
                  {signedOneDecimal(step.shift)}
                </span>
                <span className={styles.stepTotal}>
                  {`now ${oneDecimal(step.rating_after)}`}
                </span>
              </span>
              <span className={styles.stepWork}>
                {workedStep(ledger.k, step)}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className={styles.empty}>No games played.</p>
      )}

      <div className={styles.footer}>
        <p className={styles.total}>{`After ${games}: ${finalRating}`}</p>
        <p className={styles.footnote}>
          {`The card rounds this to ${formatRating(rating, 'elo')}.`}
        </p>
        <p className={styles.footnote}>
          Every figure here is rounded for display, so redoing the arithmetic
          with these printed numbers can come out a few tenths off; the engine
          keeps full precision, and every row&apos;s math checks out exactly at
          full precision.
        </p>
      </div>
    </RatingDisclosureShell>
  )
}
