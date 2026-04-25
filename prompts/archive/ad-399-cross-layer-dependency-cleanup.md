# AD-399: Cross-Layer Dependency Cleanup

## Context

An AST-based cross-layer dependency analysis of the ProbOS codebase identified 18 genuine architectural violations where modules import from layers they shouldn't depend on. Most are clean and well-managed (TYPE_CHECKING guards, dependency injection), but three categories have concrete fixes worth making:

1. **`embeddings.py` is in `cognitive/` but needed by `knowledge/` and `mesh/`** — embeddings are a knowledge concern, not a cognitive one
2. **`extract_response_text()` is in `channels/` but imported by `cognitive/`** — it's a pure dict→string extractor, not channel-specific
3. **`QAReport` dataclass is in `agents/system_qa.py` but imported by `experience/qa_panel.py`** — data transfer types belong in `types.py`

Two categories are **intentionally left as-is** (document as allowed edges):
- `cognitive` → `consensus.trust` (4 imports): Trust is a Ship's Computer service that cognitive agents naturally consume. All use dependency injection. The coupling is correct by design.
- `substrate` → `mesh` (2 imports): Both TYPE_CHECKING guarded with DI. `heartbeat.py` needs gossip protocol, `scaler.py` needs intent bus demand metrics. The DI pattern is already clean.

## Part 1: Move `embeddings.py` from `cognitive/` to `knowledge/`

### Move the file

Move `src/probos/cognitive/embeddings.py` → `src/probos/knowledge/embeddings.py`

No changes to the file contents — only its location.

### Update all imports (5 source files + 2 test files)

**Source files — update `from probos.cognitive.embeddings` → `from probos.knowledge.embeddings`:**

| File | Line | Old Import | New Import |
|------|------|-----------|------------|
| `src/probos/knowledge/semantic.py` | 55 | `from probos.cognitive.embeddings import get_embedding_function` | `from probos.knowledge.embeddings import get_embedding_function` |
| `src/probos/mesh/capability.py` | 113 | `from probos.cognitive.embeddings import compute_similarity` | `from probos.knowledge.embeddings import compute_similarity` |
| `src/probos/cognitive/episodic.py` | 38 | `from probos.cognitive.embeddings import get_embedding_function` | `from probos.knowledge.embeddings import get_embedding_function` |
| `src/probos/cognitive/workflow_cache.py` | 88 | `from probos.cognitive.embeddings import compute_similarity` | `from probos.knowledge.embeddings import compute_similarity` |
| `src/probos/cognitive/strategy.py` | 190 | `from probos.cognitive.embeddings import compute_similarity` | `from probos.knowledge.embeddings import compute_similarity` |

**Test files — update `from probos.cognitive.embeddings` → `from probos.knowledge.embeddings`:**

| File | Lines | Old Import | New Import |
|------|-------|-----------|------------|
| `tests/test_embeddings.py` | 14, 21, 28, 34, 40, 47 | `from probos.cognitive.embeddings import ...` | `from probos.knowledge.embeddings import ...` |
| `tests/test_episodic.py` | 8 | `from probos.cognitive.embeddings import _keyword_embedding, _keyword_similarity` | `from probos.knowledge.embeddings import _keyword_embedding, _keyword_similarity` |

### Backwards compatibility

Add a re-export shim in the OLD location so any untracked imports don't break:

Create `src/probos/cognitive/embeddings.py` (new, thin file):
```python
"""Backwards-compat shim — embeddings moved to probos.knowledge.embeddings (AD-399)."""
from probos.knowledge.embeddings import (  # noqa: F401
    compute_similarity,
    embed_text,
    get_embedding_function,
)
```

Wait — the memory says "Avoid backwards-compatibility hacks like renaming unused _vars, re-exporting types." Skip the shim. Just update all imports directly. If anything breaks in an import we missed, the test suite will catch it.

**Delete the shim approach. Just move the file and update all imports.**

## Part 2: Move `extract_response_text()` to `utils/`

### What to move

The function `extract_response_text()` in `src/probos/channels/response_formatter.py` is a pure dict→string extractor. It examines a dag_result dict and picks the best human-readable text from it. It has no channel-specific dependencies.

Read `src/probos/channels/response_formatter.py` fully. If `extract_response_text()` is the **only** function in the file, move the entire file to `src/probos/utils/response_formatter.py`. If there are other channel-specific functions in the file, extract just `extract_response_text()` into `src/probos/utils/response_formatter.py` and leave the rest.

### Update all imports (4 source files + 1 test file)

**Source files — update `from probos.channels.response_formatter` → `from probos.utils.response_formatter`:**

| File | Line | Old Import | New Import |
|------|------|-----------|------------|
| `src/probos/cognitive/task_scheduler.py` | 171 | `from probos.channels.response_formatter import extract_response_text` | `from probos.utils.response_formatter import extract_response_text` |
| `src/probos/api.py` | 425 | `from probos.channels.response_formatter import extract_response_text` | `from probos.utils.response_formatter import extract_response_text` |
| `src/probos/channels/base.py` | 74 | `from probos.channels.response_formatter import extract_response_text` | `from probos.utils.response_formatter import extract_response_text` |
| `src/probos/channels/__init__.py` | 4 | `from probos.channels.response_formatter import extract_response_text` | `from probos.utils.response_formatter import extract_response_text` |

**Test files:**

| File | Line | Old Import | New Import |
|------|------|-----------|------------|
| `tests/test_channel_base.py` | 10 | `from probos.channels.response_formatter import extract_response_text` | `from probos.utils.response_formatter import extract_response_text` |

**Important:** Check if `channels/__init__.py` re-exports `extract_response_text` under the `channels` namespace. If other code imports it as `from probos.channels import extract_response_text`, update the `__init__.py` re-export to point to the new location. The `__init__.py` re-export should be updated, not removed, so the public API surface doesn't break.

## Part 3: Move `QAReport` to `types.py`

### What to move

The `QAReport` dataclass in `src/probos/agents/system_qa.py` (lines 23-36) is a pure data container:

```python
@dataclass
class QAReport:
    """Result of a smoke-test run for a designed agent."""
    agent_type: str
    intent_name: str
    pool_name: str
    total_tests: int
    passed: int
    failed: int
    pass_rate: float
    verdict: str  # "passed" | "failed" | "error"
    test_details: list[dict] = field(default_factory=list)
    duration_ms: float = 0.0
    timestamp: float = 0.0
```

Move this dataclass to `src/probos/types.py` alongside the other shared types. Place it near other result/report types.

### Update imports

**In `src/probos/agents/system_qa.py`:** Remove the `QAReport` class definition. Add `from probos.types import QAReport` at the top imports.

**In `src/probos/experience/qa_panel.py`** (line 12): Change `from probos.agents.system_qa import QAReport` → `from probos.types import QAReport`

**In `tests/test_system_qa.py`** (line 14): Change `from probos.agents.system_qa import QAReport, SystemQAAgent, _infer_param_type` → split into two imports:
```python
from probos.types import QAReport
from probos.agents.system_qa import SystemQAAgent, _infer_param_type
```

## Part 4: Document Allowed Cross-Layer Edges

No code changes needed. This documents the architectural decisions for the edges we're intentionally keeping.

Add a brief comment at the top of each file explaining the allowed cross-layer dependency:

**`src/probos/cognitive/dreaming.py`** — near line 19:
```python
from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — dream consolidation mutates trust
```

**`src/probos/cognitive/feedback.py`** — near line 13:
```python
from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — feedback records trust outcomes
```

**`src/probos/cognitive/working_memory.py`** — near line 11:
```python
from probos.consensus.trust import TrustNetwork  # AD-399: allowed edge — assembles trust summary for LLM context
```

**`src/probos/cognitive/emergent_detector.py`** — find the consensus.trust import and add:
```python
# AD-399: allowed edge — reads trust for emergent pattern detection
```

**`src/probos/substrate/heartbeat.py`** — near line 13:
```python
from probos.mesh.gossip import GossipProtocol  # AD-399: allowed edge — TYPE_CHECKING + DI
```

**`src/probos/substrate/scaler.py`** — near line 21:
```python
from probos.mesh.intent import IntentBus  # AD-399: allowed edge — TYPE_CHECKING + DI
```

## Testing

Run the full test suite:
```
uv run pytest tests/ -v
```

All 2776+ tests should pass. The changes are pure refactoring — file moves and import path updates. No behavior changes. If any test fails, it means we missed an import that needs updating.

Also verify no remaining cross-layer violations for the fixed categories:
```python
# These should return no results:
grep -rn "from probos.cognitive.embeddings" src/  # should be gone (except if shim exists)
grep -rn "from probos.channels.response_formatter import extract_response_text" src/probos/cognitive/  # should be gone
grep -rn "from probos.agents.system_qa import QAReport" src/probos/experience/  # should be gone
```

## Commit Message

```
Clean up cross-layer dependency violations (AD-399)

Move embeddings.py from cognitive/ to knowledge/ (fixes knowledge→cognitive
and mesh→cognitive violations). Move extract_response_text() from channels/
to utils/ (fixes cognitive→channels violation). Move QAReport dataclass from
agents/system_qa to types.py (fixes experience→agents violation). Document
6 allowed cross-layer edges with AD-399 comments.
```
