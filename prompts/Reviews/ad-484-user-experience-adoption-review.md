# Review: AD-484 — User Experience & Adoption Readiness (v1)

**Verdict:** ⚠️ Conditional — one provider-detection logic bug + Solution-Overview drift + license-classifier conflict. All mechanical fixes.

**Date:** 2026-05-02

**Headline:** Section 2's `_cmd_init` provider-detection branch has a `__class__.__name__` substring check that is almost certainly not what the author intended; trivial fix.

---

## Required (must fix before building)

1. **Section 2 — broken `"ollama" in detected.values().__class__.__name__` check.** Lines ~199:

   ```python
   if "ollama" in detected.values().__class__.__name__ or ":11434" in llm_url:
       default_model = "llama3.1:8b"
   ```

   `detected.values().__class__.__name__` evaluates to the string `"dict_values"` (it's the class-name of a dict_values view). `"ollama" in "dict_values"` is always `False`. The intended check is `"ollama" in detected` (key membership) OR equivalent. The branch only fires today when `:11434` is in the URL — accidentally still functional for the Ollama URL path, but the intent is broken. **Fix:**

   ```python
   if "ollama" in detected or ":11434" in llm_url:
       default_model = "llama3.1:8b"
   ```

2. **License-classifier conflict between SPDX and PEP 639.** Section 1 adds:

   ```toml
   "License :: OSI Approved :: Apache Software License",
   ```

   to `[project.classifiers]`. But `pyproject.toml:10` already declares:

   ```toml
   license = "Apache-2.0"
   ```

   Modern setuptools (>=77) deprecates the classifier when the SPDX `license` string is set; some toolchains will warn or refuse to build. **Fix:** drop the `License :: OSI Approved :: Apache Software License` classifier line. Keep the SPDX `license = "Apache-2.0"` (already present).

---

## Recommended

1. **Solution Overview drift (convention #12).** Lines 21 + 41-46:

   - "v1 ships **3** real-work primitives; **2** deferred to AD-484b" (line 21)
   - Solution Overview list has **4** v1 items: PyPI, init wizard, doctor, quickstart docs (lines 25-30)
   - Deferred list has **4** items: Homebrew, demo mode, HXI Glass, Playwright (lines 41-46)

   The numerical claim ("3 ships; 2 deferred") doesn't match the body. **Fix:** rewrite the Problem-section closing line to "v1 ships 4 real-work primitives; 4 deferred to AD-484b/c" (or pick whichever framing matches the body). Mechanical.

2. **`probos doctor` exit-code branch in `main()`.** Section 3's REPLACE block:

   ```python
   if args.command == "doctor":
       import sys
       sys.exit(_cmd_doctor(args))
       return
   ```

   The `return` after `sys.exit` is unreachable (sys.exit raises SystemExit). Builder is unlikely to be confused but the dead `return` is noise. **Fix:** drop the `return`.

3. **`_detect_llm_providers` Anthropic detection misses non-default API URL.** The function adds Anthropic when `ANTHROPIC_API_KEY` is in env, with hard-coded URL `https://api.anthropic.com`. If users set a custom Anthropic-compatible endpoint URL (env `ANTHROPIC_BASE_URL`, common pattern), the detector misses it. Recommend: also check `ANTHROPIC_BASE_URL` and prefer it.

4. **Section 2's `default_url = next(iter(detected.values()), ...)` ordering depends on dict iteration order.** Python 3.7+ guarantees insertion order, and `_detect_llm_providers` inserts in deterministic order (`ollama`, `copilot-proxy`, `anthropic`). So the default is "first reachable in priority order." That's defensible; consider adding a comment so Builder doesn't rewrite.

5. **`_cmd_doctor` reuses `asyncio.run` three times in one function.** Each call creates a fresh loop. For diagnostic CLI it's fine, but if any of the helpers (`_check_nats`, `client.check_connectivity`) holds connection state, the multiple-loop pattern can leak. Recommend wrapping the whole doctor body in a single `asyncio.run(_doctor_async(...))`.

6. **Test #4 uses `Path("docs/quickstart.md").exists()`.** The CWD during pytest is the repo root by default but not guaranteed. Recommend using `Path(__file__).resolve().parent.parent / "docs" / "quickstart.md"` for robustness.

---

## Nits

- **`MANIFEST.in` `prune .github` and `prune tests`.** Trivial. PyPI users don't need either; correct.
- **`docs/quickstart.md` includes a code block with `bash`.** Markdown lint may want fenced-code language tags. Fine as-is.
- **`docs/getting-started.md` "agent-native OS runtime" framing.** Good ground-truth alignment with `pyproject.toml:8` description.
- **No new EventTypes.** Section 0 correctly states this. ✅
- **The `pyproject.toml` `[project.urls]` block places after `classifiers` but before `dependencies`.** Conventional ordering. Builder won't get confused; the position is fine.
- **Test #6 (`test_doctor_subparser_registered`)** parses `["doctor"]` against the parser — checks the dispatch wiring without invoking `_cmd_doctor`. Good test.

---

## Verified (looks good)

- `_cmd_init` exists at `__main__.py:542`. ✅
- `argparse` subparsers at `__main__.py:1077-1127`. ✅
- `Console`, `Panel`, `Table`, `Text` already imported (`__main__.py:26-29`). ✅
- `rich>=13.0` already a hard dep (`pyproject.toml:25`). ✅ (per dispatch verification point #6)
- `_default_data_dir`, `_probos_home`, `OpenAICompatibleClient`, `_check_nats` all available for reuse in `_cmd_doctor`. ✅
- `docs/quickstart.md` and `docs/getting-started.md` do NOT exist today. ✅ (verify-first)
- `[project.urls]` syntax is valid PEP 621 metadata.
- v1's "3 real-work primitives" all do real work today (no theater).
- No new pyproject deps; no new EventTypes; no runtime semantics modified. ✅

---

## Conventions audit

| # | Rule | Status |
|---|---|---|
| 1 | Public-attribute wiring | N/A (no runtime attrs) |
| 2 | stdlib-only persistence | ✅ |
| 3 | Coordinator-then-dispatch | ✅ Homebrew/demo/HXI/Playwright deferred |
| 4 | Superset-filter | ✅ existing _cmd_init behaviors preserved |
| 5 | init_<phase> | N/A (CLI-time, not runtime startup) |
| 6 | Verify-first | ✅ (footer is thorough) |
| 7 | No-theater | ✅ all 4 v1 deliverables ship real work |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store vs workforce | N/A |
| 11 | __new__-bypass defensive-getattr | N/A |
| 12 | Solution Overview drift | ⚠️ Recommended #1 |
| 13 | Pool template name collision | N/A |
| 14 | Aggressive pre-deferral | ✅ |
| 15 | Tolerance: relaxed | n/a (review tier) |

---

## Bottom Line

AD-484 is the lowest-risk Wave 8 prompt and ships clean docs + CLI work. Two Required findings are mechanical (one-line bug, one-line license-conflict drop). Six Recommended items are tightening; none block Builder dispatch. **Ready for revision pass; expected to converge in one round.**
