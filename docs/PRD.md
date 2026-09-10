# PRD — My Team Is Better

**Domain:** my-team-is-better.lol
**Status:** Draft v1 — from founder interview, 2026-09-10
**One-liner:** Ask a college football question. Get a mathematically defensible
answer, delivered by a guy at the end of the bar who is absolutely certain your
team is better — because today, the numbers happen to agree with him.

---

## 1. Problem / opportunity

Sports debate is entertainment, not analysis — "who was the best team in 2005"
gets answered by vibes, recency bias, and whoever's loudest. `cfb-strength`
already solved the analysis half: a real recursive strength-of-schedule engine
(Keener's method) that computes defensible rankings from actual game results,
validated against undisputed national champions.

What it doesn't have is a front door. Nobody wants to run a CLI to win an
argument. **My Team Is Better** puts a face and a voice on the engine: you tell
it who you root for, ask it a question, and it answers *as your guy* — smug,
confident, backed by real data — instead of as a neutral report.

## 2. Target user

College football fans who argue about all-time teams and eras — the kind of
person who already has an opinion and wants ammunition, not a dashboard. Not
targeting: current-season score-checkers, betting/fantasy users, recruiting
followers. Launch audience is realistically friends, family, and the author's
professional network (portfolio/demo use), not a marketing push.

## 3. Core experience

1. User picks (or the app remembers via account) **their team**.
2. User asks one of a small set of supported question types (structured form,
   not free-text NLP — see §5).
3. The app computes the real answer deterministically, then a persona —
   loud, good-natured, certain, and rooting for the user's team — delivers it
   in character, with the receipts (record, quality wins, worst loss, common
   opponents) visible underneath so the take is checkable, not just vibes.

### The persona

Think: the regular at the end of the bar who has an opinion on every game,
is sure his fanhood is a heavier cross to bear than yours, and will absolutely
die on a hill for his team — but is fundamentally good-natured about it, not
mean-spirited. He roots *for whichever team the user roots for* in a given
session (see §5.1) rather than having a fixed rival.

- **Tone:** PG-13 rivalry trash talk. Confident, cocky, ribbing about rival
  fanbases and heartbreak losses. No slurs, no profanity, no punching at real
  people — safe to show your mother, sharp enough to sting a rival fan.
- **Naming:** the character doesn't have a name yet. Open item, non-blocking
  for MVP — the brand (My Team Is Better) doesn't require the persona to be
  named.

## 4. What "deterministic app, AI layer" means here

This is the load-bearing architectural decision and it's a product decision
too: **the ranking is never something the AI decides.** For MVP the algorithm
is Keener's method, unmodified, matching the golden-dataset validation already
proven in `cfb-strength-orchestrated` (2001 Miami, 2004 USC, 2005 Texas, 2013
FSU, 2019 LSU must all come out #1; margin-of-victory stays excluded, per the
regression this project already found and fixed once).

The AI layer's only job is **narration and personality** on top of numbers
that are already final by the time Claude sees them. Concretely:

- The persona **may** be as opinionated as it wants about eye-test stuff,
  rivalries, "how it felt to watch," and — for genuinely split-decision years
  like 2003 (BCS gave it to LSU, AP voters to USC) or 2017 (Alabama won the
  CFP without a division/conference title) — it can voice the human/poll-era
  argument in character.
- The persona **may not** override, hedge, or "well actually" its way around
  what the algorithm says is #1, or invent a stat, score, or record that isn't
  in the computed evidence.
- When the underlying case is one of those contested years, the UI/persona
  discloses that it's contested rather than presenting it as clean-cut.

### Future state: levers (explicitly out of scope for MVP)

The founder's own instinct, and the right call: **ship 100% stock Keener
first** for a resilient, validated proof of concept, then layer on
user-adjustable weighting as a v2 feature — e.g. "what if margin of victory
counted" or "defense wins championships" (weight points-allowed over points-
scored). This becomes a second, explicitly-labeled **experimental** rating
method alongside the validated default, never a replacement for it. See
Architecture Brief §6 for how the existing `RatingMethod` protocol already
anticipates this.

## 5. MVP scope

### 5.1 Supported question types (structured, not free-text)

The UI presents these as forms/pickers, not a chat box — this keeps the AI
layer's job to "narrate known facts," not "figure out what the user meant,"
which is the single biggest scope/risk cut for a days-not-weeks timeline.

| # | Question | Backing engine call |
|---|---|---|
| 1 | "Who was the best team in `<year>`?" | `get_champion(year)` |
| 2 | "Was `<team A>` better than `<team B>` in `<year>`?" | `compare_teams(year, team_a, team_b)` |
| 3 | "How good was `<team>` in `<year>`?" | `get_team_season(year, team)` |

`list_seasons` / `list_available_years` backs the year picker so users can
only select years that are actually ingested.

**Allegiance mirroring:** the user's saved/selected team is passed alongside
every question. The persona always argues in that team's favor when it
appears in the question (types 2 and 3 above); for type 1 (no specific team
named), it roots for the user's team's *conference* or era loosely, or simply
stays a loud neutral-ish hype man for the actual #1 — exact behavior is a
prompt-design detail, not a product blocker.

### 5.1a Push back on the take (bounded debate follow-up)

A real bar-stool argument doesn't stop at the first answer — "no way, what
was Ohio State's actual record in 2007? who'd they even play?" is exactly
the reaction this app should invite, not dodge. So every verdict card gets a
**"push back on this"** free-text box. This is deliberately *not* the same
thing as the open-ended chat ruled out in §5.5 — it's a bounded follow-up
exchange anchored to the verdict already on screen (same year, same team(s)),
not a general CFB chatbot:

- The persona answers using real data fetched live for that specific
  pushback (full game-by-game schedule, a specific opponent's score, etc.) —
  it isn't limited to only the facts shown in the original verdict, because
  the whole point is a user can drill into anything the engine actually
  knows. See Architecture Brief §4.6 for how tool-calling makes this
  possible without turning the whole app into an open-ended agent.
- Capped at a small number of follow-up turns per verdict (exact number is
  an implementation/cost-tuning detail, not a product requirement) — this
  is a bar-stool argument, not an unbounded chat session.
- No account required — guest or signed-in, pushback works the same way
  (PRD §5.3).

### 5.2 Data scope

Modern/BCS-CFP era: **1998–present**. Matches the era people actually argue
about, keeps the one-time ingestion job (and CFBD free-tier call budget)
small. Historical pre-1998 seasons are a plausible v2, not a launch blocker.

### 5.3 Accounts — guest-first, never a wall

Nobody is forced to sign in or hand over credentials to ask a question. Guest
mode is the default, first-class experience, not a degraded fallback:

- **Guest**: pick a team, ask questions, get answers — no sign-in prompt
  anywhere in that path. "Your team" persists locally (e.g. `localStorage`)
  so a guest doesn't have to re-pick it every visit, it just doesn't follow
  them to another device.
- **Optional account** (social/email — implementation detail, see
  Architecture Brief §5): offered as an upgrade ("sign in to save your team
  and history across devices"), never a gate in front of the core
  experience. Adds: favorite team synced across devices, history of past
  questions/answers tied to the account.

**Open decision, revisit before build**: this was originally scoped as
"accounts from day one." Architecture Brief §7 found that Render's free
Postgres expires 30 days after creation (deleted after a 14-day grace
period) — durable accounts therefore cost real money (~$6–7/mo) from the
day they're turned on, there's no free way to have them. Since guest mode
now covers the full core experience on its own, the recommendation is to
launch guest-only at $0/month and add paid Postgres + accounts once that
spend is worth it to the founder — but that's a real scope change from the
original "day one" answer, not something to assume silently. Confirm before
`apps/api` gets built.

No further profile/social features (no following other users, no public
leaderboards, no comments) for MVP.

### 5.4 Interaction model

The **initial verdict** is single-shot and stateless — one structured
question in, one cached answer out, no server-side memory (§5.1). The
**pushback follow-up** (§5.1a) is the one place this app has real
conversation: the backend still doesn't need a database session for it,
though — the client resends the verdict's fact block plus the running
follow-up exchange with each pushback, so the server stays logically
stateless per request even though the *conversation* has turns (the "case
facts block resent each turn" pattern, not server-side session state). A
guest never loses this mid-argument just because they didn't sign in.

### 5.5 Explicitly out of scope for MVP

- Open-ended CFB chat unanchored to a specific verdict (no "just chat with
  the bot about football" entry point — every conversation starts from a
  structured question; §5.1a's pushback is a bounded exception, not a
  general chat surface)
- Current/live season data, scores, recruiting, betting lines
- The "levers"/weighting feature (see §4 future state)
- Server-persisted, unbounded multi-turn memory — the pushback exchange
  (§5.1a) is scoped and client-carried, not a general session the backend
  remembers indefinitely
- Public sharing/social features, comments, leaderboards
- Mobile app (responsive web only)
- Monetization (ads, subscriptions) — hobby budget, cost-controlled infra
  instead (see Architecture Brief)

### 5.6 Attribution — a product requirement, not a footnote

This project stands entirely on two things it didn't invent: **Keener's
method** (J.P. Keener, *The Perron-Frobenius Theorem and the Ranking of
Football Teams*, SIAM Review 35(1), 1993) and **game data from
[CollegeFootballData.com](https://collegefootballdata.com)**. Crediting both
prominently is a founder value, not a legal-minimum afterthought:

- A visible "How this works / Credits" surface in the web app citing both,
  in plain language a non-technical visitor would actually read.
- The same attribution is baked into the engine's MCP server as a resource
  (`resource://cfb-strength/credits` — see Architecture Brief §4.5) so any
  agent that connects to it — not just this web app — sees the citation as
  part of the data, not just marketing copy on a page nobody visits.
- The persona itself can nod to "the math" being real, but the formal
  citation lives in the UI/resource, not buried only in in-character banter.

## 6. Non-functional requirements

- **Cost-controlled**: hobby budget. Architecture must avoid re-paying for
  the same Claude generation twice (identical question + team + method should
  be cache-served) and should default to the cheapest Claude model that can
  hold the persona voice, since the hard reasoning is already done
  deterministically before Claude is ever called. Pushback follow-ups
  (§5.1a) are the deliberate exception — they're not cacheable the same way
  since they're free-text — so the turn cap and tool-call cap in
  Architecture Brief §4.6 are the cost guardrail there instead of caching.
- **Portfolio-grade frontend**: React + Storybook is a stated goal in its own
  right (skill-building for the author's day job), not just a means to an
  end — component quality and Storybook coverage matter as much as feature
  velocity.
- **Demoable**: should hold up in a job-interview "let me show you something
  I built" context — correctness (the golden dataset must still pass),
  clarity of the "receipts" UI, and clean architecture all matter more than
  raw feature count.

## 7. Success criteria (portfolio project — no hard KPI)

- All five golden-dataset years still resolve correctly end-to-end through
  the web app (not just the CLI).
- A handful of real people (friends/family) use it unprompted and it produces
  at least one "okay that's actually funny" or "wait, that's a good point"
  reaction.
- The author can walk a technical interviewer through the deterministic/AI
  boundary as a deliberate architecture decision, not an accident.
- Ongoing hosting + API cost stays within a hobby budget (author-defined
  ceiling, not fixed here).

## 8. Open questions / risks

- **Persona name** — TBD, non-blocking.
- **Contested-year disclosure copy** — needs a few real drafted examples
  (2003, 2017) to see if "in character but honest about the controversy"
  actually reads well; may need prompt iteration.
- **CFBD free-tier budget** (1,000 calls/month) — one-time ingest of
  1998–present should fit easily since games are fetched per-season and
  cached to `data/raw/`, but re-ingesting for corrections/new seasons should
  be budgeted deliberately, not automated on a tight loop.
- ~~Render Postgres free-tier terms~~ — **resolved**: free Postgres expires
  30 days after creation and gets deleted, unacceptable for account data.
  MVP ships guest-only with no Postgres at all ($0/month); a paid instance
  (~$6–7/mo) gets added only when accounts are actually turned on. See
  Architecture Brief §7.
