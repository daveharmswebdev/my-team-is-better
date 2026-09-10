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
  ],
  options: {
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
