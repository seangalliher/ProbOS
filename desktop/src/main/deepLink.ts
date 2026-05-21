/**
 * AD-759 deep-link parser + sanitizer for the `probos://` scheme.
 *
 * Pure function — no Electron dependency. Validates an incoming URL string
 * against the rules in `prompts/ad-759-yeo-native-desktop-tray-app.md` and
 * returns a renderer route ("/path?query") on success or a `DeepLinkError`
 * on failure.
 *
 * Rules (build prompt §3):
 *   - URL length must be <= 2048 chars
 *   - Scheme must be exactly `probos:`
 *   - Path segments allow `[a-zA-Z0-9_-]+` only
 *   - Query keys + values allow `[a-zA-Z0-9_-]+` only
 *   - Reject traversal (`..`), shell metacharacters, control chars
 */

export const MAX_DEEP_LINK_LENGTH = 2048;

const SEGMENT_RE = /^[a-zA-Z0-9_-]+$/;
const QUERY_KEY_VALUE_RE = /^[a-zA-Z0-9_-]+$/;
// Anything < 0x20, plus DEL (0x7f), is a control char.
const CONTROL_CHAR_RE = /[\u0000-\u001f\u007f]/;
// Conservative shell-metachar reject list applied to the entire raw URL.
// Note: `?` and `&` are legal URL syntax (query delimiter / pair joiner) so
// they are NOT in this set; bad queries are caught by the per-pair regex.
const SHELL_METACHAR_RE = /[`$|<>;\\'"*\s]/;

export interface DeepLinkSuccess {
  ok: true;
  route: string;
}

export interface DeepLinkError {
  ok: false;
  reason: string;
}

export type DeepLinkResult = DeepLinkSuccess | DeepLinkError;

/**
 * Parse a `probos://...` URL into a renderer route. Returns a tagged result
 * so callers can log the rejection reason without throwing.
 */
export function parseDeepLink(raw: string): DeepLinkResult {
  if (typeof raw !== "string" || raw.length === 0) {
    return { ok: false, reason: "empty-input" };
  }
  if (raw.length > MAX_DEEP_LINK_LENGTH) {
    return { ok: false, reason: "over-length" };
  }
  if (CONTROL_CHAR_RE.test(raw)) {
    return { ok: false, reason: "control-char" };
  }
  if (SHELL_METACHAR_RE.test(raw)) {
    return { ok: false, reason: "shell-metachar" };
  }
  if (!raw.toLowerCase().startsWith("probos://")) {
    return { ok: false, reason: "bad-scheme" };
  }

  // Strip scheme prefix; remainder is "path[?query]".
  const rest = raw.slice("probos://".length);
  if (rest.length === 0) {
    return { ok: false, reason: "empty-path" };
  }

  const queryIdx = rest.indexOf("?");
  const pathPart = queryIdx === -1 ? rest : rest.slice(0, queryIdx);
  const queryPart = queryIdx === -1 ? "" : rest.slice(queryIdx + 1);

  if (pathPart.length === 0) {
    return { ok: false, reason: "empty-path" };
  }

  // Reject any traversal token outright (defense in depth on top of segment regex).
  if (pathPart.split("/").some((seg) => seg === "..")) {
    return { ok: false, reason: "traversal" };
  }

  const segments = pathPart.split("/");
  for (const seg of segments) {
    if (!SEGMENT_RE.test(seg)) {
      return { ok: false, reason: "bad-path-segment" };
    }
  }

  // Validate query.
  let renderedQuery = "";
  if (queryPart.length > 0) {
    const pairs = queryPart.split("&");
    const validatedPairs: string[] = [];
    for (const pair of pairs) {
      const eqIdx = pair.indexOf("=");
      if (eqIdx === -1) {
        return { ok: false, reason: "bad-query-pair" };
      }
      const key = pair.slice(0, eqIdx);
      const value = pair.slice(eqIdx + 1);
      if (!QUERY_KEY_VALUE_RE.test(key) || !QUERY_KEY_VALUE_RE.test(value)) {
        return { ok: false, reason: "bad-query-pair" };
      }
      validatedPairs.push(`${key}=${value}`);
    }
    renderedQuery = `?${validatedPairs.join("&")}`;
  }

  const route = `/${segments.join("/")}${renderedQuery}`;
  return { ok: true, route };
}

/**
 * Scan an argv array (e.g. Electron `second-instance` event) for the first
 * `probos://...` token and return it, or null if none present.
 */
export function findDeepLinkInArgv(argv: readonly string[]): string | null {
  for (const arg of argv) {
    if (typeof arg === "string" && arg.toLowerCase().startsWith("probos://")) {
      return arg;
    }
  }
  return null;
}
