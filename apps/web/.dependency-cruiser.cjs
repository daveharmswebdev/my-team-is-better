/** @type {import('dependency-cruiser').IConfiguration} */
module.exports = {
  forbidden: [
    {
      name: 'components-must-not-import-pages',
      comment:
        'components/** are reusable presentational units; pages/** own composition and ' +
        'data-fetching (see CLAUDE.md / Architecture Brief). A component depending on a ' +
        'page would invert that boundary, so it is forbidden here rather than just documented.',
      severity: 'error',
      from: { path: '^src/components' },
      to: { path: '^src/pages' },
    },
    {
      name: 'lib-must-not-import-ui',
      comment:
        'lib/** is the UI-free layer (API client and types, formatting, pure helpers) that ' +
        'components/** and pages/** build on. lib importing a component or a page would ' +
        'make the bottom layer depend on the top and invite cycles, so it is forbidden.',
      severity: 'error',
      from: { path: '^src/lib' },
      to: { path: '^src/(components|pages)' },
    },
    {
      name: 'not-to-unresolvable',
      comment:
        'An import dependency-cruiser cannot resolve is invisible to every other rule: a ' +
        'mistyped path that crosses a boundary passes them all (#127). So an unresolvable ' +
        'import from src is an error in its own right. Two exceptions: vite/client, which ' +
        'src/vite-env.d.ts pulls in by a triple-slash types reference (vite exports that ' +
        'path under the "types" condition only, which the resolver here rightly does not ' +
        'use for runtime imports); and virtual:* ids, which a Vite plugin serves at build ' +
        'time and no file on disk backs.',
      severity: 'error',
      from: { path: '^src' },
      to: { couldNotResolve: true, pathNot: ['^vite/client$', '^virtual:'] },
    },
    {
      name: 'no-circular',
      comment:
        'A cycle between modules makes load order matter, breaks HMR and tree-shaking in ' +
        'subtle ways, and means neither side can be understood or tested alone. Split the ' +
        'shared part into its own module instead.',
      severity: 'error',
      from: { path: '^src' },
      to: { circular: true },
    },
  ],
  options: {
    // Third-party internals are not ours to police, and walking them cost ~2000 extra
    // modules per run and surfaced their own cycles and unresolvable optional deps.
    // Imports of node_modules are still recorded (and still checked by the rules above);
    // the cruise just does not descend into them.
    doNotFollow: { path: 'node_modules' },
    tsPreCompilationDeps: true,
    tsConfig: {
      fileName: 'tsconfig.app.json',
    },
    enhancedResolveOptions: {
      exportsFields: ['exports'],
      conditionNames: ['import', 'require', 'node', 'default'],
    },
  },
}
