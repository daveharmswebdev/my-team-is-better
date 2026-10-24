import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Issue #405: the live site never waits on a third party to paint. The
 * typefaces (Anton, Barlow, Barlow Condensed) used to come from a
 * render-blocking Google Fonts stylesheet, so a slow fonts.googleapis.com held
 * the page's `load` event open (#242 measured 15s+ with it held open). They
 * are now self-hosted under `public/fonts/` and declared by `@font-face` rules
 * inline in `index.html`.
 *
 * This checks the source `index.html` and, when a build exists, the built
 * `dist/index.html` too (CI runs `npm run test` before `npm run build`, so the
 * dist half only runs locally or after a build).
 *
 * (Paths resolve from Vitest's cwd -- `apps/web` -- like
 * `socialPreview.test.ts`.)
 */
const WEB_ROOT = process.cwd()

/** Every face the app's CSS asks for: family and weight, latin subset. */
const FACES = [
  { family: 'Anton', weight: '400' },
  { family: 'Barlow', weight: '400' },
  { family: 'Barlow', weight: '500' },
  { family: 'Barlow', weight: '600' },
  { family: 'Barlow', weight: '700' },
  { family: 'Barlow Condensed', weight: '500' },
  { family: 'Barlow Condensed', weight: '600' },
  { family: 'Barlow Condensed', weight: '700' },
] as const

const THIRD_PARTY_FONT_HOSTS = /fonts\.googleapis\.com|fonts\.gstatic\.com/

interface FontFaceRule {
  family: string
  weight: string
  display: string | undefined
  urls: string[]
}

function parseFontFaces(html: string): FontFaceRule[] {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const css = [...doc.querySelectorAll('style')]
    .map((style) => style.textContent ?? '')
    .join('\n')
  const rules: FontFaceRule[] = []
  for (const match of css.matchAll(/@font-face\s*\{([^}]*)\}/g)) {
    const body = match[1] ?? ''
    const prop = (name: string) =>
      new RegExp(`${name}\\s*:\\s*([^;]+);`).exec(body)?.[1]?.trim()
    const src = prop('src') ?? ''
    rules.push({
      family: (prop('font-family') ?? '').replace(/['"]/g, ''),
      weight: prop('font-weight') ?? '',
      display: prop('font-display'),
      urls: [...src.matchAll(/url\(\s*['"]?([^'")]+)['"]?\s*\)/g)].map(
        (m) => m[1] ?? '',
      ),
    })
  }
  return rules
}

function checkSelfHosted(htmlPath: string, staticRoot: string) {
  const html = readFileSync(htmlPath, 'utf8')
  expect(html, 'no request to Google Fonts').not.toMatch(THIRD_PARTY_FONT_HOSTS)

  const rules = parseFontFaces(html)
  for (const { family, weight } of FACES) {
    const rule = rules.find((r) => r.family === family && r.weight === weight)
    expect(rule, `@font-face for ${family} ${weight}`).toBeDefined()
    if (!rule) continue
    expect(rule.display, `${family} ${weight} font-display`).toBe('swap')
    expect(rule.urls.length, `${family} ${weight} src url`).toBeGreaterThan(0)
    for (const url of rule.urls) {
      expect(url, `${family} ${weight} is same-origin`).toMatch(/^\/fonts\//)
      expect(url).toMatch(/\.woff2$/)
      expect(
        existsSync(resolve(staticRoot, `.${url}`)),
        `${url} exists under ${staticRoot}`,
      ).toBe(true)
    }
  }

  // Every preload points at a face that is declared and exists.
  const doc = new DOMParser().parseFromString(html, 'text/html')
  const declared = new Set(rules.flatMap((r) => r.urls))
  const preloads = [
    ...doc.head.querySelectorAll('link[rel="preload"][as="font"]'),
  ]
  expect(preloads.length, 'above-the-fold faces are preloaded').toBeGreaterThan(
    0,
  )
  for (const link of preloads) {
    const href = link.getAttribute('href') ?? ''
    expect(declared.has(href), `preload ${href} is a declared face`).toBe(true)
    expect(link.getAttribute('type')).toBe('font/woff2')
    // Fonts are always fetched in CORS mode; without `crossorigin` the
    // preload is wasted and the face is downloaded twice.
    expect(link.hasAttribute('crossorigin'), `${href} crossorigin`).toBe(true)
  }
}

describe('self-hosted fonts (issue #405)', () => {
  it('index.html loads every face from public/fonts, never Google', () => {
    checkSelfHosted(
      resolve(WEB_ROOT, 'index.html'),
      resolve(WEB_ROOT, 'public'),
    )
  })

  it('ships the SIL Open Font License next to the files', () => {
    const license = resolve(WEB_ROOT, 'public', 'fonts', 'OFL.txt')
    expect(existsSync(license)).toBe(true)
    const text = readFileSync(license, 'utf8')
    expect(text).toMatch(/SIL OPEN FONT LICENSE Version 1\.1/)
    for (const family of ['Anton', 'Barlow']) {
      expect(text).toContain(family)
    }
  })

  const built = resolve(WEB_ROOT, 'dist', 'index.html')
  it.skipIf(!existsSync(built))(
    'the built dist/index.html does too (runs after a build)',
    () => {
      checkSelfHosted(built, resolve(WEB_ROOT, 'dist'))
    },
  )
})
