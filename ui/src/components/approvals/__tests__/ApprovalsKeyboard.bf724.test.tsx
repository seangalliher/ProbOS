/**
 * BF-724: the only route to a pending approval could not be operated from a
 * keyboard.
 *
 * AD-1201 put the approvals surface in the Bridge and gave it an expand
 * affordance into a dedicated centre. Every control on that route was a
 * clickable `div`/`span`: no role, no tab stop, no key handler, no
 * `aria-expanded`. The overlay it opened had no `role="dialog"`, no
 * `aria-modal`, no focus transfer or trap and no Escape. A keyboard user could
 * reach BRIDGE and then go no further — Approve and Deny were unreachable.
 *
 * WHY THIS WAS NEVER CAUGHT: every existing reachability test drives the
 * surface with `fireEvent.click`, which dispatches a click on any element
 * whatever its role, tab index or key handling. `fireEvent.click` on a `div`
 * passes identically before and after this fix, so the whole suite stayed green
 * over a control nobody could reach. Nothing below uses it. Focus moves with
 * real Tab keys and controls are activated with real Enter/Space, so every
 * assertion fails if an element stops being a genuine `<button>`.
 *
 * The first test crosses the whole seam — BRIDGE toggle -> Bridge panel ->
 * approval row -> centre -> Approve -> POST. Tests of either half pass against
 * the defect: the Bridge rendered its row correctly and the centre's Approve
 * button always worked. It was the join between them no keyboard could cross.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { useStore } from '../../../store/useStore';
import { BridgePanel } from '../../BridgePanel';
import { IntentSurface } from '../../IntentSurface';
import { ApprovalsCenterPanel } from '../ApprovalsCenterPanel';

const NOW_S = Math.floor(Date.now() / 1000);

const CAPABILITY_ROW = {
  id: 'cap-1',
  agent_id: 'engineering-3',
  kind: 'continue',
  target: 'continue: summarise the incident log',
  rationale: 'cut off after 3 passes',
  work_item_id: null,
  status: 'pending',
  created_at: NOW_S,
  decided_at: null,
  decided_by: '',
  decision_reason: '',
};

/** Flipped by the decide POST so later polls stop re-serving the decided row. */
let decided = false;

function okJson(body: unknown): Response {
  return { ok: true, status: 200, json: async () => body } as Response;
}

/** Routes the capability queue to one pending row; everything else is empty. */
function approvalsFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes('/decide')) { decided = true; return okJson({ ok: true }); }
    if (url.startsWith('/api/capability-requests')) {
      return okJson({ requests: decided ? [] : [CAPABILITY_ROW] });
    }
    if (url.startsWith('/api/skill-requests')) return okJson({ requests: [] });
    return okJson([]);
  });
}

function resetApprovalState(): void {
  decided = false;
  useStore.setState({
    pendingApprovals: [],
    decidedApprovals: new Set<string>(),
    approvalRequestSeq: 0,
    approvalAppliedSeq: { capability: 0, skill: 0 },
    approvalsCenterOpen: false,
    bridgeOpen: false,
    agentTasks: [],
    notifications: [],
    missionControlTasks: [],
    wardRoomDmChannels: [],
    wardRoomUnread: {},
  });
}

/**
 * The composition `App.tsx` mounts: `IntentSurface` (which owns the BRIDGE
 * toggle and renders `BridgePanel`) alongside the self-gating centre.
 * Rendering `App` itself would drag in the three.js canvas and ~20 unrelated
 * panels, so assertions would pass or fail for reasons unrelated to the
 * keyboard route — the same reasoning `App.bf710.test.tsx` records for
 * asserting that caller chain at the source level instead.
 */
function mountApprovalsRoute() {
  return render(
    <>
      <IntentSurface />
      <ApprovalsCenterPanel />
    </>,
  );
}

/** Tab until `predicate` holds, so nothing pins an exact control count. */
async function tabUntil(
  user: ReturnType<typeof userEvent.setup>,
  predicate: (el: Element | null) => boolean,
  limit = 40,
): Promise<HTMLElement> {
  for (let i = 0; i < limit; i += 1) {
    if (predicate(document.activeElement)) return document.activeElement as HTMLElement;
    await user.tab();
  }
  throw new Error(
    `focus never reached the target within ${limit} tab stops`
    + ` (stopped on ${document.activeElement?.outerHTML?.slice(0, 160)})`,
  );
}

/** Enabled focusables inside the overlay, in the order Tab must visit them.
 *  Walks `'*'` rather than a selector list: the list form does not reliably
 *  return document order under jsdom, which is the same trap the production
 *  handler avoids. Building the expectation the same way it builds its own
 *  order would hide a real ordering regression, so this states DOM order
 *  independently. */
function dialogControls(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>('*')).filter(
    el => ['BUTTON', 'INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)
      && !el.hasAttribute('disabled'),
  );
}

beforeEach(() => {
  resetApprovalState();
  vi.stubGlobal('fetch', approvalsFetch());
});

afterEach(() => {
  cleanup();
  resetApprovalState();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('BF-724 the approvals route is operable from the keyboard', () => {
  it('tabs from BRIDGE to a pending approval, opens the centre and approves — no pointer at all', async () => {
    const user = userEvent.setup();
    mountApprovalsRoute();

    // The Captain starts on the BRIDGE toggle and opens the panel with Enter.
    const bridgeToggle = await screen.findByText(/^BRIDGE/);
    bridgeToggle.focus();
    expect(bridgeToggle).toHaveFocus();
    await user.keyboard('{Enter}');
    await waitFor(() => expect(useStore.getState().bridgeOpen).toBe(true));
    await screen.findByTestId('bridge-approval-row');

    // Tab forward until focus lands on the pending approval itself.
    const row = await tabUntil(
      user,
      el => el?.getAttribute('data-testid') === 'bridge-approval-row',
    );
    expect(row.tagName).toBe('BUTTON');

    // Enter opens the centre, and focus follows it in.
    await user.keyboard('{Enter}');
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveFocus();

    // Tab to Approve and activate it — still no pointer.
    const approve = await tabUntil(
      user,
      el => el?.tagName === 'BUTTON' && el.textContent?.trim() === 'Approve',
    );
    expect(approve).toHaveFocus();
    await user.keyboard('{Enter}');

    await waitFor(() =>
      expect(screen.queryByTestId('capability-request-card')).toBeNull());
    expect(
      (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.some(
        ([url]: unknown[]) => String(url) === '/api/capability-requests/cap-1/decide',
      ),
    ).toBe(true);
  });

  it('opens the centre from the expand affordance by keyboard too', async () => {
    const user = userEvent.setup();
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    screen.getByRole('button', { name: 'Expand Approvals to full view' }).focus();
    await user.keyboard('{Enter}');

    expect(useStore.getState().approvalsCenterOpen).toBe(true);
  });
});

describe('BF-724 Enter and Space both activate the semantic controls', () => {
  /* A `<div onClick>` responds to neither. A `<div role="button" tabindex="0">`
   * responds to neither without a hand-written key handler, and hand-written
   * handlers routinely implement Enter and forget Space. Asserting both is what
   * separates a real `<button>` from an imitation of one. */
  it('Space activates the approval row', async () => {
    const user = userEvent.setup();
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    screen.getByTestId('bridge-approval-row').focus();
    await user.keyboard('[Space]');

    expect(useStore.getState().approvalsCenterOpen).toBe(true);
  });

  it('Enter activates the approval row', async () => {
    const user = userEvent.setup();
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    screen.getByTestId('bridge-approval-row').focus();
    await user.keyboard('{Enter}');

    expect(useStore.getState().approvalsCenterOpen).toBe(true);
  });

  it('Space activates the expand affordance', async () => {
    const user = userEvent.setup();
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    screen.getByRole('button', { name: 'Expand Approvals to full view' }).focus();
    await user.keyboard('[Space]');

    expect(useStore.getState().approvalsCenterOpen).toBe(true);
  });

  it('Enter and Space both toggle the collapsible header', async () => {
    const user = userEvent.setup();
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    screen.getByRole('button', { name: /Approvals \(1\)/i }).focus();

    await user.keyboard('{Enter}');
    await waitFor(() => expect(screen.queryByTestId('bridge-approval-row')).toBeNull());

    await user.keyboard('[Space]');
    expect(await screen.findByTestId('bridge-approval-row')).toBeTruthy();
  });
});

describe('BF-724 aria-expanded tracks the collapse state', () => {
  it('reports expanded, then collapsed, then expanded again', async () => {
    const user = userEvent.setup();
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    const disclosure = screen.getByRole('button', { name: /Approvals \(1\)/i });
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');

    disclosure.focus();
    await user.keyboard('{Enter}');
    expect(disclosure).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('bridge-approval-row')).toBeNull();

    await user.keyboard('{Enter}');
    expect(disclosure).toHaveAttribute('aria-expanded', 'true');
    expect(screen.getByTestId('bridge-approval-row')).toBeTruthy();
  });
});

describe('BF-724 the centre is a modal dialog', () => {
  async function openCentre(user: ReturnType<typeof userEvent.setup>) {
    render(
      <>
        <BridgePanel open={true} onClose={() => {}} />
        <ApprovalsCenterPanel />
      </>,
    );
    await screen.findByTestId('bridge-approval-row');
    const opener = screen.getByTestId('bridge-approval-row');
    opener.focus();
    await user.keyboard('{Enter}');
    return { opener, dialog: await screen.findByRole('dialog') };
  }

  it('is announced as a modal dialog with an accessible name', async () => {
    const user = userEvent.setup();
    const { dialog } = await openCentre(user);

    expect(dialog).toHaveAttribute('aria-modal', 'true');
    // Named from the visible heading, so the name cannot drift from the label.
    expect(screen.getByRole('dialog', { name: /APPROVALS \(1\)/i })).toBe(dialog);
  });

  it('gives both decision controls accessible names', async () => {
    const user = userEvent.setup();
    const { dialog } = await openCentre(user);
    const card = await screen.findByTestId('capability-request-card');

    expect(within(card).getByRole('button', { name: 'Approve' })).toBeTruthy();
    expect(within(card).getByRole('button', { name: 'Deny' })).toBeTruthy();
    expect(within(dialog).getByRole('button', { name: 'Close Approvals' })).toBeTruthy();
  });

  it('moves focus into the overlay on open and back to the opener on close', async () => {
    const user = userEvent.setup();
    const { opener, dialog } = await openCentre(user);

    expect(dialog).toHaveFocus();
    expect(opener).not.toHaveFocus();

    await user.keyboard('{Escape}');

    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('Escape dismisses the overlay', async () => {
    const user = userEvent.setup();
    await openCentre(user);

    await user.keyboard('{Escape}');

    expect(useStore.getState().approvalsCenterOpen).toBe(false);
    expect(screen.queryByTestId('approvals-center-panel')).toBeNull();
  });

  it('does not let focus escape — Tab from the last control wraps to the first', async () => {
    const user = userEvent.setup();
    const { dialog } = await openCentre(user);
    await screen.findByTestId('capability-request-card');

    const controls = dialogControls(dialog);
    expect(controls.length).toBeGreaterThan(1);

    // From the dialog container, Tab enters the control list at its head.
    await user.tab();
    expect(controls[0]).toHaveFocus();

    controls[controls.length - 1].focus();
    await user.tab();
    expect(controls[0]).toHaveFocus();

    // …and Shift+Tab off the head wraps back to the tail rather than leaving.
    await user.tab({ shift: true });
    expect(controls[controls.length - 1]).toHaveFocus();
  });
});

describe('BF-724 the visual language is unchanged', () => {
  /* A `<button>` arrives with UA chrome a `<div>` never had. Without these the
   * markup change would drag the appearance with it — most visibly the font:
   * buttons do not inherit `font-family`, so every converted control would drop
   * out of the panel's JetBrains Mono into the UA default. */
  it('neutralises the UA chrome on every control it converted', async () => {
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    const converted = [
      screen.getByRole('button', { name: /Approvals \(1\)/i }),
      screen.getByRole('button', { name: 'Expand Approvals to full view' }),
      screen.getByTestId('bridge-approval-row'),
    ];

    for (const el of converted as HTMLElement[]) {
      expect(el.tagName).toBe('BUTTON');
      expect(el).toHaveAttribute('type', 'button');
      expect(el.style.fontFamily).toBe('inherit');   // UA: buttons carry own font
      expect(el.style.borderStyle).toBe('none');     // UA: 2px outset
      expect(el.style.textAlign).toBe('left');       // UA: center
      // Each control keeps the padding of the div it replaced; only the UA's
      // own `1px 6px` must be gone.
      expect(el.style.padding).not.toBe('1px 6px');
      // The focus ring is drawn from the stylesheet. An inline `outline` would
      // outrank it and hand the UA ring back (HXI #3).
      expect(el.style.outline).toBe('');
      expect(el).toHaveAttribute('data-hxi-focus');
    }

    /* The row is the one converted control that restates its width, because a
     * `div` filled its parent for free. This app sets no global
     * `box-sizing: border-box`, so `width: 100%` without the override would add
     * the 6px side padding on top of the 100% and render the row 12px wider
     * than the div it replaced. */
    const row = screen.getByTestId('bridge-approval-row');
    expect(row.style.width).toBe('100%');
    expect(row.style.boxSizing).toBe('border-box');
  });

  it('draws focus in the panel amber, never the UA default ring', async () => {
    render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    const css = Array.from(document.querySelectorAll('style'))
      .map(s => s.textContent ?? '')
      .join('\n');

    expect(css).toContain('[data-hxi-focus]:focus{outline:none}');
    expect(css).toContain('[data-hxi-focus]:focus-visible{outline:1px solid #f0b060');
  });

  it('nests no interactive control inside another', async () => {
    /* The header holds two SIBLING buttons. A button inside a button is invalid
     * interactive content and is not reliably reachable by assistive tech — it
     * would have reintroduced the defect in a different shape. */
    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);
    await screen.findByTestId('bridge-approval-row');

    for (const button of Array.from(container.querySelectorAll('button'))) {
      expect(button.querySelector('button, [role="button"], a[href], input')).toBeNull();
    }
  });
});
