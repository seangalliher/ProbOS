/* Approvals centre — the dedicated approve/deny experience (AD-1201)
 *
 * BF-710 mounted the two approval panels in a fixed top-right stack that
 * covered the AD-325 BRIDGE toggle and read as raw cards floating over the
 * canvas. The Bridge is the attention surface, so pending approvals now appear
 * as an APPROVALS activity-feed section there; its Expand affordance opens this
 * centre — the "summary in the Bridge, click for the full experience" idiom the
 * Communications / Operations / Engineering stations already use.
 *
 * This is a host, not a rewrite. CapabilityRequestPanel (AD-857) and
 * SkillRequestPanel (AD-908) already carry working approve/deny, the reason
 * field and the correct empty-state behaviour; they keep owning their own
 * request detail and decide calls. The centre supplies the frame, the close
 * control and the empty state, and refreshes the shared store slice after a
 * decision so the Bridge count does not lag behind what the Captain just did.
 *
 * HXI Principle #3: inline SVG glyphs only, no emoji. Overlay geometry matches
 * the McpServersPanel idiom (fixed inset 0, zIndex 30, self-gated on a store
 * flag) so it sits above the Bridge rather than fighting it for the same band.
 */

import { useCallback, useEffect, useRef } from 'react';
import { useStore, type DecidedApproval } from '../../store/useStore';
import { Close } from '../icons/Glyphs';
import CapabilityRequestPanel from '../capability/CapabilityRequestPanel';
import SkillRequestPanel from '../skill/SkillRequestPanel';

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666680';

/* BF-724: the same focusable set WorkspaceFilesRail's start-work dialog uses,
 * so the two modal surfaces cannot drift on what "focusable" means. The dialog
 * container carries tabIndex={-1} and is excluded by the final clause. */
const FOCUSABLE_SELECTOR =
  'button:not(:disabled), input:not(:disabled), textarea:not(:disabled),'
  + ' select:not(:disabled), [tabindex]:not([tabindex="-1"])';

export function ApprovalsCenterPanel() {
  const open = useStore(s => s.approvalsCenterOpen);
  const pendingApprovals = useStore(s => s.pendingApprovals);
  const refreshApprovals = useStore(s => s.refreshPendingApprovals);
  const recordDecision = useStore(s => s.recordApprovalDecision);

  const dialogRef = useRef<HTMLDivElement | null>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  const close = useCallback(() => useStore.setState({ approvalsCenterOpen: false }), []);

  /* BF-724: focus transfer, in and back out.
   *
   * AD-1201 shipped this overlay as a bare `div`: no role, no modality, and no
   * focus handling. A keyboard user who reached the Bridge could not open it,
   * and if they had, focus would still have been sitting behind it on the
   * control they pressed — the overlay covers the whole viewport, so tabbing
   * would have walked an invisible page.
   *
   * The opener is captured from the live document rather than passed in, so any
   * future entry point (a palette command, a notification) gets the return trip
   * for free. `document.body` is not a real opener; restoring focus to it would
   * blur whatever the close handler moved focus to. */
  useEffect(() => {
    if (!open) return;
    const active = document.activeElement;
    openerRef.current =
      active instanceof HTMLElement && active !== document.body ? active : null;
    dialogRef.current?.focus();
    return () => {
      const opener = openerRef.current;
      openerRef.current = null;
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  /* Escape dismisses; Tab cycles inside. Handled on the dialog rather than the
   * document because focus never leaves it — and stopping propagation keeps an
   * Escape meant for this overlay from also closing whatever is behind it. */
  const onKeyDown = useCallback((event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close();
      return;
    }
    if (event.key !== 'Tab') return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    event.preventDefault();
    /* `querySelectorAll('*')` then `.matches(...)`, NOT
     * `querySelectorAll(FOCUSABLE_SELECTOR)`. The selector-list form does not
     * return document order under jsdom — it groups by selector. Measured on
     * this dialog's own shape (close button, then reason input, Approve, Deny)
     * the list form yields `[close, approve, deny, reason]` while `'*'` yields
     * the real `[close, reason, approve, deny]`, so Tab off Deny wrapped onto
     * the reason field instead of back to the top. WorkspaceFilesRail's trap
     * already walks `'*'` for exactly this reason; the shape is load-bearing,
     * not stylistic. */
    const controls = Array.from(dialog.querySelectorAll<HTMLElement>('*'))
      .filter(control => control.isConnected && control.matches(FOCUSABLE_SELECTOR));
    if (controls.length === 0) {
      dialog.focus();
      return;
    }
    const currentIndex = controls.indexOf(document.activeElement as HTMLElement);
    const nextIndex = currentIndex < 0
      ? (event.shiftKey ? controls.length - 1 : 0)
      : (currentIndex + (event.shiftKey ? -1 : 1) + controls.length) % controls.length;
    controls[nextIndex].focus();
  }, [close]);

  /* The hosted panels drop a decided request from their own list immediately.
   * Re-reading the shared slice keeps the Bridge section and the BRIDGE badge
   * in step instead of showing a stale count until the next 10s poll.
   *
   * BF-723: record the decision centrally BEFORE re-reading. The refresh alone
   * was not enough — a failed or late GET could hand back the row that was just
   * decided, and the shared slice had no way to know it should not believe it.
   * The tombstone is what makes the refresh result reconcilable. */
  const onDecided = useCallback((decided: DecidedApproval) => {
    recordDecision(decided.queue, decided.id);
    refreshApprovals();
  }, [recordDecision, refreshApprovals]);

  if (!open) return null;

  return (
    <div
      ref={dialogRef}
      data-testid="approvals-center-panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="approvals-center-title"
      tabIndex={-1}
      onKeyDown={onKeyDown}
      style={{
        position: 'fixed', inset: 0, zIndex: 30, background: 'rgba(6,6,12,0.94)',
        backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        display: 'flex', flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace", color: '#c8d0e0',
        // The container is focused programmatically on open; it is a region,
        // not a control, so it must not paint a focus ring (HXI #3).
        outline: 'none',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div>
          <div id="approvals-center-title" style={{ fontSize: 14, color: ACTIVE_AMBER, letterSpacing: 1 }}>
            APPROVALS ({pendingApprovals.length})
          </div>
          <div style={{ fontSize: 10, color: DIM, marginTop: 2 }}>
            Crew waiting on a decision — approve or deny with a reason.
          </div>
        </div>
        <button
          data-testid="approvals-center-close"
          onClick={close}
          aria-label="Close Approvals"
          style={{
            background: 'none', border: '1px solid rgba(255,255,255,0.15)',
            borderRadius: 4, color: DIM, width: 28, height: 28, cursor: 'pointer',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <Close size={14} />
        </button>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 18px 24px' }}>
        <div style={{ maxWidth: 620 }}>
          <CapabilityRequestPanel onDecided={onDecided} />
          <SkillRequestPanel onDecided={onDecided} />
          {pendingApprovals.length === 0 && (
            <div
              data-testid="approvals-center-empty"
              style={{
                fontSize: 11, color: DIM, fontStyle: 'italic',
                textAlign: 'center', padding: '48px 0',
              }}
            >
              No decisions pending.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ApprovalsCenterPanel;
