import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import CrewCollaborationPanel from './CrewCollaborationPanel';
import { useStore } from '../../store/useStore';
import type {
  LegacyCrewChildView,
  LegacyCrewVerdict,
  LegacyCrewWorkItemView,
} from '../../store/types';

/**
 * BF-836 (#1301): a verification defect rendered as `rejected`.
 *
 * BF-784 put `verification_defect` into the durable records so the trail could
 * tell "the verifier failed" from "the work was refused". The API projection
 * dropped it, so this panel showed the Captain the second when the first had
 * happened -- the exact conflation BF-777 introduced the field to prevent.
 *
 * These drive the real panel through the real fetch path, so the `verdict`
 * object has to survive `isLegacyCrewVerdict`'s EXACT-key check to render at
 * all. A test that mounted `SubtaskCard` directly would skip that validator,
 * which is the coupling this change is most likely to break.
 */

function legacyItem(id: string, title: string, parentId: string | null): LegacyCrewWorkItemView {
  return {
    id,
    title,
    description: 'Legacy crew work',
    work_type: 'task',
    status: 'in_progress',
    priority: 1,
    parent_id: parentId,
    project_id: null,
    depends_on: [],
    assigned_to: 'facilitator-1',
    created_by: 'captain',
    created_at: 1,
    updated_at: 2,
    due_at: null,
    estimated_tokens: null,
    actual_tokens: 0,
    trust_requirement: 0.5,
    required_capabilities: [],
    tags: [],
    metadata: {},
    steps: [],
    verification: {},
    schedule: {},
    ttl_seconds: null,
    template_id: null,
  };
}

function verdict(overrides: Partial<LegacyCrewVerdict>): LegacyCrewVerdict {
  return {
    accepted: false,
    confidence: 0.2,
    critique: 'the verifier raised',
    verifier_agent_id: 'verifier-1',
    verification_defect: false,
    ...overrides,
  };
}

/**
 * Glyph assertions, scoped to the subtask card and matching WHOLE path data.
 *
 * Review proved the first version too loose: a document-wide substring search
 * still passed when the circle was deleted from the "circle-and-dash", when a
 * diagonal was deleted from the cross, and when only the size was reverted.
 * The same fragments also appear in other components.
 */
function cardSvgs(): SVGSVGElement[] {
  const card = document.querySelector('[data-testid="crew-subtask-card"]');
  return card ? Array.from(card.querySelectorAll('svg')) : [];
}

function hasRejectionCross(): boolean {
  return cardSvgs().some((svg) => {
    const paths = Array.from(svg.querySelectorAll('path'))
      .map((p) => p.getAttribute('d'));
    return paths.length === 1 && paths[0] === 'M6 6l12 12M18 6L6 18';
  });
}

function hasUnverifiedGlyph(): boolean {
  return cardSvgs().some((svg) => (
    svg.getAttribute('width') === '13'
    && svg.getAttribute('height') === '13'
    // The circle and the dash must belong to the SAME svg.
    && svg.querySelector('circle') !== null
    && Array.from(svg.querySelectorAll('path'))
      .some((p) => p.getAttribute('d') === 'M8 12h8')
  ));
}

function childWith(v: LegacyCrewVerdict): LegacyCrewChildView {
  // `done`, deliberately: the status glyph is only computed for a settled
  // child, so an `in_progress` fixture renders a spinner and every glyph
  // assertion below would be vacuous.
  return {
    ...legacyItem('c1', 'Child', 'p1'),
    status: 'done',
    verdict: v,
    rounds: 1,
  };
}

function stubTree(child: LegacyCrewChildView, parentStatus = 'in_progress'): void {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({
      parent: { ...legacyItem('p1', 'Legacy goal', null), status: parentStatus },
      children: [child],
      count: 1,
    }),
  } as Response));
}

afterEach(() => {
  cleanup();
  useStore.setState({
    crewSessionsByParent: new Map(),
    liveCrewOwnerParentId: null,
    liveGeneration: null,
    liveSequence: 0,
    liveRepairEpoch: 0,
  });
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('BF-836 verification defect', () => {
  it('renders a verification defect as not-verified, never as rejected', async () => {
    stubTree(childWith(verdict({ verification_defect: true })));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-defect')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-defect').textContent).toContain('not verified');
    // The whole point: the Captain must not read a broken verifier as a
    // judgement about the work.
    expect(screen.getByTestId('crew-subtask-verdict').textContent).not.toContain('rejected');
    // ...and the GLYPH must agree with the words. It did not, until review.
    expect(hasRejectionCross()).toBe(false);
    expect(hasUnverifiedGlyph()).toBe(true);
  });

  it('renders a record written before BF-784 as unavailable, not rejected', async () => {
    // `accepted: false` alone cannot say whether the work was judged poor or
    // never judged. Reporting it as a refusal asserts something the record
    // does not support.
    stubTree(childWith(verdict({ verification_defect: null })));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-defect')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-verdict').textContent)
      .toContain('verification unavailable');
    expect(screen.getByTestId('crew-subtask-verdict').textContent).not.toContain('rejected');
    expect(hasRejectionCross()).toBe(false);
    expect(hasUnverifiedGlyph()).toBe(true);
  });

  it('still renders a genuine refusal as rejected, cross and all', async () => {
    stubTree(childWith(verdict({ verification_defect: false })));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-verdict')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-verdict').textContent).toContain('rejected');
    expect(screen.queryByTestId('crew-subtask-defect')).toBeNull();
    // The counter-case for the glyph assertion above: without this, hiding the
    // cross everywhere would pass.
    expect(hasRejectionCross()).toBe(true);
    expect(hasUnverifiedGlyph()).toBe(false);
  });

  it('still renders an acceptance as accepted', async () => {
    stubTree(childWith(verdict({ accepted: true, verification_defect: false })));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-verdict')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-verdict').textContent).toContain('accepted');
    expect(screen.queryByTestId('crew-subtask-defect')).toBeNull();
  });

  it('degrades to unknown when the backend omits the key entirely', async () => {
    // A verdict missing the key is reached through `isLegacyCrewChildView`,
    // so before the decoder defaulted it, one absent field failed the WHOLE
    // tree and the panel rendered "could not be loaded". Review caught that:
    // absence IS the tri-state's unknown, so refusing it cost the Captain the
    // entire thread to avoid one imprecise glyph. Now it decodes to null.
    const stale = { ...verdict({}) } as Record<string, unknown>;
    delete stale.verification_defect;
    // Built from `childWith` so the child is `done` -- a fixture assembled
    // from `legacyItem` alone is `in_progress` and every glyph assertion
    // below goes vacuous.
    stubTree({
      ...childWith(verdict({})),
      verdict: stale as unknown as LegacyCrewVerdict,
    });
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-verdict')).toBeTruthy();
    expect(screen.queryByText(/could not be loaded/i)).toBeNull();
    // Unknown, not rejected -- and distinct from `defect`: an absent key means
    // we cannot say whether the verifier ran, whereas `defect: true` means it
    // ran and malfunctioned. So "verification unavailable", not "not verified".
    const text = screen.getByTestId('crew-subtask-verdict').textContent ?? '';
    expect(text).toContain('verification unavailable');
    expect(text).not.toContain('rejected');
    expect(text).not.toContain('accepted');
    expect(screen.getByTestId('crew-subtask-defect')
      .getAttribute('data-verdict-state')).toBe('unknown');
    expect(hasRejectionCross()).toBe(false);
    expect(hasUnverifiedGlyph()).toBe(true);
  });

  it('rejects a non-boolean defect flag rather than trusting it', async () => {
    // Mutation found this gap: removing the validator's type check survived
    // every other test here. The decoder reads `=== true`, so a malformed
    // string would not itself report a defect -- it would render `rejected`,
    // asserting a refusal the record does not support. Either way the
    // validator must refuse it.
    const bad = { ...verdict({}), verification_defect: 'false' };
    stubTree({
      ...legacyItem('c1', 'Child', 'p1'),
      verdict: bad as unknown as LegacyCrewVerdict,
      rounds: 1,
    });
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByText(/could not be loaded/i)).toBeTruthy();
    expect(screen.queryByTestId('crew-subtask-defect')).toBeNull();
  });

  it('lets a defect outrank an acceptance', async () => {
    // Reachable and previously untested: review showed that reordering
    // `accepted` ahead of `defect` survived every test in this file. A
    // verifier that failed has said nothing about the work, so it cannot
    // have accepted it.
    stubTree(childWith(verdict({ accepted: true, verification_defect: true })));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-defect')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-verdict').textContent).toContain('not verified');
    expect(screen.getByTestId('crew-subtask-verdict').textContent).not.toContain('accepted');
  });

  it('treats an unjudged record as unavailable, not rejected', async () => {
    // The final fallthrough: `accepted: null` with a recorded `false` flag.
    // Review showed changing that return to `rejected` survived every test.
    stubTree(childWith(verdict({ accepted: null, verification_defect: false })));
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-defect')).toBeTruthy();
    expect(screen.getByTestId('crew-subtask-verdict').textContent)
      .toContain('verification unavailable');
    expect(hasRejectionCross()).toBe(false);
    expect(hasUnverifiedGlyph()).toBe(true);
  });

  // Every wire-reachable combination. The router builds both fields with
  // `.get()`, so all nine are producible; review kept finding one uncovered
  // cell at a time, so the matrix is enumerated rather than sampled.
  const MATRIX: Array<[boolean | null, boolean | null, string]> = [
    [true, false, 'accepted'],
    [true, null, 'accepted'],
    [true, true, 'not verified'],
    [false, false, 'rejected'],
    [false, null, 'verification unavailable'],
    [false, true, 'not verified'],
    [null, false, 'verification unavailable'],
    [null, null, 'verification unavailable'],
    [null, true, 'not verified'],
  ];

  for (const [accepted, defect, label] of MATRIX) {
    it(`renders accepted=${accepted} defect=${defect} as "${label}"`, async () => {
      stubTree(childWith(verdict({ accepted, verification_defect: defect })));
      render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

      const el = await screen.findByTestId('crew-subtask-verdict');
      expect(el.textContent).toContain(label);
      // A defect or an unknown must never also read as a judgement.
      if (label !== 'rejected') expect(el.textContent).not.toContain('rejected');
      if (label !== 'accepted') expect(el.textContent).not.toContain('accepted');
    });
  }

  it('shows a settled child with no verdict as unverified, not a check', async () => {
    // Reachable from the real router: a done child whose parent has no
    // provenance ref, or whose blob is missing. A dim CHECK reads as "fine"
    // for work that nothing verified.
    stubTree(
      { ...legacyItem('c1', 'Child', 'p1'), status: 'done', verdict: null, rounds: null },
    );
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    expect(await screen.findByTestId('crew-subtask-pending')).toBeTruthy();
    expect(hasUnverifiedGlyph()).toBe(true);
    expect(hasRejectionCross()).toBe(false);
  });

  it('does not promise verification once the parent is done', async () => {
    // "awaiting verification" is false for a completed parent -- it is not
    // coming. The router emits a null verdict for exactly that case.
    stubTree(
      { ...legacyItem('c1', 'Child', 'p1'), status: 'done', verdict: null, rounds: null },
      'done',
    );
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    const pending = await screen.findByTestId('crew-subtask-pending');
    expect(pending.textContent).toContain('verification unavailable');
    expect(pending.textContent).not.toContain('awaiting');
  });

  it('still says awaiting while the parent is running', async () => {
    stubTree(
      { ...legacyItem('c1', 'Child', 'p1'), status: 'in_progress', verdict: null, rounds: null },
      'in_progress',
    );
    render(<CrewCollaborationPanel threadId="t1" parentId="p1" />);

    const pending = await screen.findByTestId('crew-subtask-pending');
    expect(pending.textContent).toContain('awaiting verification');
  });
});
