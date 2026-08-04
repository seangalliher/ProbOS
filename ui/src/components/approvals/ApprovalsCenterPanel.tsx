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

import { useCallback } from 'react';
import { useStore } from '../../store/useStore';
import { Close } from '../icons/Glyphs';
import CapabilityRequestPanel from '../capability/CapabilityRequestPanel';
import SkillRequestPanel from '../skill/SkillRequestPanel';

const ACTIVE_AMBER = '#f0b060';
const DIM = '#666680';

export function ApprovalsCenterPanel() {
  const open = useStore(s => s.approvalsCenterOpen);
  const pendingApprovals = useStore(s => s.pendingApprovals);
  const refreshApprovals = useStore(s => s.refreshPendingApprovals);

  const close = useCallback(() => useStore.setState({ approvalsCenterOpen: false }), []);

  /* The hosted panels drop a decided request from their own list immediately.
   * Re-reading the shared slice keeps the Bridge section and the BRIDGE badge
   * in step instead of showing a stale count until the next 10s poll. */
  const onDecided = useCallback(() => { refreshApprovals(); }, [refreshApprovals]);

  if (!open) return null;

  return (
    <div
      data-testid="approvals-center-panel"
      style={{
        position: 'fixed', inset: 0, zIndex: 30, background: 'rgba(6,6,12,0.94)',
        backdropFilter: 'blur(12px)', WebkitBackdropFilter: 'blur(12px)',
        display: 'flex', flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace", color: '#c8d0e0',
      }}
    >
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 18px', borderBottom: '1px solid rgba(255,255,255,0.08)',
      }}>
        <div>
          <div style={{ fontSize: 14, color: ACTIVE_AMBER, letterSpacing: 1 }}>
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
