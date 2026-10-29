## Why
`docs/PRD.md` §5.4 still said per-verdict link previews (#185) "are deferred", but they shipped in #471–#473. It's a one-line coordinator fix, so it isn't filed as an issue.

## What changed
- PRD §5.4: #186 (exact-copy links) stays deferred. #185 is now described as shipped.

## Verification
- Docs-only. CI's `claude-process` job covers conflict markers.

## Delegation record
contract_gaps: none
brief_defects: none
Findings filed: none (coordinator inline)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
