/**
 * AD-811a: parse helpers for the [A2UI] choice widget.
 *
 * The Python extractor (``a2ui_extractor.py``) leaves an inline stub in
 * place of an extracted ``[A2UI]{json}[/A2UI]`` block:
 *
 *     [A2UI: a2ui-choice-1.json v1 - choice]
 *
 * ProfileChatTab splits a message body by newlines and tests each line
 * against ``A2UI_STUB_RE`` (BEFORE the artifact stub). A match renders an
 * ``A2UIChoiceCard``, which fetches the stored ``application/json``
 * artifact and parses it with ``parseChoiceSpec``.
 *
 * The content fetch (``fetchArtifactContent``) is reused from
 * ``artifactApi`` — the A2UI JSON is an ordinary AD-797 artifact, so we
 * do not duplicate the fetch here.
 */

/**
 * Stub format produced by ``a2ui_extractor.build_a2ui_stub``.
 * ASCII hyphen (NOT em-dash). AD-811b: the trailing token is the widget
 * ``kind`` (captured), so ProfileChatTab routes to the matching renderer.
 *
 * Matches:  [A2UI: <name> v<version> - <kind>]
 */
export const A2UI_STUB_RE = /^\[A2UI: ([^\]]+?) v(\d+) - (\w+)\]$/;

export interface ParsedA2UIStub {
  name: string;
  version: number;
  kind: string;
}

export function parseA2UIStub(line: string): ParsedA2UIStub | null {
  const m = A2UI_STUB_RE.exec(line);
  if (!m) return null;
  return { name: m[1], version: parseInt(m[2], 10), kind: m[3] };
}

export interface ParsedChoiceSpec {
  prompt: string;
  options: string[];
}

/**
 * Shape-validate the stored A2UI JSON. Returns ``null`` on ANY failure
 * (honest-degrade): malformed JSON, ``kind !== "choice"``, an empty
 * prompt, or fewer than 2 non-empty string options. The card falls back
 * to a wait/placeholder state rather than crashing the transcript.
 */
export function parseChoiceSpec(json: string): ParsedChoiceSpec | null {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    return null;
  }
  if (typeof data !== 'object' || data === null) return null;
  const obj = data as Record<string, unknown>;
  if (obj.kind !== 'choice') return null;
  if (typeof obj.prompt !== 'string' || obj.prompt.trim() === '') return null;
  if (!Array.isArray(obj.options)) return null;
  const options = obj.options.filter(
    (o): o is string => typeof o === 'string' && o.trim() !== '',
  );
  if (options.length < 2) return null;
  return { prompt: obj.prompt, options };
}

export interface ParsedMultiSelectSpec {
  prompt: string;
  options: string[];
  minSelect: number;
  maxSelect: number | null;
}

/**
 * AD-811b: shape-validate the stored multiselect A2UI JSON. Returns
 * ``null`` on ANY hard failure (honest-degrade): malformed JSON,
 * ``kind !== "multiselect"``, an empty prompt, a non-array ``options``,
 * or fewer than 2 non-empty string options. ``min_select`` defaults to 1
 * and is clamped into ``[1, options.length]``; ``max_select`` (when a
 * number) is clamped into ``[minSelect, options.length]`` — the backend
 * already rejected an out-of-range spec before it was stored, so the UI
 * clamps defensively rather than dropping the card.
 */
export function parseMultiSelectSpec(
  json: string,
): ParsedMultiSelectSpec | null {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    return null;
  }
  if (typeof data !== 'object' || data === null) return null;
  const obj = data as Record<string, unknown>;
  if (obj.kind !== 'multiselect') return null;
  if (typeof obj.prompt !== 'string' || obj.prompt.trim() === '') return null;
  if (!Array.isArray(obj.options)) return null;
  const options = obj.options.filter(
    (o): o is string => typeof o === 'string' && o.trim() !== '',
  );
  if (options.length < 2) return null;
  const rawMin =
    typeof obj.min_select === 'number' ? Math.floor(obj.min_select) : 1;
  const minSelect = Math.min(Math.max(rawMin, 1), options.length);
  let maxSelect: number | null = null;
  if (typeof obj.max_select === 'number') {
    maxSelect = Math.min(
      Math.max(Math.floor(obj.max_select), minSelect),
      options.length,
    );
  }
  return { prompt: obj.prompt, options, minSelect, maxSelect };
}
