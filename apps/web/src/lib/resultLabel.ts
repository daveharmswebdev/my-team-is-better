import type { GameResult } from './api/types'

const RESULT_LABELS: Record<GameResult, string> = {
  W: 'Win',
  L: 'Loss',
  T: 'Tie',
}

/**
 * The spoken word for a single-game result tag. The tag's visible text stays
 * the compact letter ("W"/"L"/"T"); this is the screen-reader text, so a tie
 * is announced as "Tie" rather than the bare letter "T" (and is never
 * distinguished from a win or loss by colour alone).
 */
export function resultLabel(result: GameResult): string {
  return RESULT_LABELS[result]
}
