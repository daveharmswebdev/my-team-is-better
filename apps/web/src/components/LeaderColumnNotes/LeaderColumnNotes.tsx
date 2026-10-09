import type { PlayerLeaderCategory } from '../../lib/api/types'
import {
  LEADER_COLUMN_NOTES,
  leaderColumnNoteId,
  leaderColumnNotes,
} from '../../lib/playerStats'
import styles from './LeaderColumnNotes.module.css'

export interface LeaderColumnNotesProps {
  /** The board on screen: its columns decide which notes show (`leaderColumnNotes`). */
  category: PlayerLeaderCategory
  /** The prefix the table's headers build each note's id from (`leaderColumnNoteId`). */
  idPrefix: string
}

/**
 * The founder's column notes (#316) for the board on screen (issue #317),
 * one paragraph each, for the page's "About these numbers" box. Each leads
 * with the marker its headers carry, hidden from assistive tech, which hears
 * the note on the headers instead: the note's text carries the id the
 * table's `aria-describedby` points at. Renders nothing on a board whose
 * columns need no note.
 */
export function LeaderColumnNotes({
  category,
  idPrefix,
}: LeaderColumnNotesProps) {
  return (
    <>
      {leaderColumnNotes(category).map((note) => (
        <p key={note}>
          <span className={styles.marker} aria-hidden="true">
            {LEADER_COLUMN_NOTES[note].marker}
          </span>{' '}
          <span id={leaderColumnNoteId(idPrefix, note)}>
            {LEADER_COLUMN_NOTES[note].text}
          </span>
        </p>
      ))}
    </>
  )
}
