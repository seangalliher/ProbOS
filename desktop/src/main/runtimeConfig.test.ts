import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  DEFAULT_RUNTIME_URL,
  configFilePath,
  isValidRuntimeUrl,
  loadRuntimeConfig,
  normaliseRuntimeUrl,
  resolveRuntimeUrl,
  saveRuntimeConfig,
} from "./runtimeConfig";

describe("runtimeConfig (AD-817)", () => {
  let tmp: string;
  beforeEach(() => { tmp = mkdtempSync(join(tmpdir(), "yeo-rtcfg-")); });
  afterEach(() => { rmSync(tmp, { recursive: true, force: true }); });

  it("isValidRuntimeUrl accepts http and https origins, rejects everything else", () => {
    expect(isValidRuntimeUrl("http://127.0.0.1:18900")).toBe(true);
    expect(isValidRuntimeUrl("https://example.com")).toBe(true);
    expect(isValidRuntimeUrl("http://127.0.0.1:18900/api/x")).toBe(false);
    expect(isValidRuntimeUrl("ftp://x")).toBe(false);
    expect(isValidRuntimeUrl("")).toBe(false);
    expect(isValidRuntimeUrl(null)).toBe(false);
  });

  it("normaliseRuntimeUrl strips trailing slashes", () => {
    expect(normaliseRuntimeUrl("http://x:1/")).toBe("http://x:1");
    expect(normaliseRuntimeUrl("http://x:1///")).toBe("http://x:1");
  });

  it("resolveRuntimeUrl returns the built-in default when no file or env present", () => {
    expect(resolveRuntimeUrl({ userDataDir: tmp, env: {} })).toBe(DEFAULT_RUNTIME_URL);
  });

  it("resolveRuntimeUrl prefers env var over default", () => {
    const got = resolveRuntimeUrl({
      userDataDir: tmp,
      env: { PROBOS_RUNTIME_URL: "http://127.0.0.1:9000" },
    });
    expect(got).toBe("http://127.0.0.1:9000");
  });

  it("resolveRuntimeUrl prefers persisted file over env and default", () => {
    saveRuntimeConfig(tmp, { runtimeUrl: "http://127.0.0.1:7777" });
    const got = resolveRuntimeUrl({
      userDataDir: tmp,
      env: { PROBOS_RUNTIME_URL: "http://127.0.0.1:9000" },
    });
    expect(got).toBe("http://127.0.0.1:7777");
  });

  it("loadRuntimeConfig returns null when the file is missing, malformed, or has an invalid URL", () => {
    expect(loadRuntimeConfig(tmp)).toBeNull();
    writeFileSync(configFilePath(tmp), "not json", "utf-8");
    expect(loadRuntimeConfig(tmp)).toBeNull();
    writeFileSync(configFilePath(tmp), JSON.stringify({ runtimeUrl: "ftp://x" }), "utf-8");
    expect(loadRuntimeConfig(tmp)).toBeNull();
  });

  it("saveRuntimeConfig throws on invalid URL and round-trips on valid URL", () => {
    expect(() => saveRuntimeConfig(tmp, { runtimeUrl: "not a url" })).toThrow();
    const saved = saveRuntimeConfig(tmp, { runtimeUrl: "http://127.0.0.1:18900/" });
    expect(saved.runtimeUrl).toBe("http://127.0.0.1:18900");
    const reloaded = loadRuntimeConfig(tmp);
    expect(reloaded?.runtimeUrl).toBe("http://127.0.0.1:18900");
  });
});
