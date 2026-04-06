import type { Agent, AgentProfileData } from '../../store/types';
import { useStore } from '../../store/useStore';
import { useEffect } from 'react';

const TRAIT_LABELS: Record<string, string> = {
  openness: 'Openness',
  conscientiousness: 'Conscientious',
  extraversion: 'Extraversion',
  agreeableness: 'Agreeableness',
  neuroticism: 'Neuroticism',
};

const TRAIT_COLORS: Record<string, string> = {
  openness: '#50b0a0',
  conscientiousness: '#5090d0',
  extraversion: '#f0b060',
  agreeableness: '#80c878',
  neuroticism: '#d05050',
};

const RANK_LABELS: Record<string, string> = {
  ensign: 'Ensign',
  lieutenant: 'Lieutenant',
  commander: 'Commander',
  senior_officer: 'Senior Officer',
};

const AGENCY_LABELS: Record<string, string> = {
  reactive: 'Reactive',
  suggestive: 'Suggestive',
  autonomous: 'Autonomous',
  unrestricted: 'Unrestricted',
};

interface Props {
  profileData: AgentProfileData | null;
  agent: Agent;
}

export function ProfileInfoTab({ profileData, agent }: Props) {
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refreshDms = useStore(s => s.refreshWardRoomDmChannels);
  const activeGame = useStore(s => s.activeGame);
  const challengeAgent = useStore(s => s.challengeAgent);
  useEffect(() => { refreshDms(); }, [refreshDms]);

  // Filter DM channels involving this agent (by agent ID prefix in channel name)
  const agentIdPrefix = (agent.id || '').slice(0, 8);
  const agentDms = agentIdPrefix
    ? dmChannels.filter(dm => dm.channel.name.includes(agentIdPrefix))
    : [];

  if (!profileData) {
    return (
      <div style={{ color: '#555568', fontSize: 12, textAlign: 'center', marginTop: 40 }}>
        Loading profile...
      </div>
    );
  }

  const personality = profileData.personality || {};
  const traits = Object.entries(personality).filter(
    ([key]) => key in TRAIT_LABELS
  );

  return (
    <div style={{ padding: '12px 14px', overflowY: 'auto', height: '100%', fontSize: 12 }}>
      {/* Identity */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
          Identity
        </div>
        <div>
          <span style={{ color: '#8888a0' }}>Rank: </span>
          <span style={{ color: '#e0dcd4' }}>
            {RANK_LABELS[profileData.rank] || profileData.rank}
          </span>
        </div>
        <div>
          <span style={{ color: '#8888a0' }}>Agency: </span>
          <span style={{ color: '#e0dcd4' }}>
            {AGENCY_LABELS[profileData.agencyLevel] || profileData.agencyLevel}
          </span>
        </div>
        {profileData.department && (
          <div>
            <span style={{ color: '#8888a0' }}>Department: </span>
            <span style={{ color: '#e0dcd4', textTransform: 'capitalize' }}>
              {profileData.department}
            </span>
          </div>
        )}
        {profileData.displayName && profileData.displayName !== profileData.callsign && (
          <div>
            <span style={{ color: '#8888a0' }}>Role: </span>
            <span style={{ color: '#e0dcd4' }}>{profileData.displayName}</span>
          </div>
        )}
        {profileData.specialization.length > 0 && (
          <div>
            <span style={{ color: '#8888a0' }}>Specialization: </span>
            <span style={{ color: '#e0dcd4' }}>{profileData.specialization.join(', ')}</span>
          </div>
        )}
      </div>

      {/* Personality — Big Five bars */}
      {traits.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 6 }}>
            Personality
          </div>
          {traits.map(([key, value]) => (
            <div key={key} style={{ marginBottom: 4 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ color: '#8888a0', fontSize: 11 }}>{TRAIT_LABELS[key]}</span>
                <span style={{ color: '#666680', fontSize: 10 }}>{Math.round((value as number) * 100)}%</span>
              </div>
              <div style={{
                height: 4, borderRadius: 2,
                background: 'rgba(255,255,255,0.06)',
                overflow: 'hidden',
              }}>
                <div style={{
                  height: '100%',
                  width: `${(value as number) * 100}%`,
                  background: TRAIT_COLORS[key] || '#5090d0',
                  borderRadius: 2,
                }} />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Hebbian connections */}
      {profileData.hebbianConnections.length > 0 && (
        <div>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Connections
          </div>
          {profileData.hebbianConnections.map((conn, i) => (
            <div key={i} style={{
              display: 'flex', justifyContent: 'space-between',
              padding: '2px 0', fontSize: 11,
            }}>
              <span style={{ color: '#e0dcd4', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {conn.targetId.slice(0, 12)}...
              </span>
              <span style={{ color: '#8888a0' }}>
                {conn.weight.toFixed(3)} ({conn.relType})
              </span>
            </div>
          ))}
        </div>
      )}

      {/* Recent Communications (AD-485) */}
      {agentDms.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Recent Communications
          </div>
          {agentDms.map(dm => (
            <div key={dm.channel.id} style={{
              padding: '4px 0', fontSize: 11,
              borderBottom: '1px solid rgba(255,255,255,0.02)',
            }}>
              <div style={{ color: '#c0bab0' }}>
                {dm.channel.description || dm.channel.name}
              </div>
              {dm.latest_thread && (
                <div style={{ color: '#8888a0', fontSize: 10, marginTop: 1 }}>
                  {(dm.latest_thread.body || '').slice(0, 80)}
                  {(dm.latest_thread.body || '').length > 80 ? '…' : ''}
                </div>
              )}
              <div style={{ color: '#6a6a7a', fontSize: 10 }}>
                {dm.thread_count} message{dm.thread_count !== 1 ? 's' : ''}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* AD-526b: Challenge to game */}
      {agent.isCrew && (
        <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <button
            onClick={() => challengeAgent(agent.id)}
            disabled={!!activeGame}
            style={{
              width: '100%',
              padding: '8px 0',
              background: activeGame ? 'rgba(100, 100, 100, 0.1)' : 'rgba(240, 176, 96, 0.1)',
              border: `1px solid ${activeGame ? 'rgba(100, 100, 100, 0.15)' : 'rgba(240, 176, 96, 0.25)'}`,
              borderRadius: 6,
              color: activeGame ? '#666' : '#f0b060',
              fontSize: 12,
              fontFamily: "'JetBrains Mono', monospace",
              cursor: activeGame ? 'default' : 'pointer',
              fontWeight: 500,
              letterSpacing: 0.5,
            }}
          >
            {activeGame ? 'Game in progress...' : 'Challenge to Tic-Tac-Toe'}
          </button>
        </div>
      )}
    </div>
  );
}
