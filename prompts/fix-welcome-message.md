# Fix: Update ProbOS Welcome/Greeting Messages

## Problem

ProbOS responds to greetings with outdated messages like "I can read, write, and inspect files. Try: read /tmp/test.txt" — this was written in Phase 4 when that was all ProbOS could do. ProbOS now has 10 bundled agents, self-modification, HXI visualization, knowledge search, emergent detection, and much more.

## What to update

### 1. MockLLMClient greeting pattern

**File:** `src/probos/cognitive/llm_client.py`

Find the pattern that matches greetings (hello, hi, hey, etc.) and update the canned response:

Old: `"Hello! I'm ProbOS, a probabilistic agent-native OS. I can read, write, and inspect files. Try: read /tmp/test.txt"`

New: `"Hello! I'm ProbOS — a probabilistic agent-native OS that learns and evolves. I can search the web, read and summarize pages, check weather, get news, translate text, manage your notes and todos, set reminders, run commands, and answer questions about my own state. I also build new capabilities on the fly when you ask me something I can't do yet. What would you like to do?"`

### 2. Prompt examples — "what can you do?" response

**File:** `src/probos/cognitive/prompt_builder.py` — in `PROMPT_EXAMPLES`

Find the "what can you do?" example response and update it:

Old: `"I can read files, write files, list directories, search for files, run shell commands, fetch URLs, and answer questions about my own state (explain what happened, describe agents, assess system health, explain my reasoning). Writes and commands go through consensus verification."`

New: `"I can search the web, read and summarize pages, check weather, get news headlines, translate text, summarize content, do calculations, manage notes and todos, set reminders, read and write files, run shell commands, and answer questions about my own state. I learn from our interactions and build new capabilities when needed. Writes and commands go through consensus verification."`

### 3. Also update in legacy system prompt (if still used)

**File:** `src/probos/cognitive/decomposer.py` — in `_LEGACY_SYSTEM_PROMPT`

Same update to the "what can you do?" example if it exists there.

## After fix

Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` — some tests may assert specific greeting text. Update those test assertions to match the new messages.

Restart `probos serve`. Type "hello" or "what can you do?" — should see the updated, comprehensive response.
