/* AD-741 — Settings overlay panel root.
 *
 * Mounted unconditionally in App.tsx (returns null when ``open`` is false),
 * mirrors the existing WardRoomPanel / CrewRosterPanel overlay pattern.
 */

import { useSettingsStore } from '../../store/useSettingsStore';
import SettingsSidebar from './SettingsSidebar';
import SettingsMain from './SettingsMain';
import { SettingsTopBar, SettingsStatusBar, YamlModal } from './SettingsTopBar';

export default function SettingsPanel() {
  const open = useSettingsStore(s => s.open);
  const loading = useSettingsStore(s => s.loading);
  const loaded = useSettingsStore(s => s.loaded);

  if (!open) return null;

  return (
    <div
      data-testid="settings-panel"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 30,
        background: 'rgba(6,6,12,0.92)',
        backdropFilter: 'blur(12px)',
        WebkitBackdropFilter: 'blur(12px)',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: "'JetBrains Mono', monospace",
        color: '#c8c8d8',
      }}
    >
      <SettingsTopBar />
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {loading && !loaded ? (
          <div style={{ flex: 1, padding: 24, color: '#666680' }}>Loading config…</div>
        ) : (
          <>
            <SettingsSidebar />
            <SettingsMain />
          </>
        )}
      </div>
      <SettingsStatusBar />
      <YamlModal />
    </div>
  );
}
