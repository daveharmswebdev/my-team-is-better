---
name: cycle
description: One full coordinator cycle with the founder's standing answers already given — orient, file every untracked gap through /triage without asking, then work the ready, unclaimed, non-colliding issues in parallel (one spoke worktree each) through /delegate and /ship. Use at session start or after /clear when the founder says "cycle", "the usual", or "keep going".
argument-hint: "[max-parallel, default 3]"
---

# Cycle

The founder ran this loop by hand for weeks, giving the same two answers every time:
"yes, triage the gaps" and "work the ready items in parallel, in separate worktrees".
Those answers are standing authorization. Don't ask them again; report what you did.

Arguments, if given: `$ARGUMENTS` (the most issues to work at once; default 3).

## 1. Orient

Run `/orient`. Its report is this cycle's state; don't re-derive it.

## 2. Triage the untracked gaps, without asking

Pass every item under **Untracked gaps** to `/triage` in one batch. Its dedupe, cluster
and volume rules still apply: "authorized to file" is not "must file". A gap that
`/triage` decides isn't worth an issue gets a sentence in the report instead. P0 and P1
stay the founder's call, so propose them; never pass `--founder-approved`.

## 3. Pick the batch

From **Open work, unclaimed** and **Suggested next**, take up to max-parallel issues in
this order: `founder` reports, then Product P0–P1, then P2, then the rest. Skip an issue
when any of these is true:

- it's claimed (`in-progress`), or its files collide with an in-flight branch;
- it's in `Needs founder`, or it needs a decision only the founder makes (a priority
  call, a product or voice judgment, anything CLAUDE.md's routing table keeps with the
  coordinator as a judgment rather than a scoped task);
- it touches a hot file another pick in this batch also touches. Two picks may share
  an owner only if their files don't overlap.

An epic isn't a pick; its next unblocked child can be. Nothing ready is a valid answer:
say why each candidate was skipped and stop.

## 4. Work the batch in parallel

1. Claim every pick first (`/delegate` step 2), so other sessions see them at once.
2. Prepare each brief (`/delegate` steps 3–5), then launch all the implementation
   spokes in **one message**, each with `isolation: "worktree"`. Briefs' `concurrency`
   fields name the other picks and their files.
3. As each returns, carry it on its own: validate, re-run gates, reviewer + validator,
   next round or `/ship`. One pick failing or needing the founder doesn't hold the
   others; park it with a comment on its issue and keep going.
4. Ship one at a time. After each merge, the next pick merges `main` before its CI
   run, so the batch never races itself.

Inline work (a typo, a one-line fix) still skips delegation, per the routing table.

## 5. Report (under 30 lines)

```
## Cycle — <date>
**Filed:** #n (Kind, Priority) … | none   **Not filed:** <gap — reason>
**Shipped:** #n → PR #p (deploy verified: api/web)
**Parked:** #n — <why, and what the founder needs to decide>
**Skipped:** #n — <reason>
**Needs founder:** <P0/P1 proposals, decisions> | none
```

Then stop. Don't start a second cycle unless the founder asked for a loop
(`/loop /cycle`).
