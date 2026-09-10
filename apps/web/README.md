# apps/web

The React + TypeScript frontend for My Team Is Better. Vite + React 19,
Storybook, and a full local toolchain (lint / type-check / test / build /
build-storybook) wired from the start -- see the repo root `CLAUDE.md`
"Engineering standards" for why.

This is currently a skeleton (issue #5): tooling proven end to end with one
trivial `Greeting` component, not real feature UI yet.

## Layout

```
src/
  components/   # reusable presentational units -- must not import from pages/
  pages/        # composition + data-fetching root, imports from components/
  test/         # Vitest setup (jest-dom matchers)
```

The `components/** -> pages/**` boundary is enforced by `dependency-cruiser`
(`.dependency-cruiser.cjs`), not just documented -- see `npm run dep-cruise`.

## Scripts

| Command                           | What it does                                                        |
| --------------------------------- | ------------------------------------------------------------------- |
| `npm run dev`                     | Vite dev server                                                     |
| `npm run build`                   | `tsc -b` (strict type-check) + Vite production build                |
| `npm run lint`                    | ESLint (`typescript-eslint`, react-hooks, react-refresh, storybook) |
| `npm run format` / `format:check` | Prettier write / check                                              |
| `npm run test` / `test:watch`     | Vitest + React Testing Library                                      |
| `npm run dep-cruise`              | dependency-cruiser module-boundary check                            |
| `npm run storybook`               | Storybook dev server                                                |
| `npm run build-storybook`         | Static Storybook build (also a CI gate)                             |
