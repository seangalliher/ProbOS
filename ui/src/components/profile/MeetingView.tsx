// AD-920: meeting-mode avatar gallery. A meeting is a live MODE of a group
// chat — the thread stays the transcript; this gallery renders every crew
// participant's VRM avatar at once, bound to the AD-722b-4 fleet
// avatar-telemetry stream (fan-out by agent_id). VRM binaries are
// operator-provided/gitignored, so each slot honest-degrades to an
// AgentAvatarBadge when no .vrm is available (or fails to load). NO voice,
// NO speaking/presence indicators (AD-921/923). HXI #3 — inline SVG only,
// amber palette, no emoji.
import { useState } from 'react';
import { Canvas } from '@react-three/fiber';
import { useStore } from '../../store/useStore';
import type { Agent, AgentProfileData } from '../../store/types';
import { CrewVRM } from './CrewVRM';
import { deriveAgentSignals } from './avatarSignals';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { useFleetAvatarTelemetry } from '../../avatars/useFleetAvatarTelemetry';

const CAPTAIN_PARTICIPANT_ID = 'captain';

/** One gallery cell: a live VRM when the agent has one, else a badge. */
function AvatarSlot({ agentId }: { agentId: string }) {
  const agent = useStore((s) => s.agents.get(agentId)) as Agent | undefined;
  const [loadFailed, setLoadFailed] = useState(false);
  // The store's base Agent type carries neither appearance nor department
  // (both are AgentProfileData fields, hydrated per-agent). Read them via a
  // narrow cast — the same runtime-field pattern GroupChatHeader uses for
  // department. Absent appearance (the CI/dev default — zero .vrm assets)
  // degrades the slot to an AgentAvatarBadge.
  const extra = agent as
    | (Agent & { appearance?: AgentProfileData['appearance']; department?: string })
    | undefined;
  const appearance = extra?.appearance;
  const vrmUrl = appearance?.vrm_url;
  const showVRM = !!vrmUrl && !loadFailed;
  const dept = extra?.department ?? '';
  const callsign = agent?.callsign ?? agentId;

  return (
    <div
      data-testid={`avatar-slot-${agentId}`}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        width: 120, height: 160,
      }}
    >
      <div style={{ width: 112, height: 132, position: 'relative' }}>
        {showVRM ? (
          <Canvas camera={{ position: [0, 1.45, 0.85], fov: 28 }} flat frameloop="always">
            <ambientLight intensity={0.4} />
            <directionalLight position={[1, 2, 2]} intensity={0.6} />
            <CrewVRM
              vrmUrl={vrmUrl!}
              agentId={agentId}
              expressionOverrides={appearance?.expression_overrides ?? {}}
              signals={deriveAgentSignals(agentId, useStore.getState() as unknown as Parameters<typeof deriveAgentSignals>[1])}
              onLoadError={() => setLoadFailed(true)}
              restingExpression={appearance?.dsl?.expression_resting ?? null}
            />
          </Canvas>
        ) : (
          <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
            <AgentAvatarBadge agentId={agentId} callsign={callsign} department={dept} size={32} />
          </div>
        )}
      </div>
      <span
        data-testid={`avatar-caption-${agentId}`}
        style={{ color: '#e0dcd4', fontSize: 11, fontWeight: 600, maxWidth: 112,
                 overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
      >
        {callsign}
      </span>
    </div>
  );
}

export function MeetingView({ threadId }: { threadId: string }) {
  const thread = useStore((s) => s.chatThreads.get(threadId));
  const agents = useStore((s) => s.agents);
  const setAvatarTelemetryFrame = useStore((s) => s.setAvatarTelemetryFrame);

  // Bind to the fleet avatar-telemetry stream while the meeting is open
  // (AD-722b-4 fans out by agent_id). Idempotent with the CognitiveCanvas
  // sink; guarantees liveness even when the canvas is unmounted. v1 reads
  // signals via deriveAgentSignals; the populated avatarTelemetry map is
  // the forward-looking per-avatar binding consumed by AD-921/923.
  useFleetAvatarTelemetry({
    onFrame: (frame) => setAvatarTelemetryFrame(frame.agent_id, frame.type, frame.payload),
  });

  if (!thread) return null;

  const crewIds = (thread.participants ?? [])
    .filter((id) => id !== CAPTAIN_PARTICIPANT_ID)
    .filter((id) => agents.get(id)?.isCrew);

  return (
    <div
      data-testid="meeting-view"
      style={{
        display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center',
        padding: 12, borderBottom: '1px solid rgba(240,176,96,0.15)',
        background: 'rgba(240,176,96,0.04)',
      }}
    >
      {crewIds.length === 0 ? (
        <span style={{ color: '#666680', fontSize: 12 }}>No crew in this meeting yet.</span>
      ) : (
        crewIds.map((id) => <AvatarSlot key={id} agentId={id} />)
      )}
    </div>
  );
}
