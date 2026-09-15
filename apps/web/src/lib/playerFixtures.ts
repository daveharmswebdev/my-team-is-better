/**
 * Player read-layer payloads (issue #296) for component tests and stories.
 * The named rows and Kurt Warner's career are copied from real responses of
 * `apps/api` booted on the committed fixture db
 * (`apps/api/tests/fixtures/cfb_verdict_fixture.sqlite3`, NFL 1999 + 2023),
 * so they carry the same numbers the e2e specs assert on. That fixture has no
 * null stats, so the null-stat helpers below are the only source of them.
 *
 * Not imported by any app code: only tests and stories use it.
 */
import type {
  CreditsDataSourceOut,
  PlayerCareerOut,
  PlayerLeaderRowOut,
  PlayerLeadersOut,
  PlayerSeasonLineOut,
  PlayerStatsOut,
} from './api/types'

export const TUA_TAGOVAILOA: PlayerLeaderRowOut = {
  rank: 1,
  player_id: 2186969283,
  display_name: 'Tua Tagovailoa',
  position: 'QB',
  first_season: 2023,
  last_season: 2023,
  games: 17,
  record: { wins: 11, losses: 6, ties: 0, starts: 17 },
  stats: {
    completions: 388,
    attempts: 560,
    passing_yards: 4624,
    passing_tds: 29,
    passing_interceptions: 14,
    sacks_suffered: 29,
    sack_yards_lost: -171,
    carries: 35,
    rushing_yards: 74,
    rushing_tds: 0,
  },
}

export const JARED_GOFF: PlayerLeaderRowOut = {
  rank: 2,
  player_id: 2454577150,
  display_name: 'Jared Goff',
  position: 'QB',
  first_season: 2023,
  last_season: 2023,
  games: 17,
  record: { wins: 12, losses: 5, ties: 0, starts: 17 },
  stats: {
    completions: 407,
    attempts: 605,
    passing_yards: 4575,
    passing_tds: 30,
    passing_interceptions: 12,
    sacks_suffered: 30,
    sack_yards_lost: -197,
    carries: 32,
    rushing_yards: 21,
    rushing_tds: 2,
  },
}

export const DAK_PRESCOTT: PlayerLeaderRowOut = {
  rank: 3,
  player_id: 2430128896,
  display_name: 'Dak Prescott',
  position: 'QB',
  first_season: 2023,
  last_season: 2023,
  games: 17,
  record: { wins: 12, losses: 5, ties: 0, starts: 17 },
  stats: {
    completions: 410,
    attempts: 590,
    passing_yards: 4516,
    passing_tds: 36,
    passing_interceptions: 9,
    sacks_suffered: 39,
    sack_yards_lost: -255,
    carries: 55,
    rushing_yards: 242,
    rushing_tds: 2,
  },
}

export const STEVE_BEUERLEIN: PlayerLeaderRowOut = {
  rank: 4,
  player_id: 2181942775,
  display_name: 'Steve Beuerlein',
  position: 'QB',
  first_season: 1999,
  last_season: 1999,
  games: 16,
  record: { wins: 8, losses: 8, ties: 0, starts: 16 },
  stats: {
    completions: 343,
    attempts: 569,
    passing_yards: 4436,
    passing_tds: 36,
    passing_interceptions: 15,
    sacks_suffered: 50,
    sack_yards_lost: -280,
    carries: 27,
    rushing_yards: 124,
    rushing_tds: 2,
  },
}

export const KURT_WARNER_REGULAR: PlayerLeaderRowOut = {
  rank: 1,
  player_id: 2044124519,
  display_name: 'Kurt Warner',
  position: 'QB',
  first_season: 1999,
  last_season: 1999,
  games: 15,
  record: { wins: 13, losses: 3, ties: 0, starts: 16 },
  stats: {
    completions: 297,
    attempts: 455,
    passing_yards: 4044,
    passing_tds: 38,
    passing_interceptions: 11,
    sacks_suffered: 26,
    sack_yards_lost: -176,
    carries: 22,
    rushing_yards: 93,
    rushing_tds: 1,
  },
}

export const JORDAN_LOVE: PlayerLeaderRowOut = {
  rank: 4,
  player_id: 2058453876,
  display_name: 'Jordan Love',
  position: 'QB',
  first_season: 2023,
  last_season: 2023,
  games: 17,
  record: { wins: 9, losses: 8, ties: 0, starts: 17 },
  stats: {
    completions: 372,
    attempts: 579,
    passing_yards: 4159,
    passing_tds: 32,
    passing_interceptions: 11,
    sacks_suffered: 30,
    sack_yards_lost: -242,
    carries: 50,
    rushing_yards: 247,
    rushing_tds: 4,
  },
}

/** `?sort=passing_yards`, regular season: the first four of 204. */
export const LEADERS_BY_YARDS: PlayerLeadersOut = {
  sport: 'nfl',
  season_type: 'regular',
  sort: 'passing_yards',
  limit: 50,
  offset: 0,
  total: 204,
  rows: [TUA_TAGOVAILOA, JARED_GOFF, DAK_PRESCOTT, STEVE_BEUERLEIN],
}

/** `?sort=passing_tds`, regular season: a real tie at rank 2. */
export const LEADERS_BY_TDS: PlayerLeadersOut = {
  sport: 'nfl',
  season_type: 'regular',
  sort: 'passing_tds',
  limit: 50,
  offset: 0,
  total: 204,
  rows: [
    KURT_WARNER_REGULAR,
    { ...DAK_PRESCOTT, rank: 2 },
    { ...STEVE_BEUERLEIN, rank: 2 },
    JORDAN_LOVE,
  ],
}

/** Every stat `null`: the source tracked none of them. */
export const UNRECORDED_STATS: PlayerStatsOut = {
  completions: null,
  attempts: null,
  passing_yards: null,
  passing_tds: null,
  passing_interceptions: null,
  sacks_suffered: null,
  sack_yards_lost: null,
  carries: null,
  rushing_yards: null,
  rushing_tds: null,
}

/**
 * A leaderboard with rows the source only partly tracked: one row missing its
 * touchdowns and completions, and one missing everything (so it has no rank).
 * Invented, since the committed fixture has no null stats.
 */
export const LEADERS_WITH_NULL_STATS: PlayerLeadersOut = {
  sport: 'nfl',
  season_type: 'regular',
  sort: 'passing_yards',
  limit: 50,
  offset: 0,
  total: 3,
  rows: [
    TUA_TAGOVAILOA,
    {
      ...JARED_GOFF,
      stats: { ...JARED_GOFF.stats, passing_tds: null, completions: null },
    },
    {
      rank: null,
      player_id: 1001,
      display_name: 'Unrecorded Player',
      position: null,
      first_season: 1999,
      last_season: 1999,
      games: null,
      record: { wins: 0, losses: 0, ties: 0, starts: 0 },
      stats: UNRECORDED_STATS,
    },
  ],
}

export const WARNER_1999_REGULAR: PlayerSeasonLineOut = {
  season: 1999,
  season_type: 'regular',
  teams: ['St. Louis Rams'],
  games: 15,
  record: { wins: 13, losses: 3, ties: 0, starts: 16 },
  stats: {
    completions: 297,
    attempts: 455,
    passing_yards: 4044,
    passing_tds: 38,
    passing_interceptions: 11,
    sacks_suffered: 26,
    sack_yards_lost: -176,
    carries: 22,
    rushing_yards: 93,
    rushing_tds: 1,
  },
  games_without_stat_lines: 1,
}

export const WARNER_1999_POSTSEASON: PlayerSeasonLineOut = {
  season: 1999,
  season_type: 'postseason',
  teams: ['St. Louis Rams'],
  games: 3,
  record: { wins: 3, losses: 0, ties: 0, starts: 3 },
  stats: {
    completions: 77,
    attempts: 121,
    passing_yards: 1063,
    passing_tds: 8,
    passing_interceptions: 4,
    sacks_suffered: 4,
    sack_yards_lost: -24,
    carries: 6,
    rushing_yards: 3,
    rushing_tds: 0,
  },
  games_without_stat_lines: 0,
}

/** `GET /api/players/2044124519?sport=nfl` on the committed fixture. */
export const KURT_WARNER_CAREER: PlayerCareerOut = {
  sport: 'nfl',
  player_id: 2044124519,
  display_name: 'Kurt Warner',
  position: 'QB',
  seasons: [WARNER_1999_REGULAR, WARNER_1999_POSTSEASON],
  regular_season: {
    season_type: 'regular',
    seasons: 1,
    games: 15,
    record: WARNER_1999_REGULAR.record,
    stats: WARNER_1999_REGULAR.stats,
  },
  postseason: {
    season_type: 'postseason',
    seasons: 1,
    games: 3,
    record: WARNER_1999_POSTSEASON.record,
    stats: WARNER_1999_POSTSEASON.stats,
  },
}

/**
 * A career the source only partly tracked, with no playoff games at all.
 * Invented, since the committed fixture has no null stats.
 */
export const CAREER_WITH_NULL_STATS: PlayerCareerOut = {
  sport: 'nfl',
  player_id: 1001,
  display_name: 'Unrecorded Player',
  position: null,
  seasons: [
    {
      season: 1999,
      season_type: 'regular',
      teams: ['Cleveland Browns'],
      games: null,
      record: { wins: 2, losses: 5, ties: 0, starts: 7 },
      stats: { ...UNRECORDED_STATS, passing_yards: 1210 },
      games_without_stat_lines: 0,
    },
  ],
  regular_season: {
    season_type: 'regular',
    seasons: 1,
    games: null,
    record: { wins: 2, losses: 5, ties: 0, starts: 7 },
    stats: { ...UNRECORDED_STATS, passing_yards: 1210 },
  },
  postseason: null,
}

/** `GET /api/credits` `data_sources` on the committed fixture, in the API's order. */
export const DATA_SOURCES: CreditsDataSourceOut[] = [
  {
    id: 'cfbd',
    name: 'CollegeFootballData.com (CFBD)',
    url: 'https://collegefootballdata.com',
    note: 'All game results are ingested from the CFBD API. This project performs no independent data collection and claims no ownership of the underlying game data.',
  },
  {
    id: 'nflverse_games',
    name: "nflverse (Lee Sharpe's NFL schedule/game data)",
    url: 'https://github.com/nflverse/nflverse-data',
    note: "NFL game results are ingested from nflverse's static CSV release assets (the schedule data was originally compiled and maintained by Lee Sharpe before nflverse took over publishing it). This project performs no independent data collection and claims no ownership of the underlying game data.",
  },
  {
    id: 'nflverse_player_stats',
    name: 'nflverse player stats (nflfastR, by Sebastian Carl and Ben Baldwin)',
    url: 'https://github.com/nflverse/nflfastR',
    note: "NFL player stats are ingested from nflverse's stats_player release (the weekly stats_player_week CSV files, 1999-2025), which nflverse creates with nflfastR's calculate_stats(). nflfastR is written by Sebastian Carl and Ben Baldwin, with contributions from Lee Sharpe, Maksim Horowitz, Ron Yurko, Samuel Ventura, Tan Ho and John Edwards, and is MIT licensed. Player identities come from nflverse's players release (players.csv). This project performs no independent data collection and claims no ownership of the underlying player data.",
  },
]
