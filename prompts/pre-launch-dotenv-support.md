# Pre-Launch: .env File Support for Secrets (AD-286)

> **Context:** Users currently need OS-specific environment variable configuration
> to set Discord tokens, API keys, and other secrets. Adding `.env` file support
> provides a cross-platform, standard approach that works on first install.

## Pre-read

- `src/probos/__main__.py` — entry point, where env vars are read
- `pyproject.toml` — dependencies
- `.gitignore` — ensure `.env` is listed

## Step 1: Add python-dotenv (AD-286)

1. Add `python-dotenv` to dependencies in `pyproject.toml` (required, not optional)

2. Add dotenv loading at the top of `main()` in `__main__.py`, before any config loading:

```python
try:
    from dotenv import load_dotenv
    load_dotenv()  # Loads .env from cwd, then walks up to find it
except ImportError:
    pass  # dotenv not installed — env vars must be set manually
```

3. Add `.env` to `.gitignore` if not already present

4. Add a `.env.example` file in the repo root documenting available env vars:

```
# ProbOS Environment Variables
# Copy this file to .env and fill in your values.
# NEVER commit .env to git.

# Discord bot token (from Discord Developer Portal)
# PROBOS_DISCORD_TOKEN=

# LLM API key (if using external API instead of Ollama)
# PROBOS_LLM_API_KEY=
```

5. Update `README.md` Quick Start or configuration section to mention `.env` file support

## Step 2: Tests

1. Verify `main()` doesn't crash when `.env` doesn't exist
2. Verify `main()` doesn't crash when `python-dotenv` is not installed (import guarded)

**Run tests:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`

## Step 3: Update PROGRESS.md

- Update test count on line 2
- Mark in Pre-Launch section: dotenv support added
