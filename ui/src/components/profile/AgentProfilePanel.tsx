import { useState, useRef, useCallback, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { ProfileChatTab } from './ProfileChatTab';
import { ArtifactDrawer } from '../artifacts/ArtifactDrawer';
import { ProfileWorkTab } from './ProfileWorkTab';
import { ProfileInfoTab } from './ProfileInfoTab';
import { ProfileServiceTab } from './ProfileServiceTab';
import { ProfileHealthTab } from './ProfileHealthTab';
import { ProfileMemoryTab } from './ProfileMemoryTab';
import { SelfImageTab } from './SelfImageTab';
import { CrewAvatarPopout } from './CrewAvatarPopout';
import { deriveAgentSignals } from './avatarSignals';
import { isGroupChat, chatDisplayName, hostAgentId } from '../chats/chatFilters';
import { isWorkspaceRoom } from '../workspace/isWorkspaceRoom';
import type { AgentProfileData, AvatarDSLDict } from '../../store/types';

type ProfileTab = 'chat' | 'work' | 'profile' | 'health' | 'memory' | 'self_image' | 'service';

const TAB_LABELS: { key: ProfileTab; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'work', label: 'Work' },
  { key: 'memory', label: 'Memory' },
  { key: 'profile', label: 'Profile' },
  { key: 'service', label: 'Service' },
  { key: 'health', label: 'Health' },
  { key: 'self_image', label: 'Self-image' },
];

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

export function AgentProfilePanel() {
  const activeProfileAgent = useStore((s) => s.activeProfileAgent);
  const agents = useStore((s) => s.agents);
  const pos = useStore((s) => s.profilePanelPos);
  const poolToGroup = useStore((s) => s.poolToGroup);
  // AD-965: the active chat thread (if any) + the thread map, so the panel can
  // tell when it is hosting a GROUP and present a neutral room identity.
  const activeProfileThreadId = useStore((s) => s.activeProfileThreadId);
  const chatThreads = useStore((s) => s.chatThreads);

  // AD-954a: the group/call surface is keyed by the THREAD, not by
  // activeProfileAgent. Detect the active group thread (>=2 crew) from
  // activeProfileThreadId, and derive the ANCHOR agent — the host id
  // ProfileChatTab needs for its 1:1-fallback plumbing + hostCallsign — FROM
  // that thread's participants (hostAgentId = first crew). So the room renders
  // from thread.id and survives an absent/stale activeProfileAgent; a 1:1 keeps
  // activeProfileAgent as its key, byte-identical.
  const activeGroupThread = (() => {
    const tid = activeProfileThreadId;
    if (!tid) return null;
    const t = chatThreads.get(tid);
    return t && isGroupChat(t, agents) ? t : null;
  })();
  const isGroupSurface = activeGroupThread !== null;
  // BF-642: a workspace room already renders WorkspaceFilesRail (Inputs +
  // Outputs) inside ProfileChatTab. Mounting the standalone ArtifactDrawer
  // beside it (AD-1074a) double-shows artifacts. Suppress the drawer when the
  // active thread is a workspace room so a single Cowork-style Files panel owns
  // the surface; 1:1 chats (no rail) keep the drawer.
  const activeWorkspaceThread = activeProfileThreadId ? chatThreads.get(activeProfileThreadId) : undefined;
  const isWorkspaceFilesRoom = isWorkspaceRoom(activeWorkspaceThread, agents);
  const agentId = activeGroupThread
    ? (hostAgentId(activeGroupThread, agents) ?? activeProfileAgent)
    : activeProfileAgent;

  const [activeTab, setActiveTab] = useState<ProfileTab>('chat');
  const [profileData, setProfileData] = useState<AgentProfileData | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  // Resizable panel state — persisted in localStorage so the captain's
  // preferred chat-window size survives reloads.
  const [size, setSize] = useState(() => {
    try {
      const stored = localStorage.getItem('hxi_profile_panel_size');
      if (stored) {
        const parsed = JSON.parse(stored);
        if (typeof parsed.w === 'number' && typeof parsed.h === 'number') return parsed;
      }
    } catch (_e) { /* fall through to default */ }
    return { w: 420, h: 580 };
  });
  useEffect(() => {
    localStorage.setItem('hxi_profile_panel_size', JSON.stringify(size));
  }, [size]);
  const [isResizing, setIsResizing] = useState(false);
  const resizeStart = useRef({ x: 0, y: 0, w: 420, h: 580 });
  // AD-721: avatar popout state.
  const [avatarOpen, setAvatarOpen] = useState(false);
  const [avatarsEnabled, setAvatarsEnabled] = useState(false);
  // AD-721d: proposed (not-yet-persisted) DSL surfaced in the popout for Captain review.
  const [proposedDsl, setProposedDsl] = useState<AvatarDSLDict | null>(null);
  const [designInFlight, setDesignInFlight] = useState(false);
  const [designError, setDesignError] = useState<string | null>(null);
  // AD-721d-1: revision-cycle state.
  const [previousDsl, setPreviousDsl] = useState<AvatarDSLDict | null>(null);
  const [proposalIteration, setProposalIteration] = useState<number>(1);
  const [proposalMaxIterations, setProposalMaxIterations] = useState<number>(3);
  // AD-721d-3: preview-render state.
  const [previewVrmUrl, setPreviewVrmUrl] = useState<string | null>(null);
  const [previewInFlight, setPreviewInFlight] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // AD-721h: VRM upload state.
  const vrmFileInputRef = useRef<HTMLInputElement | null>(null);
  const [vrmUploadInFlight, setVrmUploadInFlight] = useState(false);
  const [vrmUploadError, setVrmUploadError] = useState<string | null>(null);
  useEffect(() => {
    fetch('/api/config/avatars-enabled')
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data && typeof data.enabled === 'boolean') setAvatarsEnabled(data.enabled); })
      .catch(() => {});
  }, []);
  const dragOffset = useRef({ x: 0, y: 0 });

  const agent = agentId ? agents.get(agentId) : null;

  // Fetch profile data when agent changes. AD-954a: a group surface is a ROOM,
  // not the (derived) anchor's profile — skip the host-scoped fetch (its data
  // is never shown in group mode: the title is the room title and the
  // agent-scoped tabs are collapsed) so the panel is not coupled to the host.
  useEffect(() => {
    if (!agentId || isGroupSurface) {
      setProfileData(null);
      return;
    }
    let cancelled = false;
    fetch(`/api/agent/${agentId}/profile`)
      .then(r => r.ok ? r.json() : null)
      .then(data => {
        if (!cancelled && data) setProfileData(data);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [agentId, isGroupSurface]);

  // Mark messages read when opening — AD-954a: only a 1:1. A group surface is a
  // room, not the host's DM, so opening it must not mark the derived anchor
  // agent's 1:1 conversation read.
  useEffect(() => {
    if (agentId && !isGroupSurface) {
      useStore.getState().markAgentRead(agentId);
    }
  }, [agentId, isGroupSurface]);

  // Drag handlers
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    setIsDragging(true);
    dragOffset.current = { x: e.clientX - pos.x, y: e.clientY - pos.y };
  }, [pos]);

  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e: MouseEvent) => {
      const newX = Math.max(0, Math.min(window.innerWidth - 420, e.clientX - dragOffset.current.x));
      const newY = Math.max(0, Math.min(window.innerHeight - 100, e.clientY - dragOffset.current.y));
      useStore.getState().setProfilePanelPos({ x: newX, y: newY });
    };
    const onUp = () => setIsDragging(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isDragging]);

  // Resize handlers — bottom-right corner drags to resize.
  const onResizeMouseDown = useCallback((e: React.MouseEvent) => {
    setIsResizing(true);
    resizeStart.current = { x: e.clientX, y: e.clientY, w: size.w, h: size.h };
    e.preventDefault();
    e.stopPropagation();
  }, [size]);

  useEffect(() => {
    if (!isResizing) return;
    const onMove = (e: MouseEvent) => {
      const dw = e.clientX - resizeStart.current.x;
      const dh = e.clientY - resizeStart.current.y;
      const nw = Math.max(320, Math.min(window.innerWidth - 40, resizeStart.current.w + dw));
      const nh = Math.max(360, Math.min(window.innerHeight - 40, resizeStart.current.h + dh));
      setSize({ w: nw, h: nh });
    };
    const onUp = () => setIsResizing(false);
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [isResizing]);

  if (!agentId || !agent) return null;

  const callsign = profileData?.callsign || agent.callsign || '';
  const displayName = callsign || agent.agentType;
  const department = profileData?.department || poolToGroup?.[agent.pool] || '';
  const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';
  const isCrew = profileData?.isCrew ?? true;  // BF-017: default true until profile loads

  // AD-965: neutral, nameable group surface. When the active chat thread is a
  // GROUP (>=2 crew), the panel is a ROOM, not the host agent's profile — so
  // its identity is the group title (Teams-style, via chatDisplayName) and a
  // neutral dot, and the agent-scoped tabs (work/profile/health/memory/
  // self_image) are meaningless and collapse to Chat-only. The group lives in
  // the chat tab; GroupChatHeader (inside ProfileChatTab) still owns the
  // participant strip + rename + meeting controls. A 1:1 is byte-identical.
  const groupTitle = activeGroupThread ? chatDisplayName(activeGroupThread, agents) : '';

  // BF-017: Filter tabs — non-crew agents don't get Chat tab.
  // AD-965: a group surface is Chat-only (the other tabs are agent-scoped).
  const visibleTabs = isGroupSurface
    ? TAB_LABELS.filter(t => t.key === 'chat')
    : isCrew
      ? TAB_LABELS
      : TAB_LABELS.filter(t => t.key !== 'chat' && t.key !== 'memory' && t.key !== 'self_image' && t.key !== 'service');

  // If current tab is hidden for non-crew, switch to profile
  const effectiveTab = visibleTabs.some(t => t.key === activeTab) ? activeTab : (isGroupSurface ? 'chat' : 'profile');

  return (
    <div
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        width: size.w,
        height: size.h,
        background: 'rgba(10, 10, 18, 0.92)',
        backdropFilter: 'blur(16px)',
        WebkitBackdropFilter: 'blur(16px)',
        border: '1px solid rgba(240, 176, 96, 0.2)',
        borderRadius: 12,
        zIndex: 25,
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#e0dcd4',
        overflow: 'hidden',
        boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
      }}
    >
      {/* Title bar — draggable */}
      <div
        onMouseDown={onMouseDown}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 14px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          cursor: isDragging ? 'grabbing' : 'grab',
          userSelect: 'none',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{
            width: 8, height: 8, borderRadius: '50%',
            background: isGroupSurface ? '#8888a0' : deptColor,
          }} />
          {isGroupSurface ? (
            // AD-965: the room's own identity — the group title, not the host
            // agent. The participant cluster + rename live in GroupChatHeader
            // (inside the chat tab below).
            <span data-testid="group-surface-title" style={{ fontWeight: 600, fontSize: 14 }}>
              {groupTitle}
            </span>
          ) : (
            <>
              <span style={{ fontWeight: 600, fontSize: 14 }}>
                {displayName}
              </span>
              {callsign && agent.displayName && (
                <span style={{ color: '#8888a0', fontSize: 12 }}>
                  ({agent.displayName})
                </span>
              )}
            </>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {/* AD-721d: Design avatar (crew only, gated on avatars.enabled). */}
          {isCrew && avatarsEnabled && agentId && (
            <button
              data-testid="design-avatar-btn"
              onClick={async () => {
                if (designInFlight || !agentId) return;
                setDesignInFlight(true);
                setDesignError(null);
                try {
                  const r = await fetch(`/api/agent/${agentId}/appearance/propose`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ captain_note: '' }),
                  });
                  if (!r.ok) {
                    setDesignError(`Proposal rejected (HTTP ${r.status})`);
                    return;
                  }
                  const data = await r.json();
                  if (data && data.dsl) {
                    setProposedDsl(data.dsl as AvatarDSLDict);
                    setPreviousDsl(null);
                    setProposalIteration(Number(data.proposal_iteration ?? 1));
                    setProposalMaxIterations(Number(data.max_iterations ?? 3));
                    setAvatarOpen(true);
                  }
                } catch (e: any) {
                  setDesignError(String(e?.message || e));
                } finally {
                  setDesignInFlight(false);
                }
              }}
              aria-label="Design avatar"
              title={designError || (designInFlight ? 'Designing...' : 'Design avatar')}
              disabled={designInFlight}
              style={{
                background: 'none', border: 'none',
                color: designInFlight ? '#666680' : '#8888a0',
                cursor: designInFlight ? 'wait' : 'pointer',
                padding: '0 4px',
                filter: designInFlight ? 'none' : 'drop-shadow(0 0 0 transparent)',
              }}
              onMouseEnter={(e) => {
                if (!designInFlight) {
                  e.currentTarget.style.color = '#f0b060';
                  e.currentTarget.style.filter = 'drop-shadow(0 0 4px rgba(240,176,96,0.6))';
                }
              }}
              onMouseLeave={(e) => {
                if (!designInFlight) {
                  e.currentTarget.style.color = '#8888a0';
                  e.currentTarget.style.filter = 'drop-shadow(0 0 0 transparent)';
                }
              }}
            >
              {/* HXI Design Principle #3: stroke-based SVG, no emoji. */}
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
                   strokeLinejoin="round">
                <path d="M3 13l2-1 6.5-6.5a1.4 1.4 0 0 0-2-2L3 10v3z" />
                <path d="M10 4l2 2" />
              </svg>
            </button>
          )}
          {/* AD-721h: Upload VRM (crew only, gated on avatars.enabled). */}
          {isCrew && avatarsEnabled && agentId && (
            <>
              <input
                ref={vrmFileInputRef}
                type="file"
                accept=".vrm,application/octet-stream,model/gltf-binary"
                data-testid="upload-vrm-input"
                style={{ display: 'none' }}
                onChange={async (e) => {
                  const f = e.target.files?.[0];
                  e.target.value = '';
                  if (!f || vrmUploadInFlight) return;
                  setVrmUploadInFlight(true);
                  setVrmUploadError(null);
                  try {
                    const fd = new FormData();
                    fd.append('file', f);
                    const r = await fetch(
                      `/api/agent/${agentId}/appearance/vrm`,
                      { method: 'POST', body: fd },
                    );
                    if (!r.ok) {
                      let reason = `HTTP ${r.status}`;
                      try {
                        const body = await r.json();
                        if (body?.detail?.reason) reason = body.detail.reason;
                      } catch { /* swallow */ }
                      setVrmUploadError(reason);
                      return;
                    }
                    // Refresh profile so the new vrm_url is picked up.
                    fetch(`/api/agent/${agentId}/profile`)
                      .then(rr => rr.ok ? rr.json() : null)
                      .then(d => { if (d) setProfileData(d); })
                      .catch(() => {});
                  } catch (err: any) {
                    setVrmUploadError(String(err?.message || err));
                  } finally {
                    setVrmUploadInFlight(false);
                  }
                }}
              />
              <button
                data-testid="upload-vrm-btn"
                onClick={() => { if (!vrmUploadInFlight) vrmFileInputRef.current?.click(); }}
                aria-label="Upload VRM"
                aria-disabled={vrmUploadInFlight}
                disabled={vrmUploadInFlight}
                title={vrmUploadError
                  ? `Upload failed: ${vrmUploadError}`
                  : (vrmUploadInFlight ? 'Uploading…' : 'Upload VRM')}
                style={{
                  background: 'none', border: 'none',
                  color: vrmUploadInFlight ? '#666680' : '#8888a0',
                  cursor: vrmUploadInFlight ? 'wait' : 'pointer',
                  padding: '0 4px',
                }}
                onMouseEnter={(e) => {
                  if (!vrmUploadInFlight) e.currentTarget.style.color = '#f0b060';
                }}
                onMouseLeave={(e) => {
                  if (!vrmUploadInFlight) e.currentTarget.style.color = '#8888a0';
                }}
              >
                {/* Upload glyph — stroke-based, no emoji. */}
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                     stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"
                     strokeLinejoin="round">
                  <path d="M8 11V3" />
                  <path d="M4 7l4-4 4 4" />
                  <path d="M2 13h12" />
                </svg>
              </button>
            </>
          )}
          {/* AD-721: Show avatar (crew only, gated on avatars.enabled). */}
          {isCrew && avatarsEnabled && (
            <button
              onClick={() => setAvatarOpen(v => !v)}
              aria-label={avatarOpen ? 'Hide avatar' : 'Show avatar'}
              title={avatarOpen ? 'Hide avatar' : 'Show avatar'}
              style={{
                background: 'none', border: 'none',
                color: avatarOpen ? '#f0b060' : '#8888a0',
                cursor: 'pointer', padding: '0 4px',
              }}
            >
              <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
                <circle cx="8" cy="6" r="3" />
                <path d="M3 14c0-2.5 2.2-4.5 5-4.5s5 2 5 4.5" />
              </svg>
            </button>
          )}
          {/* AD-982a: ambient vision toggle (crew only). Grants/revokes the
              agent's permanent access to the perception camera/screen stream;
              persists across restart (data-dir override). Eye glyph = on,
              eye-off = off. */}
          {isCrew && (
            <button
              onClick={async () => {
                const next = !profileData?.visionCapable;
                try {
                  await fetch(`/api/agent/${agentId}/vision-capability/set`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                      enabled: next,
                      reason: next ? 'Captain granted ambient vision' : 'Captain revoked ambient vision',
                    }),
                  });
                  // Optimistic local update + authoritative re-fetch.
                  setProfileData(p => (p ? { ...p, visionCapable: next } : p));
                  fetch(`/api/agent/${agentId}/profile`)
                    .then(r => r.json())
                    .then(d => { if (d) setProfileData(d); })
                    .catch(() => { /* keep optimistic value */ });
                } catch { /* Tier-2: leave prior state */ }
              }}
              aria-label={profileData?.visionCapable ? 'Disable ambient vision' : 'Enable ambient vision'}
              title={profileData?.visionCapable
                ? 'Ambient vision ON — click to revoke camera/screen access'
                : 'Ambient vision OFF — click to grant camera/screen access'}
              data-testid="vision-toggle"
              style={{
                background: 'none', border: 'none',
                color: profileData?.visionCapable ? '#f0b060' : '#8888a0',
                cursor: 'pointer', padding: '0 4px',
              }}
            >
              {profileData?.visionCapable ? (
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                     stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 8s2.5-5 7-5 7 5 7 5-2.5 5-7 5-7-5-7-5z" />
                  <circle cx="8" cy="8" r="2" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 16 16" fill="none"
                     stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 8s2.5-5 7-5c1 0 1.9.25 2.7.64M14.5 9.5c.3-.5.5-1 .5-1.5 0 0-2.5-5-7-5" opacity="0.6" />
                  <path d="M6.5 6.6a2 2 0 002.9 2.8" />
                  <path d="M2 2l12 12" />
                </svg>
              )}
            </button>
          )}
          <button
            onClick={() => useStore.getState().minimizeAgentProfile()}
            style={{
              background: 'none', border: 'none', color: '#8888a0',
              fontSize: 16, cursor: 'pointer', padding: '0 4px',
              lineHeight: 1,
            }}
            title="Minimize"
          >
            &#x2013;
          </button>
          <button
            onClick={() => useStore.getState().closeAgentProfile()}
            style={{
              background: 'none', border: 'none', color: '#8888a0',
              fontSize: 16, cursor: 'pointer', padding: '0 4px',
              lineHeight: 1,
            }}
            title="Close"
          >
            &#x2715;
          </button>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{
        display: 'flex',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        {visibleTabs.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              borderBottom: effectiveTab === key ? '2px solid #f0b060' : '2px solid transparent',
              color: effectiveTab === key ? '#f0b060' : '#8888a0',
              fontSize: 12,
              fontFamily: "'JetBrains Mono', monospace",
              padding: '8px 0',
              cursor: 'pointer',
              transition: 'color 0.15s, border-color 0.15s',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {effectiveTab === 'chat' && isCrew && (
          <div style={{ display: 'flex', height: '100%', minHeight: 0 }}>
            {/* AD-1074a: chat + the Output/Workspace drawer side by side (the
                Cowork experience) - mirrors CompactApp's
                [ProfileChatTab | ArtifactDrawer] row. The drawer is
                self-contained (thread artifacts, collapsible rail). */}
            <div style={{ flex: '1 1 auto', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
              <ProfileChatTab agentId={agentId} />
            </div>
            {!isWorkspaceFilesRoom && <ArtifactDrawer />}
          </div>
        )}
        {effectiveTab === 'work' && <ProfileWorkTab agentId={agentId} />}
        {effectiveTab === 'profile' && <ProfileInfoTab profileData={profileData} agent={agent} />}
        {effectiveTab === 'service' && isCrew && <ProfileServiceTab agentId={agentId} />}
        {effectiveTab === 'health' && <ProfileHealthTab profileData={profileData} agent={agent} />}
        {effectiveTab === 'memory' && <ProfileMemoryTab agentId={agentId} />}
        {effectiveTab === 'self_image' && isCrew && (
          <SelfImageTab agentId={agentId} isActive={effectiveTab === 'self_image'} />
        )}
      </div>
      {/* AD-721: 3D avatar popout. */}
      {avatarOpen && isCrew && avatarsEnabled && (
        <CrewAvatarPopout
          agentId={agentId}
          appearance={profileData?.appearance ?? null}
          departmentColor={deptColor}
          agentSignals={deriveAgentSignals(agentId, useStore.getState() as any)}
          onClose={() => {
            setAvatarOpen(false);
            setProposedDsl(null);
            setPreviousDsl(null);
            setPreviewVrmUrl(null);
            setPreviewError(null);
          }}
          proposedDsl={proposedDsl}
          previousDsl={previousDsl}
          iteration={proposalIteration}
          maxIterations={proposalMaxIterations}
          onRequestRevision={async (note) => {
            if (!agentId) return;
            try {
              const r = await fetch(`/api/agent/${agentId}/appearance/propose`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  captain_note: note,
                  previous_dsl: proposedDsl,
                }),
              });
              if (!r.ok) {
                setDesignError(`Revision rejected (HTTP ${r.status})`);
                return;
              }
              const data = await r.json();
              if (data && data.dsl) {
                setPreviousDsl(proposedDsl);
                setProposedDsl(data.dsl as AvatarDSLDict);
                setProposalIteration(Number(data.proposal_iteration ?? proposalIteration + 1));
                setProposalMaxIterations(Number(data.max_iterations ?? proposalMaxIterations));
              }
            } catch (e: any) {
              setDesignError(String(e?.message || e));
            }
          }}
          onApproveDsl={async (dsl) => {
            const r = await fetch(`/api/agent/${agentId}/appearance`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ dsl }),
            });
            if (r.ok) {
              setProposedDsl(null);
              setPreviousDsl(null);
              setProposalIteration(1);
              setPreviewVrmUrl(null);
              setPreviewError(null);
              // Refresh profile so any cached vrm_url is picked up.
              fetch(`/api/agent/${agentId}/profile`)
                .then(rr => rr.ok ? rr.json() : null)
                .then(d => { if (d) setProfileData(d); })
                .catch(() => {});
            }
          }}
          onRejectDsl={() => {
            // AD-721d-1: best-effort server-side history clear; UI does not block on this.
            if (agentId) {
              fetch(`/api/agent/${agentId}/appearance/proposal-history`, { method: 'DELETE' })
                .catch(() => { /* swallow — Tier-1 (UX cleanup, no user impact) */ });
            }
            setProposedDsl(null);
            setPreviousDsl(null);
            setProposalIteration(1);
            setPreviewVrmUrl(null);
            setPreviewError(null);
          }}
          previewVrmUrl={previewVrmUrl}
          previewInFlight={previewInFlight}
          previewError={previewError}
          onRenderPreview={async () => {
            if (!agentId || !proposedDsl || previewInFlight) return;
            setPreviewInFlight(true);
            setPreviewError(null);
            try {
              const r = await fetch(`/api/agent/${agentId}/appearance/preview`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ dsl: proposedDsl }),
              });
              if (!r.ok) {
                let detail = `HTTP ${r.status}`;
                try {
                  const body = await r.json();
                  if (body?.detail?.reason) detail = body.detail.reason;
                } catch { /* swallow — best-effort */ }
                setPreviewError(detail);
                return;
              }
              const data = await r.json();
              if (data && data.attachment_id) {
                setPreviewVrmUrl(`/api/chat/attachments/${data.attachment_id}`);
              }
            } catch (e: any) {
              setPreviewError(String(e?.message || e));
            } finally {
              setPreviewInFlight(false);
            }
          }}
        />
      )}
      {/* Resize handle (bottom-right corner). */}
      <div
        onMouseDown={onResizeMouseDown}
        aria-label="Resize panel"
        title="Drag to resize"
        style={{
          position: 'absolute',
          right: 0,
          bottom: 0,
          width: 14,
          height: 14,
          cursor: 'nwse-resize',
          zIndex: 5,
        }}
      >
        <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="#8888a0"
             strokeWidth="1.25" strokeLinecap="round">
          <line x1="5" y1="14" x2="14" y2="5" />
          <line x1="9" y1="14" x2="14" y2="9" />
        </svg>
      </div>
    </div>
  );
}
