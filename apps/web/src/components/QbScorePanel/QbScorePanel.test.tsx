import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { PlayerQbScoreComparisonOut } from '../../lib/api/types'
import {
  BRADY_VS_BARKLEY_QB_SCORE,
  BRADY_VS_MANNING_QB_SCORE,
  BRADY_VS_MANNING_VERDICT,
  QB_SCORE_TIE,
  WARNER_VS_MCNAIR_QB_SCORE,
} from '../../lib/qbScoreFixtures'
import { QbScorePanel } from './QbScorePanel'
import type { QbNarrationState } from './QbScorePanel'

const SUCCESS: QbNarrationState = {
  status: 'success',
  text: BRADY_VS_MANNING_VERDICT.narration.text,
}

function renderPanel(
  qbScore: PlayerQbScoreComparisonOut = BRADY_VS_MANNING_QB_SCORE,
  narration: QbNarrationState = SUCCESS,
  cutOff = { a: false, b: true },
) {
  return render(
    <QbScorePanel
      qbScore={qbScore}
      dataFirstSeason={1999}
      cutOff={cutOff}
      narration={narration}
    />,
  )
}

/** The score table's row for one measure: its two scores, then its edge. */
function measureCells(measure: 'Career' | 'Peak'): string[] {
  const table = screen.getByRole('table', { name: /QB score/ })
  const row = within(table)
    .getByRole('rowheader', { name: measure })
    .closest('tr')
  if (row === null) throw new Error(`no ${measure} row`)
  return within(row)
    .getAllByRole('cell')
    .map((cell) => cell.textContent)
}

describe('QbScorePanel (issue #459)', () => {
  it('is a labelled section headed "QB score"', () => {
    renderPanel()
    expect(screen.getByRole('region', { name: 'QB score' })).toBeInTheDocument()
  })

  it('splits Brady/Manning: Brady takes the career by 0.10, Manning the peak by 0.04', () => {
    renderPanel()

    const table = screen.getByRole('table', { name: /QB score/ })
    expect(
      within(table)
        .getAllByRole('columnheader')
        .map((header) => header.textContent),
    ).toEqual(['Measure', 'Tom Brady', 'Peyton Manning', 'Edge'])
    expect(measureCells('Career')).toEqual([
      '18.19',
      '18.09',
      'Tom Brady by 0.10',
    ])
    expect(measureCells('Peak')).toEqual([
      '1.73',
      '1.77',
      'Peyton Manning by 0.04',
    ])
  })

  it("names the API's winner even where its scores would say otherwise", () => {
    // Never recomputed on the client: the engine decides.
    renderPanel({ ...BRADY_VS_MANNING_QB_SCORE, career_winner: 'b' })
    expect(measureCells('Career')[2]).toBe('Peyton Manning by 0.10')
  })

  it('a sweep names one QB on both measures', () => {
    renderPanel(WARNER_VS_MCNAIR_QB_SCORE, SUCCESS, { a: true, b: true })
    expect(measureCells('Career')).toEqual([
      '2.25',
      '0.60',
      'Kurt Warner by 1.65',
    ])
    expect(measureCells('Peak')).toEqual([
      '0.45',
      '0.12',
      'Kurt Warner by 0.33',
    ])
  })

  it('an exact tie (null winner, non-null margin) reads "Dead even"', () => {
    renderPanel(QB_SCORE_TIE)
    expect(measureCells('Career')).toEqual(['18.19', '18.19', 'Dead even'])
    expect(measureCells('Peak')).toEqual(['1.73', '1.73', 'Dead even'])
  })

  it("inconclusive: no score, no winner, the founder's line in voice", () => {
    renderPanel(BRADY_VS_BARKLEY_QB_SCORE, SUCCESS, { a: false, b: false })

    expect(screen.queryByRole('table', { name: /QB score/ })).toBeNull()
    expect(
      screen.getByText(
        /Matt Barkley has no season in our books with 224 or more dropbacks.*The body of work isn't there — inconclusive\./,
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('18.19')).toBeNull()
  })

  it('states the 1999 floor every time, and louder for a career cut off by it', () => {
    const { unmount } = renderPanel(BRADY_VS_MANNING_QB_SCORE, SUCCESS, {
      a: false,
      b: false,
    })
    expect(
      screen.getByText('Counted since 1999, where the play-by-play starts.'),
    ).toBeInTheDocument()
    unmount()

    renderPanel()
    const loud = screen.getByText(
      /^Peyton Manning's career started before 1999/,
    )
    expect(loud.tagName).toBe('STRONG')
  })

  describe('the narration', () => {
    it('renders the text as sent, never parsed', () => {
      renderPanel()
      const take = screen.getByRole('region', { name: 'The take' })
      expect(take).toHaveTextContent(BRADY_VS_MANNING_VERDICT.narration.text)
    })

    it('shows the score while the narration loads', () => {
      renderPanel(BRADY_VS_MANNING_QB_SCORE, { status: 'loading' })
      const take = screen.getByRole('region', { name: 'The take' })
      expect(take).toHaveTextContent("Hang on, I'm reading the numbers…")
      expect(take).toHaveAttribute('aria-busy', 'true')
      expect(measureCells('Career')[2]).toBe('Tom Brady by 0.10')
    })

    it('a narration failure shows its copy and never hides the score', () => {
      const message =
        'Something broke in the back before I could say my piece. The numbers up there are the numbers.'
      renderPanel(BRADY_VS_MANNING_QB_SCORE, { status: 'error', message })
      expect(
        screen.getByRole('region', { name: 'The take' }),
      ).toHaveTextContent(message)
      expect(measureCells('Peak')[2]).toBe('Peyton Manning by 0.04')
    })

    it('is announced politely as it arrives', () => {
      renderPanel(BRADY_VS_MANNING_QB_SCORE, { status: 'loading' })
      expect(screen.getByRole('region', { name: 'The take' })).toHaveAttribute(
        'aria-live',
        'polite',
      )
    })
  })

  it('offers the explanation', () => {
    renderPanel()
    expect(
      screen.getByRole('button', { name: 'How the QB score works' }),
    ).toHaveAttribute('aria-expanded', 'false')
  })
})
