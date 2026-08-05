/**
 * BF-716: the Bridge showed a blocked agent, but nothing about it read as urgent.
 *
 * Reported by the Captain against a live vessel: "I see the approval in the
 * bridge. there wasn't an obvious notification that got my attention."
 *
 * Three separate defects in what AD-1201 shipped, all visible in one screenshot:
 *
 *   1. ORDER    APPROVALS (1) rendered BELOW PERSONNEL (0), SCIENCE (0),
 *               OPERATIONS (0), ENGINEERING (0) and COMMAND (0). A blocked
 *               agent was outranked by five sections containing nothing,
 *               because the whole activity feed renders after every station.
 *               HXI #9: pending decisions rise to the top.
 *
 *   2. CONTENT  The row rendered `kind` + `agent_id` -> "CONTINUE
 *               counselor_counselor_0_67c601cb". `target` — which BF-709 had
 *               just fixed to carry the Captain's raw request rather than the
 *               assembled prompt — was fetched, stored, and never displayed.
 *
 *   3. MOTION   Nothing distinguished it from a station at rest. HXI #4:
 *               motion communicates state.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { BridgePanel } from '../BridgePanel';
import { useStore } from '../../store/useStore';
import type { PendingApproval } from '../../store/useStore';

const APPROVAL: PendingApproval = {
  id: 'a386c83e-62ba-484b-b9c9-01db8ba91921',
  queue: 'capability',
  agent_id: 'counselor_counselor_0_67c601cb',
  kind: 'continue',
  // The real target from the live vessel, post-BF-709.
  target:
    'continue: For each of the top 15 Python packages on PyPI, fetch its '
    + 'project page and record the maintainer, licence and latest version.',
  created_at: Date.now() / 1000 - 420,
};

function seed(approvals: PendingApproval[]) {
  useStore.setState({
    pendingApprovals: approvals,
    bridgeOpen: true,
  } as never);
}

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('no backend')));
  seed([APPROVAL]);
});

afterEach(() => {
  vi.unstubAllGlobals();
  useStore.setState({ pendingApprovals: [] } as never);
});

describe('BF-716: a pending approval outranks stations at rest', () => {
  it('renders the approvals section before every command station', () => {
    // Arrange / Act
    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert — compare DOM order, which is what the Captain's eye follows.
    const headers = Array.from(
      container.querySelectorAll('[data-station], [data-alerting]'),
    );
    const approvalsIdx = headers.findIndex(
      h => h.getAttribute('data-alerting') === 'true',
    );
    const firstStationIdx = headers.findIndex(h => h.hasAttribute('data-station'));

    expect(approvalsIdx).toBeGreaterThanOrEqual(0);
    expect(firstStationIdx).toBeGreaterThanOrEqual(0);
    expect(approvalsIdx).toBeLessThan(firstStationIdx);
  });

  it('does not render an approvals section when nothing is pending', () => {
    // Arrange
    seed([]);

    // Act
    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert — it must still recede; hoisting is not permanent promotion.
    expect(container.querySelector('[data-alerting="true"]')).toBeNull();
    expect(screen.queryByTestId('bridge-approval-row')).toBeNull();
  });
});

describe('BF-716: the row leads with the ask, not the agent id', () => {
  it('renders the readable target BF-709 produced', () => {
    // Act
    render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert
    const ask = screen.getByTestId('bridge-approval-ask');
    expect(ask.textContent).toContain('top 15 Python packages on PyPI');
  });

  it('does not lead with the opaque agent id', () => {
    // Act
    render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert — the agent id is not the headline. This is the exact string the
    // Captain saw and could not act on.
    const ask = screen.getByTestId('bridge-approval-ask');
    expect(ask.textContent).not.toBe('counselor_counselor_0_67c601cb');
  });

  it('falls back to the agent id when the target is empty', () => {
    // Arrange — honest degrade: something is still better than an empty row.
    seed([{ ...APPROVAL, target: '   ' }]);

    // Act
    render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert
    expect(screen.getByTestId('bridge-approval-ask').textContent).toBe(
      'counselor_counselor_0_67c601cb',
    );
  });

  it('still shows the kind so the decision type is glanceable', () => {
    // Act
    render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert — addressed by testid, because the target text also begins with
    // "continue:" and a loose /continue/i matches both.
    expect(screen.getByTestId('bridge-approval-kind').textContent).toBe('continue');
  });
});

describe('BF-716: motion marks it as waiting on the Captain', () => {
  it('marks the approvals section as alerting', () => {
    // Act
    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert
    expect(container.querySelector('[data-alerting="true"]')).toBeTruthy();
  });

  it('is the ONLY alerting section — if everything pulses, nothing does', () => {
    // Act
    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert
    expect(container.querySelectorAll('[data-alerting="true"]').length).toBe(1);
  });

  it('carries no stationId — it is a feed item, not a command station', () => {
    // Act
    const { container } = render(<BridgePanel open={true} onClose={() => {}} />);

    // Assert — hoisting it must not reclassify it (AD-1201's rule survives).
    const alerting = container.querySelector('[data-alerting="true"]');
    expect(alerting?.hasAttribute('data-station')).toBe(false);
  });
});
