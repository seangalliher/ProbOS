# AD-811b-1 — the `form` A2UI widget (3rd widget kind, #735)

**Status:** Builder-ready BuildSpec (VERIFY-FIRST, researched at HEAD `58dd7fb6`)
**Verdict:** ✅ Approved to build — ONE AD, default-OFF, surgical.
**Headline:** Add a `form` widget kind (multi-field labeled text input) that slots into the AD-811b N-kind dispatch with the `choice` + `multiselect` paths **byte-identical** and **`a2ui_extractor.py` UNTOUCHED** (the option-gate already no-ops for option-less specs).

**Current highest landed top-level AD = `AD-1052`.** AD-811b-1 is a **PRE-RESERVED #735 sub-number** (the `a2ui/__init__.py` module docstring names it: `form (AD-811b-1)`). It does **NOT** mint a new top-level AD.

**Dependencies:** AD-811a (`choice` + the `[A2UI]{json}[/A2UI]` tag), AD-811b (`multiselect` + the `_SPEC_BY_KIND` registry + `parse_a2ui_spec` + the `A2UISpec` union + `build_a2ui_stub(kind)` + the UI kind-switch). Both shipped 2026-06-24 (LOCAL/uncommitted at the time of the 811b BuildSpec; landed by HEAD `58dd7fb6`).

**Estimated tests:** pytest `test_ad811b_1_a2ui_form.py` ~28–32 cases (mirrors `test_ad811b_a2ui_multiselect.py`); vitest +1 `parseFormSpec` describe in `a2uiApi.test.ts`, +1 new `A2UIFormCard.test.tsx` (~8 cases), +1 form-dispatch describe in `ProfileChatTab.a2ui.test.tsx`.

---

## 0. Pre-flight STOP-flags (read before building)

1. **Working tree is NOT clean at HEAD `58dd7fb6`.** `git status` shows `M config/system.yaml` (a pre-existing tracked modification from other in-flight work) plus untracked drafts under `prompts/` and `docs/`. **AD-811b-1 must NOT touch `config/system.yaml` and must NOT stage that pre-existing modification.** Stage ONLY the files this BuildSpec names. If the Builder's pre-flight requires a clean tree, surface to the Architect — do **not** revert or discard the `config/system.yaml` change (it is someone else's work).

2. **The framing's "extractor option-gate guard" is ALREADY in place — `a2ui_extractor.py` needs ZERO production change.** HEAD `a2ui_extractor.py` L67-68 reads:
   ```python
   opts = getattr(spec, "options", None)
   if opts is not None and len(opts) > max_options:
   ```
   The `getattr(..., None)` default + `if opts is not None` means an **option-less `form` spec already no-ops the gate** (forms have no `options` attribute → `opts is None` → no skip). **Do NOT edit `a2ui_extractor.py`.** The "surgical extractor guard" the framing anticipated is unnecessary — it was made option-optional in AD-811b. The form test proves the no-op behaviorally; the production module stays UNTOUCHED. This is *more* surgical than the framing assumed.

3. **The 811b backend test `test_dispatch_unknown_kind_returns_none` uses `kind:"form"` as its "unknown kind" example** (`test_ad811b_a2ui_multiselect.py`). After `form` is registered, that payload `{"kind":"form","prompt":"q","options":["A","B"]}` routes to `AgentUIFormSpec.model_validate(...)`, which **fails (missing required `fields`) → returns `None`**. The test therefore **stays GREEN unchanged** (None for a new reason: valid-kind-invalid-spec instead of unknown-kind). **Do NOT edit `test_ad811b_a2ui_multiselect.py`** — it is the load-bearing regression guard and must pass unchanged. The new form test file adds a *semantically-correct* unknown-kind guard (`kind:"range"`) so the dispatch's unknown-kind branch keeps a non-stale assertion.

4. **No ESLint gate in `ui/`.** There is no `.eslintrc*` and no `eslint.config.*` in `ui/` (only vestigial `// eslint-disable-next-line` comments). The UI gate is `tsc -b` + `vite build` + `vitest`. A nested ternary in the dispatch compiles cleanly and is NOT a lint failure — but see §6c for why the dispatch keeps the existing two card JSX blocks byte-identical (the source-scan tests pin the literal `onChoice={onA2UIChoice ...}` text).

---

## 1. Problem

AD-811a shipped `choice`; AD-811b shipped `multiselect` + the N-kind dispatch. Both are `prompt` + `options: list[str]`. There is no way for a Lieutenant+ crew agent to ask the Captain a **small structured form** (a few labeled inputs) in a 1:1 DM. The `a2ui/__init__.py` docstring pre-reserves `form (AD-811b-1)` as the 3rd kind.

The KEY shape difference: a `form` is `prompt` + **`fields`** (label + free-text input per field) — there are **NO `options`**. The form card collects field VALUES (not a single/comma-joined pick) and posts them back as one readable string through the existing `sendText` chat route.

## 2. Solution (overview)

Add `AgentUIFormSpec` (+ a nested `AgentUIFormField`) as the 3rd registered kind. It slots into the AD-811b `_SPEC_BY_KIND` registry, the `A2UISpec` union, the unchanged extractor (which already no-ops the option-gate for option-less specs), the unchanged AD-797 two-call artifact write + `build_a2ui_stub(kind)`, and the single `communications.a2ui_enabled` gate (default False → byte-identical when off). The HXI gets a `parseFormSpec` + an `A2UIFormCard` (labeled text inputs + Submit) + a `form` case in the ProfileChatTab kind-switch. The card posts a single `label: value`-per-line string through the SAME `(opt) => sendText(opt)` call site — no new endpoint, no response correlation (that is AD-811f).

**Minimal v1 field shape (DECISION):** each field = `{label: str, required: bool = False}`, **free-text input only**. **No per-field type system** (text/number/date/select) in v1. See §3 for the deferral justification (→ AD-811b-1a if typed fields are ever warranted).

---

## 3. Decomposition judgement (decisions)

### 3a. ONE AD — typed fields deferred to AD-811b-1a
AD-811b-1 is ONE AD: the spec class + nested field model + registry/union line (`a2ui/__init__.py`), the teaching extension (`cognitive_agent.py`), the `parseFormSpec` + `A2UIFormCard` + ProfileChatTab `form` case (UI), and the pytest + vitest. The extractor, `reply_pipeline.py`, and `config.py` are **UNTOUCHED**.

**Defer the per-field TYPE system to AD-811b-1a.** v1 fields are `{label, required}` free-text only. Justification against the multiselect footprint: AD-811b added exactly **one** new spec class + **one** new card + **one** new parse fn + **one** dispatch case. A type system would add a `type` discriminator per field, per-type input rendering (number input, date picker, nested select), per-type validation, and per-type value coercion in the encoded response — a meaningfully larger surface that does NOT block the core capability ("ask a structured form, get values back"). Free-text covers the 80% case (names, roles, notes, numbers-as-text). Typed fields are a refinement, exactly as min/max-select UX was a refinement on `choice`. **Recommend AD-811b-1a (typed fields) only if a real workflow needs server-side numeric/date validation; do not build it now.**

### 3b. Response encoding — single readable string through `sendText` (NO new endpoint)
The card posts `spec.fields.map((f, i) => `${f.label}: ${values[i].trim()}`).join('\n')` — e.g. `"Name: Ada\nRole: Engineer"` — through `onChoice`, which the call site wires to `(opt) => sendText(opt)` (ProfileChatTab.tsx L1184). **Confirmed the contract supports a free-form string:** `onA2UIChoice?: (option: string) => void` (ProfileChatTab.tsx L115) and the multiselect card already posts a free-form joined string (`A2UIMultiSelectCard.tsx` L104 `onChoice(spec.options.filter(...).join(', '))`). No response correlation (AD-811f), no new API route. A multi-line message re-renders cleanly (each `label: value` line is plain text — no stub match in `renderMessageBodyWithArtifacts`).

### 3c. Field-count cap lives in the SCHEMA (`config.py` UNTOUCHED)
Add a module constant `_MAX_FIELDS = 20` to `a2ui/__init__.py` (mirrors `_MAX_OPTIONS_HARD_CAP = 20`). `AgentUIFormSpec`'s field validator caps at `_MAX_FIELDS`. **Confirmed `a2ui_max_options` is the only relevant config gate** (config.py L5218, `ge=2, le=20`) and it is option-specific; the extractor's option-gate no-ops for forms (opts=None), so a form's field count is bounded entirely by the schema. `config.py` stays UNTOUCHED.

---

## 4. Verified research at HEAD `58dd7fb6` (real signatures)

### 4a. `src/probos/a2ui/__init__.py` (the schema + dispatch — EDIT here)
- `_MAX_OPTIONS_HARD_CAP = 20`, `_MAX_PROMPT_LEN = 500` (module constants).
- `_clean_prompt(v: str) -> str` (trim + non-empty + ≤500) and `_clean_options(v: list[str]) -> list[str]` (trim/drop-empty/dedupe-order-preserved/2..20) — shared validators.
- `AgentUIChoiceSpec(kind: Literal["choice"]="choice", prompt, options)`; `to_json = model_dump_json`, `from_json = model_validate_json`.
- `AgentUIMultiSelectSpec(kind: Literal["multiselect"], prompt, options, min_select: int=Field(default=1, ge=1), max_select: int|None)` + `@model_validator(mode="after")` bounds.
- `A2UISpec = AgentUIChoiceSpec | AgentUIMultiSelectSpec` (the union to extend).
- `_SPEC_BY_KIND: dict[str, type[A2UISpec]] = {"choice": ..., "multiselect": ...}` (the registry to extend).
- `parse_a2ui_spec(raw: str) -> A2UISpec | None`: `json.loads` → `isinstance(data, dict)` → `kind = data.get("kind")` → `_SPEC_BY_KIND.get(kind)` if `isinstance(kind, str)` → `cls.model_validate(data)`; honest-degrade `None` on any failure.
- **No `__all__`** — new public names become importable just by defining them in the module.
- `build_a2ui_stub` is **NOT** here (it lives in the extractor). Confirmed.

### 4b. `src/probos/cognitive/dm/a2ui_extractor.py` (UNTOUCHED — verified form-safe)
- `extract_a2ui(text: str, *, max_options: int = 10) -> list[A2UISpec]` — the EXACT signature.
- The **option-gate line** (L67-68), the load-bearing line for the option-less form:
  ```python
  opts = getattr(spec, "options", None)
  if opts is not None and len(opts) > max_options:
  ```
  → an option-less `form` spec yields `opts is None` → the gate **no-ops**. **No change required.**
- `build_a2ui_stub(name: str, version: int, kind: str = "choice") -> str` → `f"[A2UI: {name} v{version} - {kind}]"` (L77). Already kind-generic.
- `replace_a2ui_with_stubs(...)`: AD-797 two-call write — `sha256(blob)` → `await attachment_store.write(content_hash, blob, "application/json", origin="agent_artifact")` → `name = f"a2ui-{spec.kind}-{name_n}.json"` → `artifact_store.add_version(...)` → `build_a2ui_stub(artifact.name, artifact.version, spec.kind)`. Already kind-generic via `spec.kind`. **No change required.**

### 4c. `cognitive_agent._conversational_a2ui_block` (EDIT — teaching, L2231)
- Returns `""` unless `a2ui_enabled` AND the agent's LIVE rank ≥ `a2ui_min_rank` (BF-263: rank derived from `runtime.trust_network.get_score(self.id)` → `Rank.from_trust`, since `self.rank` is never set).
- The teaching string (L2283-2297) currently teaches `choice` + `multiselect` JSON shapes, gap-regex-clean.
- **`_CAPABILITY_GAP_RE`** (decomposer.py L33-40) forbidden phrases: `don't have` · `can't`/`cannot`/`unable to` · `no (built-in/native)? (capability|ability|support|way|mechanism|tool)` · `not (available|supported|possible)` · `lack(s|ing)?` · `doesn't (have|support)` · `beyond (my|current) (capabilities|abilities)` · `outside (my|the) (scope|capabilities)`. The form clause must avoid all of these.

### 4d. `reply_pipeline.step_4k_extract_a2ui` (UNTOUCHED — kind-agnostic, L1233)
- Gated on `a2ui_enabled`; reads `max_options = getattr(comms_cfg, "a2ui_max_options", 10)` (L1271); calls `specs = extract_a2ui(text, max_options=max_options)` (L1276); stores via `replace_a2ui_with_stubs`. No `kind` literal anywhere. **No change required.**

### 4e. `config.py` `CommunicationsConfig` (UNTOUCHED — L5210-5220)
- `a2ui_enabled: bool = Field(default=False, ...)`, `a2ui_min_rank: str = Field(default="lieutenant", ...)`, `a2ui_max_options: int = Field(default=10, ge=2, le=20, ...)`. The form self-caps fields via the schema `_MAX_FIELDS`. **No change required.**

### 4f. UI — `ui/src/components/a2ui/a2uiApi.ts` (EDIT — add `parseFormSpec`)
- `A2UI_STUB_RE = /^\[A2UI: ([^\]]+?) v(\d+) - (\w+)\]$/`; `parseA2UIStub(line) -> {name, version, kind}` (kind already captured — a `form` stub `[A2UI: a2ui-form-1.json v1 - form]` parses with `kind: "form"` **without any change**).
- `parseChoiceSpec(json) -> {prompt, options} | null` and `parseMultiSelectSpec(json) -> {prompt, options, minSelect, maxSelect} | null` — the form parser mirrors the **`parseMultiSelectSpec` shape** (JSON.parse → object check → `kind !== 'form'` reject → prompt non-empty → array check → per-item clean/dedupe → min count → return).

### 4g. UI — `A2UIMultiSelectCard.tsx` + `A2UIChoiceCard.tsx` (card→chat contract the form mirrors)
- Props: `{threadId, name, version, onChoice: (response: string) => void}`.
- Resolve `(threadId, name, version)` against `useStore(s => s.artifactsByThread)`; `fetchArtifactContent(resolved.id).then(({text}) => setSpec(parseX(text)))`; loading `<span data-testid="a2ui-...-card">` until resolved.
- Multiselect: toggles a `Set`, `canSubmit = !submitted && selected.size >= spec.minSelect`, on submit `onChoice(spec.options.filter(o => selected.has(o)).join(', '))` then `setSubmitted(true)` (one-shot lock). Plain-text labels, no emoji.

### 4h. UI — `ProfileChatTab.tsx` dispatch (EDIT — add the `form` case)
- `renderMessageBodyWithArtifacts(text, threadId, onA2UIChoice?: (option: string) => void)` (L113-115) splits on `\n`; for each line: `const a2ui = parseA2UIStub(line)`; **the allowlist** (L126-127):
  ```tsx
  if (a2ui && threadId
      && (a2ui.kind === 'choice' || a2ui.kind === 'multiselect')) {
  ```
  then a 2-way ternary (`multiselect ? <A2UIMultiSelectCard ...> : <A2UIChoiceCard ...>`), each card passing `onChoice={onA2UIChoice ?? (() => {})}`.
- **Call site (L1184), UNTOUCHED:** `body={renderMessageBodyWithArtifacts(msg.text, threadId, (opt) => sendText(opt))}` — the single 1:1 send route the form card reuses.

### 4i. Tests (templates + guards)
- pytest template: `tests/test_ad811b_a2ui_multiselect.py` (schema validation · dispatch · extractor · stub + two-call write · pipeline · teaching). Uses **real** `ArtifactStore(tmp_path/"artifacts.db")` + **real** `FilesystemAttachmentStore(tmp_path/"attachments")` (BF-287 discipline, no MagicMock at the storage boundary); `SimpleNamespace` runtime; `_FakeTrust`; unbound-method `CognitiveAgent._conversational_a2ui_block(fake_self, {})` teaching pattern.
- Load-bearing guards (must pass UNCHANGED): `tests/test_ad811a_a2ui_choice.py`, `tests/test_ad811b_a2ui_multiselect.py`; UI `a2uiApi.test.ts`, `A2UIChoiceCard.test.tsx`, `A2UIMultiSelectCard.test.tsx`, `ProfileChatTab.a2ui.test.tsx`.
- vitest templates: `ui/src/components/a2ui/__tests__/a2uiApi.test.ts`, `A2UIMultiSelectCard.test.tsx`, `ui/src/components/profile/__tests__/ProfileChatTab.a2ui.test.tsx`.

---

## 5. File-by-file BuildSpec

### Section 1 — `src/probos/a2ui/__init__.py` (schema + registry + union)

**1a.** Add a module constant next to `_MAX_OPTIONS_HARD_CAP` / `_MAX_PROMPT_LEN`:

```python
# AD-811b-1: schema-level hard cap on a form's field count, mirroring
# `_MAX_OPTIONS_HARD_CAP`. The config gate `a2ui_max_options` is
# option-specific and no-ops for forms (the extractor reads `spec.options`,
# which a form lacks), so fields are bounded entirely by the schema.
_MAX_FIELDS = 20
```

**1b.** Add the nested field model + the form spec **after** `AgentUIMultiSelectSpec` and **before** the `A2UISpec = ...` union line:

```python
class AgentUIFormField(BaseModel):
    """One labeled free-text input in an :class:`AgentUIFormSpec`.

    AD-811b-1: v1 fields are free text only (no per-field type system —
    that is AD-811b-1a if ever warranted). ``label`` is trimmed here; the
    parent spec drops empty-label fields and dedupes by label (mirroring
    ``_clean_options``). ``required`` gates the card's Submit button.
    """

    label: str
    required: bool = False

    @field_validator("label")
    @classmethod
    def _trim_label(cls, v: str) -> str:
        # Trim only (no raise): the parent spec drops empty labels, mirroring
        # the trim-then-drop behavior of `_clean_options`.
        return (v or "").strip()


class AgentUIFormSpec(BaseModel):
    """A multi-field form widget spec carried by an ``[A2UI]{json}[/A2UI]`` tag.

    AD-811b-1: the 3rd A2UI widget kind. ``prompt`` shares the
    ``_clean_prompt`` validator; ``fields`` is an ordered list of labeled
    free-text inputs (1..``_MAX_FIELDS`` after validation — empty labels
    dropped, deduped by label, order preserved). The HXI renders one text
    input per field and posts the filled values back as ``label: value``
    lines through the existing ``sendText`` chat route.
    """

    kind: Literal["form"] = "form"
    prompt: str
    fields: list[AgentUIFormField]

    @field_validator("prompt")
    @classmethod
    def _validate_prompt(cls, v: str) -> str:
        return _clean_prompt(v)

    @field_validator("fields")
    @classmethod
    def _validate_fields(
        cls, v: list[AgentUIFormField]
    ) -> list[AgentUIFormField]:
        cleaned: list[AgentUIFormField] = []
        seen: set[str] = set()
        for f in v or []:
            if not f.label or f.label in seen:
                continue
            seen.add(f.label)
            cleaned.append(f)
        if len(cleaned) < 1:
            raise ValueError("a form spec needs at least 1 field")
        if len(cleaned) > _MAX_FIELDS:
            raise ValueError(
                f"a form spec accepts at most {_MAX_FIELDS} fields"
            )
        return cleaned

    def to_json(self) -> str:
        """Serialize to a compact JSON string (the artifact body)."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "AgentUIFormSpec":
        """Parse + validate a JSON string. Raises on malformed/invalid input."""
        return cls.model_validate_json(raw)
```

**1c.** Extend the union (one line) — SEARCH:
```python
A2UISpec = AgentUIChoiceSpec | AgentUIMultiSelectSpec
```
REPLACE:
```python
A2UISpec = AgentUIChoiceSpec | AgentUIMultiSelectSpec | AgentUIFormSpec
```

**1d.** Extend the registry — SEARCH:
```python
_SPEC_BY_KIND: dict[str, type[A2UISpec]] = {
    "choice": AgentUIChoiceSpec,
    "multiselect": AgentUIMultiSelectSpec,
}
```
REPLACE:
```python
_SPEC_BY_KIND: dict[str, type[A2UISpec]] = {
    "choice": AgentUIChoiceSpec,
    "multiselect": AgentUIMultiSelectSpec,
    "form": AgentUIFormSpec,
}
```

**1e.** Update the module docstring's "What this module does NOT do" list: remove `form (AD-811b-1)` from the deferred list (it is now done) — leave `range (AD-811b-2)`, `date (AD-811b-3)`, and the AD-811c/d/e/f items. (Cosmetic but keeps the docstring honest.)

### Section 2 — `src/probos/cognitive/dm/a2ui_extractor.py` — **UNTOUCHED**
No production change. The option-gate (`getattr(spec, "options", None)` + `if opts is not None`) already no-ops for forms; `build_a2ui_stub` + `replace_a2ui_with_stubs` are already kind-generic via `spec.kind`. The form path is proved behaviorally by the new pytest (§7), not by editing this module.

### Section 3 — `cognitive_agent._conversational_a2ui_block` (teaching, EDIT)
Replace the `return ( ... )` teaching string (L2283-2297) to ALSO teach the `form` shape. Recommended (the Builder MUST re-verify gap-clean before commit):

```python
            return (
                "\n\nOffering the Captain a quick choice: when a question has a "
                "small set of clear options, you may present them as clickable "
                "buttons. Emit [A2UI]{\"kind\":\"choice\",\"prompt\":\"your "
                "question\",\"options\":[\"Option A\",\"Option B\"]}[/A2UI] for "
                "a single pick, [A2UI]{\"kind\":\"multiselect\",\"prompt\":"
                "\"your question\",\"options\":[\"Option A\",\"Option B\","
                "\"Option C\"],\"min_select\":1}[/A2UI] when several picks make "
                "sense at once, or [A2UI]{\"kind\":\"form\",\"prompt\":\"your "
                "question\",\"fields\":[{\"label\":\"Name\"},{\"label\":"
                "\"Role\",\"required\":true}]}[/A2UI] to gather a few labeled "
                "values together. The tag becomes an interactive card; a single "
                "choice comes back as the Captain's next message, a multi-select "
                "comes back as their picks joined by commas, and a form comes "
                "back as label: value lines. Keep it short (a handful of "
                "options or fields) and continue the conversation naturally "
                "once they respond."
            )
```

Gap-regex audit of the new clauses (all clean — no forbidden phrase): "to gather a few labeled values together" · "a form comes back as label: value lines" · "Keep it short (a handful of options or fields)" · "continue the conversation naturally once they respond". Still contains `"choice"` and `"multiselect"` (keeps `test_teach_enabled_contains_both_kinds` green) and contains no banned substring (`can't`/`cannot`/`don't have`/`unable to`/`not able to`).

### Section 4 — `ui/src/components/a2ui/a2uiApi.ts` (add `parseFormSpec`)
Append after `parseMultiSelectSpec` (do NOT modify `A2UI_STUB_RE`, `parseA2UIStub`, `parseChoiceSpec`, or `parseMultiSelectSpec` — they already handle the `form` stub kind and stay byte-identical):

```ts
export interface ParsedFormField {
  label: string;
  required: boolean;
}

export interface ParsedFormSpec {
  prompt: string;
  fields: ParsedFormField[];
}

/**
 * AD-811b-1: shape-validate the stored form A2UI JSON. Returns ``null`` on
 * ANY hard failure (honest-degrade): malformed JSON, ``kind !== "form"``,
 * an empty prompt, a non-array ``fields``, or zero valid fields. Each
 * field's ``label`` is trimmed; empty-label and duplicate-label fields are
 * dropped (order preserved) — mirroring the backend ``_validate_fields``.
 * ``required`` is true only for an explicit ``true``.
 */
export function parseFormSpec(json: string): ParsedFormSpec | null {
  let data: unknown;
  try {
    data = JSON.parse(json);
  } catch {
    return null;
  }
  if (typeof data !== 'object' || data === null) return null;
  const obj = data as Record<string, unknown>;
  if (obj.kind !== 'form') return null;
  if (typeof obj.prompt !== 'string' || obj.prompt.trim() === '') return null;
  if (!Array.isArray(obj.fields)) return null;
  const fields: ParsedFormField[] = [];
  const seen = new Set<string>();
  for (const raw of obj.fields) {
    if (typeof raw !== 'object' || raw === null) continue;
    const f = raw as Record<string, unknown>;
    const label = typeof f.label === 'string' ? f.label.trim() : '';
    if (!label || seen.has(label)) continue;
    seen.add(label);
    fields.push({ label, required: f.required === true });
  }
  if (fields.length < 1) return null;
  return { prompt: obj.prompt, fields };
}
```

### Section 5 — `ui/src/components/a2ui/A2UIFormCard.tsx` (NEW — mirror A2UIMultiSelectCard)
A new card: labeled text inputs + Submit, Submit gated on required fields filled, one-shot lock, posts `label: value` lines via `onChoice`. Plain-text labels only (no emoji — HXI #3). Required-field marker is an ASCII `*`.

```tsx
/**
 * AD-811b-1: interactive form card rendered in place of an [A2UI] stub
 * whose kind is ``form`` inside ProfileChatTab message bodies.
 *
 * Mirrors ``A2UIMultiSelectCard`` for artifact resolution + fetch, but the
 * Captain fills a free-text input per field. The DM pipeline stored the
 * JSON as an ``application/json`` artifact and left an inline stub:
 *
 *     [A2UI: a2ui-form-1.json v1 - form]
 *
 * Resolves ``(threadId, name, version)`` against
 * ``useStore.artifactsByThread``, fetches the JSON via
 * ``fetchArtifactContent``, parses it with ``parseFormSpec``, and renders
 * the prompt + one labeled text input per field + a Submit button. Submit
 * is enabled once every ``required`` field has a non-empty value. On submit
 * the card locks (all controls disabled) and calls ``onChoice`` with the
 * fields encoded as ``label: value`` lines (e.g. "Name: Ada\nRole: Eng");
 * ProfileChatTab posts that back through ``sendText`` (same callback the
 * choice + multiselect cards use).
 */
import { useEffect, useMemo, useState } from 'react';
import { useStore } from '../../store/useStore';
import { fetchArtifactContent } from '../artifacts/artifactApi';
import { parseFormSpec, type ParsedFormSpec } from './a2uiApi';

const AMBER = '#f0b060';
const DIM = '#888899';

export interface A2UIFormCardProps {
  /** The chat thread the message belongs to. */
  threadId: string;
  /** Parsed-from-stub artifact name. */
  name: string;
  /** Parsed-from-stub artifact version. */
  version: number;
  /** Called with the filled fields ("label: value" lines) on submit. */
  onChoice: (response: string) => void;
}

export function A2UIFormCard(props: A2UIFormCardProps) {
  const { threadId, name, version, onChoice } = props;
  const artifactsByThread = useStore((s) => s.artifactsByThread);
  const [spec, setSpec] = useState<ParsedFormSpec | null>(null);
  const [values, setValues] = useState<string[]>([]);
  const [submitted, setSubmitted] = useState(false);

  const resolved = useMemo(() => {
    const list = artifactsByThread.get(threadId) ?? [];
    return list.find((a) => a.name === name && a.version === version) ?? null;
  }, [artifactsByThread, threadId, name, version]);

  useEffect(() => {
    if (!resolved) return;
    let cancelled = false;
    fetchArtifactContent(resolved.id)
      .then(({ text }) => {
        if (cancelled) return;
        const parsed = parseFormSpec(text);
        setSpec(parsed);
        setValues(parsed ? parsed.fields.map(() => '') : []);
      })
      .catch(() => {
        if (!cancelled) setSpec(null);
      });
    return () => {
      cancelled = true;
    };
  }, [resolved]);

  if (!resolved || !spec) {
    return (
      <span
        data-testid="a2ui-form-card"
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6,
          margin: '4px 0', padding: '4px 8px',
          border: '1px solid rgba(255,255,255,0.1)', borderRadius: 4,
          background: 'rgba(240, 176, 96, 0.04)', color: DIM,
          fontFamily: "'JetBrains Mono', monospace", fontSize: 11,
          cursor: 'wait', whiteSpace: 'nowrap',
        }}
      >
        Loading form…
      </span>
    );
  }

  const canSubmit =
    !submitted &&
    spec.fields.every((f, i) => !f.required || (values[i] ?? '').trim() !== '');

  const setField = (i: number, v: string): void => {
    if (submitted) return;
    setValues((prev) => {
      const next = prev.slice();
      next[i] = v;
      return next;
    });
  };

  const submit = (): void => {
    if (!canSubmit) return;
    setSubmitted(true);
    onChoice(
      spec.fields
        .map((f, i) => `${f.label}: ${(values[i] ?? '').trim()}`)
        .join('\n'),
    );
  };

  return (
    <div
      data-testid="a2ui-form-card"
      style={{
        display: 'block', margin: '6px 0', padding: '10px 12px',
        border: `1px solid ${AMBER}`, borderRadius: 6,
        background: 'rgba(240, 176, 96, 0.06)',
        backdropFilter: 'blur(6px)',
        color: '#e0dcd4',
        fontFamily: "'Inter', system-ui, sans-serif",
      }}
    >
      <div style={{ fontSize: 13, marginBottom: 8 }}>{spec.prompt}</div>
      <div
        style={{
          display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 8,
        }}
      >
        {spec.fields.map((f, i) => (
          <label
            key={i}
            style={{
              display: 'flex', flexDirection: 'column', gap: 3,
              fontSize: 12, color: '#e0dcd4',
            }}
          >
            <span>
              {f.label}
              {f.required ? ' *' : ''}
            </span>
            <input
              data-testid={'a2ui-form-input-' + i}
              type="text"
              value={values[i] ?? ''}
              disabled={submitted}
              onChange={(e) => setField(i, e.target.value)}
              style={{
                padding: '5px 8px', borderRadius: 4,
                border: `1px solid rgba(240, 176, 96, 0.3)`,
                background: submitted ? 'transparent' : 'rgba(0,0,0,0.2)',
                color: submitted ? DIM : '#e0dcd4',
                fontFamily: "'Inter', system-ui, sans-serif",
                fontSize: 12,
              }}
            />
          </label>
        ))}
      </div>
      <button
        data-testid="a2ui-form-submit"
        disabled={!canSubmit}
        onClick={submit}
        style={{
          padding: '5px 14px', borderRadius: 4,
          border: `1px solid ${canSubmit ? AMBER : 'rgba(240, 176, 96, 0.3)'}`,
          background: canSubmit ? 'rgba(240, 176, 96, 0.18)' : 'transparent',
          color: canSubmit ? AMBER : DIM,
          fontFamily: "'Inter', system-ui, sans-serif",
          fontSize: 12,
          cursor: canSubmit ? 'pointer' : 'default',
        }}
      >
        Submit
      </button>
    </div>
  );
}
```

### Section 6 — `ui/src/components/profile/ProfileChatTab.tsx` (dispatch — add `form`)

**6a.** Add the import after the `A2UIMultiSelectCard` import (L10):
```tsx
import { A2UIFormCard } from '../a2ui/A2UIFormCard';
```

**6b.** Extend the allowlist — SEARCH:
```tsx
    if (a2ui && threadId
        && (a2ui.kind === 'choice' || a2ui.kind === 'multiselect')) {
```
REPLACE:
```tsx
    if (a2ui && threadId
        && (a2ui.kind === 'choice' || a2ui.kind === 'multiselect'
            || a2ui.kind === 'form')) {
```

**6c.** Extend the inner ternary to a 3-way (form → multiselect → choice). **Keep the existing `<A2UIMultiSelectCard ...>` and `<A2UIChoiceCard ...>` JSX blocks byte-identical** — the source-scan tests pin the literal `onChoice={onA2UIChoice ?? (() => {})}` in each card, so do NOT refactor `onChoice` into a local. SEARCH:
```tsx
          {a2ui.kind === 'multiselect' ? (
            <A2UIMultiSelectCard
              threadId={threadId}
              name={a2ui.name}
              version={a2ui.version}
              onChoice={onA2UIChoice ?? (() => {})}
            />
          ) : (
            <A2UIChoiceCard
              threadId={threadId}
              name={a2ui.name}
              version={a2ui.version}
              onChoice={onA2UIChoice ?? (() => {})}
            />
          )}
```
REPLACE:
```tsx
          {a2ui.kind === 'form' ? (
            <A2UIFormCard
              threadId={threadId}
              name={a2ui.name}
              version={a2ui.version}
              onChoice={onA2UIChoice ?? (() => {})}
            />
          ) : a2ui.kind === 'multiselect' ? (
            <A2UIMultiSelectCard
              threadId={threadId}
              name={a2ui.name}
              version={a2ui.version}
              onChoice={onA2UIChoice ?? (() => {})}
            />
          ) : (
            <A2UIChoiceCard
              threadId={threadId}
              name={a2ui.name}
              version={a2ui.version}
              onChoice={onA2UIChoice ?? (() => {})}
            />
          )}
```
(No ESLint gate in `ui/` — the nested ternary compiles via `tsc -b` + `vite build` and keeps the existing two card blocks pinned for the source-scan tests. The call site L1184 `(opt) => sendText(opt)` is UNTOUCHED.)

**6d.** Update the dispatch comment (L122-124) to mention `form` (cosmetic, keeps the comment honest).

---

## 7. Tests

### 7a. pytest — `tests/test_ad811b_1_a2ui_form.py` (NEW, mirrors `test_ad811b_a2ui_multiselect.py`)
Reuse the SAME fixtures/helpers as the 811b test (real `ArtifactStore` + real `FilesystemAttachmentStore` on `tmp_path`, `SimpleNamespace` runtime, `_FakeTrust`, `_teach_self`, `_ctx`, `_runtime_with_stores`). Imports add `AgentUIFormSpec`, `AgentUIFormField`.

1. **Schema — `AgentUIFormSpec`:**
   - `test_form_spec_valid_parses` — `kind == "form"`, prompt, `fields` length, `fields[i].label`, `fields[i].required` default `False`.
   - `test_form_spec_required_flag_explicit_true` — a field with `required=True` round-trips.
   - `test_form_spec_empty_label_fields_dropped` — `[{"label":"A"},{"label":"  "},{"label":""},{"label":"B"}]` → `["A","B"]`.
   - `test_form_spec_dedupe_by_label_preserves_order` — `[A,B,A,C,B]` → `[A,B,C]`.
   - `test_form_spec_zero_fields_rejected` — `fields=[]` → raises.
   - `test_form_spec_over_max_fields_rejected` — 21 fields → raises (`_MAX_FIELDS=20`).
   - `test_form_spec_single_field_ok` — 1 field is valid (forms allow 1, unlike choice's 2).
   - `test_form_spec_empty_prompt_rejected` — `prompt="   "` → raises.
   - `test_form_spec_kind_not_form_rejected` — `from_json` with `kind:"choice"` → raises.
   - `test_form_spec_to_json_from_json_roundtrip` — prompt + fields (label+required) + kind survive a round trip.

2. **Dispatch — `parse_a2ui_spec`:**
   - `test_dispatch_form_returns_form_spec` — form JSON → `isinstance(spec, AgentUIFormSpec)`, `kind == "form"`.
   - `test_dispatch_choice_still_returns_choice` + `test_dispatch_multiselect_still_returns_ms` — the AD-811a/811b regression THROUGH the registry (now that `form` is registered).
   - `test_dispatch_truly_unknown_kind_returns_none` — `{"kind":"range",...}` → `None` (a non-stale unknown-kind guard; the 811b test's `kind:"form"` example is now a *valid* kind, so this replaces its semantic intent in the new file).
   - `test_dispatch_form_missing_fields_returns_none` — `{"kind":"form","prompt":"q"}` (no `fields`) → `None` (valid kind, invalid spec).
   - `test_dispatch_form_zero_fields_returns_none` — `{"kind":"form","prompt":"q","fields":[]}` → `None`.
   - `test_dispatch_malformed_json_returns_none`, `test_dispatch_non_dict_returns_none` (mirror 811b).

3. **Extractor — `extract_a2ui` (module UNCHANGED; behavioral proof):**
   - `test_extract_form_block` — `[A2UI]{form json}[/A2UI]` → 1 `AgentUIFormSpec`.
   - `test_extract_form_ignores_option_gate` — a form with 5 fields + `max_options=3` → still 1 spec (the option-gate no-ops because `getattr(form, "options", None) is None`). **This is the key guard for the option-less form.**
   - `test_extract_choice_still_gated` — a `choice` with 5 options + `max_options=3` → `[]` (the gate is unchanged for option-bearing specs).
   - `test_extract_multiselect_still_gated` — same for `multiselect`.

4. **Stub + AD-797 two-call write:**
   - `test_build_stub_form_kind` — `build_a2ui_stub("a2ui-form-1.json", 1, "form") == "[A2UI: a2ui-form-1.json v1 - form]"`.
   - `test_replace_form_names_and_stub` (async, `tmp_path`) — form spec → `a2ui-form-1.json` artifact + `[A2UI: a2ui-form-1.json v1 - form]` stub + `art.latest(...)` is not None + mime `application/json`.

5. **Pipeline — `step_4k_extract_a2ui` (module UNCHANGED; behavioral proof):**
   - `test_step_4k_enabled_extracts_form` (async) — enabled → form stub in `response_text` + artifact written.
   - `test_step_4k_disabled_form_byte_identical` (async) — disabled → `response_text` unchanged + no artifact.

6. **Teaching — `_conversational_a2ui_block`:**
   - `test_form_teach_contains_form_kind` — enabled output contains `"form"` AND still `"choice"` AND `"multiselect"`.
   - `test_form_teach_gap_regex_clean` — `_CAPABILITY_GAP_RE.search(out) is None` + no banned substring (`can't`/`cannot`/`don't have`/`unable to`/`not able to`).

### 7b. vitest — `a2uiApi.test.ts` (ADD a `parseFormSpec` describe; existing describes UNCHANGED)
- valid form → `{prompt, fields:[{label, required}]}`; `required` defaults `false`, explicit `true` preserved.
- drops empty/whitespace-label fields; dedupes by label (order preserved).
- `kind !== 'form'` → null; non-array `fields` → null; zero valid fields → null; empty prompt → null; malformed JSON → null; non-object payload → null.
- (Do NOT touch the existing `parseChoiceSpec` test that uses `{kind:'form', options:[...]}` as its negative case — `parseChoiceSpec` still rejects it on `kind !== 'choice'`.)

### 7c. vitest — `A2UIFormCard.test.tsx` (NEW, mirrors `A2UIMultiSelectCard.test.tsx`)
Real zustand store (BF-287), `fetchArtifactContent` mocked, `await findByText(prompt)` before `getByTestId` (shared-testid race guard), EMOJI_RE source + DOM guard.
- renders the prompt + one labeled input per field once resolved (`a2ui-form-input-0..n`).
- a required field shows the `*` marker; an optional field does not.
- Submit is disabled until every required field is non-empty; enabled after filling them; an optional field left blank does not block Submit.
- on submit posts `label: value` lines in field order via `onChoice` (e.g. `"Name: Ada\nRole: Engineer"`), exactly once (one-shot), and locks all inputs + Submit (a 2nd Submit click is a no-op).
- loading state when the artifact is unresolved (`Loading…`).
- no emoji in source or rendered DOM.

### 7d. vitest — `ProfileChatTab.a2ui.test.tsx` (ADD a form-dispatch describe; existing describes UNCHANGED)
- source-scan: `expect(profileChatSource).toMatch(/<A2UIFormCard[\s\S]*?onChoice=\{onA2UIChoice/)` and `expect(profileChatSource).toContain("a2ui.kind === 'form'")`.
- round-trip: render `A2UIFormCard` directly with `onChoice={(opt) => sendTextMirror('yeo', opt)}`, fill `a2ui-form-input-*`, click `a2ui-form-submit`, assert `fetch` called once with `/api/agent/yeo/chat` and POST `message` === the encoded `label: value` string.

---

## 8. What this does NOT change (out of scope)
- `src/probos/cognitive/dm/a2ui_extractor.py` — UNTOUCHED (gate already form-safe; stub/write already kind-generic).
- `src/probos/cognitive/dm/reply_pipeline.py` — UNTOUCHED (kind-agnostic).
- `src/probos/config.py` — UNTOUCHED (form self-caps fields via `_MAX_FIELDS`).
- `config/system.yaml` — UNTOUCHED (and the pre-existing `M` on it must NOT be staged).
- The existing `AgentUIChoiceSpec` / `AgentUIMultiSelectSpec` classes, `A2UIChoiceCard.tsx`, `A2UIMultiSelectCard.tsx`, `parseChoiceSpec`, `parseMultiSelectSpec`, `parseA2UIStub`, `A2UI_STUB_RE` — UNTOUCHED.
- The load-bearing guard tests — `tests/test_ad811a_a2ui_choice.py`, `tests/test_ad811b_a2ui_multiselect.py`, `a2uiApi.test.ts` (existing describes), `A2UIChoiceCard.test.tsx`, `A2UIMultiSelectCard.test.tsx`, `ProfileChatTab.a2ui.test.tsx` (existing describes) — must pass UNCHANGED.
- **Do NOT build:** typed fields (defer to AD-811b-1a), range (AD-811b-2), date (AD-811b-3), the group producer (AD-811c), channel adapters (AD-811d), DecisionQueue→A2UI (AD-811e), response correlation (AD-811f), any new API endpoint.

## 9. Tracking
- `PROGRESS.md` — add an `AD-811b-1 shipped` entry (note: PRE-RESERVED #735 sub-number; current highest top-level = AD-1052; no new top-level).
- `DECISIONS.md` — append the AD-811b-1 decision (form widget; free-text v1; typed fields deferred to AD-811b-1a; extractor/config/pipeline UNTOUCHED).
- `a2ui/__init__.py` docstring — remove `form (AD-811b-1)` from the deferred list.

## 10. Acceptance criteria
- `AgentUIFormSpec` + `AgentUIFormField` defined; `"form"` registered in `_SPEC_BY_KIND`; `A2UISpec` union extended; `_MAX_FIELDS=20`.
- `a2ui_extractor.py`, `reply_pipeline.py`, `config.py`, `config/system.yaml` byte-identical (UNTOUCHED).
- Teaching text teaches `form` and is `_CAPABILITY_GAP_RE`-clean; still teaches `choice` + `multiselect`.
- `parseFormSpec` + `A2UIFormCard` + the ProfileChatTab `form` case added; choice + multiselect render paths byte-identical.
- The form card posts a `label: value`-per-line string through the existing `(opt) => sendText(opt)` call site (no new endpoint, no correlation).
- **Backend gate:** `pytest tests/test_ad811b_1_a2ui_form.py tests/test_ad811b_a2ui_multiselect.py tests/test_ad811a_a2ui_choice.py -q -n 0` — new file green; 811a + 811b green UNCHANGED. Then the blast-radius gate `pytest tests/ -q -n 4 --dist=loadfile` (0 regressions).
- **UI gate:** `cd ui; npx vitest run` (new tests green; existing a2ui + ProfileChatTab tests green UNCHANGED) and `npm run build` (clean `tsc -b` + `vite build`). `get_errors` clean.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 11. Verified Against Codebase (2026-06-24, HEAD 58dd7fb6)

```
git rev-parse --short HEAD
  58dd7fb6
git status --short
  M config/system.yaml            # pre-existing — do NOT stage
  ?? prompts/... docs/...         # untracked drafts

src/probos/a2ui/__init__.py
  _MAX_OPTIONS_HARD_CAP = 20 ; _MAX_PROMPT_LEN = 500
  def _clean_prompt(v: str) -> str        # shared
  def _clean_options(v: list[str]) -> list[str]   # shared
  class AgentUIChoiceSpec(BaseModel): kind: Literal["choice"]="choice"; prompt; options
  class AgentUIMultiSelectSpec(BaseModel): kind: Literal["multiselect"]; ...; @model_validator(mode="after")
  A2UISpec = AgentUIChoiceSpec | AgentUIMultiSelectSpec
  _SPEC_BY_KIND: dict[str, type[A2UISpec]] = {"choice":..., "multiselect":...}
  def parse_a2ui_spec(raw: str) -> A2UISpec | None    # json.loads→dict→kind→registry→model_validate, None on fail
  (no __all__; build_a2ui_stub NOT here)

src/probos/cognitive/dm/a2ui_extractor.py
  def extract_a2ui(text: str, *, max_options: int = 10) -> list[A2UISpec]:
  L67  opts = getattr(spec, "options", None)
  L68  if opts is not None and len(opts) > max_options:        # ← no-ops for forms
  L77  def build_a2ui_stub(name: str, version: int, kind: str = "choice") -> str:
       name = f"a2ui-{spec.kind}-{name_n}.json"                # kind-generic two-call write

src/probos/cognitive/dm/reply_pipeline.py
  L1233 async def step_4k_extract_a2ui(self) -> None:
  L1271 max_options = getattr(comms_cfg, "a2ui_max_options", 10)
  L1276 specs = extract_a2ui(text, max_options=max_options)     # kind-agnostic

src/probos/cognitive/cognitive_agent.py
  L2231 def _conversational_a2ui_block(self, observation: dict) -> str:
  L2256 if not getattr(comms_cfg, "a2ui_enabled", False): return ""
  L2262 min_rank_str = getattr(comms_cfg, "a2ui_min_rank", "lieutenant")
  L2283-2297 return ( ... teaches choice + multiselect ... )    # gap-clean

src/probos/cognitive/decomposer.py
  L33 _CAPABILITY_GAP_RE = re.compile(r"don't have|can't|cannot|unable to|no ... capability|...|outside ... scope", re.I)

src/probos/config.py
  L5210 a2ui_enabled: bool = Field(default=False, ...)
  L5214 a2ui_min_rank: str = Field(default="lieutenant", ...)
  L5218 a2ui_max_options: int = Field(default=10, ge=2, le=20, ...)

ui/src/components/a2ui/a2uiApi.ts
  A2UI_STUB_RE = /^\[A2UI: ([^\]]+?) v(\d+) - (\w+)\]$/          # kind captured → "form" parses unchanged
  parseA2UIStub -> {name, version, kind}
  parseChoiceSpec / parseMultiSelectSpec                        # form parser mirrors parseMultiSelectSpec

ui/src/components/a2ui/A2UIMultiSelectCard.tsx
  props {threadId, name, version, onChoice:(response:string)=>void}
  L104 onChoice(spec.options.filter(o=>selected.has(o)).join(', '))   # free-form string post

ui/src/components/profile/ProfileChatTab.tsx
  L113-115 function renderMessageBodyWithArtifacts(text, threadId, onA2UIChoice?:(option:string)=>void)
  L126-127 if (a2ui && threadId && (a2ui.kind === 'choice' || a2ui.kind === 'multiselect')) {
  L130-144 {a2ui.kind === 'multiselect' ? <A2UIMultiSelectCard .../> : <A2UIChoiceCard .../>}  onChoice={onA2UIChoice ?? (()=>{})}
  L1184 body={renderMessageBodyWithArtifacts(msg.text, threadId, (opt) => sendText(opt))}   # UNTOUCHED call site

PROGRESS.md
  "current highest landed top-level = AD-1052"                  # AD-811b-1 is a #735 sub-number
tests/test_ad811a_a2ui_choice.py  (exists — guard)
tests/test_ad811b_a2ui_multiselect.py  (exists — guard; uses kind:"form" as its unknown-kind example)
ui/.../__tests__/{a2uiApi.test.ts, A2UIChoiceCard.test.tsx, A2UIMultiSelectCard.test.tsx, ProfileChatTab.a2ui.test.tsx}  (exist — guards)
ui/  has NO .eslintrc* / eslint.config.*  (no lint gate; tsc -b + vite build + vitest)
```
