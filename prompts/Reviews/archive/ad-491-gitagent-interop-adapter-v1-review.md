# Review: AD-491 v1 — gitagent interop adapter (publish/install boundary only)
**Verdict:** ✅ Approved
**Clean boundary adapter; no runtime wiring; sovereign DID stays authoritative. One Recommended sharpening on the CapabilityDescriptor field name.**

## Required (must fix before building)
_None._

## Recommended
1. **D2a maps `capabilities` to `[c.can for c in agent.default_capabilities]`** — but `CapabilityDescriptor`'s actual field name needs verifying. Common precedents in this codebase use `.name` (more idiomatic than `.can`). Architect grep `class CapabilityDescriptor` once at draft time and either confirm `.can` or correct to the actual field. If wrong, every export YAML will be empty under `capabilities:` and test #4 will catch it — but a 30-second grep prevents the iteration.

## Nits
1. The "version" field is hardcoded `"1"` for v1 — fine. Consider a Non-Goal: "Do NOT introduce a per-agent version field on BaseAgent in this AD; per-agent versioning is a separate AD."
2. `import_gitagent_yaml` uses `yaml.safe_load` (good) but the prompt should reiterate: never use `yaml.load` (RCE surface) anywhere in the import path. Add as a Non-Goal.
3. The "security boundary" test (#6) — clearing `probos.sovereign_id` when `runtime != "probos"` — is the most important test in the file. Worth promoting it to test #1 for visibility.
4. Test #7 uses `pytest.raises(ValueError, match="name")` — the regex must match the literal exception message; specify the exact message in the implementation (e.g. `"missing required gitagent key 'name'"`) so the test is not brittle to wording changes.
5. PyYAML dependency is already pulled in (verified in prompt). One sentence in `pyproject.toml` confirming this should be a Builder verify-step.

## Verified
- ✅ `BaseAgent` at `substrate/agent.py:18` defines `callsign`, `default_capabilities`, `intent_descriptors`, `sovereign_id`, `did` as public attributes — all five export-source attrs grep-confirmed.
- ✅ AD-441 sovereign DID infrastructure shipped (era-4 decisions log).
- ✅ No existing `interop/` package — collision-free greenfield.
- ✅ `yaml.safe_load` is the right call (PyYAML's safe loader rejects `!!python` constructors).
- ✅ The "foreign runtime clears sovereign_id" boundary is the correct security stance; `import_gitagent_yaml` doesn't write to `AgentIdentityRegistry` (correct — registry is the issuer).
- ✅ Pure-function design, no runtime wiring — minimal blast radius.
- ✅ 8 tests cover boundary surface (export shape, sovereign_id round-trip, missing-attr graceful, capability/intent serialization, round-trip-by-reference, foreign-runtime security, missing-key error, invalid-YAML error).

## Risk
LOW. Boundary adapter; no runtime mutation; no agent instantiation; pure functions; PyYAML's `safe_load`.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved — `CapabilityDescriptor.can` field name confirmed at HEAD.

### Required / Recommended / Nits
None.

### Verified
- **Recommended #1 landed**: `CapabilityDescriptor` field is `can: str` (verified at HEAD: `src/probos/types.py:26-32`). Export shape `[c.can for c in agent.default_capabilities]` correct.
- D1 new `interop/__init__.py` is collision-free greenfield.
- D2a field mapping reasonable; `version="1"` literal acknowledged as deferred per-agent versioning.
- D2b security boundary correct: foreign-runtime YAML clears `probos.sovereign_id` and `probos.did` regardless of file contents — sovereign identity must be re-issued through AD-441 registry.
- 8 tests cover happy export, sovereign_id present/missing, list serialization, round-trip, foreign-runtime clearance, missing-required raises, malformed-yaml raises.
- Phantom-API sweep: `BaseAgent` (`substrate/agent.py:18`), `CapabilityDescriptor.can` (`types.py:26`), AD-441 substrate confirmed.
- `git diff` surface: 2 new files + 1 new test. No edits to runtime, config, BaseAgent, registry.
