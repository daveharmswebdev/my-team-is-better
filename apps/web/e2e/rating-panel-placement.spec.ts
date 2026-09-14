import { test, expect } from '@playwright/test'
import type { Locator, Page } from '@playwright/test'
import { fillYear } from './fillYear.ts'

// Issue #183: a rating's show-your-work panel has to be readable wherever the
// rating sits on screen, not only near the top. The trigger is scrolled to
// three heights (near the top, mid-way, near the bottom), hovered, and the
// open panel is measured in the real app against the real API and fixture db.
//
// Since issue #198 the verdict opens in a modal that covers the viewport and
// scrolls itself, while the page behind it can't scroll. So this spec
// scrolls the modal, and it counts rating panels inside the verdict: the
// modal is a dialog too.
//
// 1280x800 is the bar the founder's check used. 1280x720 is a common laptop
// height where the popover's default height (80% of the viewport) is too
// short for four games, so it is what proves the four-game minimum holds.
//
// This project's e2e files compile without the DOM lib, so the few in-page
// measurements are sent as script text rather than typed callbacks.

interface Viewport {
  width: number
  height: number
}

const LAYOUTS: ReadonlyArray<{
  viewport: Viewport
  triggerTops: readonly number[]
}> = [
  { viewport: { width: 1280, height: 800 }, triggerTops: [80, 400, 700] },
  { viewport: { width: 1280, height: 720 }, triggerTops: [80, 360, 630] },
]

/** Texas 2005: 13 games in the fixture's Elo ledger. */
const GAMES_2005 = 13
/** The fewest complete game rows the Elo ledger must show at once. */
const MIN_VISIBLE_ROWS = 4

/** The open verdict modal, in page script. */
const OPEN_MODAL = "document.querySelector('dialog[open]')"

interface Box {
  top: number
  bottom: number
  left: number
  right: number
}

interface LedgerLayout {
  dialog: Box
  dialogScrolls: boolean
  rule: Box
  footer: Box
  listView: Box
  listOverflowY: string
  listClientHeight: number
  listScrollHeight: number
  wholeRowsInView: number
}

function viewportBox({ width, height }: Viewport): Box {
  return { top: 0, left: 0, bottom: height, right: width }
}

/** The verdict card, inside the verdict modal. */
function verdictIn(page: Page): Locator {
  return page.getByRole('dialog', { name: 'The verdict' }).getByRole('article')
}

async function askForThe2005Champion(
  page: Page,
  engine: 'keener' | 'elo',
): Promise<Locator> {
  await page.goto('/')
  if (engine === 'elo') {
    await page
      .getByRole('group', { name: 'Engine' })
      .getByRole('radio', { name: 'Elo (second opinion)' })
      .check()
  }
  await page
    .getByLabel('What do you want to know?')
    .selectOption({ label: 'Who was the best team in a year?' })
  await fillYear(page, '2005')
  await page.getByRole('button', { name: 'Get the verdict' }).click()
  const verdict = verdictIn(page)
  await expect(verdict).toBeVisible()
  return verdict
    .getByRole('region', { name: 'Texas evidence' })
    .locator('[aria-haspopup="dialog"]')
}

async function boxOf(locator: Locator): Promise<Box> {
  const box = await locator.boundingBox()
  if (box === null) {
    throw new Error('element has no box')
  }
  return {
    top: box.y,
    bottom: box.y + box.height,
    left: box.x,
    right: box.x + box.width,
  }
}

function inside(inner: Box, outer: Box): boolean {
  return (
    inner.top >= outer.top - 0.5 &&
    inner.bottom <= outer.bottom + 0.5 &&
    inner.left >= outer.left - 0.5 &&
    inner.right <= outer.right + 0.5
  )
}

/**
 * Scrolls the verdict modal so the trigger's top edge sits `top` px below the
 * viewport's top. Spacers on the modal's panel, outside the app's own layout,
 * give it room to scroll that far either way.
 */
async function placeTriggerAt(
  page: Page,
  viewport: Viewport,
  trigger: Locator,
  top: number,
) {
  await page.addStyleTag({
    content: `dialog[open] > * { padding-bottom: ${viewport.height * 2}px; }`,
  })
  const scrolledTop =
    (await boxOf(trigger)).top +
    (await page.evaluate<number>(`${OPEN_MODAL}.scrollTop`))
  if (scrolledTop < top) {
    await page.addStyleTag({
      content: `dialog[open] > * { padding-top: ${top - scrolledTop}px; }`,
    })
  }
  const current = (await boxOf(trigger)).top
  await page.evaluate(
    `${OPEN_MODAL}.scrollBy({ top: ${current - top}, behavior: 'instant' })`,
  )
  expect(Math.abs((await boxOf(trigger)).top - top)).toBeLessThanOrEqual(2)
}

/**
 * Moves the pointer from the trigger's centre, in small steps, to the nearest
 * point of the dialog's visible panel, then on into the panel's middle, and
 * checks the dialog stayed open the whole way. A panel taller than its
 * scrolling dialog is only visible inside the dialog's box, so the target is
 * clipped to it.
 */
async function travelIntoDialog(page: Page, trigger: Locator, dialog: Locator) {
  const from = await boxOf(trigger)
  const frame = await boxOf(dialog)
  const content = await boxOf(dialog.locator(':scope > *').first())
  const panel: Box = {
    top: Math.max(content.top, frame.top),
    bottom: Math.min(content.bottom, frame.bottom),
    left: Math.max(content.left, frame.left),
    right: Math.min(content.right, frame.right),
  }
  const inset = 10
  const clamp = (value: number, low: number, high: number) =>
    Math.min(Math.max(value, low), high)
  const start = {
    x: (from.left + from.right) / 2,
    y: (from.top + from.bottom) / 2,
  }
  await page.mouse.move(start.x, start.y)
  await page.mouse.move(
    clamp(start.x, panel.left + inset, panel.right - inset),
    clamp(start.y, panel.top + inset, panel.bottom - inset),
    { steps: 25 },
  )
  await expect(dialog).toBeVisible()
  await page.mouse.move(
    (panel.left + panel.right) / 2,
    (panel.top + panel.bottom) / 2,
    { steps: 25 },
  )
  await expect(dialog).toBeVisible()
  await expect(verdictIn(page).getByRole('dialog')).toHaveCount(1)
}

/** Moves the pointer to a viewport corner clear of the dialog and trigger; the dialog closes. */
async function leaveAndExpectClosed(
  page: Page,
  viewport: Viewport,
  trigger: Locator,
  dialog: Locator,
) {
  const avoid = [await boxOf(dialog), await boxOf(trigger)]
  const clear = [
    { x: 2, y: 2 },
    { x: viewport.width - 2, y: 2 },
    { x: 2, y: viewport.height - 2 },
    { x: viewport.width - 2, y: viewport.height - 2 },
  ].find(({ x, y }) =>
    avoid.every(
      (box) => x < box.left || x > box.right || y < box.top || y > box.bottom,
    ),
  )
  if (clear === undefined) {
    throw new Error('no viewport corner is clear of the dialog and trigger')
  }
  await page.mouse.move(clear.x, clear.y, { steps: 5 })
  await expect(verdictIn(page).getByRole('dialog')).toHaveCount(0)
  // Only the rating panel closed: the verdict is still open.
  await expect(verdictIn(page)).toBeVisible()
}

/**
 * The open ledger dialog's geometry, measured in the page. The verdict modal
 * is a native <dialog> with no role attribute, so `[role="dialog"]` is the
 * rating panel alone.
 */
const MEASURE_LEDGER = `(() => {
  const dialog = document.querySelector('[role="dialog"]')
  const box = (node) => {
    const r = node.getBoundingClientRect()
    return { top: r.top, bottom: r.bottom, left: r.left, right: r.right }
  }
  const byText = (text) => {
    const found = Array.from(dialog.querySelectorAll('h6, p')).find(
      (node) => node.textContent === text,
    )
    if (!found) throw new Error('no element with text ' + text)
    return found
  }
  const list = dialog.querySelector('[aria-label="Games, in order"]')
  const listRect = list.getBoundingClientRect()
  const listView = {
    top: listRect.top + list.clientTop,
    bottom: listRect.top + list.clientTop + list.clientHeight,
    left: listRect.left,
    right: listRect.right,
  }
  return {
    dialog: box(dialog),
    dialogScrolls: dialog.scrollHeight > dialog.clientHeight + 1,
    rule: box(byText('The rule — same for every team')),
    footer: box(byText('After ${GAMES_2005} games: 1,933.2').parentElement),
    listView,
    listOverflowY: getComputedStyle(list).overflowY,
    listClientHeight: list.clientHeight,
    listScrollHeight: list.scrollHeight,
    wholeRowsInView: Array.from(list.children)
      .map(box)
      .filter(
        (row) =>
          row.top >= listView.top - 0.5 && row.bottom <= listView.bottom + 0.5,
      ).length,
  }
})()`

for (const { viewport, triggerTops } of LAYOUTS) {
  test.describe(`at ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport })

    for (const triggerTop of triggerTops) {
      test(`Elo ledger, trigger ${triggerTop}px from the top: the whole panel is on screen, rule and footer in view, at least ${MIN_VISIBLE_ROWS} whole games in the list, and the pointer can reach it`, async ({
        page,
      }) => {
        const trigger = await askForThe2005Champion(page, 'elo')
        await expect(trigger).toHaveText('1,933')
        await placeTriggerAt(page, viewport, trigger, triggerTop)

        await trigger.hover()
        const dialog = page.getByRole('dialog', {
          name: 'Texas Elo rating, game by game',
        })
        await expect(dialog).toBeVisible()
        await expect(verdictIn(page).getByRole('dialog')).toHaveCount(1)
        await expect(
          dialog
            .getByRole('list', { name: 'Games, in order' })
            .getByRole('listitem'),
        ).toHaveCount(GAMES_2005)

        const layout = await page.evaluate<LedgerLayout>(MEASURE_LEDGER)
        const detail = JSON.stringify(layout)
        expect(inside(layout.dialog, viewportBox(viewport)), detail).toBe(true)
        expect(layout.dialogScrolls, detail).toBe(false)
        expect(inside(layout.rule, layout.dialog), detail).toBe(true)
        expect(inside(layout.footer, layout.dialog), detail).toBe(true)
        expect(layout.listOverflowY, detail).toBe('auto')
        expect(layout.wholeRowsInView, detail).toBeGreaterThanOrEqual(
          MIN_VISIBLE_ROWS,
        )

        await travelIntoDialog(page, trigger, dialog)
        await leaveAndExpectClosed(page, viewport, trigger, dialog)
      })

      test(`Keener breakdown, trigger ${triggerTop}px from the top: the whole panel is on screen with its heading in view, the pointer can reach it, and leaving closes it`, async ({
        page,
      }) => {
        const trigger = await askForThe2005Champion(page, 'keener')
        await expect(trigger).toHaveCount(1)
        await placeTriggerAt(page, viewport, trigger, triggerTop)

        await trigger.hover()
        const dialog = page.getByRole('dialog', {
          name: 'Texas rating breakdown',
        })
        await expect(dialog).toBeVisible()
        await expect(dialog.getByText('Rating-system baseline')).toBeAttached()

        const box = await boxOf(dialog)
        expect(inside(box, viewportBox(viewport)), JSON.stringify(box)).toBe(
          true,
        )
        const heading = await boxOf(
          dialog.getByRole('heading', { name: 'Texas rating breakdown' }),
        )
        expect(inside(heading, box), JSON.stringify({ heading, box })).toBe(
          true,
        )

        await travelIntoDialog(page, trigger, dialog)
        await leaveAndExpectClosed(page, viewport, trigger, dialog)
      })
    }
  })
}
