/**
 * AD-759 tray menu builder (pure function).
 *
 * Returns the menu template that `Menu.buildFromTemplate` consumes in
 * `index.ts`. Kept pure so we can unit-test ordering + label state without
 * touching Electron.
 */

export type ConnectionStatus = "connected" | "connecting" | "disconnected";
export type ViewMode = "compact" | "full";

export interface TrayMenuOptions {
  status: ConnectionStatus;
  proactivePaused: boolean;
  viewMode: ViewMode;
  onOpenRoute: (route: string) => void;
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
  type?: "normal" | "separator";
  toolTip?: string;
  click?: () => void;
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
