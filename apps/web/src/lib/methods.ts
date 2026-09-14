import type { Method } from './api/types'

/**
 * The rating methods `QuestionForm`'s Engine toggle offers, in the order it
 * renders them (epic #147 / issue #154). A deliberate subset of `METHODS`:
 * `elo_career` stays API-only, and `vocabularies.test.ts` records why, so a
 * method the API adds fails web CI until someone decides whether it is offered.
 */
export const DISPLAYED_METHODS = [
  'keener',
  'elo',
] as const satisfies readonly Method[]

export type DisplayedMethod = (typeof DISPLAYED_METHODS)[number]

/** The Engine toggle's fieldset legend (and so its group's accessible name). */
export const ENGINE_LEGEND = 'Engine'

/**
 * Each method's user-facing name: the Engine radio's visible text (and
 * accessible name), and the name `VerdictCard` gives the engine that answered.
 * Shared here so the form and the card can never name one engine two ways.
 * Exhaustive, so a method added to `METHODS` fails tsc until it is named --
 * including `elo_career`, which no radio offers but the type still allows.
 */
export const METHOD_RADIO_LABEL: Record<Method, string> = {
  keener: 'Keener (default)',
  elo: 'Elo (second opinion)',
  elo_career: 'Elo, career',
}
