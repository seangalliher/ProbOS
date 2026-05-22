/**
 * AD-790: first-run state management for the Yeo Desktop tray app.
 *
 * Persists ``<userData>/yeo-state.json`` with the first-run completion
 * flag. The state file is created on first successful onboarding via
 * `completeFirstRun()` and removed on `resetFirstRun()` (operator
 * invokes the latter from the tray "Reset Setup..." menu item).
 *
 * Pure-function I/O — no Electron API dependency — so the file is
 * testable under Vitest without spinning the full Electron host.
 */

import { existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { mkdirSync } from "node:fs";

export interface YeoState {
  firstRunComplete: boolean;
  setupCompletedAt?: number;
  setupVersion?: number;
}

export const SETUP_VERSION = 1;

export function stateFilePath(userDataDir: string): string {
  return join(userDataDir, "yeo-state.json");
}

export function loadState(userDataDir: string): YeoState {
  const path = stateFilePath(userDataDir);
  if (!existsSync(path)) {
    return { firstRunComplete: false };
  }
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Partial<YeoState>;
    return {
      firstRunComplete: parsed.firstRunComplete === true,
      setupCompletedAt: typeof parsed.setupCompletedAt === "number" ? parsed.setupCompletedAt : undefined,
      setupVersion: typeof parsed.setupVersion === "number" ? parsed.setupVersion : undefined,
    };
  } catch {
    // Corrupted state file - treat as un-set-up and let the wizard fix it.
    return { firstRunComplete: false };
  }
}

export function isFirstRun(userDataDir: string): boolean {
  return !loadState(userDataDir).firstRunComplete;
}

export function completeFirstRun(userDataDir: string, now: number = Date.now()): YeoState {
  const path = stateFilePath(userDataDir);
  mkdirSync(dirname(path), { recursive: true });
  const next: YeoState = {
    firstRunComplete: true,
    setupCompletedAt: now,
    setupVersion: SETUP_VERSION,
  };
  writeFileSync(path, JSON.stringify(next, null, 2), "utf-8");
  return next;
}

export function resetFirstRun(userDataDir: string): boolean {
  const path = stateFilePath(userDataDir);
  if (!existsSync(path)) return false;
  try {
    unlinkSync(path);
    return true;
  } catch {
    return false;
  }
}
