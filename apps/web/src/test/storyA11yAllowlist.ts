/**
 * The only way a story may escape the Storybook a11y gate (issue #90).
 *
 * Maps a Storybook story id (e.g. `components-teamcombobox--default`) to the
 * justification for exempting it from `storyA11yPolicy.test.ts`. An
 * allowlisted story may opt out of axe in any way the policy test otherwise
 * forbids, so each entry must name a genuine story-harness artifact, not a
 * component defect -- a real defect gets a GitHub issue and a fix instead.
 *
 * Kept empty on purpose. The policy test fails on a blank justification and on
 * an entry naming a story that no longer exists, so this list can't quietly
 * grow stale.
 */
export const STORY_A11Y_ALLOWLIST: Readonly<Record<string, string>> = {}
