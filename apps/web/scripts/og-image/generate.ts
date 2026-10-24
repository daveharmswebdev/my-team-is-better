/**
 * Regenerates public/og-image.png, the site-wide link-preview image that
 * index.html's og:image / twitter:image tags point at (issue #185).
 *
 *   npm run og-image
 *
 * Renders card.html (with public/favicon.svg inlined) in headless Chromium at
 * exactly 1200x630 CSS pixels, device scale 1, and screenshots it. The fonts
 * come from Google Fonts, so this needs network access; it fails rather than
 * bake a fallback font into the image. `src/test/socialPreview.test.ts`
 * checks the PNG's real size against the tags.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from '@playwright/test'

const here = dirname(fileURLToPath(import.meta.url))
const webRoot = resolve(here, '..', '..')
const out = resolve(webRoot, 'public', 'og-image.png')

const favicon = readFileSync(resolve(webRoot, 'public', 'favicon.svg'), 'utf8')
const card = readFileSync(resolve(here, 'card.html'), 'utf8')
const placeholders = card.split('{{FAVICON}}').length - 1
if (placeholders !== 1) {
  throw new Error(
    `card.html needs exactly one {{FAVICON}}, has ${placeholders}`,
  )
}
const html = card.replace('{{FAVICON}}', favicon)

const browser = await chromium.launch()
try {
  const page = await browser.newPage({
    viewport: { width: 1200, height: 630 },
    deviceScaleFactor: 1,
  })
  await page.setContent(html, { waitUntil: 'networkidle' })
  // `document.fonts.check` is true for a family with no @font-face at all, so
  // look for a loaded face of each family instead.
  const missing = await page.evaluate(async () => {
    await document.fonts.ready
    const loaded = new Set<string>()
    document.fonts.forEach((face) => {
      if (face.status === 'loaded') loaded.add(face.family.replace(/"/g, ''))
    })
    return ['Anton', 'Barlow', 'Barlow Condensed'].filter(
      (family) => !loaded.has(family),
    )
  })
  if (missing.length > 0) {
    throw new Error(`fonts did not load: ${missing.join(', ')}`)
  }
  await page.screenshot({ path: out, type: 'png' })
  console.log(`wrote ${out}`)
} finally {
  await browser.close()
}
