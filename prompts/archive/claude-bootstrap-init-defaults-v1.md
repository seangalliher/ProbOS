# claude-bootstrap — `probos init` security-default profile

**Issue:** [#495](https://github.com/seangalliher/ProbOS/issues/495)
**Type:** Architecture Decision (experience — init wizard hardening)
**Upstream:** https://github.com/alinaqi/claude-bootstrap (MIT, 607★)
**Depends on:** AD-484 (`probos init` wizard, `probos doctor`).
**Wave:** 130

## Goal

`claude-bootstrap` ships an opinionated project initializer whose biggest absorbable idea is its **`settings.json` permission deny-list**: routine operations (`Bash(npm test *)`, `Bash(git status *)`) are allow-listed; destructive operations (`Bash(rm -rf *)`, `Bash(git push --force *)`, `Write(.env)`) are deny-listed by default. This AD lifts that pattern into `probos init` so the generated `~/.probos/config.yaml` is **secure by default** — and any weakening of the defaults must be an explicit opt-in.

## Upstream summary (Architect-fetched 2026-05-08)

From `alinaqi/claude-bootstrap` `README.md`:

> ```json
> "permissions": {
>   "allow": [
>     "Bash(npm test *)", "Bash(npm run lint *)", "Bash(pytest *)",
>     "Bash(git status *)", "Bash(gh pr *)"
>   ],
>   "deny": [
>     "Bash(rm -rf *)", "Bash(git push --force *)",
>     "Write(.env)", "Write(.env.*)"
>   ]
> }
> ```

Their core principle: deny-list common foot-guns at the config layer, not in code that the agent might bypass. The pattern is small, declarative, and language-agnostic. The companion idea — `CLAUDE.local.md` for personal overrides that gitignore — also applies to ProbOS (`config.local.yaml` would mirror it), but that's tracked separately as a follow-up.

We absorb: (1) the deny-list as a hard default in the generated config, (2) a `--security-profile` flag (`strict|relaxed`; default `strict`), (3) the rule that the wizard NEVER prints a "weaken this for convenience" prompt — opt-in is via flag, not interactive choice. We do **not** absorb their TDD-loop hooks, agent-team scaffolding, mnemos/iCPG, or skill registry — those are out of scope for `probos init`.

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/__main__.py:599` `def _cmd_init(args: argparse.Namespace) -> None` is the existing wizard. `:651–684` writes the literal `config_content` template. **The dispatch's hint that the init wizard lives at `experience/init/` is incorrect; the wizard is in `__main__.py`.** This prompt reflects the actual location.
- ✅ `:1270` `# --- probos init ---` registers the subparser. Currently only `--force` and `--probos-home`. The new `--security-profile` flag adds at this site.
- ✅ `_cmd_init` writes a YAML template directly (string formatting). There is no current concept of a "permissions" or "security" section in the template — greenfield insertion.
- ✅ `src/probos/__main__.py:707` shows `probos doctor` mentions `probos init` already. `_cmd_doctor` (verify-first the function definition) is the right place to add a "security profile is strict" check.
- ⚠️ ProbOS does **not** today honor a `permissions.deny` list at runtime — that's a separate enforcement AD (deferred). This AD only ships the **declarative section in the generated config**. The runtime change is filed as **AD-712** (out of scope here).

## Build Ordering Note

This prompt edits `src/probos/config.py` (D4). Four Wave 130 prompts touch that file; serialize commits in this order to avoid register-block collisions: **claude-bootstrap → AD-701 → AD-707 → Memvid-QP**. claude-bootstrap is **first** — its `SecurityConfig` / `PermissionsConfig` land before the AD-701, AD-707, and Memvid-QP additions rebase on top.

## Convention #14 carve-out (Recommended R4)

`SecurityConfig.profile` defaults to `"strict"` and the `--security-profile` flag defaults to `"strict"`. **This is not a Wave 10 convention #14 violation.** Convention #14 forbids transitional `enabled: True` defaults that flip on first commit; security defaults are by definition the safe default and must be on. The deny-list shipped in `security_block_strict` is conservative; weaker profiles are explicit opt-in via `--security-profile relaxed`. Reviewers: do not flag this as a #14 violation.

## Scope

Ship: (1) the security-profile section in the generated config template, (2) the `--security-profile` flag, (3) a `probos doctor` check that warns when the section is missing or weakened. Do **not** wire runtime enforcement.

## Deliverables

### D1. Update `_cmd_init` in `src/probos/__main__.py`

Add at the top of `_cmd_init`, after the existing `home` resolution:

```python
profile = getattr(args, "security_profile", "strict")
if profile not in ("strict", "relaxed"):
    profile = "strict"
```

Append a new `security:` block to the generated `config_content` template. Keep the existing template intact and add **at the end**:

```python
security_block_strict = """\
# AD-709: Security profile (claude-bootstrap-derived defaults)
# Generated with profile=strict. Edit ONLY by adding entries to ``allow``.
# Do NOT remove entries from ``deny`` without first reviewing the docs.
security:
  profile: "strict"
  permissions:
    allow:
      - "shell:pytest *"
      - "shell:git status *"
      - "shell:git diff *"
      - "shell:git log *"
    deny:
      - "shell:rm -rf *"
      - "shell:git push --force *"
      - "shell:git reset --hard *"
      - "fs:write:.env"
      - "fs:write:.env.*"
      - "fs:write:**/credentials.json"
"""

security_block_relaxed = """\
# AD-709: Security profile (claude-bootstrap-derived defaults)
# Generated with profile=relaxed. THIS PROFILE IS WEAKER — explicit opt-in only.
# To re-enable strict defaults, run: probos init --force --security-profile strict
security:
  profile: "relaxed"
  permissions:
    allow:
      - "shell:*"
    deny:
      - "shell:rm -rf /"
      - "fs:write:.env"
"""

config_content = config_content + (
    security_block_strict if profile == "strict" else security_block_relaxed
)
```

### D2. Argparse flag

In the existing init-parser registration block (verify-first: `__main__.py:1270`):

```python
init_parser.add_argument(
    "--security-profile",
    choices=("strict", "relaxed"),
    default="strict",
    help="Security defaults to bake into the generated config (default: strict)",
)
```

The flag is dest `security_profile` (argparse default).

### D3. `probos doctor` check

In `_cmd_doctor`, add a new check inside the existing `failures` accumulation pattern:

```python
# AD-709: Security profile sanity check
if cfg is not None:
    sec = getattr(cfg, "security", None)
    # Recommended R3: the existing _cmd_doctor already loads ``cfg`` near
    # the top of the function; the snippet below assumes that loader is
    # in scope. If ``cfg`` may be ``None`` on a degraded boot, the
    # ``if cfg is not None`` guard above already handles it; do not
    # re-load the config here.
    if sec is None:
        failures.append(
            "security: section missing from config.yaml — re-run "
            "`probos init --force --security-profile strict` to generate it",
        )
    else:
        profile = getattr(sec, "profile", "")
        deny = getattr(getattr(sec, "permissions", None), "deny", []) or []
        if profile != "strict":
            console.print(
                "  [yellow]![/yellow] security.profile is "
                f"'{profile}' (not 'strict') — review at your discretion"
            )
        if not deny:
            failures.append(
                "security.permissions.deny is empty — at minimum, deny "
                "shell:rm -rf and fs:write:.env per AD-709 defaults",
            )
```

### D4. Pydantic model

In `src/probos/config.py`, add (the spec uses `typing.Literal`; verify-first whether `config.py` already imports it — if not, add `from typing import Literal` at the top of the file):

```python
class PermissionsConfig(BaseModel):
    """AD-709: declarative permission lists (enforcement deferred to AD-712)."""
    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)


class SecurityConfig(BaseModel):
    """AD-709: security profile section."""
    profile: Literal["strict", "relaxed"] = "strict"
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
```

Wire onto the top-level config model alongside `system:`, `cognitive:`, etc. (verify-first the registration site).

### D5. Tests — `tests/test_claude_bootstrap_init_defaults.py`

Required (≥ 7):

1. `test_init_strict_profile_writes_deny_block` — invoke `_cmd_init` with `tmp_path` and `--security-profile=strict`; read the generated `config.yaml`; assert `"deny:"` block present with `shell:rm -rf *` and `fs:write:.env`.
2. `test_init_relaxed_profile_writes_relaxed_block` — `--security-profile=relaxed`; generated config contains `profile: "relaxed"` and a comment line warning that this profile is weaker.
3. `test_init_default_profile_is_strict` — no flag → `profile: "strict"` in generated config.
4. `test_init_invalid_profile_falls_back_to_strict` — pass `--security-profile=loose` (or simulate via munged args) → strict block emitted.
5. `test_pydantic_security_config_defaults_to_strict_with_empty_lists` — instantiate `SecurityConfig()`, assert `profile == "strict"`, `permissions.allow == []`, `permissions.deny == []`.
6. `test_pydantic_security_config_rejects_unknown_profile` — `SecurityConfig(profile="loose")` raises `ValidationError`.
7. `test_doctor_flags_missing_security_section` — stub config with no `security` attr; call `_cmd_doctor` (or the new check helper extracted into a function); assert failure recorded.
8. `test_doctor_flags_empty_deny_list` — security present but `permissions.deny == []`; failure recorded.
9. `test_doctor_warns_on_relaxed_profile` — relaxed profile present with a real deny list; warning printed but NOT recorded as a failure.

## Hard constraints (do NOT do)

- Do **not** add runtime enforcement of the deny-list — defer to **AD-712**.
- Do **not** prompt the user interactively to weaken defaults. The CLI flag is the only path to a relaxed profile.
- Do **not** absorb claude-bootstrap's TDD hook scripts, agent-team scaffolding, mnemos / iCPG / skills registry, or `CLAUDE.md` `@include` model.
- Do **not** copy any text from claude-bootstrap verbatim — paraphrase. The MIT license permits absorption of the pattern; we authored our own copy.
- Do **not** remove the existing `_cmd_init` defaults (LLM endpoint, model, etc.) — the security block is **additive**.

## Acceptance criteria

- **Pre-flight (Wave 129 convention #20):** run `git diff --numstat | sort -k2nr | head -5`; >200 deletions on any tracked file = STOP and surface to the Architect before reading source.
- All new code passes lint with full type annotations on public methods.
- 7+ tests pass.
- Existing test suite passes unchanged (no regressions).
- Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_claude_bootstrap_init_defaults.py -v -n 0`
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Forward markers

- **AD-712**: runtime enforcement of `security.permissions.deny` (intercept at the shell-agent / file-writer agent boundaries).
- **AD-709-1**: `config.local.yaml` overlay (claude-bootstrap's `CLAUDE.local.md` analog) — gitignored personal overrides.
- **AD-709-2**: `probos init --upgrade-security` — non-destructive migration that adds the security block to an existing config without overwriting the rest.

## Revision (2026-05-08)

- **Recommended R2 (`Literal` import):** Added explicit "verify-first whether `config.py` already imports `Literal`; if not, add `from typing import Literal`" instruction in D4.
- **Recommended R3 (`cfg` scope):** Added comment in D3 documenting that `cfg` is loaded by the existing `_cmd_doctor` body; spec no longer reads as if `cfg` materializes from nowhere.
- **Recommended R4 (#14 carve-out):** Added explicit "Convention #14 carve-out" section so reviewers do not mis-flag the secure-by-default `profile="strict"` as a transitional-flag violation.
- **Cross-cutting:** Added Build Ordering Note marking claude-bootstrap as **first** in the config.py serialization chain, plus pre-flight working-tree integrity reminder.
