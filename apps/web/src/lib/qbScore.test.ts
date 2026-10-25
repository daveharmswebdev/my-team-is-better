import { describe, expect, it, vi } from 'vitest'
import {
  PlayerApiError,
  PlayersNotComparableError,
  VerdictHttpError,
  VerdictNetworkError,
} from './api/client'
import {
  BRADY_VS_BARKLEY_QB_SCORE,
  BRADY_VS_MANNING_QB_SCORE,
  QB_SCORE_TIE,
} from './qbScoreFixtures'
import {
  formatQbMargin,
  formatQbScore,
  formatQbWeight,
  qbFloorLine,
  qbInconclusiveCopy,
  qbMeasureEdge,
  qbNarrationErrorCopy,
} from './qbScore'

describe('formatQbScore / formatQbMargin (issue #459)', () => {
  it('prints a score to 2 decimals, as the narration reads it', () => {
    expect(formatQbScore(18.191422342438862)).toBe('18.19')
    expect(formatQbScore(18.09044282356341)).toBe('18.09')
    expect(formatQbScore(1.72614444796375)).toBe('1.73')
    expect(formatQbScore(1.7703582866237446)).toBe('1.77')
  })

  it('prints a negative score with a minus sign, and never a signed zero', () => {
    expect(formatQbScore(-0.010091300883148607)).toBe('−0.01')
    expect(formatQbScore(-0.001)).toBe('0.00')
  })

  it("prints a margin as its absolute value to 2 decimals: Manning's peak is 0.04, never -0.04", () => {
    expect(formatQbMargin(0.10097951887545165)).toBe('0.10')
    expect(formatQbMargin(-0.04421383865999462)).toBe('0.04')
  })

  it('prints a weight as the API sent it, without float noise', () => {
    expect(formatQbWeight(0.826)).toBe('0.826')
    expect(formatQbWeight(0.17400000000000002)).toBe('0.174')
    expect(formatQbWeight(0.5)).toBe('0.5')
  })
})

describe('qbMeasureEdge (issue #459)', () => {
  it("names the API's winner and the absolute margin on each measure", () => {
    expect(qbMeasureEdge(BRADY_VS_MANNING_QB_SCORE, 'career')).toBe(
      'Tom Brady by 0.10',
    )
    expect(qbMeasureEdge(BRADY_VS_MANNING_QB_SCORE, 'peak')).toBe(
      'Peyton Manning by 0.04',
    )
  })

  it('reads the winner off the response, never off the scores', () => {
    // A response naming b on career though a's score is higher is still b's:
    // the math lives in the engine.
    expect(
      qbMeasureEdge(
        { ...BRADY_VS_MANNING_QB_SCORE, career_winner: 'b' },
        'career',
      ),
    ).toBe('Peyton Manning by 0.10')
  })

  it('says an exact tie (null winner, non-null margin) without crashing', () => {
    expect(qbMeasureEdge(QB_SCORE_TIE, 'career')).toBe('Dead even')
    expect(qbMeasureEdge(QB_SCORE_TIE, 'peak')).toBe('Dead even')
  })
})

describe('qbInconclusiveCopy (issue #459)', () => {
  it('is null when both QBs have a qualifying season', () => {
    expect(qbInconclusiveCopy(BRADY_VS_MANNING_QB_SCORE)).toBeNull()
  })

  it("names who has no qualifying season, in the founder's line", () => {
    expect(qbInconclusiveCopy(BRADY_VS_BARKLEY_QB_SCORE)).toBe(
      "Matt Barkley has no season in our books with 224 or more dropbacks, so there's no score to put up. The body of work isn't there — inconclusive.",
    )
  })

  it('covers player a, and neither', () => {
    expect(
      qbInconclusiveCopy({
        ...BRADY_VS_BARKLEY_QB_SCORE,
        inconclusive: 'a_no_qualifying_season',
      }),
    ).toMatch(/^Tom Brady has no season in our books/)
    expect(
      qbInconclusiveCopy({
        ...BRADY_VS_BARKLEY_QB_SCORE,
        inconclusive: 'neither_has_qualifying_season',
      }),
    ).toBe(
      "Neither one has a season in our books with 224 or more dropbacks, so there's nothing to score. The body of work isn't there — inconclusive.",
    )
  })
})

describe('qbFloorLine (issue #459)', () => {
  it('states the 1999 floor every time', () => {
    expect(qbFloorLine(1999, [])).toBe(
      'Counted since 1999, where the play-by-play starts.',
    )
  })

  it('says it louder, by name, when a career began before the data', () => {
    expect(qbFloorLine(1999, ['Peyton Manning'])).toBe(
      "Peyton Manning's career started before 1999, and the play-by-play doesn't go back that far: only his seasons from 1999 on are scored.",
    )
    expect(qbFloorLine(1999, ['Kurt Warner', 'Steve McNair'])).toBe(
      "Both careers started before 1999, and the play-by-play doesn't go back that far: only their seasons from 1999 on are scored.",
    )
  })

  it('is null on a db with no stat rows', () => {
    expect(qbFloorLine(null, [])).toBeNull()
  })
})

describe('qbNarrationErrorCopy: every narration failure in voice (issue #459)', () => {
  const noRawStatus = /\b(400|404|422|500|503)\b|error|status/i

  it.each([
    [
      '400 players_not_comparable',
      new PlayersNotComparableError(400, {
        error: 'players_not_comparable',
        a_group: 'QB',
        b_group: 'RB',
      }),
      "I only call these for two quarterbacks, so I'm sitting this one out. The numbers up there are the numbers.",
    ],
    [
      '404 unknown_player',
      new PlayerApiError(404, {
        error: 'unknown_player',
        player_id: 1,
        sport: 'nfl',
      }),
      'I lost one of these two in my book, so no call from me. The numbers up there are the numbers.',
    ],
    [
      '422 request validation',
      new VerdictHttpError(422, '{"detail":[]}'),
      'Your question came through garbled before I could weigh in. The numbers up there are the numbers.',
    ],
    [
      '503 stale database',
      new VerdictHttpError(503, '{"detail":{"error":"stale_database"}}'),
      'Something broke in the back before I could say my piece. The numbers up there are the numbers.',
    ],
    [
      'network failure or timeout',
      new VerdictNetworkError('anything'),
      "Lost you there, pal. My two cents didn't make it through. The numbers up there are the numbers.",
    ],
    [
      'anything unclassified',
      new Error('boom'),
      'Something broke in the back before I could say my piece. The numbers up there are the numbers.',
    ],
  ])('%s', (_name, error, copy) => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const text = qbNarrationErrorCopy(error)
    expect(text).toBe(copy)
    expect(text).not.toMatch(noRawStatus)
  })
})
