/**
 * AD-790: tests for the first-run state file primitives.
 */

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  SETUP_VERSION,
  completeFirstRun,
  isFirstRun,
  loadState,
  resetFirstRun,
  stateFilePath,
} from "./firstRun";

describe("firstRun state (AD-790)", () => {
  let tmp: string;

  beforeEach(() => {
    tmp = mkdtempSync(join(tmpdir(), "yeo-firstrun-"));
  });

  afterEach(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  it("isFirstRun returns true on a brand-new userData dir", () => {
    expect(isFirstRun(tmp)).toBe(true);
  });

  it("loadState returns firstRunComplete=false when no file exists", () => {
    const s = loadState(tmp);
    expect(s.firstRunComplete).toBe(false);
    expect(s.setupCompletedAt).toBeUndefined();
  });

  it("completeFirstRun writes the state file with the current setupVersion", () => {
    const before = Date.now();
    const result = completeFirstRun(tmp, before);
    expect(result.firstRunComplete).toBe(true);
    expect(result.setupVersion).toBe(SETUP_VERSION);
    expect(result.setupCompletedAt).toBe(before);
    expect(existsSync(stateFilePath(tmp))).toBe(true);
  });

  it("isFirstRun returns false after completeFirstRun", () => {
    completeFirstRun(tmp);
    expect(isFirstRun(tmp)).toBe(false);
  });

  it("loadState round-trips through the JSON file", () => {
    completeFirstRun(tmp, 1700000000000);
    const s = loadState(tmp);
    expect(s.firstRunComplete).toBe(true);
    expect(s.setupCompletedAt).toBe(1700000000000);
    expect(s.setupVersion).toBe(SETUP_VERSION);
  });

  it("loadState recovers gracefully from a corrupted state file", () => {
    // Write garbage at the state-file location.
    const fs = require("node:fs") as typeof import("node:fs");
    fs.mkdirSync(tmp, { recursive: true });
    fs.writeFileSync(stateFilePath(tmp), "{not valid json", "utf-8");
    const s = loadState(tmp);
    expect(s.firstRunComplete).toBe(false);
  });

  it("resetFirstRun removes the state file and returns true", () => {
    completeFirstRun(tmp);
    expect(existsSync(stateFilePath(tmp))).toBe(true);
    const removed = resetFirstRun(tmp);
    expect(removed).toBe(true);
    expect(existsSync(stateFilePath(tmp))).toBe(false);
    expect(isFirstRun(tmp)).toBe(true);
  });

  it("resetFirstRun returns false when no state file exists", () => {
    expect(resetFirstRun(tmp)).toBe(false);
  });

  it("the persisted JSON contains stable field names that downstream tools can parse", () => {
    completeFirstRun(tmp, 1234567890);
    const raw = readFileSync(stateFilePath(tmp), "utf-8");
    const parsed = JSON.parse(raw);
    expect(parsed.firstRunComplete).toBe(true);
    expect(parsed.setupCompletedAt).toBe(1234567890);
    expect(parsed.setupVersion).toBe(SETUP_VERSION);
  });
});
