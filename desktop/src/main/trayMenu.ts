/**
 * AD-759 tray menu builder (pure function).
 *
 * Returns the menu template that `Menu.buildFromTemplate` consumes in
 * `index.ts`. Kept pure so we can unit-test ordering + label state without
 * touching Electron.
 */

export type ConnectionStatus = "connected" | "connecting" | "disconnected";
export type ViewMode = "compact" | "full";

/**
 * AD-841d: management surfaces reachable from the tray "Management" submenu.
 * Each id MUST match a `ViewTarget` in `ui/src/deepLinkView.ts` (AD-841c).
 * `desktop/` and `ui/` are separate TS projects with no shared module, so the
 * list is duplicated here — keep both in sync. "Skills" = the Ship's Locker.
 */
export type ViewTarget =
  | "agents" | "skills" | "settings" | "wardroom" | "work" | "system";

export interface TrayAgent {
  /** Stable agent id used as path segment for /api/agents/{id}/chat */
  id: string;
  /** Display label rendered in the submenu (e.g. "Yao"). */
  name: string;
}

export interface TrayMenuOptions {
  status: ConnectionStatus;
  proactivePaused: boolean;
  viewMode: ViewMode;
  /** AD-815b: agents shown in the "Chat with..." submenu. Empty = submenu disabled. */
  agents?: readonly TrayAgent[];
  onOpenRoute: (route: string) => void;
  /** AD-815b: invoked when the captain picks an agent from the submenu. */
  onStartChatWithAgent?: (agentId: string) => void;
  /** AD-841d: invoked when the captain picks a surface from the "Management" submenu. */
  onOpenView?: (id: ViewTarget) => void;
  /** AD-841f: invoked when the captain opens the Connection diagnostics panel. */
  onShowDiagnostics?: () => void;
  onToggleProactive: () => void;
  onToggleViewMode: () => void;
  onCheckForUpdates: () => void;
  onResetSetup: () => void;
  onQuit: () => void;
}

export interface TrayMenuItem {
  id: string;
  label: string;
  enabled?: boolean;
  type?: "normal" | "separator" | "submenu";
  toolTip?: string;
  click?: () => void;
  submenu?: TrayMenuItem[];
}

function statusLabel(status: ConnectionStatus): string {
  switch (status) {
    case "connected":
      return "Status: Connected";
    case "connecting":
      return "Status: Connecting…";
    case "disconnected":
      return "Status: Disconnected";
  }
}

/**
 * Build the tray menu template. Order matches the spec in
 * `prompts/ad-759-yeo-native-desktop-tray-app.md` §2.
 *
 * Returns exactly 11 entries (8 actionable items + 1 separator + Quit), but
 * the build-prompt's "exactly 8 items in the documented order" refers to the
 * actionable items shown above the separator. We assert both counts in the
 * test.
 */
export function buildTrayMenu(opts: TrayMenuOptions): TrayMenuItem[] {
  return [
    {
      id: "status",
      label: statusLabel(opts.status),
      enabled: false,
    },
    {
      id: "connection-diagnostics",
      label: "Connection diagnostics…",
      toolTip: "Show the runtime URL + connection status, and retry the connection.",
      click: opts.onShowDiagnostics,
    },
    {
      id: "open-chat",
      label: "Open chat",
      click: () => opts.onOpenRoute("/"),
    },
    {
      id: "daily-briefing",
      label: "Daily briefing",
      click: () => opts.onOpenRoute("/briefing"),
    },
    {
      id: "quick-capture",
      label: "Quick capture",
      click: () => opts.onOpenRoute("/capture"),
    },
    ...buildChatWithSubmenu(opts),
    {
      id: "toggle-proactive",
      label: opts.proactivePaused ? "Resume proactive mode" : "Pause proactive mode",
      click: opts.onToggleProactive,
    },
    {
      id: "view-mode",
      label:
        opts.viewMode === "compact"
          ? "Switch to Full view"
          : "Switch to Compact view",
      toolTip:
        opts.viewMode === "compact"
          ? "Show the full HXI canvas, panels, and crew."
          : "Show the chat-only experience (like Copilot / Claude Chat).",
      click: opts.onToggleViewMode,
    },
    ...buildManagementSubmenu(opts),
    {
      id: "settings",
      label: "Settings",
      click: () => opts.onOpenRoute("/settings"),
    },
    {
      id: "check-updates",
      label: "Check for updates",
      enabled: false,
      toolTip: "Available in AD-759c",
      click: opts.onCheckForUpdates,
    },
    {
      id: "reset-setup",
      label: "Reset Setup…",
      toolTip: "Re-run the first-run onboarding wizard (AD-790)",
      click: opts.onResetSetup,
    },
    {
      id: "separator-1",
      label: "",
      type: "separator",
    },
    {
      id: "quit",
      label: "Quit",
      click: opts.onQuit,
    },
  ];
}

/**
 * Count actionable (non-separator) items. Spec requires 8.
 */
export function actionableCount(items: readonly TrayMenuItem[]): number {
  return items.filter((i) => i.type !== "separator").length;
}

/**
 * AD-815b: build the "Chat with..." submenu entry from the supplied agents.
 *
 * Returns an empty array when no agents are supplied (preserves the original
 * 10-item layout). When at least one agent is supplied, returns a single
 * submenu item slotting between "Quick capture" and the proactive toggle.
 */
export function buildChatWithSubmenu(
  opts: Pick<TrayMenuOptions, "agents" | "onStartChatWithAgent">,
): TrayMenuItem[] {
  const agents = opts.agents ?? [];
  if (agents.length === 0) {
    return [];
  }
  const onStart = opts.onStartChatWithAgent;
  return [
    {
      id: "chat-with",
      label: "Chat with…",
      type: "submenu",
      submenu: agents.map((a) => ({
        id: `chat-with:${a.id}`,
        label: a.name,
        click: onStart ? (): void => onStart(a.id) : undefined,
      })),
    },
  ];
}

const MANAGEMENT_VIEWS: readonly { id: ViewTarget; label: string }[] = [
  { id: "agents", label: "Agents" },
  { id: "skills", label: "Skills" },
  { id: "settings", label: "Settings" },
  { id: "wardroom", label: "Ward Room" },
  { id: "work", label: "Work" },
  { id: "system", label: "System" },
];

/**
 * AD-841d: build the "Management" submenu. Unlike `buildChatWithSubmenu`, it is
 * ALWAYS present (the six surfaces are static). Each entry calls
 * `opts.onOpenView?.(id)` — NO Electron side effects, so the builder stays pure.
 */
export function buildManagementSubmenu(
  opts: Pick<TrayMenuOptions, "onOpenView">,
): TrayMenuItem[] {
  const onOpenView = opts.onOpenView;
  return [
    {
      id: "management",
      label: "Management",
      type: "submenu",
      submenu: MANAGEMENT_VIEWS.map((v) => ({
        id: `view:${v.id}`,
        label: v.label,
        click: onOpenView ? (): void => onOpenView(v.id) : undefined,
      })),
    },
  ];
}
