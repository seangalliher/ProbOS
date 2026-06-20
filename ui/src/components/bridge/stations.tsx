/* AD-943: Command-Station model + registry — the Bridge's Ship's-Computer
 * command layer. A station = a menu group for one area of the ship, holding
 * launch ACTIONS and inline CONFIG. The 3 existing Bridge sections are migrated
 * here; personnel/science/command are modelled placeholders the AD-944/945/946
 * wave fills. NOT an agent surface (AD-398). Deep visual pass = AD-943a. */
import type { ReactNode } from 'react';
import { useStore } from '../../store/useStore';
import { useSettingsStore } from '../../store/useSettingsStore';
import { BridgeSystem, BridgeThreads } from './BridgeSystem';
import { BridgeKanban } from './BridgeKanban';
import { BridgeCommunications } from './BridgeCommunications';
import { BridgeEnvironment } from './BridgeEnvironment';

export type StationId =
  | 'communications' | 'personnel' | 'science'
  | 'operations' | 'engineering' | 'command';

/** A discrete "open / launch" item a station offers. AD-944 fills these with
 *  store actions (openWardRoom, openCrewManifest, …). Empty in AD-943. */
export interface StationAction {
  id: string;
  label: string;
  onInvoke: () => void;
  count?: number;
}

/** An inline configuration surface embedded in a station (e.g. the
 *  Communications DM-rank settings). AD-945 folds the bottom-right toggles in. */
export interface StationConfig {
  id: string;
  label: string;
  render: () => ReactNode;
}

/** A command station = a menu group for one area of the ship. */
export interface CommandStation {
  id: StationId;
  title: string;
  accent: string;            // reuses an existing per-section color token
  defaultOpen: boolean;
  count?: number;            // live header count (e.g. dmChannels.length)
  onExpand?: () => void;     // primary launch (the section Expand affordance)
  onExpandLabel?: string;    // AD-946: palette label for the onExpand launch (e.g. "Work Board")
  body?: () => ReactNode;    // inline body (migrated System/Comms/Work bodies)
  actions: StationAction[];  // discrete launches (empty until AD-944)
  config: StationConfig[];   // inline config surfaces
}

/** Canonical 6-station taxonomy — pure, presentation-free metadata. All accents
 *  reuse existing tokens (no new colors). */
export const STATION_META: Record<StationId, { title: string; accent: string }> = {
  communications: { title: 'Communications', accent: '#b080d0' },
  personnel:      { title: 'Personnel',      accent: '#50b0a0' },
  science:        { title: 'Science',        accent: '#5090d0' },
  operations:     { title: 'Operations',     accent: '#d0a030' },
  engineering:    { title: 'Engineering',    accent: '#70a0d0' },
  command:        { title: 'Command',        accent: '#f0b060' },
};

/** The Bridge render order for the stations layer. */
export const STATION_ORDER: StationId[] = [
  'communications', 'personnel', 'science', 'operations', 'engineering', 'command',
];

/** Build the typed station list. The 3 existing Bridge sections are migrated
 *  here (Communications, Work Board→operations, System→engineering);
 *  personnel/science/command are MODELLED placeholders (empty actions/config,
 *  no body) that AD-944/945/946 fill. */
export function buildBridgeStations(ctx: {
  dmChannelCount: number;
  kanbanCount: number;
  totalUnread: number;
}): CommandStation[] {
  const m = STATION_META;
  return [
    {
      id: 'communications',
      title: m.communications.title,
      accent: m.communications.accent,
      defaultOpen: false,
      count: ctx.dmChannelCount,
      onExpand: () => useStore.setState({ wardRoomOpen: true, wardRoomView: 'channels' }),
      body: () => (
        <div style={{ marginBottom: 8 }}>
          <div style={{ fontSize: 9, color: '#666', marginBottom: 4, fontWeight: 600 }}>THREADS</div>
          <BridgeThreads />
        </div>
      ),
      actions: [
        // The Ward Room launch carries the live unread badge the header Expand cannot.
        { id: 'ward-room-action', label: 'Ward Room', count: ctx.totalUnread,
          onInvoke: () => { void useStore.getState().openWardRoom(); } },
        { id: 'chats-toggle', label: 'Chats',
          onInvoke: () => useStore.getState().openChats() },
      ],
      config: [
        { id: 'comms-admin', label: 'Communications', render: () => <BridgeCommunications /> },
      ],
    },
    {
      id: 'personnel',
      title: m.personnel.title, accent: m.personnel.accent,
      defaultOpen: false,
      actions: [
        { id: 'crew-action', label: 'Crew',
          onInvoke: () => { void useStore.getState().openCrewManifest(); } },
        { id: 'personnel-toggle', label: 'Personnel',
          onInvoke: () => useStore.getState().openPersonnelConsole() },
        { id: 'behavioral-metrics-toggle', label: 'Metrics',
          onInvoke: () => { void useStore.getState().openBehavioralMetrics(); } },
      ],
      config: [],
    },
    {
      id: 'science',
      title: m.science.title, accent: m.science.accent,
      defaultOpen: false,
      actions: [
        { id: 'notebooks-toggle', label: 'Notebooks',
          onInvoke: () => { void useStore.getState().openNotebooks(); } },
        { id: 'knowledge-browser-toggle', label: 'Records',
          onInvoke: () => { void useStore.getState().openKnowledgeBrowser(); } },
        { id: 'spatial-explorer-toggle', label: 'Explorer',
          onInvoke: () => useStore.getState().openSpatialExplorer() },
      ],
      config: [],
    },
    {
      id: 'operations',
      title: m.operations.title,
      accent: m.operations.accent,
      defaultOpen: false,
      count: ctx.kanbanCount,
      onExpand: () => useStore.setState({ mainViewer: 'work' }),
      onExpandLabel: 'Work Board',
      body: () => <BridgeKanban />,
      actions: [],
      config: [],
    },
    {
      id: 'engineering',
      title: m.engineering.title,
      accent: m.engineering.accent,
      defaultOpen: false,
      count: 0,
      onExpand: () => useStore.setState({ mainViewer: 'system' }),
      onExpandLabel: 'System',
      body: () => <BridgeSystem />,
      actions: [
        // AD-1001b: Engineering gains discrete actions, so (per the AD-946
        // flatten precedent) it now surfaces its ACTIONS in the palette instead
        // of the onExpand fallback. Mirror the System expand as an explicit
        // action so the System launch is preserved — exactly how Communications
        // mirrors its Ward Room expand as an action. The header Expand button
        // still uses onExpand above.
        { id: 'engineering-system', label: 'System',
          onInvoke: () => useStore.setState({ mainViewer: 'system' }) },
        // The Ship's Locker — ship-wide capabilities catalog (tools, skills,
        // mesh intents, MCP). A Ship's-Computer / Engineering concern.
        { id: 'ships-locker-toggle', label: "Ship's Locker",
          onInvoke: () => useStore.setState({ shipsLockerOpen: true }) },
        // AD-1018: MCP Servers — the operator management surface for runtime-
        // mutable MCP server registrations (CRUD + auth). Engineering concern.
        { id: 'mcp-servers-toggle', label: 'MCP Servers',
          onInvoke: () => useStore.setState({ mcpServersOpen: true }) },
        // AD-1024: MCP Apps — launch a registered MCP app into a sandboxed frame
        // (the read-only gallery over the AD-597 engine). Engineering concern.
        { id: 'mcp-apps-toggle', label: 'MCP Apps',
          onInvoke: () => useStore.setState({ mcpAppsOpen: true }) },
        // AD-1021: Code/Text Workstation — opens an empty scratch buffer (build
        // proposals open it via the IntentSurface card). Engineering concern.
        { id: 'workstation-toggle', label: 'Workstation',
          onInvoke: () => useStore.getState().openWorkstation({ kind: 'scratch', title: 'Scratch', language: 'markdown', content: '' }) },
      ],
      // AD-945: the four bottom-right environment toggles (sound / voice / wake-word /
      // legend), relocated from DecisionSurface into the Ship's-Computer command layer.
      config: [
        { id: 'environment', label: 'Environment', render: () => <BridgeEnvironment /> },
      ],
    },
    {
      id: 'command',
      title: m.command.title, accent: m.command.accent,
      defaultOpen: false,
      actions: [
        { id: 'topnav-settings', label: 'Settings',
          onInvoke: () => { void useSettingsStore.getState().openSettings(); } },
      ],
      config: [],
    },
  ];
}

/** A station renders in AD-943 iff it has a body, an action, or a config item.
 *  Placeholders are modelled but NOT shown until later ADs fill them. */
export function isPopulated(st: CommandStation): boolean {
  return !!st.body || st.actions.length > 0 || st.config.length > 0;
}
