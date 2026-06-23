import { describe, it, expect } from "vitest";
import { buildTrayMenu, actionableCount, buildManagementSubmenu } from "./trayMenu";

function noop(): void {
  /* test stub */
}

describe("buildTrayMenu", () => {
  it("returns the documented 11 actionable items in order", () => {
    const items = buildTrayMenu({
      status: "connected",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });

    expect(actionableCount(items)).toBe(11);
    expect(items.map((i) => i.id)).toEqual([
      "status",
      "open-chat",
      "daily-briefing",
      "quick-capture",
      "toggle-proactive",
      "view-mode",
      "management",
      "settings",
      "check-updates",
      "reset-setup",
      "separator-1",
      "quit",
    ]);
  });

  it("status label reflects 'connected' state", () => {
    const items = buildTrayMenu({
      status: "connected",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    expect(items[0].label).toBe("Status: Connected");
  });

  it("status label reflects 'connecting' state", () => {
    const items = buildTrayMenu({
      status: "connecting",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    expect(items[0].label).toBe("Status: Connecting…");
  });

  it("status label reflects 'disconnected' state", () => {
    const items = buildTrayMenu({
      status: "disconnected",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    expect(items[0].label).toBe("Status: Disconnected");
  });

  it("proactive toggle label flips with paused state", () => {
    const itemsActive = buildTrayMenu({
      status: "connected",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    expect(itemsActive.find((i) => i.id === "toggle-proactive")?.label).toBe("Pause proactive mode");

    const itemsPaused = buildTrayMenu({
      status: "connected",
      proactivePaused: true,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    expect(itemsPaused.find((i) => i.id === "toggle-proactive")?.label).toBe("Resume proactive mode");
  });

  it("check-for-updates is disabled with tooltip pointing to AD-759c", () => {
    const items = buildTrayMenu({
      status: "connected",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: noop,
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    const checkUpdates = items.find((i) => i.id === "check-updates");
    expect(checkUpdates).toBeDefined();
    expect(checkUpdates?.enabled).toBe(false);
    expect(checkUpdates?.toolTip).toContain("AD-759c");
  });

  it("click handlers route to the expected paths", () => {
    const routes: string[] = [];
    const items = buildTrayMenu({
      status: "connected",
      proactivePaused: false,
      viewMode: "compact",
      onOpenRoute: (r) => routes.push(r),
      onToggleProactive: noop,
      onToggleViewMode: noop,
      onCheckForUpdates: noop,
      onResetSetup: noop,
      onQuit: noop,
    });
    items.find((i) => i.id === "open-chat")?.click?.();
    items.find((i) => i.id === "daily-briefing")?.click?.();
    items.find((i) => i.id === "quick-capture")?.click?.();
    items.find((i) => i.id === "settings")?.click?.();
    expect(routes).toEqual(["/", "/briefing", "/capture", "/settings"]);
  });

  it("exposes a Management submenu with the six surfaces in order", () => {
    const items = buildTrayMenu({
      status: "connected", proactivePaused: false, viewMode: "compact",
      onOpenRoute: noop, onToggleProactive: noop, onToggleViewMode: noop,
      onCheckForUpdates: noop, onResetSetup: noop, onQuit: noop,
    });
    const mgmt = items.find((i) => i.id === "management");
    expect(mgmt?.type).toBe("submenu");
    expect(mgmt?.submenu?.map((s) => s.id)).toEqual([
      "view:agents", "view:skills", "view:settings",
      "view:wardroom", "view:work", "view:system",
    ]);
    expect(mgmt?.submenu?.map((s) => s.label)).toEqual([
      "Agents", "Skills", "Settings", "Ward Room", "Work", "System",
    ]);
  });

  it("Management entries invoke onOpenView with the matching id", () => {
    const seen: string[] = [];
    const items = buildTrayMenu({
      status: "connected", proactivePaused: false, viewMode: "compact",
      onOpenRoute: noop, onOpenView: (id) => seen.push(id),
      onToggleProactive: noop, onToggleViewMode: noop,
      onCheckForUpdates: noop, onResetSetup: noop, onQuit: noop,
    });
    items.find((i) => i.id === "management")?.submenu?.forEach((s) => s.click?.());
    expect(seen).toEqual(["agents", "skills", "settings", "wardroom", "work", "system"]);
  });

  it("buildManagementSubmenu is pure and omits clicks when onOpenView is absent", () => {
    const items = buildManagementSubmenu({});
    expect(items).toHaveLength(1);
    expect(items[0].id).toBe("management");
    expect(items[0].submenu).toHaveLength(6);
    expect(items[0].submenu?.every((s) => s.click === undefined)).toBe(true);
  });
});
