// AD-920: meeting-mode avatar gallery. A meeting is a live MODE of a group
// chat — the thread stays the transcript; this gallery renders every crew
// participant's VRM avatar at once, bound to the AD-722b-4 fleet
// avatar-telemetry stream (fan-out by agent_id). VRM binaries are
// operator-provided/gitignored, so each slot honest-degrades to an
// AgentAvatarBadge when no .vrm is available (or fails to load). AD-923 adds
// the who's-speaking highlight (amber ring + pulse on the active speaker, the
// others dim — HXI #4 motion = state) and a presence header. HXI #3 — inline
// SVG/CSS only, amber palette, no emoji.
import { useState, useRef, useEffect, type CSSProperties } from 'react';
import { Canvas } from '@react-three/fiber';
import { useStore } from '../../store/useStore';
import type { Agent, AgentProfileData } from '../../store/types';
import { CrewVRM } from './CrewVRM';
import { deriveAgentSignals } from './avatarSignals';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { useFleetAvatarTelemetry } from '../../avatars/useFleetAvatarTelemetry';
import { useCameraStore } from '../../store/useCameraStore';
import { useScreenStore } from '../../store/useScreenStore';
import { getCameraStream } from '../../hooks/useCameraStream';
import { getScreenStream } from '../../hooks/useScreenStream';

const CAPTAIN_PARTICIPANT_ID = 'captain';

/** One gallery cell: a live VRM when the agent has one, else a badge. */
function AvatarSlot({
  agentId,
  speaking = false,
  someoneSpeaking = false,
}: {
  agentId: string;
  speaking?: boolean;
  someoneSpeaking?: boolean;
}) {
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

  // AD-923: who's-speaking highlight (HXI #4 motion = state) — a WRAPPER
  // treatment on the inner avatar container only, CrewVRM is untouched.
  //   speaking            -> amber ring + meetingSpeakingPulse, full opacity
  //   dim (someone else)  -> opacity 0.5, no ring/animation
  //   idle (nobody)       -> neutral, full opacity
  const dim = !speaking && someoneSpeaking;
  const innerStyle: CSSProperties = {
    width: 112,
    height: 132,
    position: 'relative',
    borderRadius: 8,
    opacity: dim ? 0.5 : 1,
    transition: 'opacity 0.25s ease',
    ...(speaking
      ? {
          boxShadow: '0 0 0 2px #f0b060, 0 0 12px rgba(240,176,96,0.55)',
          animation: 'meetingSpeakingPulse 1.6s ease-in-out infinite',
        }
      : {}),
  };

  return (
    <div
      data-testid={`avatar-slot-${agentId}`}
      data-speaking={speaking ? 'true' : 'false'}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        width: 120, height: 160,
      }}
    >
      <div data-dim={dim ? 'true' : 'false'} style={innerStyle}>
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

/**
 * AD-939: the Captain's gallery slot. The Captain is the meeting host and is
 * always present; this slot renders their LIVE video when a camera or screen
 * is shared (camera preferred — the AD-733 / AD-733-2 streams, read-only),
 * else an amber stroke-SVG person glyph (HXI #3 — no emoji). It is the first
 * cell in the gallery, ahead of the crew AvatarSlots. No new capture is
 * started here: the existing MediaStream is mirrored into a muted <video>.
 */
function CaptainSlot() {
  const cameraActive = useCameraStore((s) => s.active);
  const screenActive = useScreenStore((s) => s.active);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // Prefer the camera stream, else the screen stream. Attach the live
  // MediaStream to the muted <video>; detach on teardown / source change.
  useEffect(() => {
    const stream = cameraActive ? getCameraStream() : screenActive ? getScreenStream() : null;
    const el = videoRef.current;
    if (el && stream) {
      el.srcObject = stream;
      el.play?.().catch(() => {});
    }
    return () => {
      if (el) el.srcObject = null;
    };
  }, [cameraActive, screenActive]);
  const hasVideo = cameraActive || screenActive;
  return (
    <div
      data-testid="captain-slot"
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        width: 120, height: 160,
      }}
    >
      <div
        style={{
          width: 112, height: 132, position: 'relative', borderRadius: 8,
          overflow: 'hidden', background: 'rgba(255,255,255,0.04)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        {hasVideo ? (
          <video
            data-testid="captain-video"
            ref={videoRef}
            autoPlay
            muted
            playsInline
            style={{ width: '100%', height: '100%', objectFit: 'cover' }}
          />
        ) : (
          <div
            data-testid="captain-icon"
            style={{
              width: 64, height: 64, borderRadius: '50%',
              background: 'rgba(240,176,96,0.12)', border: '1px solid rgba(240,176,96,0.4)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}
          >
            <svg
              width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#f0b060"
              strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
            >
              <circle cx="12" cy="8" r="4" />
              <path d="M4 21c0-4 3.5-6 8-6s8 2 8 6" />
            </svg>
          </div>
        )}
      </div>
      <span style={{ color: '#f0b060', fontSize: 11, fontWeight: 600 }}>You (Captain)</span>
    </div>
  );
}

export function MeetingView({
  threadId,
  speakingAgentId = null,
}: {
  threadId: string;
  speakingAgentId?: string | null;
}) {
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

  // AD-923: someone is speaking iff the indicator seam is non-null. The
  // matching slot lights; the others dim (see AvatarSlot).
  const someoneSpeaking = speakingAgentId != null;

  return (
    <div
      data-testid="meeting-view"
      style={{
        display: 'flex', flexDirection: 'column', gap: 8,
        padding: 12, borderBottom: '1px solid rgba(240,176,96,0.15)',
        background: 'rgba(240,176,96,0.04)',
      }}
    >
      {/* AD-923: meetingSpeakingPulse keyframes — co-located <style> idiom
          (mirrors CrewCollaborationPanel.tsx:186). Browser-real motion = state
          (HXI #4); jsdom ignores the animation but the inline style/attr is
          asserted in tests. */}
      <style>{`
        @keyframes meetingSpeakingPulse {
          0%, 100% { box-shadow: 0 0 0 2px #f0b060, 0 0 8px rgba(240,176,96,0.4); }
          50% { box-shadow: 0 0 0 2px #f0b060, 0 0 16px rgba(240,176,96,0.8); }
        }
      `}</style>

      {/* AD-923: presence header — crew count + the Captain-present chip. The
          Captain is the viewer (excluded from the gallery), always present
          while the meeting surface is shown. Join/leave needs no new code: the
          gallery re-renders on thread.participants change. */}
      <div
        data-testid="meeting-presence"
        style={{
          display: 'flex', alignItems: 'center', gap: 8,
          fontSize: 11, color: '#a0a0b8',
        }}
      >
        <span>{crewIds.length} in meeting</span>
        <span
          data-testid="captain-present"
          style={{
            color: '#f0b060', fontWeight: 600,
            border: '1px solid rgba(240,176,96,0.3)', borderRadius: 10,
            padding: '1px 8px', fontSize: 10,
          }}
        >
          You (Captain)
        </span>
      </div>

      {/* Avatar gallery */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center' }}>
        {/* AD-939: the Captain (meeting host) is always present and renders
            first — live camera/screen video when shared, else an amber person
            icon. The crew AvatarSlots follow (they now hydrate after AD-938). */}
        <CaptainSlot />
        {crewIds.length === 0 ? (
          <span style={{ color: '#666680', fontSize: 12 }}>No crew in this meeting yet.</span>
        ) : (
          crewIds.map((id) => (
            <AvatarSlot
              key={id}
              agentId={id}
              speaking={id === speakingAgentId}
              someoneSpeaking={someoneSpeaking}
            />
          ))
        )}
      </div>
    </div>
  );
}
