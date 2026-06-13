# Build Prompt — ripgrep-Absorption Wave (AD-989 + AD-990 + AD-991)

**Architect:** verify-first complete (2026-06-13). All file:line refs read against the
live codebase. **Builder:** implement exactly; do not expand scope.

**Thesis (commercial research note carries the framing):** code is an *exact-token*
domain — lexical/regex content search ("grep the project") beats embedding/RAG for it
(exact, always-fresh, self-explaining: you see the matched line). ProbOS already leans
lexical (AD-979c hybrid FTS5, BF-625 BM25 ranking, AD-988 retrieval transparency); this
wave absorbs ripgrep's *pattern* (NOT its Rust code) to fill a real hole: **there is no
content-grep capability in the mesh.**

**License / disposition (surfaced per standing rule):** ripgrep is dual MIT/Unlicense —
free to pattern-absorb, but it is Rust → no Rust dep, no rewrite. Absorption = the
*pattern* (gitignore-aware traversal, linear-time-safe matching) in pure Python, plus an
*optional* shell-out to the operator's `rg` binary under gitignored `/tools/` (the exact
BYO-binary disposition already used for Piper TTS / Rhubarb). `pathspec`/`re2` are NOT
installed → **zero new hard deps**; pure-Python implementations; re2 noted as a forward
marker for true linear-time guarantees.

Build order: **AD-991 (leaf) → AD-990 (leaf) → AD-989 (depends on both).**

---

## AD-991 — ReDoS-safe supplied-pattern matching (security leaf)

Python `re` is a backtracking engine; an agent- or Captain-supplied pattern is a latent
ReDoS (catastrophic-backtracking DoS) vector. ripgrep is immune (finite automata, linear
time). Absorb the *guarantee intent* via a boundary guard.

### New `src/probos/substrate/safe_regex.py`
- `class UnsafePatternError(ValueError)`.
- `safe_compile(pattern: str, *, flags: int = 0, max_len: int = 1000) -> re.Pattern`:
  - reject `len(pattern) > max_len` → `UnsafePatternError`.
  - reject known catastrophic signatures via a static scan — nested quantifiers on a
    group: `(…+)+`, `(…+)*`, `(…*)+`, `(…*)*`, `(…+)?…+`-style. Implement with a small
    set of compiled meta-regexes against the *pattern text* (e.g.
    `r"\([^)]*[+*]\)[+*]"`). Conservative: a few well-known signatures, documented as a
    heuristic boundary guard, NOT a proof.
  - otherwise return `re.compile(pattern, flags)`; a `re.error` re-raises as
    `UnsafePatternError` (invalid pattern is also a boundary rejection).
- Module docstring: states this is defense-in-depth at the boundary; true linear-time
  safety is `re2` (forward marker, optional operator dep), not shipped.

### Tests `tests/test_ad991_safe_regex.py` (BF-287 — pure, no mocks)
- happy path: a normal pattern compiles and matches.
- length cap rejects an over-long pattern.
- each catastrophic signature (`(a+)+`, `(a*)*`, `(.*)*`) raises `UnsafePatternError`.
- invalid regex raises `UnsafePatternError` (not `re.error`).
- flags (e.g. `re.IGNORECASE`) are honored.

---

## AD-990 — gitignore-aware file traversal util + FileSearchAgent fix

`FileSearchAgent._search_files` (`agents/file_search.py:111`) uses raw `p.rglob(pattern)`
— it descends `.venv/`, `node_modules/`, `__pycache__/`, `data/`, `site/` (no ignore
respect). That's `find`, not `grep`. Absorb ripgrep's automatic-filtering pattern.

### New `src/probos/substrate/file_walk.py` (pure Python, zero new deps)
- `class IgnoreSpec`: parsed `.gitignore` / `.ignore` rules. Support the COMMON cases
  (faithful subset, documented): blank lines + `#` comments skipped; `!` negation;
  trailing-`/` = directory-only; leading-`/` = anchored-to-root; `*`/`?`/`**` via
  `fnmatch.translate`. `matches(rel_posix: str, is_dir: bool) -> bool` (last-match-wins
  for negation). Exotic gitignore semantics are out of scope (note it).
- `_DEFAULT_IGNORE_DIRS: frozenset` backstop = `{".git",".venv","venv","node_modules",
  "__pycache__",".mypy_cache",".pytest_cache",".ruff_cache","dist","build","site",
  ".tox",".idea",".vscode","data"}`.
- `load_ignore_spec(root: Path) -> IgnoreSpec`: reads `root/.gitignore` + `root/.ignore`
  if present (Tier-2: missing/unreadable → empty spec).
- `is_binary(path, *, sniff_bytes=8192) -> bool`: NUL-byte sniff.
- `iter_files(root, *, ignore_spec=None, include_hidden=False, skip_binary=True,
  respect_default_ignores=True, max_files=20000) -> Iterator[Path]`: os.walk-based;
  prunes default-ignore dirs + hidden dirs + ignore-spec dir matches *in place* (don't
  descend); yields files passing the spec; bounded by `max_files`. Deterministic
  (sorted). Tier-2: per-entry errors skipped.

### `src/probos/agents/file_search.py`
- Add an optional intent param `include_ignored: bool = False`. `_search_files` walks via
  `iter_files` (ignore-aware) when `include_ignored` is false (the new DEFAULT — matches
  ripgrep + fixes the `.venv` bug), or falls back to the raw `rglob` when
  `include_ignored` is true (escape hatch). Glob match preserved via `Path(f).match(pattern)`.
  Update the `IntentDescriptor` (note the new param + the ignore-by-default behavior in
  `usage_hint`).
- This is an intentional, strictly-better behavior change (no test pins the old
  `.venv`-walking behavior; none exists). Document it in the AD.

### Tests `tests/test_ad990_file_walk.py` (BF-287 — real `tmp_path` tree, no mocks)
- `iter_files` skips a `.venv/`/`node_modules/`/`__pycache__/` subtree.
- `.gitignore` with `*.log` + `build/` excludes matching files/dirs; `!keep.log`
  negation re-includes.
- hidden files skipped unless `include_hidden=True`.
- binary file skipped unless `skip_binary=False`.
- `max_files` bound respected.
- FileSearchAgent: default search excludes a `.venv` match; `include_ignored=True`
  includes it (the escape hatch).

---

## AD-989 — CodeSearchAgent / `search_content` (the headline capability)

A content-grep mesh capability returning transparent `path:line:matched-text` (directly
serves AD-988's "show why it matched"). The thing that makes "grep the project instead of
RAG" real for the Architect/Builder + crew.

### New `src/probos/agents/code_search.py` — `CodeSearchAgent(BaseAgent)`
- `agent_type="code_search"`, `tier="core"`, `initial_confidence=0.8`, NO consensus
  (read-only). Mirror `FileSearchAgent`'s lifecycle exactly (perceive→decide→act→report).
- Intent `search_content`, params: `{path:<abs dir|file>, pattern:<regex>,
  max_results?:int=200, case_insensitive?:bool=false, glob?:<glob filter>,
  include_ignored?:bool=false}`. `IntentDescriptor` with
  `usage_hint="[MESH search_content path=<dir> pattern=<regex>] (grep file contents → path:line:text)"`.
- Engine selection (mirror `piper_backend._resolve_binary_path`):
  - **Prefer `rg`**: `shutil.which("rg")` OR a configured `tools/rg[.exe]`. When present,
    run `rg --line-number --no-heading --color never [--ignore-case] [--glob <g>]
    [-uuu if include_ignored] -e <pattern> <path>` via `asyncio.create_subprocess_exec`
    (NOT shell — no injection), bounded by a timeout + `--max-count`/`max_results`. Parse
    `path:line:text`. Tier-2: any subprocess failure → fall through to Python.
  - **Pure-Python fallback**: `safe_compile(pattern, …)` (AD-991) → iterate
    `iter_files(path, …)` (AD-990, ignore-aware) → line-by-line match (skip lines >
    `_MAX_LINE_BYTES=2000` — bounds backtracking surface) → collect
    `{path, line_number, line[:300]}` up to `max_results`.
  - `pattern` is ALWAYS run through `safe_compile` for the Python path; the `rg` path is
    inherently linear so it just bounds output.
- Return `{success, data:[{path,line,text}], count, engine:"rg"|"python", truncated:bool}`.
- Bounded everywhere (max_results, max_files via the walk, per-line cap, subprocess
  timeout). Honest-degrade on every failure.

### Wiring (mirror FileSearchAgent exactly)
- `runtime.py` (~line 1046, after the `file_search` register): `self.spawner.register_template("code_search", CodeSearchAgent)` + import at top.
- `startup/agent_fleet.py` `_builtin_pools` (~line 50, after the `search` row): `("code_search", "code_search", 2),`.
- `startup/fleet_organization.py` `pool_names` (~line 49): add `"code_search"`.
- `cognitive/dm/reply_pipeline.py` `_MESH_READ_INTENT_POOLS` (~line 42): add `"search_content": "code_search",` (so the `[MESH search_content …]` affordance routes + the AD-983a hint surfaces crew-wide).

### Tests `tests/test_ad989_code_search.py` (BF-287 — real `tmp_path` tree + real agent, no mocks; force the Python engine by monkeypatching `shutil.which` → None so the test is deterministic regardless of whether `rg` is installed)
- finds a literal match → returns `{path,line,text}` with correct 1-based line number.
- regex match (`def \w+`), case-insensitive flag, glob filter (`*.py` only).
- respects ignores by default (no `.venv` hit); `include_ignored=True` includes it.
- `max_results` bound + `truncated=True`.
- a catastrophic supplied pattern (`(a+)+$`) is rejected via AD-991 (error result, no hang).
- missing path → error result; binary file skipped.
- the IntentDescriptor exposes `search_content` with the `[MESH …]` usage_hint.

---

## Do NOT change
- The semantic/episodic recall path, the Oracle, FTS5 — this wave is FILE-CONTENT grep,
  orthogonal to memory recall.
- Consensus/trust. CodeSearchAgent is read-only core; no consensus.
- No new hard dependency. `rg`/`re2`/`pathspec` are all optional/forward-marker.
- Don't build a full gitignore engine (faithful common-subset only; note the boundary).

## Verify compliance with `.github/copilot-instructions.md` Engineering Principles.
