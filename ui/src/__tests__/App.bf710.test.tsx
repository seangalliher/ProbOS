/**
 * BF-710: pin that the approval panels are actually MOUNTED by production.
 *
 * WHAT IS PINNED HERE: a property of `ui/src/App.tsx` — that it imports both
 * approval panels from their real module paths and renders both elements inside
 * the tree it returns.
 *
 * WHY A COMPONENT-LEVEL TEST CANNOT PIN IT: `render(<CapabilityRequestPanel />)`
 * mounts the component *by definition*. Both panels already had passing test
 * files (`CapabilityRequestPanel.test.tsx`, `SkillRequestPanel.test.tsx`) that
 * did exactly that, and they stayed green for the entire period in which no
 * shipped code path mounted either panel — the Captain's only approve/deny
 * surface was unreachable. A test that supplies the mount can never detect a
 * missing mount. The reachability question is a property of the caller, so the
 * assertion has to be made about the caller.
 *
 * App.tsx is asserted at the source level rather than by `render(<App />)`
 * because App mounts the full HXI (WebSocket hook, three.js canvas, ~20 sibling
 * panels), so a render-based check would pass or fail for reasons unrelated to
 * this mount. Source-level guards on a component that is expensive to mount are
 * an established idiom here — see `components/mesh/__tests__/MobileMesh.test.tsx`
 * and `components/workspace/__tests__/WorkspaceFilesRail.test.tsx`.
 */
import { describe, it, expect } from 'vitest';
import appSource from '../App.tsx?raw';
import CapabilityRequestPanel from '../components/capability/CapabilityRequestPanel';
import SkillRequestPanel from '../components/skill/SkillRequestPanel';

/** The JSX App actually returns — imports alone are not a mount. */
function returnedTree(source: string): string {
  const start = source.indexOf('return (');
  expect(start).toBeGreaterThan(-1);
  return source.slice(start);
}

describe('App approval-panel mount (BF-710)', () => {
  it('imports both approval panels from their real module paths', () => {
    expect(appSource).toContain(
      "from './components/capability/CapabilityRequestPanel'",
    );
    expect(appSource).toContain("from './components/skill/SkillRequestPanel'");
    // The specifiers above resolve — these imports are the same modules.
    expect(typeof CapabilityRequestPanel).toBe('function');
    expect(typeof SkillRequestPanel).toBe('function');
  });

  it('renders CapabilityRequestPanel inside the tree App returns', () => {
    expect(returnedTree(appSource)).toContain('<CapabilityRequestPanel />');
  });

  it('renders SkillRequestPanel inside the tree App returns', () => {
    expect(returnedTree(appSource)).toContain('<SkillRequestPanel />');
  });

  it('mounts both unconditionally — the panels gate themselves', () => {
    /* Each panel returns null once loaded with an empty pending list, so no
     * conditional wrapper is needed and none should creep in: a gate in App
     * would be a second place that can silently switch the surface off. */
    const tree = returnedTree(appSource);
    for (const marker of ['<CapabilityRequestPanel />', '<SkillRequestPanel />']) {
      const line = tree
        .split('\n')
        .find((l) => l.includes(marker)) as string;
      expect(line).toBeTruthy();
      expect(line.trim()).toBe(marker);
    }
  });
});
