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
  PlayerComparisonOut,
  PlayerHeadToHeadGameOut,
  PlayerHeadToHeadOut,
  PlayerLeaderRowOut,
  PlayerLeadersOut,
  PlayerSearchOut,
  PlayerSearchRowOut,
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

// ---------------------------------------------------------------------------
// Comparison and search (issue #301). Steve McNair's career, the Warner/McNair
// comparison and the search rows are copied from `apps/api` booted on the
// committed fixture db; the invented payloads say so.
// ---------------------------------------------------------------------------

const MCNAIR_1999_REGULAR: PlayerSeasonLineOut = {
  season: 1999,
  season_type: 'regular',
  teams: ['Tennessee Titans'],
  games: 11,
  record: { wins: 9, losses: 2, ties: 0, starts: 11 },
  stats: {
    completions: 187,
    attempts: 331,
    passing_yards: 2179,
    passing_tds: 12,
    passing_interceptions: 8,
    sacks_suffered: 16,
    sack_yards_lost: -74,
    carries: 72,
    rushing_yards: 337,
    rushing_tds: 8,
  },
  games_without_stat_lines: 0,
}

const MCNAIR_1999_POSTSEASON: PlayerSeasonLineOut = {
  season: 1999,
  season_type: 'postseason',
  teams: ['Tennessee Titans'],
  games: 4,
  record: { wins: 3, losses: 1, ties: 0, starts: 4 },
  stats: {
    completions: 62,
    attempts: 107,
    passing_yards: 514,
    passing_tds: 1,
    passing_interceptions: 2,
    sacks_suffered: 5,
    sack_yards_lost: -27,
    carries: 30,
    rushing_yards: 209,
    rushing_tds: 3,
  },
  games_without_stat_lines: 0,
}

/** `GET /api/players/2385180619?sport=nfl` on the committed fixture. */
export const STEVE_MCNAIR_CAREER: PlayerCareerOut = {
  sport: 'nfl',
  player_id: 2385180619,
  display_name: 'Steve McNair',
  position: 'QB',
  seasons: [MCNAIR_1999_REGULAR, MCNAIR_1999_POSTSEASON],
  regular_season: {
    season_type: 'regular',
    seasons: 1,
    games: 11,
    record: MCNAIR_1999_REGULAR.record,
    stats: MCNAIR_1999_REGULAR.stats,
  },
  postseason: {
    season_type: 'postseason',
    seasons: 1,
    games: 4,
    record: MCNAIR_1999_POSTSEASON.record,
    stats: MCNAIR_1999_POSTSEASON.stats,
  },
}

/** `GET /api/players/compare?a=2044124519&b=2385180619&sport=nfl` on the committed fixture. */
export const WARNER_VS_MCNAIR: PlayerComparisonOut = {
  sport: 'nfl',
  a: KURT_WARNER_CAREER,
  b: STEVE_MCNAIR_CAREER,
  regular_season_head_to_head: {
    season_type: 'regular',
    record: { wins: 0, losses: 1, ties: 0, starts: 1 },
    games: [
      {
        season: 1999,
        season_type: 'regular',
        week: 8,
        start_date: '1999-10-31',
        source_id: '1999_08_STL_TEN',
        a_team: 'St. Louis Rams',
        b_team: 'Tennessee Titans',
        a_points: 21,
        b_points: 24,
        a_stats: {
          completions: 29,
          attempts: 46,
          passing_yards: 328,
          passing_tds: 3,
          passing_interceptions: 0,
          sacks_suffered: 6,
          sack_yards_lost: -41,
          carries: 2,
          rushing_yards: 22,
          rushing_tds: 0,
        },
        b_stats: {
          completions: 13,
          attempts: 29,
          passing_yards: 186,
          passing_tds: 2,
          passing_interceptions: 0,
          sacks_suffered: 1,
          sack_yards_lost: -8,
          carries: 12,
          rushing_yards: 36,
          rushing_tds: 1,
        },
      },
    ],
  },
  postseason_head_to_head: {
    season_type: 'postseason',
    record: { wins: 1, losses: 0, ties: 0, starts: 1 },
    games: [
      {
        season: 1999,
        season_type: 'postseason',
        week: 21,
        start_date: '2000-01-30',
        source_id: '1999_21_STL_TEN',
        a_team: 'St. Louis Rams',
        b_team: 'Tennessee Titans',
        a_points: 23,
        b_points: 16,
        a_stats: {
          completions: 24,
          attempts: 45,
          passing_yards: 414,
          passing_tds: 2,
          passing_interceptions: 0,
          sacks_suffered: 2,
          sack_yards_lost: -7,
          carries: 1,
          rushing_yards: 1,
          rushing_tds: 0,
        },
        b_stats: {
          completions: 22,
          attempts: 36,
          passing_yards: 214,
          passing_tds: 0,
          passing_interceptions: 0,
          sacks_suffered: 1,
          sack_yards_lost: -6,
          carries: 8,
          rushing_yards: 64,
          rushing_tds: 0,
        },
      },
    ],
  },
}

/**
 * Two players who never started against each other, one of them with null
 * stats and no playoff games. Invented: the head-to-heads are the API's
 * never-met shape (0-0-0, no games).
 */
export const NEVER_MET_COMPARISON: PlayerComparisonOut = {
  sport: 'nfl',
  a: KURT_WARNER_CAREER,
  b: CAREER_WITH_NULL_STATS,
  regular_season_head_to_head: {
    season_type: 'regular',
    record: { wins: 0, losses: 0, ties: 0, starts: 0 },
    games: [],
  },
  postseason_head_to_head: {
    season_type: 'postseason',
    record: { wins: 0, losses: 0, ties: 0, starts: 0 },
    games: [],
  },
}

const WARNER_MCNAIR_WEEK_8 = WARNER_VS_MCNAIR.regular_season_head_to_head
  .games[0] as PlayerHeadToHeadGameOut

/**
 * A head-to-head the source only partly tracked: no stat line at all for one
 * starter, and a missing touchdown count for the other. Invented.
 */
export const HEAD_TO_HEAD_WITH_UNRECORDED_STATS: PlayerHeadToHeadOut = {
  season_type: 'regular',
  record: { wins: 1, losses: 0, ties: 1, starts: 2 },
  games: [
    {
      ...WARNER_MCNAIR_WEEK_8,
      week: null,
      a_points: 24,
      b_points: 21,
      a_stats: null,
    },
    {
      ...WARNER_MCNAIR_WEEK_8,
      season: 2000,
      week: null,
      start_date: null,
      source_id: null,
      a_points: 17,
      b_points: 17,
      b_stats: {
        ...(WARNER_MCNAIR_WEEK_8.b_stats as PlayerStatsOut),
        passing_tds: null,
      },
    },
  ],
}

const STEVE_MCNAIR_ROW: PlayerSearchRowOut = {
  player_id: 2385180619,
  display_name: 'Steve McNair',
  position: 'QB',
  first_season: 1999,
  last_season: 1999,
}

/** `GET /api/players/search?q=McNair&sport=nfl` on the committed fixture. */
export const SEARCH_MCNAIR: PlayerSearchOut = {
  sport: 'nfl',
  query: 'McNair',
  limit: 10,
  rows: [STEVE_MCNAIR_ROW],
}

/** `GET /api/players/search?q=mc&sport=nfl` on the committed fixture, in the API's order. */
export const SEARCH_MC: PlayerSearchOut = {
  sport: 'nfl',
  query: 'mc',
  limit: 10,
  rows: [
    STEVE_MCNAIR_ROW,
    {
      player_id: 2396327401,
      display_name: 'Mike Tomczak',
      position: 'QB',
      first_season: 1999,
      last_season: 1999,
    },
    {
      player_id: 2320243141,
      display_name: 'Cade McNown',
      position: 'QB',
      first_season: 1999,
      last_season: 1999,
    },
    {
      player_id: 2363866023,
      display_name: 'Donovan McNabb',
      position: 'QB',
      first_season: 1999,
      last_season: 1999,
    },
    {
      player_id: 2273944701,
      display_name: 'AJ McCarron',
      position: 'QB',
      first_season: 2023,
      last_season: 2023,
    },
    {
      player_id: 2014816368,
      display_name: 'Jerick McKinnon',
      position: 'RB',
      first_season: 2023,
      last_season: 2023,
    },
  ],
}
