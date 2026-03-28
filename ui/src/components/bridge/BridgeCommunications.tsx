import { useStore } from '../../store/useStore';
import { useEffect, useState } from 'react';

/** AD-485: Communications admin panel in Bridge System area */
export function BridgeCommunications() {
  const settings = useStore(s => s.communicationsSettings);
  const refreshSettings = useStore(s => s.refreshCommunicationsSettings);
  const updateSettings = useStore(s => s.updateCommunicationsSettings);
  const dmChannels = useStore(s => s.wardRoomDmChannels);
  const refreshDms = useStore(s => s.refreshWardRoomDmChannels);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<any[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => { refreshSettings(); refreshDms(); }, [refreshSettings, refreshDms]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const resp = await fetch(`/api/wardroom/dms/archive?q=${encodeURIComponent(searchQuery)}`);
      if (resp.ok) {
        const data = await resp.json();
        setSearchResults(data.results || []);
      }
    } catch { /* swallow */ }
    setSearching(false);
  };

  const sectionStyle = {
    marginBottom: 16,
    padding: '12px',
    background: 'rgba(255,255,255,0.02)',
    borderRadius: 6,
    border: '1px solid rgba(255,255,255,0.04)',
  };

  const labelStyle = {
    fontSize: 10, letterSpacing: 1, fontWeight: 700 as const,
    color: '#8888a0', textTransform: 'uppercase' as const,
    marginBottom: 8, display: 'block' as const,
  };

  return (
    <div style={{ padding: '8px 0' }}>
      {/* DM Settings */}
      <div style={sectionStyle}>
        <span style={labelStyle}>DM Settings</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 11, color: '#c0bab0' }}>Minimum rank to DM:</span>
          <select
            value={settings.dm_min_rank}
            onChange={e => updateSettings({ dm_min_rank: e.target.value })}
            style={{
              background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 4, padding: '3px 8px', color: '#e0dcd4', fontSize: 11,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            <option value="ensign">Ensign (all crew)</option>
            <option value="lieutenant">Lieutenant</option>
            <option value="commander">Commander</option>
            <option value="senior">Senior</option>
          </select>
        </div>
      </div>

      {/* Message History Search */}
      <div style={sectionStyle}>
        <span style={labelStyle}>Message History Search</span>
        <div style={{ display: 'flex', gap: 6 }}>
          <input
            type="text"
            placeholder="Search DM messages..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            style={{
              flex: 1, background: 'rgba(255,255,255,0.06)',
              border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4,
              padding: '4px 8px', color: '#e0dcd4', fontSize: 11,
              fontFamily: "'JetBrains Mono', monospace",
            }}
          />
          <button
            onClick={handleSearch}
            disabled={searching}
            style={{
              background: 'rgba(240,176,96,0.15)', border: '1px solid rgba(240,176,96,0.3)',
              borderRadius: 4, padding: '4px 10px', color: '#f0b060', fontSize: 10,
              cursor: 'pointer', fontFamily: "'JetBrains Mono', monospace",
            }}
          >
            {searching ? '...' : 'Search'}
          </button>
        </div>
        {searchResults.length > 0 && (
          <div style={{ marginTop: 8, maxHeight: 200, overflowY: 'auto' }}>
            {searchResults.map((r, i) => (
              <div key={i} style={{
                padding: '6px 8px', borderBottom: '1px solid rgba(255,255,255,0.04)',
                fontSize: 11,
              }}>
                <div style={{ color: '#6a6a7a', fontSize: 10 }}>{r.channel}</div>
                <div style={{ color: '#c0bab0' }}>
                  {(r.thread?.title || '').slice(0, 80)}
                </div>
                <div style={{ color: '#8888a0', fontSize: 10 }}>
                  {(r.thread?.body || '').slice(0, 120)}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* DM Activity Summary */}
      <div style={sectionStyle}>
        <span style={labelStyle}>DM Channels ({dmChannels.length})</span>
        {dmChannels.length === 0 ? (
          <div style={{ color: '#6a6a7a', fontSize: 11 }}>No DM activity yet.</div>
        ) : (
          <div style={{ maxHeight: 150, overflowY: 'auto' }}>
            {dmChannels.map(dm => (
              <div key={dm.channel.id} style={{
                padding: '4px 0', fontSize: 11, color: '#c0bab0',
                borderBottom: '1px solid rgba(255,255,255,0.02)',
              }}>
                {dm.channel.description || dm.channel.name}
                <span style={{ color: '#6a6a7a', marginLeft: 8, fontSize: 10 }}>
                  {dm.thread_count} msg{dm.thread_count !== 1 ? 's' : ''}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
