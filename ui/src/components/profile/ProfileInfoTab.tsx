import type { Agent, AgentProfileData } from '../../store/types';
import { useStore } from '../../store/useStore';
import { useEffect, useState } from 'react';
import {
  getAvailableVoices,
  getServerPiperVoices,
  speakResponse,
  type VoiceProfile,
} from '../../audio/voice';

/** BF-291: union of browser and Piper voice sources. Both share `.name`
 *  which is all the picker needs; quality/lang are surfaced when the
 *  server source is available. */
type PickerVoice = { name: string; quality?: string; lang?: string };

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

  // AD-718: Per-agent voice profile editor state.
  const [currentProfile, setCurrentProfile] = useState<VoiceProfile>({
    voice_name: profileData?.voiceProfile?.voice_name ?? '',
    pitch: profileData?.voiceProfile?.pitch ?? 0.9,
    rate: profileData?.voiceProfile?.rate ?? 0.95,
    volume: profileData?.voiceProfile?.volume ?? 0.8,
    // AD-718c: optional per-agent wake phrase.
    wake_phrase: profileData?.voiceProfile?.wake_phrase ?? '',
  });
  const [availableVoices, setAvailableVoices] = useState<PickerVoice[]>([]);
  // AD-718e: language filter for the voice picker. Empty string = "All".
  const [voiceLangFilter, setVoiceLangFilter] = useState<string>('');
  // AD-718a: agent-authored voice proposal preview state.
  const [proposal, setProposal] = useState<VoiceProfile | null>(null);
  const [proposalRationale, setProposalRationale] = useState<string>('');
  const [proposalError, setProposalError] = useState<string>('');
  const [proposalBusy, setProposalBusy] = useState<boolean>(false);
  const [revisionNote, setRevisionNote] = useState<string>('');
  const [showRevisionInput, setShowRevisionInput] = useState<boolean>(false);
  useEffect(() => {
    let cancelled = false;
    // BF-291: prefer server-side Piper catalog when the runtime backend is
    // piper; fall back to the browser SpeechSynthesisVoice list (Edge TTS
    // on Windows) when the backend is browser or unreachable.
    (async () => {
      const piper = await getServerPiperVoices();
      if (cancelled) return;
      if (piper !== null) {
        setAvailableVoices(piper.map(v => ({
          name: v.name,
          quality: v.quality,
          lang: v.lang,
        })));
      } else {
        setAvailableVoices(getAvailableVoices().map(v => ({ name: v.name })));
      }
    })();
    return () => { cancelled = true; };
  }, []);
  // Re-sync when profileData arrives or agent changes.
  useEffect(() => {
    if (profileData?.voiceProfile) {
      setCurrentProfile({
        voice_name: profileData.voiceProfile.voice_name ?? '',
        pitch: profileData.voiceProfile.pitch ?? 0.9,
        rate: profileData.voiceProfile.rate ?? 0.95,
        volume: profileData.voiceProfile.volume ?? 0.8,
        wake_phrase: profileData.voiceProfile.wake_phrase ?? '',
      });
    }
  }, [profileData?.voiceProfile, agent.id]);

  const persistVoiceProfile = (next: VoiceProfile, rationale: string = ''): void => {
    fetch(`/api/agent/${agent.id}/voice-profile`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        voice_name: next.voice_name ?? '',
        pitch: next.pitch ?? 0.9,
        rate: next.rate ?? 0.95,
        volume: next.volume ?? 0.8,
        wake_phrase: next.wake_phrase ?? '',
        proposal_rationale: rationale,
      }),
    })
      .then(() => {
        // Notify ProfileChatTab (and any other listeners) to refetch.
        window.dispatchEvent(new CustomEvent('voice-profile-updated', {
          detail: { agentId: agent.id },
        }));
      })
      .catch(() => {});  // Tier-2 log-and-degrade
  };

  // AD-718a: trigger an agent-authored voice proposal. Optional captain note
  // re-runs the LLM with revision context.
  const fetchVoiceProposal = (captainNote: string = ''): void => {
    setProposalBusy(true);
    setProposalError('');
    fetch(`/api/agent/${agent.id}/voice-profile/propose`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ captain_note: captainNote }),
    })
      .then(async (resp) => {
        if (!resp.ok) {
          throw new Error(`HTTP ${resp.status}`);
        }
        const body = await resp.json();
        const vp: VoiceProfile = {
          voice_name: body?.voice_profile?.voice_name ?? '',
          pitch: body?.voice_profile?.pitch ?? 0.9,
          rate: body?.voice_profile?.rate ?? 0.95,
          volume: body?.voice_profile?.volume ?? 0.8,
          // AD-718c: surface the proposed wake_phrase to the Captain for
          // approve / hand-edit.
          wake_phrase: body?.voice_profile?.wake_phrase ?? '',
        };
        setProposal(vp);
        setProposalRationale(typeof body?.rationale === 'string' ? body.rationale : '');
        setShowRevisionInput(false);
        setRevisionNote('');
      })
      .catch((err) => {
        setProposalError(String(err?.message ?? err));
      })
      .finally(() => {
        setProposalBusy(false);
      });
  };

  const dismissProposal = (): void => {
    setProposal(null);
    setProposalRationale('');
    setProposalError('');
    setShowRevisionInput(false);
    setRevisionNote('');
  };

  const approveProposal = (): void => {
    if (!proposal) return;
    persistVoiceProfile(proposal, proposalRationale);
    setCurrentProfile(proposal);
    dismissProposal();
  };

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

      {/* AD-718: Per-agent voice picker (crew only). */}
      {agent.isCrew && (
        <div style={{ marginTop: 12, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,0.06)' }}>
          <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase', marginBottom: 4 }}>
            Voice
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {/* AD-718e: language filter dropdown. Distinct ``lang`` codes
                pulled from availableVoices; ``All`` = no filter. */}
            <label
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
              data-testid="ad718e-lang-filter-label"
            >
              <span style={{ color: '#8888a0', minWidth: 50 }}>Lang</span>
              <select
                aria-label="Voice language filter"
                data-testid="ad718e-lang-filter"
                value={voiceLangFilter}
                onChange={(e) => setVoiceLangFilter(e.target.value)}
                style={{
                  flex: 1,
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 4,
                  color: '#e0dcd4',
                  fontSize: 11,
                  padding: '4px 6px',
                }}
              >
                <option value="" style={{ background: '#1a1a24', color: '#e0dcd4' }}>All</option>
                {Array.from(
                  new Set(
                    availableVoices
                      .map(v => (v.lang ?? '').split(/[_-]/)[0])
                      .filter(Boolean)
                  ),
                )
                  .sort()
                  .map(code => (
                    <option key={code} value={code} style={{ background: '#1a1a24', color: '#e0dcd4' }}>
                      {code}
                    </option>
                  ))}
              </select>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: '#8888a0', minWidth: 50 }}>Voice</span>
              <select
                value={currentProfile.voice_name ?? ''}
                onChange={(e) => {
                  const next = { ...currentProfile, voice_name: e.target.value };
                  setCurrentProfile(next);
                  persistVoiceProfile(next);
                }}
                aria-label="Voice selector"
                style={{
                  flex: 1,
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 4,
                  color: '#e0dcd4',
                  fontSize: 11,
                  padding: '4px 6px',
                }}
              >
                <option value="" style={{ background: '#1a1a24', color: '#e0dcd4' }}>(global default)</option>
                {availableVoices
                  .filter(v => {
                    if (!voiceLangFilter) return true;
                    const code = (v.lang ?? '').split(/[_-]/)[0];
                    return code === voiceLangFilter;
                  })
                  .map(v => (
                  <option
                    key={v.name}
                    value={v.name}
                    style={{ background: '#1a1a24', color: '#e0dcd4' }}
                  >
                    {v.quality ? `${v.name} (${v.quality})` : v.name}
                  </option>
                ))}
              </select>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: '#8888a0', minWidth: 50 }}>Pitch</span>
              <input
                type="range"
                min={0} max={2} step={0.05}
                value={currentProfile.pitch ?? 0.9}
                onChange={(e) => setCurrentProfile(p => ({ ...p, pitch: parseFloat(e.target.value) }))}
                onMouseUp={() => persistVoiceProfile(currentProfile)}
                onTouchEnd={() => persistVoiceProfile(currentProfile)}
                aria-label="Pitch"
                style={{ flex: 1 }}
              />
              <span style={{ color: '#c0bab0', minWidth: 32 }}>{(currentProfile.pitch ?? 0.9).toFixed(2)}</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: '#8888a0', minWidth: 50 }}>Rate</span>
              <input
                type="range"
                min={0.1} max={2} step={0.05}
                value={currentProfile.rate ?? 0.95}
                onChange={(e) => setCurrentProfile(p => ({ ...p, rate: parseFloat(e.target.value) }))}
                onMouseUp={() => persistVoiceProfile(currentProfile)}
                onTouchEnd={() => persistVoiceProfile(currentProfile)}
                aria-label="Rate"
                style={{ flex: 1 }}
              />
              <span style={{ color: '#c0bab0', minWidth: 32 }}>{(currentProfile.rate ?? 0.95).toFixed(2)}</span>
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span
                style={{ color: '#8888a0', minWidth: 50, display: 'inline-flex', alignItems: 'center', gap: 4 }}
              >
                {/* AD-735: inline SVG speaker glyph (HXI Design Principle #3 — no emoji).
                    Matches the DecisionSurface speaker family. */}
                <svg
                  width="11"
                  height="11"
                  viewBox="0 0 16 16"
                  fill="none"
                  stroke={(currentProfile.volume ?? 0.8) > 0 ? '#f0b060' : '#666680'}
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  aria-hidden="true"
                >
                  <path d="M2 6v4l3 3h1V3H5L2 6z" />
                  <path d="M9 5.5c.7.7 1 1.5 1 2.5s-.3 1.8-1 2.5" />
                </svg>
                <span>Volume</span>
              </span>
              <input
                type="range"
                min={0} max={1} step={0.05}
                value={currentProfile.volume ?? 0.8}
                onChange={(e) =>
                  setCurrentProfile(p => ({ ...p, volume: parseFloat(e.target.value) }))
                }
                onMouseUp={() => persistVoiceProfile(currentProfile)}
                onTouchEnd={() => persistVoiceProfile(currentProfile)}
                aria-label="Volume"
                data-testid="volume-slider"
                style={{ flex: 1 }}
              />
              <span style={{ color: '#c0bab0', minWidth: 32 }}>
                {Math.round((currentProfile.volume ?? 0.8) * 100)}%
              </span>
            </label>
            {/* AD-718c: per-agent wake phrase. Empty = no per-agent wake;
                system-wide "Computer" still routes to the agent via @callsign. */}
            <label style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ color: '#8888a0', minWidth: 70 }}>Wake phrase</span>
              <input
                type="text"
                maxLength={50}
                value={currentProfile.wake_phrase ?? ''}
                onChange={(e) =>
                  setCurrentProfile(p => ({ ...p, wake_phrase: e.target.value }))
                }
                onBlur={() => persistVoiceProfile(currentProfile)}
                aria-label="Wake phrase"
                placeholder="(none)"
                data-testid="wake-phrase-input"
                style={{
                  flex: 1,
                  background: 'rgba(255,255,255,0.04)',
                  border: '1px solid rgba(255,255,255,0.08)',
                  borderRadius: 4,
                  color: '#e0dcd4',
                  fontSize: 11,
                  padding: '4px 6px',
                }}
              />
            </label>
            <button
              type="button"
              onClick={() => speakResponse('This is how I sound.', currentProfile, agent.id)}
              style={{
                marginTop: 4,
                padding: '4px 8px',
                background: 'rgba(240, 176, 96, 0.1)',
                border: '1px solid rgba(240, 176, 96, 0.25)',
                borderRadius: 4,
                color: '#f0b060',
                fontSize: 11,
                cursor: 'pointer',
                alignSelf: 'flex-start',
              }}
            >
              Test
            </button>

            {/* AD-718a: agent-authored voice proposal affordance. */}
            <button
              type="button"
              aria-label="Propose voice"
              onClick={() => fetchVoiceProposal('')}
              disabled={proposalBusy}
              style={{
                marginTop: 4,
                padding: '4px 8px',
                background: 'rgba(240, 176, 96, 0.06)',
                border: '1px solid rgba(240, 176, 96, 0.2)',
                borderRadius: 4,
                color: proposalBusy ? '#666680' : '#f0b060',
                fontSize: 11,
                cursor: proposalBusy ? 'default' : 'pointer',
                alignSelf: 'flex-start',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              <svg
                width={12}
                height={12}
                viewBox="0 0 12 12"
                fill="none"
                stroke={proposalBusy ? '#666680' : '#f0b060'}
                strokeWidth={1.5}
                strokeLinecap="round"
                aria-hidden="true"
              >
                <path d="M6 1.5 v9 M2 4 l4 -2.5 4 2.5 M2 8 l4 2.5 4 -2.5" />
              </svg>
              {proposalBusy ? 'Proposing…' : 'Propose voice'}
            </button>
            {proposalError && (
              <div
                role="alert"
                style={{ color: '#d05050', fontSize: 11, marginTop: 2 }}
              >
                Proposal failed: {proposalError}
              </div>
            )}
            {proposal && (
              <div
                role="region"
                aria-label="Voice proposal preview"
                style={{
                  marginTop: 6,
                  padding: '6px 8px',
                  background: 'rgba(240, 176, 96, 0.05)',
                  border: '1px solid rgba(240, 176, 96, 0.18)',
                  borderRadius: 4,
                  fontSize: 11,
                  color: '#c0bab0',
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                }}
              >
                <div style={{ color: '#8888a0', fontSize: 10, textTransform: 'uppercase' }}>
                  Proposal
                </div>
                <div>
                  <span style={{ color: '#8888a0' }}>Voice: </span>
                  <span>{currentProfile.voice_name || '(default)'}</span>
                  <span style={{ color: '#666680' }}> → </span>
                  <span style={{ color: '#f0b060' }}>{proposal.voice_name || '(default)'}</span>
                </div>
                <div>
                  <span style={{ color: '#8888a0' }}>Pitch: </span>
                  <span>{(currentProfile.pitch ?? 0.9).toFixed(2)}</span>
                  <span style={{ color: '#666680' }}> → </span>
                  <span style={{ color: '#f0b060' }}>{(proposal.pitch ?? 0.9).toFixed(2)}</span>
                </div>
                <div>
                  <span style={{ color: '#8888a0' }}>Rate: </span>
                  <span>{(currentProfile.rate ?? 0.95).toFixed(2)}</span>
                  <span style={{ color: '#666680' }}> → </span>
                  <span style={{ color: '#f0b060' }}>{(proposal.rate ?? 0.95).toFixed(2)}</span>
                </div>
                <div>
                  <span style={{ color: '#8888a0' }}>Volume: </span>
                  <span>{(currentProfile.volume ?? 0.8).toFixed(2)}</span>
                  <span style={{ color: '#666680' }}> → </span>
                  <span style={{ color: '#f0b060' }}>{(proposal.volume ?? 0.8).toFixed(2)}</span>
                </div>
                {proposalRationale && (
                  <div style={{ color: '#8888a0', fontStyle: 'italic' }}>
                    “{proposalRationale}”
                  </div>
                )}
                <div style={{ display: 'flex', gap: 6, marginTop: 4, flexWrap: 'wrap' }}>
                  <button
                    type="button"
                    aria-label="Sample proposed voice"
                    onClick={() => speakResponse('This is how I would sound.', proposal, agent.id)}
                    style={{
                      padding: '3px 8px',
                      background: 'rgba(240, 176, 96, 0.08)',
                      border: '1px solid rgba(240, 176, 96, 0.25)',
                      borderRadius: 3,
                      color: '#f0b060',
                      fontSize: 11,
                      cursor: 'pointer',
                    }}
                  >
                    Sample
                  </button>
                  <button
                    type="button"
                    aria-label="Approve voice proposal"
                    onClick={approveProposal}
                    style={{
                      padding: '3px 8px',
                      background: 'rgba(128, 200, 120, 0.08)',
                      border: '1px solid rgba(128, 200, 120, 0.3)',
                      borderRadius: 3,
                      color: '#80c878',
                      fontSize: 11,
                      cursor: 'pointer',
                    }}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    aria-label="Request voice revisions"
                    onClick={() => setShowRevisionInput(v => !v)}
                    style={{
                      padding: '3px 8px',
                      background: 'rgba(240, 176, 96, 0.04)',
                      border: '1px solid rgba(240, 176, 96, 0.2)',
                      borderRadius: 3,
                      color: '#f0b060',
                      fontSize: 11,
                      cursor: 'pointer',
                    }}
                  >
                    Request revisions
                  </button>
                  <button
                    type="button"
                    aria-label="Reject voice proposal"
                    onClick={dismissProposal}
                    style={{
                      padding: '3px 8px',
                      background: 'transparent',
                      border: '1px solid rgba(255,255,255,0.12)',
                      borderRadius: 3,
                      color: '#8888a0',
                      fontSize: 11,
                      cursor: 'pointer',
                    }}
                  >
                    Reject
                  </button>
                </div>
                {showRevisionInput && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 4 }}>
                    <input
                      type="text"
                      maxLength={280}
                      value={revisionNote}
                      onChange={(e) => setRevisionNote(e.target.value)}
                      aria-label="Captain revision note"
                      placeholder="e.g. lower pitch, more measured"
                      style={{
                        background: 'rgba(255,255,255,0.04)',
                        border: '1px solid rgba(255,255,255,0.08)',
                        borderRadius: 3,
                        color: '#e0dcd4',
                        fontSize: 11,
                        padding: '3px 6px',
                      }}
                    />
                    <button
                      type="button"
                      aria-label="Submit revision note"
                      onClick={() => fetchVoiceProposal(revisionNote)}
                      disabled={proposalBusy}
                      style={{
                        padding: '3px 8px',
                        background: 'rgba(240, 176, 96, 0.08)',
                        border: '1px solid rgba(240, 176, 96, 0.25)',
                        borderRadius: 3,
                        color: '#f0b060',
                        fontSize: 11,
                        cursor: proposalBusy ? 'default' : 'pointer',
                        alignSelf: 'flex-start',
                      }}
                    >
                      Submit revision
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
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
