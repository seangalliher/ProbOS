/* ContextRibbon — dense HUD strip at top of glass layer (AD-390) */

import { useStore } from '../../store/useStore';
import type { AgentTaskView } from '../../store/types';
import type { NotificationView } from '../../store/types';

export type BridgeState = 'idle' | 'autonomous' | 'attention';

export function deriveBridgeState(
  tasks: AgentTaskView[] | null,
  notifications: NotificationView[] | null,
): BridgeState {
  const activeTasks = tasks?.filter(
    t => t.status !== 'done' && t.status !== 'failed',
  ) ?? [];

  const hasAttentionTask = activeTasks.some(t => t.requires_action);
  const hasAttentionNotif = notifications?.some(
    n => n.notification_type === 'action_required' && !n.acknowledged,
  ) ?? false;

  if (hasAttentionTask || hasAttentionNotif) return 'attention';
  if (activeTasks.length > 0) return 'autonomous';
  return 'idle';
}

const STATE_COLORS: Record<BridgeState, string> = {
  idle: '#38c8c0',
  autonomous: '#d4a029',
  attention: '#f0ae40',
};

const STATE_LABELS: Record<BridgeState, string> = {
  idle: 'IDLE',
  autonomous: 'AUTONOMOUS',
  attention: 'ATTENTION',
};

const sep = (
  <span style={{ color: '#333', margin: '0 6px', userSelect: 'none' }}>{'\u00B7'}</span>
);

interface ContextRibbonProps {
  bridgeState: BridgeState;
}

export function ContextRibbon({ bridgeState }: ContextRibbonProps) {
  const agents = useStore((s) => s.agents);
  const agentTasks = useStore((s) => s.agentTasks);
  const notifications = useStore((s) => s.notifications);
  const systemMode = useStore((s) => s.systemMode);

  const activeTasks = agentTasks?.filter(
    t => t.status !== 'done' && t.status !== 'failed',
  ) ?? [];
  const attentionCount =
    (agentTasks?.filter(t => t.requires_action).length ?? 0) +
    (notifications?.filter(n => n.notification_type === 'action_required' && !n.acknowledged).length ?? 0);

  const stateColor = STATE_COLORS[bridgeState];

  return (
    <div
      data-testid="context-ribbon"
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        right: 0,
        height: 32,
        zIndex: 10,
        display: 'flex',
        alignItems: 'center',
        padding: '0 16px',
        background: 'rgba(10, 10, 18, 0.5)',
        backdropFilter: 'blur(8px)',
        WebkitBackdropFilter: 'blur(8px)',
        borderBottom: `1px solid ${stateColor}22`,
        boxShadow: `0 1px 8px ${stateColor}11`,
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 10,
        color: '#666680',
        letterSpacing: 1,
        pointerEvents: 'auto',
        transition: 'border-color 1.2s linear, box-shadow 1.2s linear',
      }}
    >
      {/* Bridge state dot + label */}
      <span style={{
        width: 6, height: 6, borderRadius: '50%',
        background: stateColor, display: 'inline-block',
        marginRight: 6, flexShrink: 0,
        boxShadow: `0 0 6px ${stateColor}66`,
      }} />
      <span style={{ color: stateColor, fontWeight: 600 }}>
        {STATE_LABELS[bridgeState]}
      </span>

      {sep}
      <span>{agents.size} agents</span>

      {sep}
      <span>{activeTasks.length} active</span>

      {attentionCount > 0 && (
        <>
          {sep}
          <span style={{ color: '#f0ae40' }}>{attentionCount} attention</span>
        </>
      )}

      {sep}
      <span>{systemMode}</span>
    </div>
  );
}
