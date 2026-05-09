# Review: claude-bootstrap — `probos init` security defaults
**Verdict:** ✅ Approved
**Secure-by-default discipline correct; runtime enforcement properly deferred to AD-712.**

## Required (must fix before building)
_None._

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. D4's `SecurityConfig` uses `Literal["strict", "relaxed"]` but does not import `Literal`. Add `from typing import Literal` to the spec, or use `str` + `field_validator` per the existing `config.py` pattern (verify-first which approach the file already uses).
3. D3's `_cmd_doctor` patch reads `cfg = ...` from outer scope but doesn't show how `cfg` is loaded. Either point to the existing line in `_cmd_doctor` that loads the config, or wrap in a guard `if 'cfg' in locals() and cfg is not None`.
4. Profile-default = `"strict"` is correct (secure-by-default). Note that this is **not** a violation of convention #14 (transitional `enabled` flags) — security defaults must be on. Call this out in the prompt body so reviewers don't flag it.

## Nits
- The `"shell:rm -rf /"` deny in the relaxed profile is narrower than `"shell:rm -rf *"` in strict. Intentional (relaxed = developer convenience) but worth a one-line comment.
- D5 tests #4 (`test_init_invalid_profile_falls_back_to_strict`) — argparse with `choices=("strict", "relaxed")` will reject `"loose"` at parse time with `SystemExit`. The fallback in `_cmd_init` only fires for programmatically-constructed bad args. Test the fallback path explicitly, not via argparse.
- "Do not copy any text from claude-bootstrap verbatim" hard-constraint is good license hygiene; consider also "do not copy comments verbatim".

## Verified
- `src/probos/__main__.py:598` `_cmd_init` (prompt says `:599`, drift = 1).
- `src/probos/__main__.py:691` `_cmd_doctor` — confirmed.
- The init wizard does live in `__main__.py`, not `experience/init/` — prompt explicitly corrects the dispatch's incorrect hint. Good verify-first hygiene.
- `--security-profile` flag is a clean addition; `dest="security_profile"` follows argparse defaults.
- Runtime enforcement explicitly deferred to **AD-712** — boundary clean.
- Sample deny entries (`shell:rm -rf *`, `shell:git push --force *`, `fs:write:.env*`) cover the claude-bootstrap headline patterns.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Pass-1 had 0 Required; pass-2 confirms cross-cutting items landed.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ Build Ordering Note added (config.py serialization slot). Working-tree integrity reminder in Acceptance.
- ✅ No phantom-API regressions introduced.
- ✅ All previously-verified symbols still match HEAD.

### Pass-2 outcome
Held at ✅. Cleared for Builder dispatch.
