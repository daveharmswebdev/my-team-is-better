/**
 * TypeScript mirror of `apps/api/src/api/models.py`'s response/error shapes.
 * Field names and nesting intentionally match the Python source exactly --
 * see that file for the source of truth; this file is not a substitute for
 * reading it.
 */

/**
 * A single completed game's result from one team's side. `'T'` is a tie
 * (equal scores, any sport -- issue #83); it can appear in `games` and in
 * common-opponent results, but never in `quality_wins` or `worst_loss`.
 */
export type GameResult = 'W' | 'L' | 'T'

/**
 * Which side of a game this team played (issue #294): team-relative like
 * `GameResult`, never a stadium name. `'neutral'` takes precedence over
 * home/away, so wherever a row also carries `neutral_site`, that flag always
 * equals `venue === 'neutral'` -- the engine refuses to build a pair that
 * disagrees, so the API cannot send one.
 */
export type GameVenue = 'home' | 'away' | 'neutral'

export interface OpponentResultOut {
  /** `games.id` (issue #218): the one per-game identity; key lists of games on it. */
  game_id: number
  opponent_team_id: number
  opponent_name: string
  opponent_rank: number | null
  opponent_rating: number | null
  result: GameResult
  team_score: number
  opponent_score: number
  week: number | null
  season_type: string
  /** This team's own side; `neutral_site` below always agrees with it. */
  venue: GameVenue
  /** Kept because the API still publishes it; no component reads it today. */
  neutral_site: boolean
  /**
   * Issue #349: whether `venue` can be stated as fact. CFBD's venue data is
   * unreliable before 2008 (founder, #343), so a CFB game before 2008 is
   * reliable only when it is on #359's curated override list; every NFL game
   * and every CFB game from 2008 on is reliable. Display only: when false,
   * don't print "at X" or "(neutral)".
   */
  venue_reliable: boolean
}

export interface OpponentCreditOut {
  opponent_team_id: number
  opponent_name: string
  games_played: number
  wins: number
  losses: number
  credit: number
  contribution: number
  explanation: string
}

export interface RatingBreakdownOut {
  entries: OpponentCreditOut[]
  residual_contribution: number
}

/**
 * One game of an Elo season, from one team's side (issue #183). Every number
 * is the engine's own, at full precision: apps/web formats these and never
 * recomputes them. `rating_gap` is `rating_before - opponent_rating_before +
 * home_field_adjustment`, and `rating_after` is `rating_before + shift`.
 */
export interface EloGameStepOut {
  game_number: number
  week: number | null
  season_type: string
  start_date: string | null
  opponent_team_id: number
  opponent_name: string
  venue: GameVenue
  team_points: number
  opponent_points: number
  result: GameResult
  rating_before: number
  opponent_rating_before: number
  /** `+hfa` at home, `-hfa` away, `0` at a neutral site. */
  home_field_adjustment: number
  rating_gap: number
  /** This team's expected score, 0..1. */
  win_expectancy: number
  mov_multiplier: number
  /** Signed, this team's. */
  shift: number
  rating_after: number
  /** Issue #349: whether `venue` can be stated as fact; see `OpponentResultOut.venue_reliable`. */
  venue_reliable: boolean
}

/**
 * The work behind an Elo rating (issue #183): the constants the engine ran
 * with, and every game in order. `steps[0].rating_before` is
 * `starting_rating`, each step starts where the previous one ended, and the
 * last `rating_after` is the team's rating.
 */
export interface EloLedgerOut {
  starting_rating: number
  k: number
  hfa: number
  scale: number
  mov_scale: number
  mov_autocorr: number
  /**
   * The margin-of-victory denominator floor as a fraction of `mov_scale`,
   * stored with the ledger (issue #194); the panel prints it rather than
   * assuming a half.
   */
  mov_denom_floor_fraction: number
  steps: EloGameStepOut[]
}

export interface TeamCaseOut {
  year: number
  /** Echoes the request's already-validated method; picks `formatRating`'s display scale. */
  method: Method
  team_id: number
  team_name: string
  rank: number
  rating: number
  wins: number
  losses: number
  /** Required on the API side (issue #83). Render records via `formatRecord`. */
  ties: number
  rating_breakdown: RatingBreakdownOut
  /**
   * Issue #183: the Elo ledger under `elo`; `null` under `keener` and
   * `elo_career`. Required: the API always sends the key.
   */
  elo_ledger: EloLedgerOut | null
  games: OpponentResultOut[]
  quality_wins: OpponentResultOut[]
  worst_loss: OpponentResultOut | null
}

export interface ComparisonTeamSummaryOut {
  team_id: number
  team_name: string
  rank: number
  rating: number
  wins: number
  losses: number
  /** Required on the API side (issue #83). Render records via `formatRecord`. */
  ties: number
  rating_breakdown: RatingBreakdownOut
  /** Same as `TeamCaseOut.elo_ledger`. */
  elo_ledger: EloLedgerOut | null
  quality_wins: OpponentResultOut[]
  worst_loss: OpponentResultOut | null
}

export interface HeadToHeadMeetingOut {
  /** `games.id` (issue #218), like `OpponentResultOut.game_id`. */
  game_id: number
  week: number | null
  season_type: string
  neutral_site: boolean
  home_team: string
  away_team: string
  home_points: number
  away_points: number
  winner: string | null
  /** Issue #349: whether `neutral_site` can be stated as fact; see `OpponentResultOut.venue_reliable`. */
  venue_reliable: boolean
}

export interface HeadToHeadOut {
  played: boolean
  meetings: HeadToHeadMeetingOut[]
}

/**
 * One game a compared side played against a shared opponent (issue #130).
 * Team-relative, like `OpponentResultOut`: `result` and the score pair are
 * from that side's perspective, so apps/web never re-derives which side it is.
 */
export interface CommonOpponentMeetingOut {
  /** `games.id` (issue #218), like `OpponentResultOut.game_id`. */
  game_id: number
  /** From that side's perspective, like `OpponentResultOut`. */
  result: GameResult
  team_score: number
  opponent_score: number
  week: number | null
  season_type: string
  /**
   * That side's own venue. Deliberately no `neutral_site` companion, here or
   * in the engine contract: `'neutral'` already says it, for both teams.
   */
  venue: GameVenue
  /** Issue #349: that side's `OpponentResultOut.venue_reliable`, copied. */
  venue_reliable: boolean
}

/**
 * A team both compared sides played, with every meeting per side. There is
 * deliberately no per-side W-L-T aggregate: it is derivable from the list and
 * would be one more thing that could disagree with it (issue #130).
 */
export interface CommonOpponentOut {
  opponent_team_id: number
  opponent_name: string
  opponent_rank: number | null
  /** Every meeting this season, chronological (regular season by week, then postseason); never empty (issue #130). */
  team_a_meetings: CommonOpponentMeetingOut[]
  /** Same, for team_b. */
  team_b_meetings: CommonOpponentMeetingOut[]
}

export interface ComparisonResultOut {
  year: number
  /** Echoes the request's already-validated method (issue #152); picks `formatRating`'s display scale. */
  method: Method
  team_a: ComparisonTeamSummaryOut
  team_b: ComparisonTeamSummaryOut
  head_to_head: HeadToHeadOut
  common_opponents: CommonOpponentOut[]
  /** `team_a.rating - team_b.rating`, on the method's own scale. */
  rating_diff: number
  /** Engine sentence, still sent for the persona and MCP; apps/web deliberately doesn't render it (#24). */
  verdict: string
}

export interface NarrationOut {
  text: string
  contested: boolean
  cached: boolean
}

/**
 * Mirrors `MethodRankOut` (issue #155): where one other rating method ranks
 * a verdict's team that season. Rank only, never a rating -- the methods'
 * ratings are on different scales.
 */
export interface MethodRankOut {
  method: Method
  rank: number
}

export interface TeamCaseEnvelope {
  evidence: TeamCaseOut
  narration: NarrationOut
  /**
   * Issue #155: every registered method other than the answering one that
   * has a ratings row for this team and season, in `METHODS` order. The API
   * applies no UI policy, so it can include methods apps/web doesn't offer
   * (`elo_career`); filter to `DISPLAYED_METHODS` before rendering. May be [].
   */
  other_method_ranks: MethodRankOut[]
}

export interface ComparisonEnvelope {
  evidence: ComparisonResultOut
  narration: NarrationOut
  /** Issue #155: `TeamCaseEnvelope.other_method_ranks`, for `team_a`. */
  team_a_other_method_ranks: MethodRankOut[]
  /** Issue #155: `TeamCaseEnvelope.other_method_ranks`, for `team_b`. */
  team_b_other_method_ranks: MethodRankOut[]
}

export type VerdictEnvelope = TeamCaseEnvelope | ComparisonEnvelope

// ---------------------------------------------------------------------------
// credits -- mirrors apps/api/src/api/models.py's `CreditsOut` (About page).
// ---------------------------------------------------------------------------

export interface CreditsMethodologyOut {
  name: string
  citation: string
  url: string
  summary: string
  /**
   * The registered rating methods this citation covers, in the engine's
   * order (issue #144). Required and never empty: the engine checks every
   * registered method appears in exactly one credit and that `methods[0]`
   * is unique across credits, so the About page keys each article's id on
   * it (`/about#elo`, `/about#keener`).
   */
  methods: Method[]
}

export interface CreditsDataSourceOut {
  /**
   * The source's stable id (issue #296): `'cfbd'`, `'nflverse_games'`,
   * `'nflverse_player_stats'` today. Pick a credit or its copy by this, never
   * by `name` (which can be reworded) or by position.
   */
  id: string
  name: string
  url: string
  note: string
}

export interface CreditsOut {
  /**
   * Every rating method the engine implements, in the order the API sends
   * them -- Keener's method (the validated default) first, then Elo (the
   * second opinion). Render in the order received; do not sort.
   */
  methodologies: CreditsMethodologyOut[]
  data_sources: CreditsDataSourceOut[]
}

// ---------------------------------------------------------------------------
// players -- mirrors apps/api/src/api/models.py's player read layer (issue
// #296): `GET /api/players/leaders` and `GET /api/players/{player_id}`.
// ---------------------------------------------------------------------------

/**
 * The engine's `PlayerSeasonType` literal, in its order. Not in
 * `apps/api/openapi-vocabularies.json` (it publishes `sport`, `method` and
 * `group`), so nothing checks this list against the API yet; it is copied
 * from `cfb_strength.contracts`.
 */
export const PLAYER_SEASON_TYPES = ['regular', 'postseason'] as const

export type PlayerSeasonType = (typeof PLAYER_SEASON_TYPES)[number]

/**
 * The engine's `PlayerPositionGroup` literal, in its display order (issue
 * #436, epic #372): the groups /nfl/compare compares within. A player's group
 * comes from his position label (FB is RB); every other label, and a missing
 * one, has none (`null`). Checked against the API's published
 * `apps/api/openapi-vocabularies.json` (`group`, order included) by
 * `vocabularies.test.ts`.
 */
export const PLAYER_POSITION_GROUPS = ['QB', 'RB', 'WR', 'TE'] as const

export type PlayerPositionGroup = (typeof PLAYER_POSITION_GROUPS)[number]

/**
 * The engine's `PlayerLeaderCategory` literal, in its order (issue #312):
 * what a board ranks. A stat category, never a position -- the rushing board
 * ranks everyone with a carry, quarterbacks included, the receiving board
 * (issue #314) everyone with a target or a reception, the kicking board
 * (issue #315) everyone with a field-goal or extra-point attempt, the
 * punting board everyone with a punt, and the defense board (issue #317)
 * everyone with more than zero in any of its five stats. Same caveat as
 * `PLAYER_SEASON_TYPES`.
 */
export const PLAYER_LEADER_CATEGORIES = [
  'passing',
  'rushing',
  'receiving',
  'kicking',
  'punting',
  'defense',
] as const

export type PlayerLeaderCategory = (typeof PLAYER_LEADER_CATEGORIES)[number]

/**
 * The sorts each category accepts, its default first: the mirror of the
 * engine's `PLAYER_LEADER_SORTS_BY_CATEGORY`. Every sort belongs to exactly
 * one category, and the API answers a pair from two categories with a 422 at
 * `sort`, so this is the only list a caller may pick a sort from -- never a
 * string check of its own.
 *
 * Two kicking sorts (issue #315), `fg_pct` and `fg_made_50_plus`, are
 * computed by the engine and are not `PlayerStatsOut` fields; every other
 * sort is the stat of the same name.
 */
export const PLAYER_LEADER_SORTS_BY_CATEGORY = {
  passing: ['passing_yards', 'passing_tds', 'wins'],
  rushing: ['rushing_yards', 'rushing_tds', 'carries'],
  receiving: ['receiving_yards', 'receiving_tds', 'receptions'],
  kicking: [
    'fg_made',
    'fg_pct',
    'fg_made_50_plus',
    'fg_long',
    'fg_att',
    'pat_made',
  ],
  punting: ['pt_yards', 'pt_net_yards', 'pt_att', 'pt_inside_20'],
  defense: [
    'def_sacks',
    'def_interceptions',
    'def_tackles_solo',
    'def_fumbles_forced',
    'def_pass_defended',
  ],
} as const satisfies Record<PlayerLeaderCategory, readonly string[]>

/**
 * The mirror of the engine's `PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS`
 * (`cfb_strength.contracts`, issue #315): the career field-goal attempts a
 * kicker needs, in that season type, to be on the `fg_pct` board at all. The
 * API leaves everyone below it off that board, and `total` counts only those
 * at or above it -- so the board can be short, or empty.
 */
export const PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS = {
  regular: 100,
  postseason: 15,
} as const satisfies Record<PlayerSeasonType, number>

/**
 * The engine's `PlayerLeaderSort` literal; always descending. Derived from
 * the map above rather than restated, so the two cannot drift apart.
 */
export const PLAYER_LEADER_SORTS = [
  ...PLAYER_LEADER_SORTS_BY_CATEGORY.passing,
  ...PLAYER_LEADER_SORTS_BY_CATEGORY.rushing,
  ...PLAYER_LEADER_SORTS_BY_CATEGORY.receiving,
  ...PLAYER_LEADER_SORTS_BY_CATEGORY.kicking,
  ...PLAYER_LEADER_SORTS_BY_CATEGORY.punting,
  ...PLAYER_LEADER_SORTS_BY_CATEGORY.defense,
] as const

export type PlayerLeaderSort = (typeof PLAYER_LEADER_SORTS)[number]

/** A W-L-T as the listed starter. `starts` is the API's own `wins + losses + ties`: render it, don't re-derive it. */
export interface StarterRecordOut {
  wins: number
  losses: number
  ties: number
  starts: number
}

/**
 * Every stat is `null` when the source did not record it -- never 0. Sack
 * stats are mirrored faithfully but not shown in v1, by choice: the yards a
 * sacked passer lost are published positive (#298), so `sack_yards_lost`
 * reads the way its name and an official stat line read.
 *
 * The receiving stats (issue #314) are mirrored in full, but only
 * `receptions`, `receiving_yards` and `receiving_tds` are shown, and only on
 * the receiving board. `targets` is never shown: the source did not track it
 * for 2003-2008, which the db stores as null (#345), so a career total
 * spanning those years is null. First downs and fumbles lost are
 * not shown in v1 either.
 *
 * The kicking and punting stats (issue #315) are shown only on their own
 * boards. `fg_long` and `pt_long` are career maxima, not sums, and are `null`
 * for a player who never made a field goal or never punted -- there is no
 * longest of nothing -- so on those boards a `null` there is a dash, not
 * "not recorded". Every other kicking or punting 0 is a recorded zero.
 * `pat_att` and `pt_long` are mirrored but not shown; `fg_made_50_59` and
 * `fg_made_60_` (which keeps nflverse's trailing underscore) are shown only
 * summed, as the 50+ column.
 *
 * The five defense stats (issue #317) are shown only on the defense board,
 * in the contract's order here (not the board's sort order). `def_sacks` is
 * a decimal; the other four are counts. A non-defender carries the source's
 * recorded zeros. Founder decision (#316): `def_sacks` and
 * `def_fumbles_forced` can run short of the official total for 1999-2009,
 * and `def_tackles_solo` and `def_pass_defended` are unofficial, so the
 * board shows a note with each pair. The engine's EPA columns are not
 * published.
 */
export interface PlayerStatsOut {
  completions: number | null
  attempts: number | null
  passing_yards: number | null
  passing_tds: number | null
  passing_interceptions: number | null
  sacks_suffered: number | null
  sack_yards_lost: number | null
  carries: number | null
  rushing_yards: number | null
  rushing_tds: number | null
  /** Never null in any season 1999-2025 (measured on #352), so a 0 is a real zero. Not a leader sort. */
  rushing_first_downs: number | null
  /** Not a leader sort. */
  rushing_fumbles_lost: number | null
  receptions: number | null
  targets: number | null
  receiving_yards: number | null
  receiving_tds: number | null
  receiving_first_downs: number | null
  receiving_fumbles_lost: number | null
  fg_made: number | null
  fg_att: number | null
  fg_long: number | null
  fg_made_50_59: number | null
  fg_made_60_: number | null
  pat_made: number | null
  pat_att: number | null
  pt_att: number | null
  pt_yards: number | null
  pt_net_yards: number | null
  pt_long: number | null
  pt_inside_20: number | null
  def_interceptions: number | null
  /** A decimal: a sack split between two rushers is 0.5 each, so 17.5 is real and is never rounded. */
  def_sacks: number | null
  def_fumbles_forced: number | null
  def_tackles_solo: number | null
  def_pass_defended: number | null
}

/**
 * How much of a player's real career this db's stats hold (#446, epic #443),
 * mirroring `PlayerCoverageOut`. Two spans: the *career* span is what the
 * source's roster says he played; the *data* span is the seasons this db has
 * player stats for at all. `cut_off` (== `cut_off_before`) means the career
 * began before the data, so every total is a slice of it and must not carry
 * a larger-number mark. `cut_off_after` alone (an active player whose current
 * season isn't in yet) is informational: "stats through <data_last_season>".
 */
export interface PlayerCoverageOut {
  /** From the source's roster, not this db's stat rows; `null` when it doesn't say. */
  career_first_season: number | null
  career_last_season: number | null
  /** This db's player-stats span, the same for every player; `null` with no stat rows. */
  data_first_season: number | null
  data_last_season: number | null
  /** This player's own lines in this db, either season type; `null` with none. */
  covered_first_season: number | null
  covered_last_season: number | null
  /** Distinct seasons with a line here: the "6" in "his last 6 of 15 seasons". */
  covered_seasons: number
  /** `career_last_season - career_first_season + 1`: the "15"; `null` without both ends. */
  career_seasons: number | null
  cut_off_before: boolean
  cut_off_after: boolean
  /** Equal to `cut_off_before`. */
  cut_off: boolean
}

export interface PlayerLeaderRowOut {
  /** Competition rank over the whole population (ties share it: 1, 2, 2, 4); `null` only when the sort value is `null`. */
  rank: number | null
  player_id: number
  display_name: string
  position: string | null
  first_season: number
  last_season: number
  games: number | null
  record: StarterRecordOut
  stats: PlayerStatsOut
  coverage: PlayerCoverageOut
}

export interface PlayerLeadersOut {
  sport: Sport
  /** What this board ranks (#312): qualifying, the rows and the sort all belong to it. */
  category: PlayerLeaderCategory
  season_type: PlayerSeasonType
  /** Always the resolved sort: a request without one is answered with the category's default. */
  sort: PlayerLeaderSort
  limit: number
  offset: number
  /**
   * The whole qualifying population's size, so a client can page. On the
   * `fg_pct` board (#315) only the kickers at `PLAYER_LEADER_FG_PCT_MIN_ATTEMPTS`
   * count, so it may be 0.
   */
  total: number
  /** This db's player-stats span (not any player's career); `null` with no stat rows. */
  data_first_season: number | null
  data_last_season: number | null
  rows: PlayerLeaderRowOut[]
}

export interface PlayerSeasonLineOut {
  season: number
  season_type: PlayerSeasonType
  teams: string[]
  games: number | null
  record: StarterRecordOut
  stats: PlayerStatsOut
  /** Completed games of this line's teams with no player stat lines at all, which these totals therefore undercount. */
  games_without_stat_lines: number
}

export interface PlayerCareerTotalsOut {
  season_type: PlayerSeasonType
  seasons: number
  games: number | null
  record: StarterRecordOut
  stats: PlayerStatsOut
}

export interface PlayerCareerOut {
  sport: Sport
  player_id: number
  display_name: string
  position: string | null
  /** `position`'s group (#433); `null` for a label with none (K, LB, ...). */
  group: PlayerPositionGroup | null
  /** Chronological; regular season before postseason within a season. */
  seasons: PlayerSeasonLineOut[]
  /** `null` when the player has no season line of that type. */
  regular_season: PlayerCareerTotalsOut | null
  postseason: PlayerCareerTotalsOut | null
  coverage: PlayerCoverageOut
}

// `GET /api/players/compare` and `GET /api/players/search` (issue #301).

/** One game both players started at quarterback, for opposite teams. */
export interface PlayerHeadToHeadGameOut {
  season: number
  season_type: PlayerSeasonType
  week: number | null
  start_date: string | null
  source_id: string | null
  a_team: string
  b_team: string
  a_points: number
  b_points: number
  /** `null` when the source has no stat line for that starter in this game. */
  a_stats: PlayerStatsOut | null
  b_stats: PlayerStatsOut | null
}

export interface PlayerHeadToHeadOut {
  season_type: PlayerSeasonType
  /** `a`'s W-L-T against `b`. */
  record: StarterRecordOut
  /** Chronological, as the engine orders them. */
  games: PlayerHeadToHeadGameOut[]
}

export interface PlayerComparisonOut {
  sport: Sport
  a: PlayerCareerOut
  b: PlayerCareerOut
  /** Always present: 0-0-0 with no games when the two never met. */
  regular_season_head_to_head: PlayerHeadToHeadOut
  postseason_head_to_head: PlayerHeadToHeadOut
  /**
   * The engine's era-adjusted QB score (#451, epic #439). `null` unless both
   * players' group is QB.
   */
  qb_score: PlayerQbScoreComparisonOut | null
}

// ---------------------------------------------------------------------------
// The era-adjusted QB score (issue #451, epic #439) -- mirrors
// `apps/api/src/api/models.py`'s `PlayerQbScore*Out`. The API never rounds,
// recomputes or reorders the engine's numbers, and neither does apps/web:
// winners and margins are read, never derived.
// ---------------------------------------------------------------------------

/** Mirrors `QbScoreSide`: which player, as the request named them. */
export type QbScoreSide = 'a' | 'b'

/** Mirrors `QbScoreInconclusiveReason`: who has no qualifying season. */
export type QbScoreInconclusiveReason =
  | 'a_no_qualifying_season'
  | 'b_no_qualifying_season'
  | 'neither_has_qualifying_season'

/** Mirrors `QbScoreMetric`: the two scored metrics, the keys of `weights`. */
export type QbScoreMetric = 'epa_per_dropback' | 'rush_epa_per_play'

/**
 * One metric in one season: the raw value against that season's qualifying
 * QBs. The three era fields are `null` when the season doesn't qualify.
 */
export interface PlayerQbMetricValueOut {
  value: number
  season_mean: number | null
  /** Population SD over that season's qualifying QBs. */
  season_sd: number | null
  /** `(value - season_mean) / season_sd`; 0.0 when `season_sd` is 0. */
  z: number | null
}

export interface PlayerQbScoreSeasonOut {
  season: number
  /** Pass attempts plus sacks suffered. */
  dropbacks: number
  /** `dropbacks >= min_dropbacks`: only these are judged and counted. */
  qualifies: boolean
  /** Scored with `weights.epa_per_dropback`; `null` with no dropbacks. */
  epa_per_dropback: PlayerQbMetricValueOut | null
  /** Scored with `weights.rush_epa_per_play`; `null` with no plays. */
  rush_epa_per_play: PlayerQbMetricValueOut | null
  /** ANY/A: shown for context, never scored. */
  any_a: PlayerQbMetricValueOut | null
  /** The season's score, sum of `weights[metric] * z`; `null` unless it qualifies. */
  composite: number | null
  /** One of the seasons the peak averages. */
  in_peak: boolean
}

export interface PlayerQbScoreOut {
  sport: Sport
  player_id: number
  display_name: string
  version: string
  /** Every regular season with a stat row, qualifying or not, chronological. */
  seasons: PlayerQbScoreSeasonOut[]
  qualifying_seasons: number
  /** Sum of the qualifying composites; `null` with no qualifying season. */
  career: number | null
  /** Mean of the best `peak_seasons` composites, empty slots 0.0; `null` with none. */
  peak: number | null
  /** How many of the peak slots were filled with 0.0 (league average). */
  peak_filled_with_average: number
  first_season: number | null
  first_scored_season: number | null
}

export interface PlayerQbScoreComparisonOut {
  sport: Sport
  version: string
  a: PlayerQbScoreOut
  b: PlayerQbScoreOut
  /** Any margin wins; `null` when inconclusive or exactly tied. */
  career_winner: QbScoreSide | null
  peak_winner: QbScoreSide | null
  /** `a.career - b.career` (signed); `null` when inconclusive. */
  career_margin: number | null
  /** `a.peak - b.peak` (signed); `null` when inconclusive. */
  peak_margin: number | null
  /** Set exactly when either QB has no qualifying season. */
  inconclusive: QbScoreInconclusiveReason | null
  /** Each scored metric's weight in a composite; they sum to 1. */
  weights: Record<QbScoreMetric, number>
  /** The fewest dropbacks a season needs to qualify. */
  min_dropbacks: number
  /** How many best seasons the peak averages. */
  peak_seasons: number
}

/** `POST /api/players/compare/verdict`'s body (`QbVerdictRequest`). */
export interface QbVerdictPayload {
  a: number
  b: number
  sport: Sport
}

export interface QbVerdictPlayerOut {
  player_id: number
  display_name: string
  /** The last-name form the narration may use; `null` when ambiguous or one word. */
  short_name: string | null
  coverage: PlayerCoverageOut
  regular_season_record: StarterRecordOut | null
  postseason_record: StarterRecordOut | null
}

export interface QbVerdictEvidenceOut {
  sport: Sport
  /** Exactly `GET /api/players/compare`'s `qb_score` for this pair. */
  qb_score: PlayerQbScoreComparisonOut
  a: QbVerdictPlayerOut
  b: QbVerdictPlayerOut
  /** The first season the score can count (1999); `null` with no stat rows. */
  data_first_season: number | null
  regular_season_head_to_head: StarterRecordOut
  postseason_head_to_head: StarterRecordOut
}

/** A 200 is always narratable: on a Claude failure the API serves its own fallback text. */
export interface QbVerdictEnvelope {
  evidence: QbVerdictEvidenceOut
  narration: NarrationOut
}

export interface PlayerSearchRowOut {
  player_id: number
  display_name: string
  position: string | null
  /** As on a career. */
  group: PlayerPositionGroup | null
  first_season: number
  last_season: number
  coverage: PlayerCoverageOut
}

export interface PlayerSearchOut {
  sport: Sport
  /** The query as matched: stripped of surrounding whitespace. */
  query: string
  limit: number
  /** The request's `group` filter, echoed (#433); `null` = unfiltered. */
  group: PlayerPositionGroup | null
  rows: PlayerSearchRowOut[]
}

// ---------------------------------------------------------------------------
// catalog -- mirrors apps/api/src/api/models.py's `YearsOut`/`TeamsOut`
// (`/api/years`, `/api/teams`), the year/team picker's valid-selection
// universe (`QuestionForm`'s year suggestions and `TeamCombobox` fields).
// ---------------------------------------------------------------------------

export interface YearsOut {
  years: number[]
}

/**
 * Mirrors `apps/api`'s `TeamsOut`: `teams` is the canonical flat
 * submitted-value list and stays exactly as it was, while `team_details`
 * (epic #76 / issue #78) is a parallel array of the same names in the same
 * order plus display metadata. Both arrays come from one query on the API
 * side, so they cannot drift and may be zipped by index -- `QuestionForm`
 * feeds `team_details` to `TeamCombobox` and nothing reads the two together.
 */
export interface TeamsOut {
  teams: string[]
  team_details: TeamDetail[]
}

/**
 * One team's display/matching detail -- mirrors the per-team rows
 * `/api/teams` returns alongside `TeamsOut`'s flat name list (epic #76).
 * `name` is the canonical `teams.school` string and is the only thing a
 * picker ever submits: byte-identical, because the verdict lookup, the
 * persona grounding check, the golden dataset, and every cached narration
 * key are keyed on it. `mascot` is `null` for every NFL team (the canonical
 * name already contains city + nickname) and for a handful of CFB teams;
 * `aliases` holds deduped abbreviations/alternate spellings and may be empty.
 */
export interface TeamDetail {
  name: string
  mascot: string | null
  aliases: string[]
}

// ---------------------------------------------------------------------------
// sport -- mirrors the API's `Sport` Literal (re-exported by
// `apps/api/src/api/models.py` from the engine's `cfb_strength.contracts`),
// used on the catalog and verdict request models and on `unknown_team`.
// `QuestionForm`'s College/NFL toggle (issue #60) is the only producer of a
// non-default value today.
// ---------------------------------------------------------------------------

/**
 * The source list for `Sport`, for the runtime guard behind
 * `isVerdictErrorBody`, and for `QuestionForm`'s league radios (issue #143),
 * which all derive from it. The per-league copy is not derived from it but is
 * still checked: every `Record<Sport, string>` label map needs an entry per
 * league or tsc fails, and `QuestionForm.test.tsx` asserts one radio per entry,
 * in this order. Checked against the API's
 * published `apps/api/openapi-vocabularies.json` (`sport`, order included) by
 * `vocabularies.test.ts` (issue #112), so a league the API gains without
 * apps/web following it fails CI rather than silently degrading a mapped 404
 * into a generic error.
 */
export const SPORTS = ['cfb', 'nfl'] as const

export type Sport = (typeof SPORTS)[number]

// ---------------------------------------------------------------------------
// method -- mirrors the API's `Method` Literal (re-exported by
// `apps/api/src/api/models.py` from the engine's `cfb_strength.contracts`),
// echoed on `TeamCaseOut.method` and `ComparisonResultOut.method`.
// ---------------------------------------------------------------------------

/**
 * The source list for `Method` (epic #147 / issue #82). `formatRating` keys an
 * exhaustive `Record<Method, ...>` display-rule table on it, so a method added
 * here fails tsc until it picks a display scale. Checked against the API's
 * published `apps/api/openapi-vocabularies.json` (`method`, order included) by
 * `vocabularies.test.ts`, so a method the API gains without apps/web following
 * it fails CI rather than rendering at the wrong scale.
 */
export const METHODS = ['keener', 'elo', 'elo_career'] as const

export type Method = (typeof METHODS)[number]

/** True when `evidence` is a `TeamCaseOut` (champion/team-case routes) rather than a `ComparisonResultOut` (compare route). */
export function isTeamCaseEnvelope(
  envelope: VerdictEnvelope,
): envelope is TeamCaseEnvelope {
  return 'team_id' in envelope.evidence
}

// ---------------------------------------------------------------------------
// error bodies -- mirrors apps/api/src/api/errors.py's four mapped cases.
// ---------------------------------------------------------------------------

export interface UnknownYearErrorBody {
  error: 'unknown_year'
  year: number
  available_years: number[]
}

export interface AmbiguousTeamErrorBody {
  error: 'ambiguous_team'
  query: string
  candidates: string[]
}

/**
 * 404: the name resolved to no team with a rating for that exact
 * `year`/`sport` (issue #100). Split out of `ambiguous_team`, which used to
 * carry this case with an *empty* `candidates` array and therefore rendered
 * as "did you mean:" followed by nothing to pick.
 *
 * Deliberately carries **no** correction candidates. An earlier cut of this
 * body had a fuzzy-matched `suggestions` array; it was removed from the wire
 * because the engine's fuzzy stage already resolves or offers (as
 * `ambiguous_team`, one candidate allowed since #123) anything scoring >= 0.6,
 * so the only names that could ever reach this branch score below that -- and
 * at that range there is no cutoff separating signal from noise
 * ("Gonzaga"/"Georgia" scores 0.5714, above "Texas"/"Houston Texans" at
 * 0.5263). The pills would have offered real-but-irrelevant teams. This is a
 * pure not-found state: `query`, plus the `year` and `sport` scope that came
 * up empty, which is what `VerdictError`'s copy names.
 */
export interface UnknownTeamErrorBody {
  error: 'unknown_team'
  query: string
  year: number
  sport: Sport
}

export interface SameTeamComparisonErrorBody {
  error: 'same_team_comparison'
  team_name: string
}

export type VerdictErrorBody =
  | UnknownYearErrorBody
  | AmbiguousTeamErrorBody
  | UnknownTeamErrorBody
  | SameTeamComparisonErrorBody

/**
 * Discriminated union covering the four mapped HTTP error cases plus a
 * catch-all for network/unreachable-API failures -- shared by `VerdictError`
 * and `VerdictCard` so both render off the same shape.
 */
export type VerdictErrorState =
  | { kind: 'unknown_year'; body: UnknownYearErrorBody }
  | { kind: 'ambiguous_team'; body: AmbiguousTeamErrorBody }
  | { kind: 'unknown_team'; body: UnknownTeamErrorBody }
  | { kind: 'same_team_comparison'; body: SameTeamComparisonErrorBody }
  | { kind: 'network_error'; message: string }

/** The full set of states `VerdictCard` renders -- loading, success, or one of the five error cases above. */
export type VerdictCardState =
  | { status: 'loading' }
  | { status: 'success'; envelope: VerdictEnvelope }
  | { status: 'error'; error: VerdictErrorState }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null
}

/**
 * Whether `value` is one of `SPORTS`. Exported so every check of a league
 * that arrived from outside the app -- an API body, a share link's `sport`
 * param (issue #184) -- uses this one guard.
 */
export function isSport(value: unknown): value is Sport {
  // Widened to `readonly unknown[]` so `includes` accepts an unvalidated value.
  return (SPORTS as readonly unknown[]).includes(value)
}

/**
 * 404 from `GET /api/players/{player_id}` (issue #296): no player with that id
 * in that sport. Echoes what was asked, like `UnknownTeamErrorBody`.
 */
export interface UnknownPlayerErrorBody {
  error: 'unknown_player'
  player_id: number
  sport: Sport
}

export function isUnknownPlayerErrorBody(
  value: unknown,
): value is UnknownPlayerErrorBody {
  return (
    isRecord(value) &&
    value['error'] === 'unknown_player' &&
    typeof value['player_id'] === 'number' &&
    isSport(value['sport'])
  )
}

export function isPlayerPositionGroup(
  value: unknown,
): value is PlayerPositionGroup {
  // Widened to `readonly unknown[]` so `includes` accepts an unvalidated value.
  return (PLAYER_POSITION_GROUPS as readonly unknown[]).includes(value)
}

/**
 * 400 from `GET /api/players/compare` (issue #433, epic #372): the two
 * players aren't in one position group -- different groups, or either with
 * none. Both groups are echoed; `null` is "no group", never "unknown".
 * Founder decision (#372): the page refuses the pair, never shows it.
 */
export interface PlayersNotComparableErrorBody {
  error: 'players_not_comparable'
  a_group: PlayerPositionGroup | null
  b_group: PlayerPositionGroup | null
}

export function isPlayersNotComparableErrorBody(
  value: unknown,
): value is PlayersNotComparableErrorBody {
  const isGroupOrNull = (group: unknown) =>
    group === null || isPlayerPositionGroup(group)
  return (
    isRecord(value) &&
    value['error'] === 'players_not_comparable' &&
    isGroupOrNull(value['a_group']) &&
    isGroupOrNull(value['b_group'])
  )
}

export function isPlayerSeasonType(value: unknown): value is PlayerSeasonType {
  // Widened to `readonly unknown[]` so `includes` accepts an unvalidated value.
  return (PLAYER_SEASON_TYPES as readonly unknown[]).includes(value)
}

export function isPlayerLeaderSort(value: unknown): value is PlayerLeaderSort {
  return (PLAYER_LEADER_SORTS as readonly unknown[]).includes(value)
}

export function isPlayerLeaderCategory(
  value: unknown,
): value is PlayerLeaderCategory {
  return (PLAYER_LEADER_CATEGORIES as readonly unknown[]).includes(value)
}

/**
 * Whether `value` is one of `category`'s own sorts -- the only pairing the
 * API accepts (issue #312). A sort that belongs to another category is a 422,
 * so this is what a caller checks before sending one.
 */
export function isSortInCategory(
  category: PlayerLeaderCategory,
  value: unknown,
): value is PlayerLeaderSort {
  return (
    PLAYER_LEADER_SORTS_BY_CATEGORY[category] as readonly unknown[]
  ).includes(value)
}

/** The sort a category defaults to: its first, which the API echoes when none is sent. */
export function defaultSortFor(
  category: PlayerLeaderCategory,
): PlayerLeaderSort {
  return PLAYER_LEADER_SORTS_BY_CATEGORY[category][0]
}

export function isVerdictErrorBody(value: unknown): value is VerdictErrorBody {
  if (!isRecord(value) || typeof value['error'] !== 'string') {
    return false
  }
  switch (value['error']) {
    case 'unknown_year':
      return (
        typeof value['year'] === 'number' &&
        Array.isArray(value['available_years'])
      )
    case 'ambiguous_team':
      return (
        typeof value['query'] === 'string' && Array.isArray(value['candidates'])
      )
    case 'unknown_team':
      return (
        typeof value['query'] === 'string' &&
        typeof value['year'] === 'number' &&
        isSport(value['sport'])
      )
    case 'same_team_comparison':
      return typeof value['team_name'] === 'string'
    default:
      return false
  }
}
