import { describe, expect, it } from 'vitest'
import {
  FAULK_VS_FARMER,
  HILL_VS_LAMB,
  KURT_WARNER_CAREER,
  SMITH_VS_PETERSON,
  STEVE_MCNAIR_CAREER,
  fixtureCoverage,
} from './playerFixtures'
import {
  careerCallout,
  careerSpanText,
  compareCallout,
  coveredSeasonsText,
  cutOffLegend,
  cutOffMarkerLabel,
  dataSpanLine,
  marksRow,
  searchSpanText,
  statsThroughLine,
} from './playerCoverage'

const EMMITT = SMITH_VS_PETERSON.a
const FAULK = FAULK_VS_FARMER.a
const FARMER = FAULK_VS_FARMER.b

/** Emmitt Smith's real coverage, but six seasons of it in the books. */
const SIX_OF_FIFTEEN = fixtureCoverage(1990, 2004, 1999, 2004)
/** The committed e2e fixture's Emmitt Smith: 1999 alone in the books. */
const ONE_OF_FIFTEEN = fixtureCoverage(1990, 2004, 1999, 1999)

describe('the fixtures this copy is built from (#448)', () => {
  it('holds the measured cut-offs', () => {
    expect(EMMITT.coverage).toMatchObject({
      career_first_season: 1990,
      career_last_season: 2004,
      data_first_season: 1999,
      covered_seasons: 6,
      career_seasons: 15,
      cut_off: true,
    })
    expect(FAULK.coverage.cut_off).toBe(true)
    expect(FARMER.coverage.cut_off).toBe(false)
    expect(HILL_VS_LAMB.a.coverage).toMatchObject({
      cut_off: false,
      cut_off_after: true,
    })
  })
})

describe('compareCallout (#448)', () => {
  it('names the one cut-off player, his real span and the slice', () => {
    expect(
      compareCallout(
        { name: 'Emmitt Smith', coverage: SIX_OF_FIFTEEN },
        { name: 'Robert Farmer', coverage: FARMER.coverage },
      ),
    ).toBe(
      "Hold on. Emmitt Smith played 1990 to 2004, and our books open in 1999. That's his last 6 of 15 seasons up there, not the whole career. Nobody's crowning anybody on those totals.",
    )
  })

  it('names the cut-off player whichever side he is on', () => {
    expect(
      compareCallout(
        { name: FARMER.display_name, coverage: FARMER.coverage },
        { name: FAULK.display_name, coverage: FAULK.coverage },
      ),
    ).toBe(
      "Hold on. Marshall Faulk played 1994 to 2006, and our books open in 1999. That's his last 1 of 13 seasons up there, not the whole career. Nobody's crowning anybody on those totals.",
    )
  })

  it('says it once for both when both are cut off', () => {
    expect(
      compareCallout(
        { name: 'Emmitt Smith', coverage: SIX_OF_FIFTEEN },
        {
          name: 'Jerry Rice',
          coverage: fixtureCoverage(1985, 2004, 1999, 2004),
        },
      ),
    ).toBe(
      "Hold on. Both of these guys were playing before our books open in 1999. Emmitt Smith: last 6 of 15 seasons. Jerry Rice: last 6 of 20. Slices of careers, not careers. Nobody's crowning anybody on those totals.",
    )
  })

  it('keeps "seasons" plural after the career length when one season is in the books', () => {
    expect(
      compareCallout(
        { name: KURT_WARNER_CAREER.display_name, coverage: ONE_OF_FIFTEEN },
        {
          name: STEVE_MCNAIR_CAREER.display_name,
          coverage: STEVE_MCNAIR_CAREER.coverage,
        },
      ),
    ).toBe(
      "Hold on. Both of these guys were playing before our books open in 1999. Kurt Warner: last 1 of 15 seasons. Steve McNair: last 1 of 13. Slices of careers, not careers. Nobody's crowning anybody on those totals.",
    )
  })

  it('says nothing when neither is cut off, or only runs past the data', () => {
    expect(
      compareCallout(
        { name: 'Robert Farmer', coverage: FARMER.coverage },
        { name: 'Tyreek Hill', coverage: HILL_VS_LAMB.a.coverage },
      ),
    ).toBeNull()
    expect(
      compareCallout(
        { name: 'Tyreek Hill', coverage: HILL_VS_LAMB.a.coverage },
        { name: 'CeeDee Lamb', coverage: HILL_VS_LAMB.b.coverage },
      ),
    ).toBeNull()
  })
})

describe('careerCallout (#448)', () => {
  it('says what is missing, facts first', () => {
    expect(
      careerCallout({ name: 'Emmitt Smith', coverage: SIX_OF_FIFTEEN }),
    ).toBe(
      "Emmitt Smith played 1990 to 2004. Our books open in 1999, so this is his last 6 of 15 seasons. The first 9 aren't here, and yelling at the bartender won't change it.",
    )
  })

  it('reads in the singular for one season in the books', () => {
    expect(
      careerCallout({ name: EMMITT.display_name, coverage: ONE_OF_FIFTEEN }),
    ).toBe(
      "Emmitt Smith played 1990 to 2004. Our books open in 1999, so this is his last 1 of 15 seasons. The first 14 aren't here, and yelling at the bartender won't change it.",
    )
  })

  it('drops the "first N" sentence when nothing is left over', () => {
    // A gap year can make the covered count reach the career length.
    const full = { ...SIX_OF_FIFTEEN, covered_seasons: 15 }
    expect(careerCallout({ name: 'Emmitt Smith', coverage: full })).toBe(
      'Emmitt Smith played 1990 to 2004. Our books open in 1999, so this is his last 15 of 15 seasons.',
    )
    expect(
      careerCallout({
        name: 'Emmitt Smith',
        coverage: { ...SIX_OF_FIFTEEN, covered_seasons: 16 },
      }),
    ).not.toContain('The first')
  })

  it('says nothing for a career inside the data, or one running past it', () => {
    expect(
      careerCallout({ name: 'Robert Farmer', coverage: FARMER.coverage }),
    ).toBeNull()
    expect(
      careerCallout({ name: 'Tyreek Hill', coverage: HILL_VS_LAMB.a.coverage }),
    ).toBeNull()
  })
})

describe('statsThroughLine (#448)', () => {
  it('is a plain line for a career running past the data', () => {
    expect(statsThroughLine([HILL_VS_LAMB.a.coverage])).toBe(
      "Stats through 2023. This season isn't in our books yet.",
    )
    expect(statsThroughLine([FARMER.coverage, HILL_VS_LAMB.b.coverage])).toBe(
      "Stats through 2023. This season isn't in our books yet.",
    )
  })

  it('is absent when nobody runs past the data', () => {
    expect(statsThroughLine([FARMER.coverage, EMMITT.coverage])).toBeNull()
  })
})

describe('spans (#448)', () => {
  it('reads the data span from the API, never a typed year', () => {
    expect(dataSpanLine(1999, 2023)).toBe('NFL player stats: 1999–2023.')
    expect(dataSpanLine(2002, 2025)).toBe('NFL player stats: 2002–2025.')
    expect(dataSpanLine(null, 2023)).toBeNull()
    expect(dataSpanLine(1999, null)).toBeNull()
  })

  it('reads the real career span when the source has one', () => {
    expect(careerSpanText(EMMITT.coverage)).toBe('1990–2004')
    expect(careerSpanText(FARMER.coverage)).toBe('1999')
    expect(
      careerSpanText({ ...FARMER.coverage, career_first_season: null }),
    ).toBeNull()
  })

  it('reads a cut-off seasons cell as covered of career, with the covered span', () => {
    expect(coveredSeasonsText(SIX_OF_FIFTEEN)).toBe('6 of 15 (1999–2004)')
    expect(coveredSeasonsText(ONE_OF_FIFTEEN)).toBe('1 of 15 (1999)')
    expect(coveredSeasonsText(EMMITT.coverage)).toBe('6 of 15 (1999–2004)')
    expect(coveredSeasonsText(FARMER.coverage)).toBeNull()
    expect(coveredSeasonsText(HILL_VS_LAMB.a.coverage)).toBeNull()
  })

  it('gives a search row the real span and where the stats start when cut off', () => {
    expect(
      searchSpanText({
        first_season: 1999,
        last_season: 2004,
        coverage: SIX_OF_FIFTEEN,
      }),
    ).toBe('1990–2004 · stats from 1999')
    expect(
      searchSpanText({
        first_season: 1999,
        last_season: 1999,
        coverage: FARMER.coverage,
      }),
    ).toBe('1999')
    expect(
      searchSpanText({
        first_season: 2016,
        last_season: 2023,
        coverage: HILL_VS_LAMB.a.coverage,
      }),
    ).toBe('2016–2023')
  })

  it('labels a leader row whose career began before the data', () => {
    expect(cutOffMarkerLabel(EMMITT.coverage)).toBe('career began before 1999')
    expect(cutOffMarkerLabel(FARMER.coverage)).toBeNull()
    expect(cutOffLegend([FARMER.coverage, EMMITT.coverage])).toBe(
      '‹ marks a career that began before 1999: those totals are missing its early seasons.',
    )
    expect(cutOffLegend([FARMER.coverage, HILL_VS_LAMB.a.coverage])).toBeNull()
    expect(cutOffMarkerLabel(HILL_VS_LAMB.a.coverage)).toBeNull()
  })
})

describe('marksRow: the larger-number rule (founder, #448)', () => {
  it('marks no career total when either side is cut off', () => {
    expect(marksRow('total', EMMITT.coverage, FARMER.coverage)).toBe(false)
    expect(marksRow('total', FARMER.coverage, EMMITT.coverage)).toBe(false)
    expect(marksRow('total', EMMITT.coverage, FAULK.coverage)).toBe(false)
  })

  it('still marks a rate over the covered seasons', () => {
    expect(marksRow('rate', EMMITT.coverage, FARMER.coverage)).toBe(true)
    expect(marksRow('rate', EMMITT.coverage, FAULK.coverage)).toBe(true)
  })

  it('marks totals when nobody is cut off, running past the data included', () => {
    expect(marksRow('total', FARMER.coverage, FARMER.coverage)).toBe(true)
    expect(
      marksRow('total', HILL_VS_LAMB.a.coverage, HILL_VS_LAMB.b.coverage),
    ).toBe(true)
  })
})
