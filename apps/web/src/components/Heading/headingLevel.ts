/** An HTML heading level: `h1` to `h6`. */
export type HeadingLevel = 1 | 2 | 3 | 4 | 5 | 6

/** The level for a heading nested one step under `level`; HTML stops at h6. */
export function nextHeadingLevel(level: HeadingLevel): HeadingLevel {
  return level === 6 ? 6 : ((level + 1) as HeadingLevel)
}
