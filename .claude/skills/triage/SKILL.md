---
name: triage
description: Turn pre-existing findings from spoke, reviewer or validator returns (or an untracked gap) into GitHub issues without flooding the tracker — dedupe against open and closed issues, attach recurring symptoms to a design-flaw cluster or epic, require labels, and batch once per round.
argument-hint: "[findings.json or description]"
---

# Triage findings

Input: `$ARGUMENTS`. Usually the `pre-existing` findings from this round's returns.
`blocking` findings are not issues: they go to the next round, unless the round cap was
hit. Skip `nit`s unless one is cheap and obviously worth tracking.

Filing is outward-facing and other sessions read the tracker, so do the whole round in
one pass and report what you did.

## For each finding

1. **Already tracked?** If `tracked_issue` is set, open it and confirm it's the same
   defect. Comment only if the finding adds real evidence (a new failing input, a
   file:line); otherwise just record the link.
2. **Search before filing**, in both states, by symptom and by file:
   ```bash
   gh issue list --state all --limit 20 --search "<2-4 distinctive words> in:title,body"
   gh issue list --state all --limit 20 --search "<file path or function name>"
   ```
   A closed issue with the same symptom is a regression: reopen-worthy evidence, not a
   fresh issue. Reference the old number.
3. **Cluster check.** If three or more open issues share a root cause (same module, same
   `category`, each fix adding one more exception or allow-list entry), don't file a
   fourth symptom. Comment on the cluster's epic, or propose one that names the design
   flaw rather than the symptoms (e.g. "persona grounding matches numbers in free text
   after the fact"), and link the members.
4. **File a new issue** only when 1–3 found nothing:
   - **Title:** the concrete failure, input → wrong output (e.g. "A year too large for
     SQLite makes /api/verdict/champion return 500 instead of unknown_year").
   - **Body:** evidence (command and output, or the failing input), file:line, how it was
     found (issue, round, agent), why it isn't blocking this round, and a suggested fix
     if it's obvious.
   - **Labels, never none:** one of `bug`, `enhancement`, `documentation`,
     `accessibility`, plus the area label (`area:api`, `area:web`, `area:engine`). Add
     `epic` only to an umbrella issue.
   - Never add `in-progress` (that's a claim) or a milestone.

## Report

| Finding (category — summary) | Result |
|---|---|
| … | #n new / #n existing (commented or linked) / cluster #epic |
