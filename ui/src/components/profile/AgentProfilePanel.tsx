import { useState, useRef, useCallback, useEffect } from 'react';
import { useStore } from '../../store/useStore';
import { ProfileChatTab } from './ProfileChatTab';
import { ProfileWorkTab } from './ProfileWorkTab';
import { ProfileInfoTab } from './ProfileInfoTab';
import { ProfileHealthTab } from './ProfileHealthTab';
import type { AgentProfileData } from '../../store/types';

type ProfileTab = 'chat' | 'work' | 'profile' | 'health';

const TAB_LABELS: { key: ProfileTab; label: string }[] = [
  { key: 'chat', label: 'Chat' },
  { key: 'work', label: 'Work' },
  { key: 'profile', label: 'Profile' },
  { key: 'health', label: 'Health' },
];

const DEPT_COLORS: Record<string, string> = {
  engineering: '#b0a050',
  science: '#50b0a0',
  medical: '#5090d0',
  security: '#d05050',
  bridge: '#d0a030',
};

export function AgentProfilePanel() {
  const agentId = useStore((s) => s.activeProfileAgent);
  const agents = useStore((s) => s.agents);
  const pos = useStore((s) => s.profilePanelPos);
  const poolToGroup = useStore((s) => s.poolToGroup);

  const [activeTab, setActiveTab] = useState<ProfileTab>('chat');
  const [profileData, setProfileData] = useState<AgentProfileData | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const dragOffset = useRef({ x: 0, y: 0 });

  const agent = agentId ? agents.get(agentId) : null;

  // Fetch profile data when agent changes
  useEffect(() => {
    if (!agentId) {
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
  }, [agentId]);

  // Mark messages read when opening
  useEffect(() => {
    if (agentId) {
      useStore.getState().markAgentRead(agentId);
    }
  }, [agentId]);

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

  if (!agentId || !agent) return null;

  const callsign = profileData?.callsign || agent.callsign || '';
  const displayName = callsign || agent.agentType;
  const department = profileData?.department || poolToGroup?.[agent.pool] || '';
  const deptColor = DEPT_COLORS[department?.toLowerCase()] || '#666';

  return (
    <div
      style={{
        position: 'fixed',
        left: pos.x,
        top: pos.y,
        width: 420,
        height: 580,
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
            background: deptColor,
          }} />
          <span style={{ fontWeight: 600, fontSize: 14 }}>
            {displayName}
          </span>
          {callsign && (
            <span style={{ color: '#8888a0', fontSize: 12 }}>
              ({agent.agentType})
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
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
        {TAB_LABELS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              flex: 1,
              background: 'none',
              border: 'none',
              borderBottom: activeTab === key ? '2px solid #f0b060' : '2px solid transparent',
              color: activeTab === key ? '#f0b060' : '#8888a0',
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
        {activeTab === 'chat' && <ProfileChatTab agentId={agentId} />}
        {activeTab === 'work' && <ProfileWorkTab agentId={agentId} />}
        {activeTab === 'profile' && <ProfileInfoTab profileData={profileData} agent={agent} />}
        {activeTab === 'health' && <ProfileHealthTab profileData={profileData} agent={agent} />}
      </div>
    </div>
  );
}
