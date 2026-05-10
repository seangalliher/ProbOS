import { describe, it, expect } from 'vitest';
// Use Vite's `?raw` import to read the source without Node typings.
// This keeps the test browser-bundler-compatible (no @types/node needed)
// and survives `tsc -b` in the prod build.
import wakeWordSource from '../audio/wakeWord.ts?raw';

// AD-705 D8 test #21: lazy-load source-level guard.
//
// This test asserts that `onnxruntime-web` is NEVER referenced in a static
// top-level `import`. Captain answer Q5 (2026-05-09): lazy-load is
// non-negotiable. First-paint must not regress for Captains who never
// enable voice.

describe('wakeWord lazy-load (AD-705 D1, hard-stop #10)', () => {
  it('21. wakeWord.ts does not statically import onnxruntime-web', () => {
    const src = wakeWordSource;
    // Static-import patterns at module top-level. The dynamic import
    // (await import(moduleName)) is allowed and required.
    const staticImportRe = /^\s*import\s+[^;]*['"]onnxruntime-web['"]/m;
    expect(staticImportRe.test(src)).toBe(false);
    // The string literal must NOT appear inside a static `import`. We
    // additionally assert that the dynamic-import path uses an indirect
    // string variable so Vite/Vitest cannot statically resolve.
    const indirectImportRe = /import\s*\(\s*\/\*\s*@vite-ignore\s*\*\/\s*\w+\s*\)/;
    expect(indirectImportRe.test(src)).toBe(true);
  });
});
