import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Issue #405: the live site never waits on a third party to paint. The
 * typefaces (Anton, Barlow, Barlow Condensed) used to come from a
 * render-blocking Google Fonts stylesheet, so a slow fonts.googleapis.com held
 * the page's `load` event open (#242 measured 15s+ with it held open). They
 * are now self-hosted under `public/fonts/`.
 *
 * Issue #408: the `@font-face` rules live in one stylesheet,
 * `src/styles/fonts.css`, imported by both the app (`src/main.tsx`) and
 * Storybook's preview (`.storybook/preview.tsx`), so the stories and the a11y
 * checks that run on them paint in the brand faces, and the two can't drift.
 * `index.html` keeps only the preloads and must not grow a second copy of the
 * rules. Storybook serves `public/` (`staticDirs` in `.storybook/main.ts`), so
 * the `/fonts/*.woff2` urls resolve there too.
 *
 * This checks the sources and, when a build exists, the built `dist/` too (CI
 * runs `npm run test` before `npm run build`, so the dist half only runs
 * locally or after a build).
 *
 * (Paths resolve from Vitest's cwd -- `apps/web` -- like
 * `socialPreview.test.ts`.)
 */
const WEB_ROOT = process.cwd()

/** The one place every face is declared. */
const FONTS_CSS = resolve(WEB_ROOT, 'src', 'styles', 'fonts.css')

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

function parseFontFaces(css: string): FontFaceRule[] {
  const rules: FontFaceRule[] = []
  for (const match of css.matchAll(/@font-face\s*\{([^}]*)\}/g)) {
    const body = match[1] ?? ''
    const prop = (name: string) =>
      new RegExp(`${name}\\s*:\\s*([^;}]+)[;}]?`).exec(body)?.[1]?.trim()
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

/** Every face is declared, swaps, and is a same-origin woff2 that exists. */
function checkFaces(css: string, staticRoot: string): FontFaceRule[] {
  expect(css, 'no request to Google Fonts').not.toMatch(THIRD_PARTY_FONT_HOSTS)

  const rules = parseFontFaces(css)
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
  return rules
}

/** Every font preload in an HTML file points at a declared face. */
function checkPreloads(htmlPath: string, rules: FontFaceRule[]) {
  const html = readFileSync(htmlPath, 'utf8')
  expect(html, 'no request to Google Fonts').not.toMatch(THIRD_PARTY_FONT_HOSTS)

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

/** The CSS of every inline `<style>` in an HTML file. */
function inlineCss(htmlPath: string): string {
  const doc = new DOMParser().parseFromString(
    readFileSync(htmlPath, 'utf8'),
    'text/html',
  )
  return [...doc.querySelectorAll('style')]
    .map((style) => style.textContent ?? '')
    .join('\n')
}

/** Absolute paths of a module's side-effect stylesheet imports. */
function cssImports(modulePath: string): string[] {
  const source = readFileSync(modulePath, 'utf8')
  return [...source.matchAll(/^import\s+['"]([^'"]+\.css)['"]/gm)].map((m) =>
    resolve(modulePath, '..', m[1] ?? ''),
  )
}

describe('self-hosted fonts (issue #405)', () => {
  it('src/styles/fonts.css loads every face from public/fonts, never Google', () => {
    checkFaces(readFileSync(FONTS_CSS, 'utf8'), resolve(WEB_ROOT, 'public'))
  })

  it('index.html preloads declared faces and keeps no second copy of the rules', () => {
    const indexHtml = resolve(WEB_ROOT, 'index.html')
    checkPreloads(indexHtml, parseFontFaces(readFileSync(FONTS_CSS, 'utf8')))
    expect(
      parseFontFaces(inlineCss(indexHtml)),
      'index.html declares no @font-face of its own: fonts.css is the one source',
    ).toEqual([])
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
    'the built dist/ does too: bundled CSS declares every face, html preloads them (runs after a build)',
    () => {
      const assets = resolve(WEB_ROOT, 'dist', 'assets')
      const css = readdirSync(assets)
        .filter((name) => name.endsWith('.css'))
        .map((name) => readFileSync(resolve(assets, name), 'utf8'))
        .join('\n')
      const rules = checkFaces(css, resolve(WEB_ROOT, 'dist'))
      checkPreloads(built, rules)
    },
  )
})

describe('the app and Storybook share the font rules (issue #408)', () => {
  it('src/main.tsx imports src/styles/fonts.css', () => {
    expect(cssImports(resolve(WEB_ROOT, 'src', 'main.tsx'))).toContain(
      FONTS_CSS,
    )
  })

  it('.storybook/preview.tsx imports src/styles/fonts.css', () => {
    expect(
      cssImports(resolve(WEB_ROOT, '.storybook', 'preview.tsx')),
    ).toContain(FONTS_CSS)
  })

  it('.storybook/main.ts serves public/, so /fonts/*.woff2 resolves', () => {
    const main = readFileSync(
      resolve(WEB_ROOT, '.storybook', 'main.ts'),
      'utf8',
    )
    expect(main).toMatch(/staticDirs\s*:\s*\[[^\]]*['"]\.\.\/public['"]/)
  })
})
