import { describe, it, expect } from 'vitest';
// Use Vite's `?raw` import to read the source without Node typings.
// This keeps the test browser-bundler-compatible (no @types/node needed)
// and survives `tsc -b` in the prod build.
import wakeWordSource from '../audio/wakeWord.ts?raw';

// AD-705 D8 test #21 (BF-307 update): lazy-load source-level guard.
//
// Captain answer Q5 (2026-05-09): lazy-load is non-negotiable; first-paint
// must not regress for Captains who never enable voice. The original guard
// also asserted the indirect-string ``@vite-ignore`` pattern on the
// assumption that ``onnxruntime-web`` was an operator-pulled
// ``optionalDependency``. BF-306 promoted ORT to a real dep, and BF-307
// showed the indirect pattern actively broke production (browsers cannot
// resolve a bare specifier from a dynamic ``import()`` — the call always
// threw silently, returning null). The lazy-load posture is preserved by
// the dynamic import itself (Vite code-splits into its own chunk); the
// indirection was harmful, not helpful.

describe('wakeWord lazy-load (AD-705 D1, hard-stop #10, BF-307)', () => {
  it('21. wakeWord.ts does not statically import onnxruntime-web', () => {
    const src = wakeWordSource;
    // Static-import patterns at module top-level. Dynamic ``await import``
    // is the required pattern; it gets Vite-code-split into its own chunk
    // so first-paint is unaffected for Captains who never enable voice.
    const staticImportRe = /^\s*import\s+[^;]*['"]onnxruntime-web['"]/m;
    expect(staticImportRe.test(src)).toBe(false);
    // BF-307: the dynamic-import path MUST use a literal specifier so
    // Vite bundles it; bare-specifier dynamic imports fail in the browser.
    const dynamicImportRe = /import\s*\(\s*['"]onnxruntime-web['"]\s*\)/;
    expect(dynamicImportRe.test(src)).toBe(true);
  });
});

