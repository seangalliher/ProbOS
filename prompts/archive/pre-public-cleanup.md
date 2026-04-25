# Pre-Public Cleanup — Open Source Release Prep

**Role:** You are a release engineer preparing the ProbOS repo for its first public push to GitHub under the Apache 2.0 license.

**Context:** ProbOS has been developed in a single private repo. A separate private commercial repo (`d:\probos-commercial`) already contains all business strategy, pricing, and enterprise-specific documents. This prompt handles cleaning the *public* repo so it contains zero confidential material, proper licensing, and accurate metadata.

**Test baseline:** 1590 Python tests + 15 Vitest tests = 1605 total. All must still pass after cleanup.

---

## Step 1: Add Apache 2.0 LICENSE file

Create a `LICENSE` file in the repo root with the full Apache License 2.0 text.
- Use the standard Apache 2.0 text (https://www.apache.org/licenses/LICENSE-2.0)
- Copyright line: `Copyright 2025-2026 Nooplex LLC`

---

## Step 2: Remove confidential files from working tree

Delete these files/directories from the working tree. They have already been copied to `d:\probos-commercial`.

```
git rm docs/business-plan.md
git rm docs/demo-script-selfmod.md
git rm docs/nooplex-alignment-tracker.md
git rm -r Vibes/  -- EXCEPT keep Vibes/Nooplex_Final.md
git rm -r MagicMock/
```

**Important:** Keep `Vibes/Nooplex_Final.md` — it is the project manifesto and stays public. Remove all other Vibes files:
- `Vibes/HXI Project Structure.md`
- `Vibes/ProbOS Vision.md`
- `Vibes/Probos_Simple_Understanding`
- `Vibes/hxi-adaptive-cognitive-interface.md`
- `Vibes/hxi-architecture-v2.md`
- `Vibes/phase-3b-attention-prompt.md`
- `Vibes/probabilistic-os.jsx`
- `Vibes/probos-claude-code-prompt.md`

---

## Step 3: Scrub git history

Use `git filter-repo` to remove ALL traces of confidential files from commit history. These files were committed in earlier phases and must not appear in any historical commit.

Files to scrub from history:
```
git filter-repo --invert-paths \
  --path docs/business-plan.md \
  --path docs/demo-script-selfmod.md \
  --path docs/nooplex-alignment-tracker.md \
  --path "Vibes/HXI Project Structure.md" \
  --path "Vibes/ProbOS Vision.md" \
  --path "Vibes/Probos_Simple_Understanding" \
  --path "Vibes/hxi-adaptive-cognitive-interface.md" \
  --path "Vibes/hxi-architecture-v2.md" \
  --path "Vibes/phase-3b-attention-prompt.md" \
  --path "Vibes/probabilistic-os.jsx" \
  --path "Vibes/probos-claude-code-prompt.md" \
  --path MagicMock/ \
  --force
```

**Pre-requisites:**
- Install `git-filter-repo`: `pip install git-filter-repo`
- Back up the repo before running (`cp -r d:/ProbOS d:/ProbOS-backup`)
- This rewrites ALL commits — the user must force-push after

**After filter-repo:** `Vibes/Nooplex_Final.md` should still be present in history and working tree.

---

## Step 4: Expand .gitignore

Replace the current `.gitignore` with a comprehensive version:

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.venv/
venv/
.pytest_cache/
*.egg-info/
dist/
build/
*.egg

# Data / artifacts
data/
*.db
*.sqlite3
MagicMock/

# Environment
.env
.env.*
.env.local

# Node / UI
node_modules/
ui/dist/
ui/coverage/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db
Desktop.ini

# Logs
*.log
```

---

## Step 5: Update pyproject.toml metadata

Add missing metadata fields to `[project]` in `pyproject.toml`:

```toml
[project]
name = "probos"
version = "0.1.0"
description = "Probabilistic agent-native OS runtime"
requires-python = ">=3.12"
license = "Apache-2.0"
authors = [
    { name = "Sean Galliher", email = "sean@nooplex.dev" },
]
readme = "README.md"
keywords = ["ai", "agents", "cognitive-mesh", "autonomous", "multi-agent"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3.12",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
]

[project.urls]
Homepage = "https://probos.dev"
Repository = "https://github.com/probos/probos"
```

**Note:** Confirm the author email and GitHub org name with the user — the above are placeholders based on earlier discussions. Adjust as needed.

---

## Step 6: Update README.md

The current README references "24 agents" and an outdated project description. Update the header stats to reflect current state:

- Agent count: 47 agents across 20+ pools
- Test count: 1605 tests (1590 Python + 15 Vitest)
- Phase: 27 complete
- Key capabilities to highlight: self-modification, Bayesian trust, Hebbian routing, episodic memory, dreaming, HXI visualization, federation

Do NOT rewrite the entire README — just update the stats/numbers that are stale. The design philosophy and architecture sections are still accurate.

---

## Step 7: Scan for remaining confidential references

Search the entire codebase for any remaining references to confidential material:

```
grep -ri "nooplex llc" --include="*.py" --include="*.md" --include="*.toml"
grep -ri "business-plan" --include="*.py" --include="*.md"
grep -ri "pricing" --include="*.py" --include="*.md"
grep -ri "\$2,000\|\$8,000\|\$2K\|\$8K" --include="*.md"
grep -ri "enterprise tier\|enterprise overlay" --include="*.md"
grep -ri "great artists steal" --include="*.md"
grep -ri "probos-commercial\|probos-enterprise" --include="*.md" --include="*.py"
```

Remove or redact any hits. Exception: `Nooplex LLC` in the LICENSE copyright line is fine.

Also check PROGRESS.md to confirm all commercial content was already removed in the previous session (pricing tiers, RBAC details, enterprise roadmap, dogfooding mention, repo separation strategy).

---

## Step 8: Commit staged Vitest infrastructure

The following files are currently untracked and should be committed:

```
ui/src/__tests__/useStore.test.ts
ui/src/test/setup.ts
ui/vitest.config.ts
```

Plus the modified `ui/package.json` and `ui/package-lock.json` (devDependencies added for vitest).

Commit message: "Add Vitest infrastructure with 15 store tests"

---

## Step 9: Verify

1. Run all Python tests: `python -m pytest tests/ -q` — expect 1590 passing
2. Run Vitest: `cd ui && npx vitest run` — expect 15 passing
3. Verify no confidential files remain: `git ls-files | grep -i "business-plan\|demo-script\|alignment-tracker\|MagicMock"`
4. Verify LICENSE exists: `cat LICENSE | head -1`
5. Verify .gitignore blocks sensitive patterns: `git status` should NOT show .env, MagicMock/, *.sqlite3

---

## Step 10: Final commit and user instructions

After all steps pass, create a commit: "Prepare repo for public open-source release"

Then inform the user:
1. History has been rewritten — they must `git push --force` to their remote
2. The probos-commercial repo at `d:\probos-commercial` needs:
   - `git config user.email` and `git config user.name` set
   - A private GitHub repo created
   - Initial push
3. The public repo is ready for `git remote set-url origin` to the new public GitHub URL and push

---

## What NOT to do

- Do NOT remove the `prompts/` directory — it stays public
- Do NOT remove `.github/copilot-instructions.md` — it stays public
- Do NOT remove `Vibes/Nooplex_Final.md` — it's the project manifesto
- Do NOT modify any Python source code or test files (beyond pyproject.toml metadata)
- Do NOT add enterprise extension points — that's future work during OSS development
- Do NOT create a CONTRIBUTING.md — the copilot-instructions.md serves this purpose for now
