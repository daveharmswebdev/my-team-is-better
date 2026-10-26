import { describe, expect, it } from 'vitest'
import {
  COMPARE_SHARE_PATH,
  VERDICT_SHARE_PATH,
  compareShareUrl,
  verdictShareUrl,
} from './sharePaths'

const ORIGIN = 'https://my-team-is-better-web.onrender.com'

describe('share link paths (issue #185)', () => {
  it('mints a verdict link under /s with the query untouched', () => {
    expect(VERDICT_SHARE_PATH).toBe('/s')
    expect(
      verdictShareUrl(
        ORIGIN,
        'q=team_case&sport=cfb&year=2005&engine=keener&team=Texas&for=Texas+A%26M',
      ),
    ).toBe(
      `${ORIGIN}/s?q=team_case&sport=cfb&year=2005&engine=keener&team=Texas&for=Texas+A%26M`,
    )
  })

  it('mints a comparison link under /s/nfl/compare, a then b', () => {
    expect(COMPARE_SHARE_PATH).toBe('/s/nfl/compare')
    expect(compareShareUrl(ORIGIN, 2153701690, 2072050236)).toBe(
      `${ORIGIN}/s/nfl/compare?a=2153701690&b=2072050236`,
    )
  })
})
