import type { HTMLAttributes } from 'react'
import type { HeadingLevel } from './headingLevel'

export interface HeadingProps extends HTMLAttributes<HTMLHeadingElement> {
  /** Which `h1`-`h6` to render. Set by where the heading sits in the page's outline. */
  level: HeadingLevel
}

/**
 * A heading whose level is chosen by its caller (issue #219), so a
 * component that is composed into different places can keep the page's
 * outline unbroken -- axe's heading-order rule fails a level that jumps by
 * more than one. Its look comes from `className`, never from the tag:
 * changing `level` must not change how it looks.
 */
export function Heading({ level, ...props }: HeadingProps) {
  const Tag = `h${level}` as const
  return <Tag {...props} />
}
