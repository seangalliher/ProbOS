# AD-1025 — Anchor operator-asset + runtime-artifact paths to the ProbOS root, not CWD (audio/tts + startup)

**Issue #969 · no epic · depends on AD-738 (Piper TTS, shipped) and AD-690 (rejection cache, shipped).**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1024 (#968, verified highest reserved). This AD = AD-1025 (next free).**

Make ProbOS resolve operator-supplied binary/voice assets and runtime DB artifacts against the ProbOS install root (and the absolute runtime data dir), **never the process current working directory (CWD)**, so `probos serve` produces identical behavior regardless of which directory it is launched from.

---

## Why / context

Live incident (2026-06-17): the Captain launched `probos serve --interactive` from a sibling workspace folder (outside the repo root) for the first time. The boot log showed:

```
WARNING probos.audio.tts.piper_backend AD-738: piper binary not found at tools/piper/piper; degrading to browser
WARNING ... AD-690: rejection cache failed to start at data\rejection_cache.sqlite: unable to open database file
```

Both are **false negatives caused by CWD-relative path resolution**. The Piper binary and voices are correctly installed at `D:\ProbOS\tools\piper\` (`piper.exe` + `voices\en_US-amy-medium.onnx[.json]` all present), and `D:\ProbOS\data\` exists — but neither resolves when CWD is the sibling folder rather than the repo root. Net effect: agents silently fell back to browser/Edge TTS, and Step-7i relationship inference was skipped.

This **already violates a decided convention**:
- `TTSConfig.binary_path`'s own docstring ([config.py](src/probos/config.py#L2657-L2660)) says *"Path (relative to repo root or absolute)"* — but the implementation resolves against CWD, contradicting the documented contract.
- **AD-739** established *"relative paths resolve against `runtime.data_dir`"* ([config.py](src/probos/config.py#L538-L541)); `runtime.data_dir` is **absolute** by default (`_DEFAULT_DATA_DIR = _platform_data_dir()`, [runtime.py](src/probos/runtime.py#L216)).
- **BF-628** established *"resolve … against the runtime data dir"* for packs (PROGRESS.md, AD-1003c entry).
- The correct anchor pattern for bundled `tools/` assets already exists: [__main__.py](src/probos/__main__.py#L334-L336) computes `project_root = Path(__file__).resolve().parent.parent.parent` and looks under `project_root / "tools" / exe` for the NATS/ollama binaries.

The Piper backend ([piper_backend.py](src/probos/audio/tts/piper_backend.py#L32-L52)) and the rejection-cache wirer ([finalize.py](src/probos/startup/finalize.py#L1053-L1055)) simply never adopted the anchor. This AD brings both into line.

## Pinned design decisions

### DD-1 — Anchor relative TTS asset paths to the ProbOS install root, not CWD (load-bearing)
`_resolve_binary_path` ([piper_backend.py](src/probos/audio/tts/piper_backend.py#L32)) currently does `Path(configured).resolve()` (CWD-relative). `_resolve_voice_model` ([piper_backend.py](src/probos/audio/tts/piper_backend.py#L45)) hardcodes `Path("tools/piper/voices").resolve()` (CWD-relative). Both must resolve **relative** configured paths against the install root, mirroring [__main__.py](src/probos/__main__.py#L334).

Add a module-level helper to `piper_backend.py`:
```python
def _probos_root() -> Path:
    # src/probos/audio/tts/piper_backend.py -> parents[4] = repo/install root.
    # Mirrors __main__.py:334 project_root (used for bundled tools/).
    return Path(__file__).resolve().parents[4]
```
**VERIFY the `parents[4]` depth by counting path segments at build** (tts→audio→probos→src→root). The AD-458 review caught exactly this kind of depth assumption — count, don't assume. Resolution rule for both helpers: **absolute configured path → used as-is; relative → `_probos_root() / <relative>`.** Windows `.exe` auto-append stays. The current CWD is never consulted. This is strictly safer: when CWD already equals the repo root (the prior happy path) `_probos_root()` resolves to the same place, so there is **zero regression** — it only additionally fixes launch-from-elsewhere.

### DD-2 — Make the Piper voices directory configurable (it is hardcoded today)
`_resolve_voice_model` hardcodes `tools/piper/voices`. Add `voices_dir: str = "tools/piper/voices"` to `TTSConfig` ([config.py](src/probos/config.py#L2632)), thread it through `select_backend` ([tts/__init__.py](src/probos/audio/tts/__init__.py#L24)) → `PiperBackend.__init__` ([piper_backend.py](src/probos/audio/tts/piper_backend.py#L70)) → both `_resolve_voice_model` call sites (the configured voice AND the BF-291 `voice_override` path at [piper_backend.py](src/probos/audio/tts/piper_backend.py#L124-L140)). Resolve it via the DD-1 rule. Default value preserves the current location byte-for-byte.

### DD-3 — rejection-cache uses the absolute `runtime.data_dir`, not the relative `config.data_dir`
[finalize.py](src/probos/startup/finalize.py#L1053) reads `data_dir = getattr(config, "data_dir", "data")` (relative `"data"`) then `Path(data_dir) / "rejection_cache.sqlite"`. Replace the source with the absolute runtime dir: `runtime.data_dir` (property, [runtime.py](src/probos/runtime.py#L1463)). Keep the existing honest-degrade try/except. **VERIFY `runtime.data_dir` is the public absolute property at build** (api.py already reads it via `getattr(runtime, "data_dir", None)`). This is the BF-628 class.

### DD-4 — Make the degrade WARNING actionable (backend-only, no API/UI change)
The miss was hard to spot because the WARNING logs the *configured* string (`tools/piper/piper`), not the *resolved* path it actually looked at. Update the two degrade WARNINGs in `synthesize` ([piper_backend.py](src/probos/audio/tts/piper_backend.py#L114-L146)) to include the resolved absolute candidate path(s) tried (what, why, what-next per the logging standard). No new EventType, **no change to `GET /api/avatars/tts/status`, no `voice.ts` change** — a richer status surface is deferred (see Do-NOT-build).

### DD-5 — Bounded audit, report-only
Grep `src/` for other live `Path("tools/…")` / `Path("data/…")` `.resolve()` operator/runtime paths of the same class. **List any findings in the PR/commit body as follow-up candidates. Do NOT fix anything beyond Piper + the rejection cache in this AD** — an unbounded path-resolution sweep is explicitly out of scope.

## Build
1. **`_probos_root()` + anchored resolution** — add the helper and rewrite `_resolve_binary_path` / `_resolve_voice_model` in [piper_backend.py](src/probos/audio/tts/piper_backend.py) per DD-1. `_resolve_voice_model` takes the resolved voices base (from `voices_dir`) instead of the hardcoded literal.
2. **`voices_dir` config + threading** — add the field to `TTSConfig` ([config.py](src/probos/config.py#L2632)) per DD-2; pass `voices_dir=config.voices_dir` in `select_backend` ([tts/__init__.py](src/probos/audio/tts/__init__.py#L24)); add the `voices_dir` param to `PiperBackend.__init__` and use it at both `_resolve_voice_model` call sites.
3. **rejection-cache anchor** — in `_wire_relationship_inference` ([finalize.py](src/probos/startup/finalize.py#L1053)) use `runtime.data_dir` per DD-3.
4. **Actionable degrade logs** — DD-4 WARNING text in `synthesize`.
5. **Audit note** — DD-5 grep; record findings in the commit body.
6. **Tests** — new `tests/test_ad1025_path_anchoring.py`; update any now-obsolete CWD-relative assertions in `tests/test_ad738_piper_tts.py` (pre-authorized — see Acceptance).

## Acceptance
- `tests/test_ad1025_path_anchoring.py` (NEW) covers, with **real `tmp_path` fixtures** (BF-287 — no MagicMock):
  - a **relative** `binary_path` resolves against `_probos_root()`, NOT CWD: monkeypatch `_probos_root` to a `tmp_path` containing `tools/piper/piper(.exe)`, `os.chdir` to an unrelated dir, assert the binary is still found (the headline regression — reproduces the incident).
  - an **absolute** `binary_path` is used as-is (byte-identical to today).
  - a **relative** `voices_dir` resolves against `_probos_root()`; the BF-291 `voice_override` path honors the same anchor.
  - Windows `.exe` auto-append still works on the anchored path (skip/guard on non-win32).
  - the degrade WARNING includes the resolved candidate path (assert via `caplog`).
- `_wire_relationship_inference` writes `rejection_cache.sqlite` under the **absolute** `runtime.data_dir` (assert the resolved `db_path` is absolute and under `runtime.data_dir`, independent of CWD). Real `SQLiteRejectionCache` + `tmp_path` data dir; honest-degrade path unchanged.
- `tests/test_ad738_piper_tts.py`: the `_resolve_binary_path` / `_resolve_voice_model` cases are migrated to the anchored contract (these are obsolete-contract tests encoding the OLD CWD behavior — **pre-authorized to update**, per the user-memory "behavior-changing AC coexisting with equivalence tests" rule). Report the before/after count; the *count must not drop* (migrate in place, add the new cases in the new file).
- Default behavior byte-identical for existing installs: with CWD == repo root and the default `tools/piper/...` layout, resolution lands on the same files as before. `voices_dir` default = `"tools/piper/voices"` ⇒ no operator action required.
- Gate `-k "ad738 or ad1025 or ad690 or tts or piper or rejection"` green (prior ad738/ad690 counts preserved + new). Full gate per repo convention: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n auto`.
- Real-fixture tests per BF-287; full type annotations on the new helper + changed signatures; logging context per standard (what/why/what-next).
- **Verify compliance with `.github/copilot-instructions.md`** (async hygiene, layer discipline, type annotations, logging context, no scope creep).

## Do NOT build here
❌ A `degraded`/`degraded_reason` field on `GET /api/avatars/tts/status` or any `ui/src/audio/voice.ts` change — **deferred to AD-1025a** (forward marker). ❌ The boot-log verbosity / phase-collapse / `--verbose` work — **that is AD-1026**, dispatched separately. ❌ A startup-time Piper self-probe (belongs with AD-1026's startup self-check). ❌ Fixing any other CWD-relative path DD-5 surfaces (report only). ❌ De-duplicating `_probos_home()` / `_platform_data_dir()` across modules (known DRY debt — not this AD). ❌ Moving the operator's existing `tools/piper/` location or changing the default voice `en_US-amy-medium`. ❌ Changing `BaseAgent` / `IntentMessage` / `select_backend`'s public name. ❌ A new top-level AD number — this is AD-1025.

## Files (verify each at build)
- [src/probos/audio/tts/piper_backend.py](src/probos/audio/tts/piper_backend.py) — add `_probos_root()`; anchor `_resolve_binary_path` + `_resolve_voice_model`; `voices_dir` ctor param + threading to both voice call sites; DD-4 WARNING text.
- [src/probos/audio/tts/__init__.py](src/probos/audio/tts/__init__.py) — `select_backend` passes `voices_dir=config.voices_dir`.
- [src/probos/config.py](src/probos/config.py#L2632) — add `voices_dir` field to `TTSConfig`.
- [src/probos/startup/finalize.py](src/probos/startup/finalize.py#L1053) — rejection-cache uses `runtime.data_dir`.
- `tests/test_ad1025_path_anchoring.py` (NEW) — anchored-resolution + rejection-cache-dir + degrade-log coverage.
- [tests/test_ad738_piper_tts.py](tests/test_ad738_piper_tts.py) — migrate the two resolver cases to the anchored contract (count preserved).

## Done-when
All acceptance green; gate `-k "ad738 or ad1025 or ad690 or tts or piper or rejection"` green (prior-AD counts unchanged + new); launching `probos serve` from any directory finds the operator's `tools/piper/` assets and writes `rejection_cache.sqlite` under the absolute data dir; full type annotations on new/changed public surfaces; **verify compliance with `.github/copilot-instructions.md`**; update `PROGRESS.md` + `DECISIONS.md` (AD-1025 entry) in the same commit.
