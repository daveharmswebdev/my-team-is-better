import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * Issue #185: a My Team Is Better link pasted into iMessage, Slack, Facebook
 * or X previews as the app (title, description, image card). Link scrapers
 * don't run JS, so the tags must be static in `index.html`, with absolute
 * URLs on the production origin, and the image must really be the size the
 * tags claim (a mismatch makes some scrapers drop the large card).
 *
 * This covers only the site-wide preview. Per-verdict previews would need
 * server-rendered tags and are out of scope here.
 *
 * (Paths resolve from Vitest's cwd -- `apps/web` -- like
 * `lib/api/vocabularies.test.ts`.)
 */
const WEB_ROOT = process.cwd()
const PRODUCTION_ORIGIN = 'https://my-team-is-better-web.onrender.com'

const REQUIRED_PROPERTIES = [
  'og:type',
  'og:site_name',
  'og:title',
  'og:description',
  'og:url',
  'og:image',
  'og:image:width',
  'og:image:height',
  'og:image:alt',
] as const

function parseHead(path: string): Document {
  return new DOMParser().parseFromString(
    readFileSync(path, 'utf8'),
    'text/html',
  )
}

function meta(doc: Document, attr: 'property' | 'name', key: string): string {
  const el = doc.head.querySelector(`meta[${attr}="${key}"]`)
  const content = el?.getAttribute('content')?.trim()
  if (!content) throw new Error(`missing <meta ${attr}="${key}" content="...">`)
  return content
}

/** Width and height from a PNG's IHDR chunk (bytes 16-23, big-endian). */
function pngSize(path: string): { width: number; height: number } {
  const bytes = readFileSync(path)
  const signature = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]
  expect([...bytes.subarray(0, 8)]).toEqual(signature)
  expect(bytes.subarray(12, 16).toString('ascii')).toBe('IHDR')
  return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) }
}

function checkSocialTags(doc: Document) {
  for (const property of REQUIRED_PROPERTIES) {
    expect(() => meta(doc, 'property', property), property).not.toThrow()
  }
  expect(meta(doc, 'property', 'og:type')).toBe('website')
  expect(meta(doc, 'name', 'twitter:card')).toBe('summary_large_image')
  expect(meta(doc, 'name', 'description')).not.toHaveLength(0)

  for (const property of ['og:url', 'og:image']) {
    const url = new URL(meta(doc, 'property', property))
    expect(url.protocol, property).toBe('https:')
    expect(url.origin, property).toBe(PRODUCTION_ORIGIN)
  }

  const imageUrl = new URL(meta(doc, 'property', 'og:image'))
  expect(imageUrl.pathname).toMatch(/\.png$/)
  const imagePath = resolve(WEB_ROOT, 'public', `.${imageUrl.pathname}`)
  expect(existsSync(imagePath), `${imagePath} exists`).toBe(true)

  const { width, height } = pngSize(imagePath)
  expect(width).toBe(1200)
  expect(height).toBe(630)
  expect(Number(meta(doc, 'property', 'og:image:width'))).toBe(width)
  expect(Number(meta(doc, 'property', 'og:image:height'))).toBe(height)
}

describe('social link preview tags (issue #185)', () => {
  it('index.html carries every Open Graph / Twitter card tag', () => {
    checkSocialTags(parseHead(resolve(WEB_ROOT, 'index.html')))
  })

  // `npm run test` runs before `npm run build` in CI, so dist/ is usually
  // absent there; when a build exists, its emitted head must keep the tags.
  const built = resolve(WEB_ROOT, 'dist', 'index.html')
  it.runIf(existsSync(built))('the built dist/index.html keeps them', () => {
    checkSocialTags(parseHead(built))
  })
})
