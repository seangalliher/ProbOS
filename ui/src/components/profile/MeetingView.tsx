// AD-920: meeting-mode avatar gallery. A meeting is a live MODE of a group
// chat — the thread stays the transcript; this gallery renders every crew
// participant's VRM avatar at once, bound to the AD-722b-4 fleet
// avatar-telemetry stream (fan-out by agent_id). VRM binaries are
// operator-provided/gitignored, so each slot honest-degrades to an
// AgentAvatarBadge when no .vrm is available (or fails to load). AD-923 adds
// the who's-speaking highlight (amber ring + pulse on the active speaker, the
// others dim — HXI #4 motion = state) and a presence header. HXI #3 — inline
// SVG/CSS only, amber palette, no emoji.
import { useState, useRef, useEffect, useCallback, type CSSProperties } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { useStore } from '../../store/useStore';
import type { Agent, AgentProfileData } from '../../store/types';
import { CrewVRM } from './CrewVRM';
import { deriveAgentSignals } from './avatarSignals';
import { AgentAvatarBadge } from '../AgentAvatarBadge';
import { useFleetAvatarTelemetry } from '../../avatars/useFleetAvatarTelemetry';
import { useCameraStore } from '../../store/useCameraStore';
import { useScreenStore } from '../../store/useScreenStore';
import { getCameraStream, startCameraStream, stopCameraStream } from '../../hooks/useCameraStream';
import { getScreenStream } from '../../hooks/useScreenStream';
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion';

const CAPTAIN_PARTICIPANT_ID = 'captain';

// AD-974: drag-to-resize the meeting gallery. The Captain drags the handle at
// the bottom of the gallery DOWN to enlarge the video portraits (UP to shrink).
// The scale is clamped and persisted to localStorage so it survives reopen.
const _GALLERY_SCALE_KEY = 'hxi_meeting_gallery_scale';
const _GALLERY_SCALE_MIN = 1;
const _GALLERY_SCALE_MAX = 3;
const _GALLERY_SCALE_PX_PER_UNIT = 220; // vertical drag px per +1.0 scale

export function clampGalleryScale(v: number): number {
  if (!Number.isFinite(v)) return _GALLERY_SCALE_MIN;
  return Math.min(_GALLERY_SCALE_MAX, Math.max(_GALLERY_SCALE_MIN, v));
}

function _loadGalleryScale(): number {
  try {
    const raw = localStorage.getItem(_GALLERY_SCALE_KEY);
    return raw != null ? clampGalleryScale(parseFloat(raw)) : _GALLERY_SCALE_MIN;
  } catch {
    return _GALLERY_SCALE_MIN;
  }
}

// AD-947 / AD-964: face-frame the gallery camera. A bare <Canvas camera={{position}}>
// has no lookAt, so react-three-fiber points the camera at the origin
// [0,0,0] (the floor) — the avatar rendered showing only its FEET. The
// CrewAvatarPopout avoids this with OrbitControls target={[0,1.42,0]}; the
// non-interactive gallery slots have no controls, so aim the camera at the
// avatar's head. AD-964: the target is now PER-AVATAR — ``targetY`` is the
// face-center height (the measured crown minus a fixed head-center drop), so a
// tall and a short crew member each show a centered head instead of a fixed
// 1.42 crop. Until the crown is measured it defaults to ~1.42 (prior framing).
// The camera is moved level with the target (preserving the original gentle
// downward tilt and viewing distance) AND aimed at it. Pure side-effect.
const _HEAD_CENTER_DROP = 0.12; // crown → head/face center (≈ half a head)
const _DEFAULT_FACE_Y = 1.42;   // fallback face height before measurement (AD-947)

function FaceFraming({ targetY }: { targetY: number }) {
  const camera = useThree((s) => s.camera);
  useEffect(() => {
    camera.position.set(0, targetY + 0.03, 0.85);
    camera.lookAt(0, targetY, 0);
    camera.updateProjectionMatrix();
  }, [camera, targetY]);
  return null;
}

/** One gallery cell: a live VRM when the agent has one, else a badge. */
function AvatarSlot({
  agentId,
  speaking = false,
  someoneSpeaking = false,
  scale = 1,
  reducedMotion = false,
}: {
  agentId: string;
  speaking?: boolean;
  someoneSpeaking?: boolean;
  /** AD-974: gallery size multiplier (drag-to-resize). 1 = the original size. */
  scale?: number;
  /** AD-984b: when the OS requests reduced motion, the speaking RING still
   *  renders (state is preserved) but the pulse animation is suppressed. */
  reducedMotion?: boolean;
}) {
  const agent = useStore((s) => s.agents.get(agentId)) as Agent | undefined;
  const [loadFailed, setLoadFailed] = useState(false);
  // AD-964: the avatar's measured crown (top-of-head) world-Y, reported by
  // CrewVRM after load. null until measured → default face framing.
  const [headTopY, setHeadTopY] = useState<number | null>(null);
  // BF-613: the crew VRM lives on the per-agent profile
  // (AgentProfileData.appearance), which is NOT carried on the store's base
  // Agent. The prior code read `appearance` off a cast of the base Agent, so it
  // was ALWAYS undefined in production and every crew slot fell back to the
  // badge even when a .vrm existed (the avatar rendered only in the separate
  // CrewAvatarPopout, which hydrates from GET /api/agent/{id}/profile). Hydrate
  // the same way here; honest-degrade to the badge on any fetch failure (the
  // CI/dev default with zero .vrm assets, and the no-backend case).
  const [appearance, setAppearance] = useState<AgentProfileData['appearance'] | null>(null);
  useEffect(() => {
    if (!agentId || typeof fetch !== 'function') return;
    let cancelled = false;
    fetch(`/api/agent/${agentId}/profile`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (!cancelled && data?.appearance) setAppearance(data.appearance); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [agentId]);
  // Department (badge color) still comes off the store Agent via a narrow cast
  // — the same runtime-field pattern GroupChatHeader uses; it degrades to ''.
  const extra = agent as (Agent & { department?: string }) | undefined;
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
  // AD-974: scale the portrait box (and wrapper/caption below) so the gallery
  // can be dragged larger. Original dims: inner 112x132, wrapper 120x160.
  const innerW = Math.round(112 * scale);
  const innerH = Math.round(132 * scale);
  const innerStyle: CSSProperties = {
    width: innerW,
    height: innerH,
    position: 'relative',
    borderRadius: 8,
    opacity: dim ? 0.5 : 1,
    transition: 'opacity 0.25s ease',
    // AD-984b: the speaking ring (state) ALWAYS applies when speaking; the
    // pulse ANIMATION is gated on the OS reduced-motion preference (HXI #4 —
    // motion encodes state, but respect the accessibility opt-out).
    ...(speaking
      ? {
          boxShadow: '0 0 0 2px #f0b060, 0 0 12px rgba(240,176,96,0.55)',
          ...(reducedMotion ? {} : { animation: 'meetingSpeakingPulse 1.6s ease-in-out infinite' }),
        }
      : {}),
  };

  return (
    <div
      data-testid={`avatar-slot-${agentId}`}
      data-speaking={speaking ? 'true' : 'false'}
      style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
        width: Math.round(120 * scale), height: Math.round(160 * scale),
      }}
    >
      <div data-dim={dim ? 'true' : 'false'} style={innerStyle}>
        {showVRM ? (
          <Canvas camera={{ position: [0, 1.45, 0.85], fov: 28 }} flat frameloop="always">
            <FaceFraming targetY={headTopY != null ? headTopY - _HEAD_CENTER_DROP : _DEFAULT_FACE_Y} />
            <ambientLight intensity={0.4} />
            <directionalLight position={[1, 2, 2]} intensity={0.6} />
            <CrewVRM
              vrmUrl={vrmUrl!}
              agentId={agentId}
              expressionOverrides={appearance?.expression_overrides ?? {}}
              signals={deriveAgentSignals(agentId, useStore.getState() as unknown as Parameters<typeof deriveAgentSignals>[1])}
              onLoadError={() => setLoadFailed(true)}
              onHeadY={setHeadTopY}
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
        style={{ color: '#e0dcd4', fontSize: 11, fontWeight: 600, maxWidth: innerW,
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
function CaptainSlot({ scale = 1 }: { scale?: number }) {
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
        width: Math.round(120 * scale), height: Math.round(160 * scale),
      }}
    >
      <div
        style={{
          width: Math.round(112 * scale), height: Math.round(132 * scale),
          position: 'relative', borderRadius: 8,
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
      {/* BF-613: turn the Captain's camera on/off from inside the meeting to
          share it with the crew. Drives the SAME global camera the rest of the
          HXI uses (startCameraStream is idempotent); the slot above reflects
          the live stream once active. Stroke-SVG only, amber when on (HXI #3). */}
      <button
        data-testid="captain-camera-toggle"
        onClick={() => { if (cameraActive) { void stopCameraStream(); } else { void startCameraStream(); } }}
        aria-label={cameraActive ? 'Turn camera off' : 'Turn camera on'}
        aria-pressed={cameraActive}
        title={cameraActive ? 'Turn camera off' : 'Turn camera on'}
        style={{
          display: 'flex', alignItems: 'center', gap: 4,
          background: 'none', border: 'none', cursor: 'pointer', padding: '2px 4px',
          color: cameraActive ? '#f0b060' : '#888', fontSize: 10, fontWeight: 600,
        }}
      >
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
        >
          <path d="M23 7l-7 5 7 5V7z" />
          <rect x="1" y="5" width="15" height="14" rx="2" ry="2" />
        </svg>
        {cameraActive ? 'Camera on' : 'Camera off'}
      </button>
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

  // AD-974: persisted gallery scale + the drag-to-resize handle. The Captain
  // drags the handle at the bottom of the gallery DOWN to enlarge the portraits
  // (UP to shrink); the value is clamped [1,3] and saved on mouse-up so it
  // survives reopen. The ref mirrors the latest scale so the mouse-up persist
  // writes the final value (not the stale closure value from mousedown).
  const [galleryScale, setGalleryScale] = useState<number>(_loadGalleryScale);
  const galleryScaleRef = useRef(galleryScale);
  useEffect(() => { galleryScaleRef.current = galleryScale; }, [galleryScale]);
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startScale = galleryScaleRef.current;
    const onMove = (ev: MouseEvent) => {
      const next = clampGalleryScale(
        startScale + (ev.clientY - startY) / _GALLERY_SCALE_PX_PER_UNIT,
      );
      galleryScaleRef.current = next;
      setGalleryScale(next);
    };
    const onUp = () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      try { localStorage.setItem(_GALLERY_SCALE_KEY, String(galleryScaleRef.current)); } catch { /* Tier-2 */ }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, []);

  if (!thread) return null;

  const crewIds = (thread.participants ?? [])
    .filter((id) => id !== CAPTAIN_PARTICIPANT_ID)
    .filter((id) => agents.get(id)?.isCrew);

  // AD-923: someone is speaking iff the indicator seam is non-null. The
  // matching slot lights; the others dim (see AvatarSlot).
  const someoneSpeaking = speakingAgentId != null;
  // AD-984b: OS reduced-motion preference. Gates the speaking pulse animation
  // (the ring still renders) — honest-degrades to false without matchMedia.
  const reducedMotion = usePrefersReducedMotion();

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
      <div
        role="group"
        aria-label="Meeting participants"
        style={{ display: 'flex', flexWrap: 'wrap', gap: 12, justifyContent: 'center' }}
      >
        {/* AD-939: the Captain (meeting host) is always present and renders
            first — live camera/screen video when shared, else an amber person
            icon. The crew AvatarSlots follow (they now hydrate after AD-938). */}
        <CaptainSlot scale={galleryScale} />
        {crewIds.length === 0 ? (
          <span style={{ color: '#9a9ab2', fontSize: 12 }}>No crew in this meeting yet.</span>
        ) : (
          crewIds.map((id) => (
            <AvatarSlot
              key={id}
              agentId={id}
              speaking={id === speakingAgentId}
              someoneSpeaking={someoneSpeaking}
              scale={galleryScale}
              reducedMotion={reducedMotion}
            />
          ))
        )}
      </div>

      {/* AD-974: drag-to-resize handle. Drag DOWN to enlarge the video
          portraits, UP to shrink (cursor: ns-resize). Lives BELOW the gallery
          so the screen-pixel drag math is unaffected by the scaled content.
          Stroke/amber grip, no emoji (HXI #3). */}
      <div
        data-testid="meeting-resize-handle"
        onMouseDown={onResizeMouseDown}
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize meeting video"
        title="Drag to resize the video"
        style={{
          height: 12, cursor: 'ns-resize', flexShrink: 0,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}
      >
        <div style={{ width: 48, height: 3, borderRadius: 2, background: 'rgba(240,176,96,0.4)' }} />
      </div>
    </div>
  );
}
