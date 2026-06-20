# AD-1026 — Quiet, phased boot output with a `--verbose` flag (CLI / __main__)

**Issue #970 · no epic · independent.**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: AD-1025 (#969, just shipped local). This AD = AD-1026 (next free).**

Make the default `probos serve` boot output short and issue-focused: suppress INFO log noise on the console (the rotating file log keeps full INFO+), collapse the per-pool boot detail into a one-line summary, and surface only warnings/errors by default. A new `--verbose`/`-v` flag restores today's full detail.

---

## Why / context

The boot log has grown long. Two streams produce it:
1. **Python logging** — `_setup_logging` ([__main__.py](src/probos/__main__.py#L73)) sets the root logger to `config.system.log_level` (INFO) and attaches a console `StreamHandler` that inherits that level, so every subsystem's INFO line prints to the console at boot. (~11 noisy loggers are individually pinned to WARNING at [__main__.py](src/probos/__main__.py#L115-L125) — a whack-a-mole that hasn't kept up.) A rotating **file** handler always captures INFO+ to `<platform_data_dir>/logs/probos.log` ([__main__.py](src/probos/__main__.py#L95-L111)).
2. **Rich boot sequence** — `_boot_runtime` ([__main__.py](src/probos/__main__.py#L404)) prints the banner, data dir, ollama/LLM/NATS status, then a **per-pool loop** ([__main__.py](src/probos/__main__.py#L490-L505)) emitting one `✓ Pool …` line per pool (12+ lines), then totals + `ProbOS ready.`

The Captain wants: collapse the phases, show detail only when there's an issue, and a flag for the full detailed boot. The clean mechanism is **console log level + phase gating**, not more per-logger pinning.

## Pinned design decisions

### DD-1 — Default console = WARNING; `--verbose` = the configured level (load-bearing)
Add a `verbose: bool = False` parameter to `_setup_logging` ([__main__.py](src/probos/__main__.py#L73)). Keep the **file** handler at INFO+ (unchanged — full diagnostics always on disk). Set the **console** `StreamHandler` level via a new pure helper:
```python
def _console_log_level(log_level: str, verbose: bool) -> int:
    if verbose:
        return getattr(logging, log_level.upper(), logging.INFO)
    return logging.WARNING
```
Root logger stays at the configured level (so the file handler still receives INFO+). Net: default boot shows only WARNING/ERROR on the console (= "detail only if there's an issue"); `--verbose` restores the configured INFO/DEBUG console stream (today's behavior). **This is an intentional default-behavior change** (console INFO→WARNING); the file log preserves everything. The existing per-logger `setLevel(WARNING)` block may stay as-is (harmless) — do not expand or remove it.

### DD-2 — Collapse the per-pool boot lines behind `verbose`
Extract a pure helper `_render_boot_summary(status: dict, verbose: bool) -> list[str]` that returns the Rich markup lines for the pool section. **Default (`verbose=False`)**: a single summary line — `✓ {total_agents} agents across {N} pools` plus the existing red-team line. **`verbose=True`**: the current per-pool `✓ Pool {name}: {n} {type} agents` lines (byte-identical to today). `_boot_runtime` calls the helper and prints its lines instead of the inline loop. Keep the banner, `Data dir:`, ollama/LLM/NATS status, and `ProbOS ready.` lines in BOTH modes (few + connectivity-relevant). A pool that failed/degraded must still surface — if any pool's `info()` shows it is not at expected size, include that pool's line even in the collapsed view (issue-on-detail).

### DD-3 — `--verbose`/`-v` flag, threaded through the serve + default boot paths
Add `serve_parser.add_argument("--verbose", "-v", action="store_true", help="Detailed boot log (INFO+ on console, per-pool detail)")` at the serve subparser ([__main__.py](src/probos/__main__.py#L2300-L2316)). Thread `verbose` from `args.verbose` → `_serve(...)` (the serve dispatch call at [__main__.py](src/probos/__main__.py#L2378-L2389)) → `_boot_runtime(..., verbose=...)` → `_setup_logging(..., verbose=...)` and the `_render_boot_summary` call. Also thread it into `_boot_and_run` ([__main__.py](src/probos/__main__.py#L516)) (the `--interactive` path) and default `verbose=False` for the bare-`probos` default-shell path ([__main__.py](src/probos/__main__.py#L2393)). **VERIFY every function signature in the chain at build** (`_serve`, `_boot_runtime`, `_boot_and_run`) and update call sites — do not assume parameter names.

### DD-4 — End-of-boot health pointer (small capstone)
Attach a module-level counting `logging.Handler` in `_setup_logging` that tallies WARNING+ records, exposed via `_boot_warning_count() -> int` (reset at the top of `_setup_logging`). After `ProbOS ready.` in `_boot_runtime`, if the count > 0 and NOT verbose, print one dim line: `⚠ {n} notice(s) during boot — full log: {logfile}; rerun with --verbose for detail.` (Resolve `{logfile}` to `<platform_data_dir>/logs/probos.log`.) This serves "show detail if there's an issue" by always pointing at the detail. Keep it ≤1 line; no EventType, no new config. If verbose, omit (the detail already printed).

## Build
1. **`_console_log_level` + `verbose` param** — add the pure helper and the `verbose` param to `_setup_logging`; set the console handler via it; file handler unchanged. ([__main__.py](src/probos/__main__.py#L73))
2. **`_render_boot_summary`** — pure helper per DD-2; replace the inline per-pool loop in `_boot_runtime` with a call to it. ([__main__.py](src/probos/__main__.py#L490-L505))
3. **`--verbose` flag + threading** — DD-3 across `serve_parser`, `_serve`, `_boot_runtime`, `_boot_and_run`.
4. **Boot health pointer** — DD-4 counting handler + `_boot_warning_count()` + the one-line pointer.
5. **Tests** — new `tests/test_ad1026_boot_verbosity.py`.

## Acceptance
- `tests/test_ad1026_boot_verbosity.py` (NEW), with logger-state isolation (snapshot/restore `logging.getLogger().handlers` + level in a fixture — no cross-test pollution):
  - `_console_log_level("INFO", verbose=False) == logging.WARNING`; `(..., verbose=True) == logging.INFO`; `("DEBUG", verbose=True) == logging.DEBUG`; unknown level → INFO fallback.
  - After `_setup_logging("INFO", verbose=False)`: the console `StreamHandler` is at WARNING and a file handler (if creatable) is at INFO. After `verbose=True`: console at INFO. (Find handlers by type; tolerate the file handler being absent if the dir can't be made.)
  - `_render_boot_summary(status, verbose=False)` returns the single-total + red-team lines and NO per-pool lines; `verbose=True` returns one line per pool. A degraded pool (current_size < expected) appears even when `verbose=False`.
  - `_boot_warning_count()` reflects WARNING+ records emitted after setup and is reset by a fresh `_setup_logging` call.
  - argparse: `serve --verbose` and `serve -v` set `args.verbose=True`; absence ⇒ `False`.
- Default-quiet is the new default; `--verbose` reproduces today's console+pool detail. The rotating file log still receives INFO+ in both modes (assert the file handler level is INFO regardless of `verbose`).
- Real-fixture tests per BF-287 (no MagicMock for the logging/handler assertions — inspect real handler objects). Full type annotations on the new helpers; logging-context standard respected.
- Gate `-k "ad1026 or main or serve or logging or boot"` green; smoke: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n auto -k "ad1026 or distribution or __main__ or boot"`.
- **Verify compliance with `.github/copilot-instructions.md`** (type annotations, logging context, no scope creep, async hygiene).

## Do NOT build here
❌ A new `system.verbose_boot` config field — the CLI flag is the mechanism this AD ships (config persistence is a deferrable follow-up). ❌ Restructuring `_ensure_ollama` / `_create_llm_client` / `_check_nats` output (leave their lines as-is). ❌ Removing or expanding the existing per-logger `setLevel(WARNING)` block. ❌ A `RichHandler` swap or any logging-framework change beyond the console level + counter. ❌ Touching `runtime.start()` or any boot LOGIC — this AD is presentation only. ❌ Changing the banner version string. ❌ The AD-1025 path-anchoring work (separate, already shipped). ❌ A new top-level AD number — this is AD-1026.

## Files (verify each at build)
- [src/probos/__main__.py](src/probos/__main__.py) — `_console_log_level` (NEW helper), `_setup_logging(verbose=...)`, counting handler + `_boot_warning_count`, `_render_boot_summary` (NEW helper) + use in `_boot_runtime`, `--verbose` flag + threading through `_serve`/`_boot_runtime`/`_boot_and_run`.
- `tests/test_ad1026_boot_verbosity.py` (NEW) — helper + handler-level + argparse + summary coverage.

## Done-when
Default `probos serve` console boot is short (WARNING+ only, collapsed pool summary, health pointer when issues exist); `probos serve --verbose` shows the full INFO console stream + per-pool detail; the file log is INFO+ in both modes; gate green; full type annotations; **verify compliance with `.github/copilot-instructions.md`**; update `PROGRESS.md` + `DECISIONS.md` (AD-1026 entry) in the same commit.
