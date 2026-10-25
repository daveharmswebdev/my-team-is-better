import type { Meta, StoryObj } from '@storybook/react-vite'
import { expect, userEvent, within } from 'storybook/test'
import {
  BRADY_VS_BARKLEY_QB_SCORE,
  BRADY_VS_MANNING_QB_SCORE,
  BRADY_VS_MANNING_VERDICT,
  QB_SCORE_TIE,
  WARNER_VS_CUNNINGHAM_VERDICT,
  WARNER_VS_MCNAIR_QB_SCORE,
  WARNER_VS_MCNAIR_VERDICT,
} from '../../lib/qbScoreFixtures'
import { qbNarrationErrorCopy } from '../../lib/qbScore'
import { VerdictNetworkError } from '../../lib/api/client'
import { QbScorePanel } from './QbScorePanel'

/**
 * The QB score panel (issue #459). Every payload is a real API response
 * (`qbScoreFixtures`): production for Brady, Manning and Barkley, the
 * committed fixture db for Warner and McNair. The tie is the one invented
 * shape.
 */
const meta = {
  title: 'components/QbScorePanel',
  component: QbScorePanel,
  tags: ['autodocs'],
  args: {
    qbScore: BRADY_VS_MANNING_QB_SCORE,
    dataFirstSeason: 1999,
    // Manning's career began in 1998, before the data.
    cutOff: { a: false, b: true },
    narration: {
      status: 'success',
      text: BRADY_VS_MANNING_VERDICT.narration.text,
    },
  },
} satisfies Meta<typeof QbScorePanel>

export default meta

type Story = StoryObj<typeof meta>

/** Brady takes the career by 0.10, Manning the peak by 0.04. */
export const SplitVerdict: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const table = canvas.getByRole('table', { name: /QB score/ })
    await expect(table).toHaveTextContent('Tom Brady by 0.10')
    await expect(table).toHaveTextContent('Peyton Manning by 0.04')
  },
}

/** One QB takes both: Warner over McNair on the fixture db. */
export const OneQbSweeps: Story = {
  args: {
    qbScore: WARNER_VS_MCNAIR_QB_SCORE,
    cutOff: { a: true, b: true },
    narration: {
      status: 'success',
      text: WARNER_VS_MCNAIR_VERDICT.narration.text,
    },
  },
}

/**
 * Randall Cunningham's 1999 is 214 dropbacks, under the rule: no score, in
 * voice (fixture db, with its stub-narrator fallback text).
 */
export const Inconclusive: Story = {
  args: {
    qbScore: WARNER_VS_CUNNINGHAM_VERDICT.evidence.qb_score,
    cutOff: { a: true, b: true },
    narration: {
      status: 'success',
      text: WARNER_VS_CUNNINGHAM_VERDICT.narration.text,
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    await expect(canvas.queryByRole('table', { name: /QB score/ })).toBeNull()
    await expect(
      canvas.getByText(/The body of work isn't there — inconclusive\.$/),
    ).toBeVisible()
  },
}

/** Production's inconclusive pair: Matt Barkley, narration still loading. */
export const InconclusiveLoading: Story = {
  args: {
    qbScore: BRADY_VS_BARKLEY_QB_SCORE,
    cutOff: { a: false, b: false },
    narration: { status: 'loading' },
  },
}

/** Invented: an exact tie, a null winner beside a zero margin. */
export const Tie: Story = {
  args: { qbScore: QB_SCORE_TIE },
}

/** The score is up while the narration is still on its way. */
export const NarrationLoading: Story = {
  args: { narration: { status: 'loading' } },
}

/** The narration failed: the narrator says so, and the score stays. */
export const NarrationError: Story = {
  args: {
    narration: {
      status: 'error',
      message: qbNarrationErrorCopy(new VerdictNetworkError('')),
    },
  },
}

/** The explanation opened from the keyboard. */
export const ExplanationOpen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement)
    const toggle = canvas.getByRole('button', {
      name: 'How the QB score works',
    })
    toggle.focus()
    await userEvent.keyboard('{Enter}')
    await expect(toggle).toHaveAttribute('aria-expanded', 'true')
    await expect(
      canvas.getByRole('region', { name: 'How the QB score works' }),
    ).toHaveTextContent('0.826')
  },
}
