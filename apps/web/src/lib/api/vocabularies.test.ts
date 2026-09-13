import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { SPORTS, isVerdictErrorBody } from './types'

/**
 * Issue #112 (epic #113): apps/web's closed vocabularies are checked against
 * what the API actually publishes, not against a second hand-written copy.
 *
 * `apps/api/openapi-vocabularies.json` is generated from the API's live
 * `/openapi.json` by `python -m api.openapi_vocabularies`, and apps/api's test
 * suite fails when it is stale, so it is the API's published contract. It belongs to apps/api: read
 * it, never edit it. A league the API gains without apps/web following it
 * turns this file red.
 *
 * (Vite rewrites `import.meta.url` to a non-`file:` value under test, so this
 * resolves from Vitest's cwd -- `apps/web` -- instead. CI's apps-web job
 * checks out the whole repo and runs `npm run test` from apps/web.)
 */
const VOCABULARIES_PATH = resolve(
  process.cwd(),
  '../api/openapi-vocabularies.json',
)

type Vocabularies = Record<string, string[]>

function loadVocabularies(): Vocabularies {
  // Throws (failing every test below) if the file is missing or not JSON --
  // a missing contract must never pass by comparing nothing.
  const parsed: unknown = JSON.parse(readFileSync(VOCABULARIES_PATH, 'utf8'))
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${VOCABULARIES_PATH} is not a JSON object`)
  }
  const vocabularies: Vocabularies = {}
  for (const [name, values] of Object.entries(parsed)) {
    if (
      !Array.isArray(values) ||
      !values.every((value) => typeof value === 'string')
    ) {
      throw new Error(
        `${VOCABULARIES_PATH}: vocabulary "${name}" is not an array of strings`,
      )
    }
    vocabularies[name] = values
  }
  return vocabularies
}

/** A published vocabulary apps/web deliberately does not enumerate. */
interface NotMirrored {
  mirrored: false
  reason: string
}

/**
 * One explicit decision per vocabulary the API publishes: either apps/web's
 * mirror list (which must equal the API's, order included), or a documented
 * "not mirrored" marker. The keys must equal the file's keys exactly, so a new
 * vocabulary on the API side fails web CI until someone decides here.
 */
const WEB_VOCABULARY_DECISIONS: Record<
  string,
  readonly string[] | NotMirrored
> = {
  // Not mirrored: apps/web never enumerates or sends a rating method -- it
  // only renders whatever `TeamCaseOut.method` the API returns, and the API
  // itself publishes that field without an enum (allowlisted on its side),
  // so `TeamCaseOut.method` correctly stays `string` in types.ts.
  method: {
    mirrored: false,
    reason:
      'web never enumerates or sends methods; TeamCaseOut.method stays string',
  },
  // Mirrored: `QuestionForm`'s league toggle sends it, and
  // `isVerdictErrorBody` validates `unknown_team.sport` against it.
  sport: SPORTS,
}

function isNotMirrored(
  decision: readonly string[] | NotMirrored,
): decision is NotMirrored {
  return !Array.isArray(decision)
}

describe('published API vocabularies (issue #112)', () => {
  const vocabularies = loadVocabularies()

  it('parsed a real, non-empty sport vocabulary (floor: never vacuous)', () => {
    const sport = vocabularies['sport']
    expect(Array.isArray(sport)).toBe(true)
    expect(sport?.length).toBeGreaterThan(0)
    expect(sport?.every((value) => typeof value === 'string')).toBe(true)
  })

  it('has an explicit web decision for exactly the vocabularies the API publishes', () => {
    expect(Object.keys(WEB_VOCABULARY_DECISIONS).sort()).toEqual(
      Object.keys(vocabularies).sort(),
    )
  })

  it('documents why every not-mirrored vocabulary is not mirrored', () => {
    for (const decision of Object.values(WEB_VOCABULARY_DECISIONS)) {
      if (isNotMirrored(decision)) {
        expect(decision.reason.trim()).not.toBe('')
      }
    }
  })

  it('mirrors every mirrored vocabulary exactly, order included', () => {
    const mirrored = Object.entries(WEB_VOCABULARY_DECISIONS).filter(
      ([, decision]) => !isNotMirrored(decision),
    )
    expect(mirrored.length).toBeGreaterThan(0)
    for (const [name, decision] of mirrored) {
      if (!isNotMirrored(decision)) {
        expect({ [name]: [...decision] }).toEqual({
          [name]: vocabularies[name],
        })
      }
    }
  })

  it("mirrors the API's sport list exactly, order included", () => {
    expect([...SPORTS]).toEqual(vocabularies['sport'])
  })

  describe('isVerdictErrorBody follows the sport list', () => {
    function unknownTeamBody(sport: unknown) {
      return { error: 'unknown_team', query: 'Gonzaga', year: 2020, sport }
    }

    it('accepts an unknown_team body for every sport the API publishes', () => {
      const published = vocabularies['sport'] ?? []
      expect(published.length).toBeGreaterThan(0)
      for (const sport of [...SPORTS, ...published]) {
        expect({
          sport,
          accepted: isVerdictErrorBody(unknownTeamBody(sport)),
        }).toEqual({ sport, accepted: true })
      }
    })

    it('rejects an unknown_team body whose sport is outside the list', () => {
      // Plausible future leagues are rejected only while the API doesn't
      // publish them: a league added correctly (to the API and to SPORTS)
      // drops out of this list instead of failing it, while a guard that
      // silently accepts an unpublished 'nba' still fails here.
      const published: readonly unknown[] = vocabularies['sport'] ?? []
      const outside = [
        'nba',
        'mlb',
        'nhl',
        'wnba',
        'mls',
        'cbb',
        'CFB',
        'NFL',
        ' cfb',
        'nfl ',
        '',
        null,
        undefined,
        0,
      ].filter((value) => !published.includes(value))
      expect(outside.length).toBeGreaterThan(0)
      for (const sport of outside) {
        expect(SPORTS as readonly unknown[]).not.toContain(sport)
        expect({
          sport,
          accepted: isVerdictErrorBody(unknownTeamBody(sport)),
        }).toEqual({ sport, accepted: false })
      }
    })
  })
})
