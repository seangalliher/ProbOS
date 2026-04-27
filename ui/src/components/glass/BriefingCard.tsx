/* BriefingCard — return-to-bridge summary after Captain absence (AD-390) */

import type { BridgeState } from './ContextRibbon';
import { StatusDone } from '../icons/Glyphs';

const STATE_LABELS: Record<BridgeState, string> = {
  idle: 'Idle',
  autonomous: 'Autonomous',
  attention: 'Attention Required',
};

interface BriefingCardProps {
  completedCount: number;
  newNotifCount: number;
  bridgeState: BridgeState;
  onDismiss: () => void;
}

export function BriefingCard({ completedCount, newNotifCount, bridgeState, onDismiss }: BriefingCardProps) {
  return (
    <div
      data-testid="briefing-card"
      onClick={onDismiss}
      style={{
        position: 'absolute',
        top: '35%',
        left: '50%',
        transform: 'translateX(-50%)',
        width: 320,
        padding: '16px 20px',
        background: 'rgba(26, 26, 46, 0.8)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(255, 255, 255, 0.08)',
        borderRadius: 4,
        boxShadow: '0 4px 20px rgba(0, 0, 0, 0.5)',
        cursor: 'pointer',
        pointerEvents: 'auto',
        zIndex: 15,
        animation: 'briefing-fade-in 0.3s ease-out',
      }}
    >
      <div style={{
        fontFamily: "'Inter', sans-serif",
        fontSize: 14,
        fontWeight: 600,
        color: '#e0e0e0',
        marginBottom: 12,
      }}>
        While you were away:
      </div>

      <div style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 11,
        color: '#808090',
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}>
        {completedCount > 0 && (
          <div>
            <span style={{ color: '#50c878', marginRight: 8 }}><StatusDone size={8} /></span>
            {completedCount} task{completedCount !== 1 ? 's' : ''} completed
          </div>
        )}
        {newNotifCount > 0 && (
          <div>
            <span style={{ color: '#5090d0', marginRight: 8 }}><StatusDone size={8} /></span>
            {newNotifCount} new notification{newNotifCount !== 1 ? 's' : ''}
          </div>
        )}
        <div>
          <span style={{ color: '#666', marginRight: 8 }}><StatusDone size={8} /></span>
          Bridge: {STATE_LABELS[bridgeState]}
        </div>
      </div>

      <div style={{
        marginTop: 12,
        fontSize: 9,
        color: '#555',
        fontFamily: "'JetBrains Mono', monospace",
        letterSpacing: 1,
      }}>
        CLICK TO DISMISS
      </div>
    </div>
  );
}
