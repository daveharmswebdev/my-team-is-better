import styles from './Pager.module.css'

export interface PagerProps {
  /** Names the navigation landmark. */
  label: string
  /** The API's `offset` for the page on screen. */
  offset: number
  /** The API's `limit`. */
  limit: number
  /** How many rows the API sent for this page. */
  shown: number
  /** The API's `total`. */
  total: number
  /** Asks for the page starting at this offset. */
  onPage: (offset: number) => void
}

function count(value: number): string {
  return value.toLocaleString('en-US')
}

/**
 * Previous / next paging over an API-paged list (issue #296), with an "x–y of
 * total" range. It only moves `offset` by `limit`; the API does the paging.
 * An unavailable button is `aria-disabled` rather than `disabled`, so it keeps
 * focus when a keyboard user reaches the last page.
 */
export function Pager({
  label,
  offset,
  limit,
  shown,
  total,
  onPage,
}: PagerProps) {
  const hasPrevious = offset > 0
  const hasNext = offset + shown < total
  const range =
    shown === 0
      ? `0 of ${count(total)}`
      : `${count(offset + 1)}–${count(offset + shown)} of ${count(total)}`

  return (
    <nav className={styles.pager} aria-label={label}>
      <button
        type="button"
        className={styles.button}
        aria-disabled={!hasPrevious}
        onClick={() => {
          if (hasPrevious) {
            onPage(Math.max(0, offset - limit))
          }
        }}
      >
        Previous page
      </button>
      <p className={styles.range}>{range}</p>
      <button
        type="button"
        className={styles.button}
        aria-disabled={!hasNext}
        onClick={() => {
          if (hasNext) {
            onPage(offset + limit)
          }
        }}
      >
        Next page
      </button>
    </nav>
  )
}
