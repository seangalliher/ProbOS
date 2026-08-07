/**
 * Reachability guard for the approve/deny surface — BF-710, replaced by AD-1201.
 *
 * WHAT IS PINNED HERE: that some shipped code path renders the approval panels.
 * The property is unchanged from BF-710; only the chain that satisfies it moved.
 *
 * BF-710 satisfied it by having `App.tsx` render `<CapabilityRequestPanel />`
 * and `<SkillRequestPanel />` directly, inside a fixed top-right container. That
 * container sat at the exact coordinates of the AD-325 BRIDGE toggle and covered
 * it, so AD-1201 moved the surface into the Bridge. The chain is now three links
 * instead of one:
 *
 *     App.tsx  --renders-->  ApprovalsCenterPanel  --renders-->  both panels
 *     App.tsx  --renders-->  IntentSurface --renders--> BridgePanel
 *                                            |- APPROVALS section, whose
 *                                               onExpand opens the centre
 *
 * Every link is asserted below. Break any one of them — drop the centre from
 * App, drop either panel from the centre, drop the APPROVALS section from the
 * Bridge, or drop the `approvalsCenterOpen` wiring that opens the centre — and
 * this file fails. Deleting it instead of replacing it would restore the exact
 * condition BF-710 existed to fix.
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
 * App.tsx and BridgePanel are asserted at the source level rather than by
 * `render(<App />)` because App mounts the full HXI (WebSocket hook, three.js
 * canvas, ~20 sibling panels), so a render-based check would pass or fail for
 * reasons unrelated to this mount. Source-level guards on a component that is
 * expensive to mount are an established idiom here — see
 * `components/mesh/__tests__/MobileMesh.test.tsx` and
 * `components/workspace/__tests__/WorkspaceFilesRail.test.tsx`. The one link
 * that is cheap to mount — the Bridge's expand affordance — is exercised for
 * real in `components/approvals/__tests__/ApprovalsInBridge.test.tsx`.
 */
import { describe, it, expect } from 'vitest';
import appSource from '../App.tsx?raw';
import bridgeSource from '../components/BridgePanel.tsx?raw';
import centerSource from '../components/approvals/ApprovalsCenterPanel.tsx?raw';
import { ApprovalsCenterPanel } from '../components/approvals/ApprovalsCenterPanel';
import CapabilityRequestPanel from '../components/capability/CapabilityRequestPanel';
import SkillRequestPanel from '../components/skill/SkillRequestPanel';

/** The JSX a component actually returns — imports alone are not a mount. */
function returnedTree(source: string): string {
  /* BF-724: this was `indexOf('return (')`, which ALSO matches the
   * `return () => { … }` cleanup of a `useEffect`. App.tsx has carried three
   * such cleanups since before this file existed, so "the tree it returns" has
   * quietly meant "everything after the first effect cleanup" — the assertions
   * below happened to hold on the wider slice, so nothing ever failed. Adding a
   * focus-transfer effect to ApprovalsCenterPanel would have done the same to
   * the centre. Anchoring on the newline that follows a JSX `return (` tells the
   * statement apart from the arrow. Every assertion below is unchanged; this
   * only makes them mean what they already claimed. */
  const start = source.search(/return \(\r?\n/);
  expect(start).toBeGreaterThan(-1);
  return source.slice(start);
}

describe('approvals surface reachability (BF-710, re-homed by AD-1201)', () => {
  it('the tree helper anchors on a JSX return, not on an effect cleanup', () => {
    /* BF-724: a guard on the guard. Every assertion in this file is evaluated
     * against `returnedTree(...)`, and until BF-724 that helper matched
     * `return (` anywhere — including the `return () => { … }` cleanup of a
     * `useEffect`. App.tsx has carried three such cleanups since before this
     * file existed, so "the tree it returns" has silently meant "everything
     * after the first effect cleanup" and nothing ever failed. Adding a
     * focus-transfer effect to the centre would have done the same to
     * `centerSource`. Anchoring is invisible when it is wrong, so it gets its
     * own assertion rather than relying on the others to notice. */
    for (const source of [appSource, bridgeSource, centerSource]) {
      expect(returnedTree(source)).toMatch(/^return \(\r?\n/);
    }
  });

  it('App imports the approvals centre from its real module path', () => {
    expect(appSource).toContain(
      "from './components/approvals/ApprovalsCenterPanel'",
    );
    // The specifier above resolves — this import is the same module.
    expect(typeof ApprovalsCenterPanel).toBe('function');
  });

  it('App renders the approvals centre inside the tree it returns', () => {
    expect(returnedTree(appSource)).toContain('<ApprovalsCenterPanel />');
  });

  it('App mounts the centre unconditionally — it gates itself on the store flag', () => {
    /* The centre returns null while `approvalsCenterOpen` is false, so no
     * conditional wrapper is needed and none should creep in: a gate in App
     * would be a second place that can silently switch the surface off. */
    const line = returnedTree(appSource)
      .split('\n')
      .find((l) => l.includes('<ApprovalsCenterPanel />')) as string;
    expect(line).toBeTruthy();
    expect(line.trim()).toBe('<ApprovalsCenterPanel />');
  });

  it('the centre imports both approval panels from their real module paths', () => {
    expect(centerSource).toContain("from '../capability/CapabilityRequestPanel'");
    expect(centerSource).toContain("from '../skill/SkillRequestPanel'");
    expect(typeof CapabilityRequestPanel).toBe('function');
    expect(typeof SkillRequestPanel).toBe('function');
  });

  it('the centre renders both approval panels inside the tree it returns', () => {
    const tree = returnedTree(centerSource);
    expect(tree).toContain('<CapabilityRequestPanel');
    expect(tree).toContain('<SkillRequestPanel');
  });

  it('BridgePanel renders an APPROVALS section that opens the centre', () => {
    /* The Bridge is now the only path a Captain has to the centre, so the
     * section and its expand wiring are part of the reachability chain. */
    const tree = returnedTree(bridgeSource);
    expect(tree).toContain('title="Approvals"');
    expect(tree).toContain('approvalsCenterOpen: true');
  });

  it('BridgePanel gates the APPROVALS section on there being pending requests', () => {
    /* HXI #9 — the section rises and recedes. An always-present empty section
     * would be the same clutter the floating stack was. */
    expect(returnedTree(bridgeSource)).toContain('pendingApprovals.length > 0 &&');
  });

  it('the APPROVALS section carries no stationId — it is feed, not a station', () => {
    /* `BridgeSection` keys its accent edge off `stationId`; passing one here
     * would give a feed item the command-station treatment (HXI #9). */
    const tree = returnedTree(bridgeSource);
    const titleAt = tree.indexOf('title="Approvals"');
    expect(titleAt).toBeGreaterThan(-1);
    const tagStart = tree.lastIndexOf('<BridgeSection', titleAt);
    expect(tagStart).toBeGreaterThan(-1);
    // Props run from the tag start to the line that closes the opening tag.
    // `>` inside an `onExpand={() => ...}` arrow makes a bare indexOf('>')
    // unreliable, so walk lines until one is exactly the closing angle.
    const lines = tree.slice(tagStart).split('\n');
    const closeAt = lines.findIndex((l, i) => i > 0 && l.trim() === '>');
    expect(closeAt).toBeGreaterThan(0);
    const props = lines.slice(0, closeAt).join('\n');
    expect(props).toContain('title="Approvals"');
    expect(props).not.toContain('stationId');
  });

  it('App no longer pins the approval panels over the BRIDGE toggle', () => {
    /* BF-710's wrapper sat at `top: 12, right: 12, zIndex: 26`; the AD-325
     * BRIDGE toggle is at `top: 12, right: 12, zIndex: 25`. Nothing in App may
     * claim that band again — the commercial-overlay badge holds the mirrored
     * top-LEFT slot and is unaffected. */
    const tree = returnedTree(appSource);
    expect(tree).not.toContain('zIndex: 26');
    expect(tree).not.toContain('<CapabilityRequestPanel');
    expect(tree).not.toContain('<SkillRequestPanel');
  });
});
