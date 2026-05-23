/**
 * AD-817: runtime URL persistence + resolution for the Yeo desktop host.
 *
 * Resolution order (highest priority first):
 *   1. Persisted value in <userData>/runtime-config.json
 *   2. PROBOS_RUNTIME_URL environment variable
 *   3. Built-in default (DEFAULT_RUNTIME_URL)
 *
 * Pure-function I/O — no Electron API dependency — so the module is
 * testable under Vitest without spinning the full Electron host.
 */

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

/**
 * BF-324 already validated 127.0.0.1:* through CSP. This default is a
 * polite breaking change for operators previously relying on 8765 —
 * documented in the AD-817 release note; behaviour falls back to the
 * env var, so anyone who has set PROBOS_RUNTIME_URL=http://127.0.0.1:8765
 * is unaffected.
 */
export const DEFAULT_RUNTIME_URL = "http://127.0.0.1:18900";

/** Common ports the runtime is likely to bind in dev/prod configurations. */
export const PORT_CANDIDATES: ReadonlyArray<number> = [
  18900, 8765, 8000, 8080,
];

export interface RuntimeConfig {
  runtimeUrl: string;
}

export function configFilePath(userDataDir: string): string {
  return join(userDataDir, "runtime-config.json");
}

/** Validate that a string looks like an http(s)://host[:port] URL with no path. */
export function isValidRuntimeUrl(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    const u = new URL(value);
    if (u.protocol !== "http:" && u.protocol !== "https:") return false;
    // Reject paths/search/hash — runtime URL is an origin only.
    if (u.pathname !== "/" && u.pathname !== "") return false;
    if (u.search || u.hash) return false;
    return true;
  } catch {
    return false;
  }
}

/** Strip any trailing slash for consistent string concatenation downstream. */
export function normaliseRuntimeUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

export function loadRuntimeConfig(userDataDir: string): RuntimeConfig | null {
  const path = configFilePath(userDataDir);
  if (!existsSync(path)) return null;
  try {
    const raw = readFileSync(path, "utf-8");
    const parsed = JSON.parse(raw) as Partial<RuntimeConfig>;
    if (!isValidRuntimeUrl(parsed.runtimeUrl)) return null;
    return { runtimeUrl: normaliseRuntimeUrl(parsed.runtimeUrl) };
  } catch {
    return null;
  }
}

export function saveRuntimeConfig(
  userDataDir: string,
  config: RuntimeConfig,
): RuntimeConfig {
  if (!isValidRuntimeUrl(config.runtimeUrl)) {
    throw new Error(`invalid runtime URL: ${config.runtimeUrl}`);
  }
  const normalised: RuntimeConfig = {
    runtimeUrl: normaliseRuntimeUrl(config.runtimeUrl),
  };
  const path = configFilePath(userDataDir);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(normalised, null, 2), "utf-8");
  return normalised;
}

export interface ResolveOptions {
  userDataDir: string;
  env?: NodeJS.ProcessEnv;
}

/**
 * Resolve the runtime URL using the documented precedence. Pure — the env
 * argument is injectable so tests don't have to mutate process.env.
 */
export function resolveRuntimeUrl({
  userDataDir,
  env = process.env,
}: ResolveOptions): string {
  const stored = loadRuntimeConfig(userDataDir);
  if (stored) return stored.runtimeUrl;
  const envUrl = env.PROBOS_RUNTIME_URL;
  if (typeof envUrl === "string" && isValidRuntimeUrl(envUrl)) {
    return normaliseRuntimeUrl(envUrl);
  }
  return DEFAULT_RUNTIME_URL;
}
