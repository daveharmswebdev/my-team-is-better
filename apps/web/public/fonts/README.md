# Self-hosted typefaces

The app's three typefaces, served from this origin so no page load waits on a
third party (issue #405; before it, a render-blocking Google Fonts stylesheet
held the page's `load` event open whenever fonts.googleapis.com was slow).
`index.html` declares them with inline `@font-face` rules (`font-display: swap`)
and preloads the faces above the fold.

## Credits

- **Anton** by Vernon Adams, Copyright 2020 The Anton Project Authors
  (https://github.com/googlefonts/AntonFont).
- **Barlow** and **Barlow Condensed** by Jeremy Tribby, Copyright 2017 The
  Barlow Project Authors (https://github.com/jpt/barlow).

All three are licensed under the SIL Open Font License, Version 1.1; the full
text is in [`OFL.txt`](./OFL.txt), served alongside the files at
`/fonts/OFL.txt`.

## Source

Latin subset, woff2, fetched once on 2026-10-24 from the files Google Fonts'
CSS API served for the stylesheet `index.html` used to link
(`https://fonts.googleapis.com/css2?family=Anton&family=Barlow:wght@400;500;600;700&family=Barlow+Condensed:wght@500;600;700&display=swap`).
Each rule's `unicode-range` is copied from that CSS.

| File                               | Family           | Weight | Source                                                                                            |
| ---------------------------------- | ---------------- | ------ | ------------------------------------------------------------------------------------------------- |
| `anton-400-latin.woff2`            | Anton            | 400    | https://fonts.gstatic.com/s/anton/v27/1Ptgg87LROyAm3Kz-C8CSKlv.woff2                              |
| `barlow-400-latin.woff2`           | Barlow           | 400    | https://fonts.gstatic.com/s/barlow/v13/7cHpv4kjgoGqM7E_DMs5ynghnQ.woff2                           |
| `barlow-500-latin.woff2`           | Barlow           | 500    | https://fonts.gstatic.com/s/barlow/v13/7cHqv4kjgoGqM7E3_-gs51ostz0rdg.woff2                       |
| `barlow-600-latin.woff2`           | Barlow           | 600    | https://fonts.gstatic.com/s/barlow/v13/7cHqv4kjgoGqM7E30-8s51ostz0rdg.woff2                       |
| `barlow-700-latin.woff2`           | Barlow           | 700    | https://fonts.gstatic.com/s/barlow/v13/7cHqv4kjgoGqM7E3t-4s51ostz0rdg.woff2                       |
| `barlow-condensed-500-latin.woff2` | Barlow Condensed | 500    | https://fonts.gstatic.com/s/barlowcondensed/v13/HTxwL3I-JCGChYJ8VI-L6OO_au7B4-Lwz3bWuYMBYro.woff2 |
| `barlow-condensed-600-latin.woff2` | Barlow Condensed | 600    | https://fonts.gstatic.com/s/barlowcondensed/v13/HTxwL3I-JCGChYJ8VI-L6OO_au7B4873z3bWuYMBYro.woff2 |
| `barlow-condensed-700-latin.woff2` | Barlow Condensed | 700    | https://fonts.gstatic.com/s/barlowcondensed/v13/HTxwL3I-JCGChYJ8VI-L6OO_au7B46r2z3bWuYMBYro.woff2 |

`OFL.txt` combines the projects' `OFL.txt` files from
https://github.com/google/fonts/tree/main/ofl (`anton/`, `barlow/`,
`barlowcondensed/`), whose license bodies are identical.

Adding a weight: fetch its latin woff2 the same way, add a row here, an
`@font-face` rule in `index.html`, and the face to
`src/test/selfHostedFonts.test.ts`.
