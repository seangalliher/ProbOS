# BF-657: CI `python-tests` red for weeks — ChromaDB collections pass `embedding_function=None`, so Chroma substitutes its own network-downloaded default EF that cannot fetch `onnx.tar.gz` in CI

**One-line:** `get_embedding_function()` returns **`None`** when both real-model downloads fail (AD-170 keyword-fallback intent). All ChromaDB collection sites pass that `None` straight into `get_or_create_collection(embedding_function=None, …)`. In chromadb 1.5.8, **`embedding_function=None` makes Chroma substitute its OWN built-in `DefaultEmbeddingFunction` (all-MiniLM ONNX)**, which lazily downloads `~/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz` at the first `.add()`/`.query()`. In CI the HF download is rate-limited (the `HF_TOKEN` boot warning) **and** the Chroma-S3 onnx download is blocked, so ~14 embedding-dependent tests die with `FileNotFoundError: …/onnx.tar.gz`. The CI step `Clear stale chroma onnx cache` (`rm -rf ~/.cache/chroma/onnx_models`) forces a fresh download every run → guaranteed failure. **Local passes because the model is cached in `~/.cache`; CI has no cache and can't download.** Fix: introduce a **network-free local `EmbeddingFunction`** and a `get_collection_embedding_function()` helper that is **never `None`**, swap the collection sites to it, and force it in CI via a `PROBOS_EMBEDDINGS=local` toggle.

**Status:** Ready to build
**Type:** BF (bug fix) — assign **BF-657** (verified next free; highest shipped is **BF-656**; `git grep "BF-657"` returns only a "do-NOT-use" note inside `prompts/bf-656-boot-log-warning-hygiene.md`, no BF-657 tracker entry exists. Do **NOT** mint an AD — one shared backend BF sequence.)
**GitHub issue:** seangalliher/ProbOS#1020 (OPEN, titled "BF-657: CI python-tests red for weeks …")
**Branch:** `main` (HEAD `a7968f4b`)
**Dependencies:** none. Deps already in CI: `chromadb>=1.0` → **1.5.8 installed**, `sentence-transformers>=3.0` → **5.4.1 installed** (`pyproject.toml` L31-32). No pyproject change.
**Estimated tests:** ~10 new (one new file `tests/test_bf657_local_embedding_fallback.py`). No existing test is obsoleted (verified — see §5).
**Target files:**
- `src/probos/knowledge/embeddings.py` — add `LocalHashEmbeddingFunction`, `get_collection_embedding_function()`, `get_active_embedding_model_name()`, and the `PROBOS_EMBEDDINGS` short-circuit at the top of `get_embedding_function()`.
- `src/probos/cognitive/episodic.py` — 2 EF swaps (:685, :1299) + 1 model-name swap (:1338); update the `from probos.knowledge.embeddings import …` lines.
- `src/probos/cognitive/procedure_store.py` — 1 EF swap (:283) + 1 model-name swap (:284); update import (:278).
- `src/probos/cognitive/self_improvement/evolution_store.py` — 1 EF swap (:68); update import (:67-ish).
- `src/probos/knowledge/semantic.py` — 1 EF swap (:59) + 1 model-name swap (:60); update import (:55).
- `src/probos/startup/cognitive_services.py` — 1 model-name swap (:418); update import (:417).
- `.github/workflows/ci.yml` — add `env: PROBOS_EMBEDDINGS: local` to the `python-tests` job; remove the now-dead `Clear stale chroma onnx cache` step (L32-33). **Committable.**
- `tests/test_bf657_local_embedding_fallback.py` (new) — forced-local regression + a previously-failing scenario re-run under forced-local.
- `PROGRESS.md` — `**BF-657 shipped**` line (mirror the BF-656 line format).

> **Do NOT stage `config/system.yaml`** (Captain local — shows `M` across sessions from live-instance writes). `.github/workflows/ci.yml` and `pyproject.toml` **are** committable repo files. No `pyproject.toml` change is needed (deps already present).

---

## 1. Problem

CI job `python-tests` (`.github/workflows/ci.yml`) has been RED for weeks. ~14 embedding-dependent tests fail with:

```
FileNotFoundError: [Errno 2] No such file or directory:
  '…/.cache/chroma/onnx_models/all-MiniLM-L6-v2/onnx.tar.gz'
```

Affected classes (per the issue): `test_semantic_knowledge.py::TestAgentIndexing`, `test_ad584_recall_qa_fix.py::TestRecallPipelineIntegration` / `TestEmbeddingModelMigration`, `test_knowledge_store.py::TestEpisodicMemorySeed`.

The AD-170 design intent is "no embeddings available → degrade to keyword overlap." That intent is **defeated at collection creation**: passing `embedding_function=None` does **not** mean "no embeddings" to ChromaDB — it means "use your built-in default," which is the network-downloaded all-MiniLM ONNX model. So instead of degrading, every collection silently opts into a network dependency that CI cannot satisfy.

Local dev passes because the model is already in `~/.cache`; CI wipes the onnx cache every run and cannot download it.

---

## 2. Root cause (verified against HEAD `a7968f4b`; installed **chromadb 1.5.8**, sentence-transformers 5.4.1)

### 2a. `get_embedding_function()` returns `None` when both downloads fail

[src/probos/knowledge/embeddings.py](../src/probos/knowledge/embeddings.py#L96) `get_embedding_function()` (L96):
- **Try 1** (L108-127): `SentenceTransformerEmbeddingFunction(model_name="multi-qa-MiniLM-L6-cos-v1")` — HF download. In CI: unauthenticated HF rate-limit (the `HF_TOKEN` boot warning) → raises → caught (L128).
- **Try 2** (L131-138): `DefaultEmbeddingFunction()` (all-MiniLM ONNX from Chroma-S3) — `_embedding_fn(["test"])` at L134 forces the onnx download. In CI: blocked/failed → raises → caught (L139).
- **Fallback** (L140-146): `_embedding_fn = None; _embedding_available = False; return None` (AD-170 keyword fallback). **Both `_embedding_available` and `_embedding_fn` are memoized singletons** (L88-89, L104-105) — resolved once per process.

### 2b. All collection sites pass that `None` into `get_or_create_collection`, so Chroma substitutes its ONNX default

`git grep -n "get_or_create_collection" -- src` → **9 real calls** (+ 1 docstring-only at `_episodic_probe.py:14`). Each method obtains **one** `ef = get_embedding_function()` and reuses it across that method's calls:

| # | File:line (`ef = …`) | `get_or_create_collection` call(s) using `ef` | Method |
|---|---|---|---|
| 1 | [episodic.py:685](../src/probos/cognitive/episodic.py#L685) | :686 | `migrate_embedding_model` (AD-584 recreate) |
| 2 | [episodic.py:1299](../src/probos/cognitive/episodic.py#L1299) | :1301, :1315 | `EpisodicMemory.start()` |
| 3 | [procedure_store.py:283](../src/probos/cognitive/procedure_store.py#L283) | :286, :294, :312 | `_init_chroma()` |
| 4 | [evolution_store.py:68](../src/probos/cognitive/self_improvement/evolution_store.py#L68) | :69 | `LessonEvolutionStore.start()` |
| 5 | [semantic.py:59](../src/probos/knowledge/semantic.py#L59) | :64, :72, :105 | `SemanticKnowledgeLayer.start()` |

**Empirically confirmed (chromadb 1.5.8):** `get_or_create_collection(name=…, embedding_function=None, …)` does not disable embeddings — Chroma resolves its `DefaultEmbeddingFunction` (`ONNXMiniLM_L6_V2`) and downloads `onnx.tar.gz` lazily at the first `.add()`/`.query()`. That is the `FileNotFoundError` in CI. The `None`-means-keyword-fallback intent is **defeated at collection creation**.

Note `evolution_store.py` wraps its `start()` in a broad `except Exception → self._collection = None` (L82-88). Today, offline, its collection is created with `None` (no error at create) and either crashes later at `.add()`/`.query()` **outside** that try/except, or — if Chroma resolves the default EF eagerly — degrades to no-collection (silently disabling lesson search). Either way it should use the local EF for parity.

### 2c. CI forces the failure every run

[.github/workflows/ci.yml](../.github/workflows/ci.yml#L32) L32-33 `Clear stale chroma onnx cache: rm -rf ~/.cache/chroma/onnx_models || true` → no cache → the lazy download is attempted on every run and fails. L41 runs `uv run pytest tests/ --maxfail=10 -q --tb=short`. The `python-tests` job has **no `env:` block** (L10-16).

### 2d. Installed chromadb 1.5.8 `EmbeddingFunction` protocol (determines the local EF shape)

`chromadb.api.types.EmbeddingFunction` is a `@runtime_checkable Protocol[D]`:
- **Required:** `__call__(self, input: Documents) -> Embeddings` (`@abstractmethod`). `__init_subclass__` wraps `__call__` so the return is passed through `validate_embeddings(normalize_embeddings(result))` — a plain `list[list[float]]` is accepted (verified by probe; no float32 coercion needed at the impl level).
- **Emit a `DeprecationWarning` + "will be required in a future version" if not overridden** — so implement all of: `__init__(self, …)`, `name() -> str` (`@staticmethod`), `build_from_config(config: dict) -> EmbeddingFunction` (`@staticmethod`), `get_config(self) -> dict`.
- Provided defaults (do NOT override): `default_space()`→`"l2"`, `supported_spaces()`, `validate_config()`, `validate_config_update()`, `is_legacy()`, `embed_query()`.

**Persistence / reopen behavior (empirically proven against 1.5.8, decisive for migration coherence):**
- A fully-compliant local EF (implements `__init__`/`__call__`/`name`/`get_config`/`build_from_config`) supports `PersistentClient` **create → add → query → REOPEN** (fresh client over the same path) with `count` preserved and **no network**. ✅
- **Chroma 1.5.8 RAISES `ValueError("An embedding function already exists in the collection configuration, and a new one is provided … Embedding function conflict")` when a persisted collection is reopened with an EF whose config differs from the stored one — in BOTH directions** (local↔real). Same-config reopen succeeds. ✅
- Consequence: the **existing** `except ValueError as exc: if "Embedding function conflict" in str(exc):` → reopen-without-EF → `modify(metadata={"embedding_model": "__ef_conflict__"})` recovery path ([episodic.py:1308-1327](../src/probos/cognitive/episodic.py#L1308), [procedure_store.py:288-301](../src/probos/cognitive/procedure_store.py#L288), [semantic.py:66-80](../src/probos/knowledge/semantic.py#L66)) **is** the mechanism that governs a local↔real transition — **provided the local EF has a distinct, stable config** so Chroma's conflict detector fires. **Chroma's EF-config conflict detection is the PRIMARY coherence guard; the `embedding_model` name comparison is a secondary/honest-labeling layer.**

### 2e. The hardcoded model name — confirmed latent mislabel (pre-existing; scoped-out)

[embeddings.py:91](../src/probos/knowledge/embeddings.py#L91) `get_embedding_model_name()` **hardcodes** `"multi-qa-MiniLM-L6-cos-v1"` regardless of which backend actually won. When **Try 2** (Chroma default all-MiniLM ONNX) wins, collections are labeled `multi-qa-…` but hold all-MiniLM vectors — a latent **mislabel**. It does not cause silent vector-mixing corruption because Try-1 and Try-2 are **different EF classes**, so Chroma's EF-config conflict (§2d) still forces a recreate on a Try-2→Try-1 reopen. This Try-1/Try-2 mislabel is **pre-existing and out of scope** for BF-657 (documented, not fixed). BF-657 only needs the **local** fallback to report a distinct name (§3c).

---

## 3. Fix design

Four coherent parts, all in `embeddings.py` plus mechanical swaps at the call sites and one CI edit. **Do not** change `get_embedding_function()`'s `None`-return semantics for `embed_text`/`compute_similarity` (keyword fallback stays) — blast radius stays minimal.

### 3a. `LocalHashEmbeddingFunction` (network-free, deterministic, persistence-safe) — new in `embeddings.py`

A fully protocol-compliant (§2d) ChromaDB `EmbeddingFunction` producing a fixed-dimension **dense** vector via token hashing. Design (Builder implements; describe precisely, do not copy a full impl elsewhere):

```python
_LOCAL_EMBED_DIM = 384
_LOCAL_MODEL_NAME = "probos-local-hash-v1"   # distinct + versioned; NOT any real model name

class LocalHashEmbeddingFunction(EmbeddingFunction[Documents]):
    """Network-free deterministic bag-of-hashed-tokens EF (BF-657).

    Lexical fallback so ChromaDB collection creation never passes None
    (which would trigger Chroma's network-downloaded default ONNX EF).
    NOT a semantic model — token overlap only. Stable across process
    restarts (persisted vectors must match query vectors after a reboot).
    """
    def __init__(self, dim: int = _LOCAL_EMBED_DIM) -> None: ...
    def __call__(self, input: Documents) -> Embeddings:
        # for each doc: tokens = _tokenize(doc)  # REUSE the module _tokenize (stop-words stripped)
        #   vec = [0.0]*dim
        #   for tok in tokens: vec[_stable_bucket(tok) % dim] += 1.0   # tf accumulate
        #   L2-normalize vec (skip if all-zero)
        # return list[list[float]]
    @staticmethod
    def name() -> str: return _LOCAL_MODEL_NAME
    def get_config(self) -> dict[str, Any]: return {"dim": self._dim}
    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "LocalHashEmbeddingFunction":
        return LocalHashEmbeddingFunction(dim=config.get("dim", _LOCAL_EMBED_DIM))
```

**CRITICAL — stable hash, not builtin `hash()`.** The existing `_keyword_embedding` (L44) uses `hash(word)`, which is **fine for in-process `compute_similarity`** but **WRONG for a persisted Chroma collection**: Python's `hash()` is salted per process (`PYTHONHASHSEED`), so stored vectors and post-reboot query vectors would land in different buckets → broken recall after a restart. `_stable_bucket(tok)` MUST use a stable digest, e.g. `int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=8).digest(), "big")` (proven across reopen in the probe). Add a module-level `_stable_bucket(token: str) -> int` helper.

**Reuse `_tokenize` (DRY + correctness):** `_tokenize` strips `_STOP_WORDS`, which is what makes similar-vs-dissimilar ranking correct. (A raw regex without stop-word removal makes common words like "on"/"a"/"the" dominate — the probe confirmed mediocre ranking without stripping.) The local EF is a **lexical** fallback: it ranks texts that **share surface tokens**, not synonyms. Tests must pick "similar" pairs that share tokens (see §6).

Type annotations required on all public methods (Engineering Principles). Contextual module logger only; no per-call logging.

### 3b. `get_collection_embedding_function()` — new; NEVER returns `None`

```python
def get_collection_embedding_function() -> Any:
    """EF for ChromaDB collection creation — NEVER None.

    Real EF when a network embedding model is available, else the
    network-free LocalHashEmbeddingFunction (BF-657). Passing None to
    get_or_create_collection makes Chroma substitute its own downloaded
    default ONNX EF, which cannot fetch onnx.tar.gz in CI.
    """
    return get_embedding_function() or LocalHashEmbeddingFunction()
```

Leaves `get_embedding_function()`, `embed_text`, `compute_similarity`, `_keyword_embedding` untouched.

### 3c. `get_active_embedding_model_name()` — new; migration-coherence labeling

```python
def get_active_embedding_model_name() -> str:
    """embedding_model metadata name reflecting the ACTIVE backend.

    Returns the local fallback EF's name when no network model is
    available (so an offline->online transition triggers a clean
    re-embed via the name comparison, agreeing with Chroma's EF-config
    conflict detection), else the real model name.
    """
    if get_embedding_function() is None:
        return LocalHashEmbeddingFunction.name()
    return get_embedding_model_name()
```

Order-independent (uses the memoized `get_embedding_function()` singleton). **Why this is coherent and minimal:** Chroma's EF-config conflict (§2d) is the primary guard; this makes the secondary `embedding_model` name comparison **agree** with it and keeps a local collection **honestly labeled** `probos-local-hash-v1` so an offline→online boot re-embeds cleanly. It does **not** attempt to distinguish Try-1 vs Try-2 (the pre-existing §2e mislabel stays out of scope).

### 3d. Swap the call sites

**EF resolution (5 sites, Category A)** — change `ef = get_embedding_function()` → `ef = get_collection_embedding_function()`, and add `get_collection_embedding_function` to that file's `from probos.knowledge.embeddings import …`:
- [episodic.py:685](../src/probos/cognitive/episodic.py#L685) (inside `migrate_embedding_model`; its local `from probos.knowledge.embeddings import get_embedding_function` at ~L684).
- [episodic.py:1299](../src/probos/cognitive/episodic.py#L1299) (the `start()` import at ~L1291).
- [procedure_store.py:283](../src/probos/cognitive/procedure_store.py#L283) (import at [:278](../src/probos/cognitive/procedure_store.py#L278)).
- [evolution_store.py:68](../src/probos/cognitive/self_improvement/evolution_store.py#L68) (import at ~L67).
- [semantic.py:59](../src/probos/knowledge/semantic.py#L59) (import at [:55](../src/probos/knowledge/semantic.py#L55)).

**Model-name source (4 sites, Category B — migration coherence)** — change `get_embedding_model_name()` → `get_active_embedding_model_name()`, add it to the import:
- [episodic.py:1338](../src/probos/cognitive/episodic.py#L1338) (the "ensure `embedding_model` metadata" write in `start()`; import at ~L1332).
- [cognitive_services.py:418](../src/probos/startup/cognitive_services.py#L418) (`_embedding_model_name` passed to `migrate_embedding_model`; import at [:417](../src/probos/startup/cognitive_services.py#L417)).
- [procedure_store.py:284](../src/probos/cognitive/procedure_store.py#L284) (`model_name`; same import line as the EF swap).
- [semantic.py:60](../src/probos/knowledge/semantic.py#L60) (`model_name`; same import line as the EF swap).

> **Do NOT** change `migrate_embedding_model`'s internal `"embedding_model": model_name` write ([episodic.py:691](../src/probos/cognitive/episodic.py#L691)) — it writes its **param** verbatim; fixing the caller (`cognitive_services.py:418`) propagates the active name. This keeps `TestEmbeddingModelMigration` (which calls `migrate_embedding_model` directly with an explicit `model_name`) unaffected.
> **Do NOT** touch `config.py:1002 embedding_model` / `section_registry.py:214 memory.embedding_model` — a separate user-facing setting the collection sites don't read (they use `get_embedding_model_name()`).

### 3e. CI-determinism toggle `PROBOS_EMBEDDINGS` — short-circuit at the top of `get_embedding_function()`

At the very top of `get_embedding_function()` (before the `_embedding_available is not None` memo check, or immediately after it in a way that still forces `None` — Builder's choice, but it MUST skip Try-1/Try-2):

```python
import os  # module-level (top of file)
...
def get_embedding_function() -> Any | None:
    global _embedding_fn, _embedding_available
    if os.getenv("PROBOS_EMBEDDINGS", "").strip().lower() == "local":
        _embedding_fn = None
        _embedding_available = False
        return None   # skip the slow HF / Chroma-S3 download probes; keyword + local-EF path
    if _embedding_available is not None:
        return _embedding_fn
    ... (existing Try-1 / Try-2 / fallback unchanged)
```

Effect under `PROBOS_EMBEDDINGS=local`: `get_embedding_function()` returns `None` fast (no download attempts) → `get_collection_embedding_function()` returns the local EF (collections network-free) → `get_active_embedding_model_name()` returns the local name → `embed_text`/`compute_similarity` use keyword fallback (unchanged semantics). Any other value (or unset) = today's behavior exactly.

**Pydantic-config vs raw-env justification (required by Engineering Principles):** this is a legitimate low-level env read, NOT business config. `embeddings.py` is a leaf utility imported across many layers; `get_embedding_function()` is a zero-arg memoized singleton with no `SystemConfig` handle — threading a config object through it is a large, cross-cutting blast radius. Direct precedent: `tests/conftest.py:24` `os.environ.setdefault("PROBOS_NATS_ENABLED", "false")` and the `PROBOS_DATA_DIR` reads (conftest + `runtime._platform_data_dir`). So raw `os.getenv` at this seam is the correct, in-pattern choice. Name `PROBOS_EMBEDDINGS` is unused (`git grep` empty).

### 3f. CI workflow (`.github/workflows/ci.yml`)

- Add a job-level `env:` to `python-tests` (after `timeout-minutes: 30`, L16):
  ```yaml
  env:
    # BF-657: force the network-free local embedding fallback so ChromaDB
    # collections never trigger Chroma's downloaded default ONNX EF (CI has
    # no onnx cache and cannot download). Production stays on real embeddings.
    PROBOS_EMBEDDINGS: local
  ```
- **Remove** the now-dead `Clear stale chroma onnx cache` step (L32-33): with the local EF forced, the onnx cache is never used, so the step is pointless (it only ever guaranteed the failure). Leave the `Run tests` step (L41) unchanged.

Production defaults are untouched (real embeddings when available). Only the CI job and forced-local tests use the toggle.

---

## 4. Boundaries — what this does NOT change

- **Do NOT** change `get_embedding_function()`'s Try-1/Try-2/`None`-fallback logic except adding the `PROBOS_EMBEDDINGS` short-circuit. It still returns `None` when real models are unavailable (keyword fallback for `embed_text`/`compute_similarity` preserved).
- **Do NOT** modify `embed_text`, `compute_similarity`, `_keyword_embedding`, `_keyword_similarity`, `reformulate_query`, or `get_embedding_model_name()` (still returns the hardcoded real name — `get_active_embedding_model_name()` wraps it).
- **Do NOT** change the `except ValueError "Embedding function conflict"` recovery blocks, the `__ef_conflict__` sentinel, or the migration re-embed logic in `migrate_embedding_model` / `_migrate_collections_if_needed` / `procedure_store._init_chroma`. They stay — Chroma's conflict detection (§2d) is the primary local↔real guard and is untouched.
- **Do NOT** change `migrate_embedding_model`'s `model_name` param write (:691) or its signature.
- **Do NOT** touch `config.py`/`section_registry.py` `embedding_model` (separate user setting), `settings/` UI, or `_episodic_probe.py`.
- **Do NOT** set `PROBOS_EMBEDDINGS` in `tests/conftest.py` — keep local dev on real cached embeddings so the real path is still exercised; the new tests force local per-test (monkeypatch/env) and CI forces it at the job level.
- **Do NOT** stage `config/system.yaml`. **Do NOT** touch `DECISIONS.md` (BF, not an AD) or add a `docs/development/roadmap.md` Bug-Tracker row (BF rows stopped at BF-624 — skip per BF-652/654/655/656 precedent).
- No emoji; contextual logs only.

### Residual risk (pre-existing, documented, NOT introduced by BF-657)
- **online→offline reopen of a real collection:** stored real EF config + reopen offline → Chroma "Embedding function conflict" → the recovery reopens **without** an EF → Chroma reconstructs the **real** EF from the stored config → fails if the real model is uncached offline. This exists **today** (with `ef=None` reopening a real collection) and is a rare degraded state; each site log-and-degrades (`semantic` debug-logs; `procedure_store`/`evolution_store` degrade to `None`). Hardening the recovery reopen to pass the local EF is a deeper change — **out of scope**, noted.
- The §2e Try-1/Try-2 hardcoded-name mislabel — out of scope, noted.

---

## 5. Existing tests — keep green; obsolete-contract audit

| Test | Exercises | Effect of this fix |
|---|---|---|
| `test_knowledge_store.py::TestEpisodicMemorySeed` (`test_seed_restores_episodes`, `test_seed_preserves_ids`) | `EpisodicMemory.start()` + `seed()` + `recent()` (time-ordered, **no embeddings**) | Currently **crashes** in CI at `start()`/collection use (onnx). With the local EF, `start()` is network-free → **passes**. `recent()` never embeds → assertions structural. |
| `test_semantic_knowledge.py::TestAgentIndexing` (4 tests) | `index_agent()` → `count()==1`, metadata, idempotent, `query(...)` → `len(ids)>=1` | Structural assertions satisfied by lexical local EF. `test_multiple_agents_searchable` asserts only `>= 1` over 2 docs. **Passes.** |
| `test_ad584_recall_qa_fix.py::TestRecallPipelineIntegration` (8 tests) | `recall_for_agent_scored`/`recall_weighted` → `isinstance(results, list)`, dedup; source-scans; `test_dual_query_takes_best_score` uses a **MagicMock** collection | `isinstance list`/dedup satisfied by local EF (test docstring: "if ONNX unavailable … test is informational"). MagicMock test never touches embeddings. **Passes.** |
| `test_ad584_recall_qa_fix.py::TestEmbeddingModelMigration` (4 tests, 27-30) | `migrate_embedding_model(em, "<explicit>")` → `migrated>0` / count preserved / metadata == the explicit param | EF swap at :685 makes the re-embed network-free. They pass an **explicit** `model_name`, so Category B (startup wiring) does not touch them. **Passes.** |

**No existing test is obsoleted.** No test asserts QA semantic quality that a lexical EF cannot deliver (a real-model-quality test would be un-runnable in CI regardless — a forward note, not a BF-657 concern). If the Builder finds a test that asserts real-model semantic ranking and it now fails under forced-local, it should gate on `get_embedding_function() is not None` (skip when local) — but none is expected among the failing set.

---

## 6. Test plan

New file `tests/test_bf657_local_embedding_fallback.py`. **Force the local backend explicitly** (monkeypatch or env) — do NOT rely on the machine's cached real model (that would hide the fix). `asyncio_mode=auto` is the repo default (no per-test marker needed for async).

### `class TestLocalEmbeddingFunction`
1. **`test_protocol_methods_present`** — `LocalHashEmbeddingFunction()` implements `__call__`, `name()` (`== "probos-local-hash-v1"`), `get_config()` (`{"dim": 384}`), `build_from_config(cfg)`; `build_from_config(ef.get_config())` yields an equivalent EF (same dim). No `DeprecationWarning` on construction/use (assert via `warnings.catch_warnings(record=True)`).
2. **`test_deterministic_and_dimensioned`** — two independent instances embed the same text to the **same** 384-length vector (stable hash, not salted `hash()`); different texts → different vectors; empty/whitespace → all-zero vector (no crash).
3. **`test_similar_texts_rank_above_dissimilar`** — build vectors for a token-sharing pair (e.g. `"the cat sat on the mat"` vs `"a cat on a mat"`) and a dissimilar text (`"quarterly financial revenue taxes"`); assert cosine(similar-pair) > cosine(similar, dissimilar). (Lexical: the "similar" pair must **share surface tokens** — the local EF is not semantic.)

### `class TestGetCollectionEmbeddingFunction`
4. **`test_never_none_when_get_embedding_function_none`** — monkeypatch `embeddings.get_embedding_function` → `lambda: None`; assert `get_collection_embedding_function()` is a `LocalHashEmbeddingFunction` (never `None`) and calling it returns 384-dim vectors.
5. **`test_passthrough_when_real_ef_available`** — monkeypatch `get_embedding_function` → return a sentinel object; assert `get_collection_embedding_function()` returns that sentinel (real EF wins).
6. **`test_active_model_name_reflects_backend`** — monkeypatch `get_embedding_function` → `None` ⇒ `get_active_embedding_model_name() == "probos-local-hash-v1"`; → sentinel ⇒ `== get_embedding_model_name()` (the real hardcoded name).

### `class TestRealChromaNetworkFree` (real `PersistentClient`, `tmp_path`, forced local)
7. **`test_collection_add_query_no_network`** — monkeypatch `get_embedding_function` → `None`; `ef = get_collection_embedding_function()`; real `chromadb.PersistentClient(tmp_path)`; `get_or_create_collection(name="t", embedding_function=ef, metadata={"embedding_model": get_active_embedding_model_name()})`; `.add()` 3 docs (2 token-sharing + 1 unrelated) + `.query()`; assert no exception, results returned, and the token-sharing doc ranks above the unrelated one. (Belt-and-suspenders: set `HF_HUB_OFFLINE=1`/`TRANSFORMERS_OFFLINE=1` via monkeypatch to prove no network is touched — the local EF touches none regardless.)
8. **`test_collection_reopen_preserves_count`** — create+add via the local EF; drop the client; reopen a **fresh** `PersistentClient` over the same `tmp_path` with the **same** local EF; assert `count()` preserved and `.query()` works (guards the reopen/persistence residual-risk area proven in the probe).

### `class TestPreviouslyFailingUnderForcedLocal` (CI-equivalence — the trap)
9. **`test_episodic_seed_recent_under_forced_local`** — set `monkeypatch.setenv("PROBOS_EMBEDDINGS", "local")` **and** reset the memo (`embeddings._embedding_available = None; embeddings._embedding_fn = None`) so the toggle path is exercised; construct `EpisodicMemory(str(tmp_path/"ep.db"))`, `await start()`, `seed([episode])`, assert `recent(10)` returns the episode — i.e. re-run the `TestEpisodicMemorySeed` scenario under the exact CI condition and assert it passes network-free. (Also asserts the env short-circuit actually skips the download probes.)
10. **`test_semantic_index_agent_under_forced_local`** — same forced-local setup; `SemanticKnowledgeLayer(db_path=tmp_path/"semantic")`, `await start()`, `index_agent(...)`, assert `_collections["agents"].count() == 1` and a `query()` returns `>= 1` — the `TestAgentIndexing` scenario under forced-local.

> Tests 9-10 are the mandatory "re-run a previously-failing test under forced-local" requirement. They must reset the `embeddings` memo after `setenv` so the env path is genuinely taken (the singleton is otherwise resolved once per process). Restore the memo in teardown if the file has other tests that need real embeddings (or keep all forced-local tests isolated).

### Gate commands (MUST prove CI-equivalence with local FORCED — not the cached model)
```powershell
$env:PROBOS_DATA_DIR = (New-Item -ItemType Directory -Force -Path "$env:TEMP\probos_bf657_$(Get-Random)").FullName
$env:PROBOS_EMBEDDINGS = "local"     # CI-equivalent: forces the network-free path

# new file + the previously-failing suites, under forced-local, serial, isolated:
d:/ProbOS/.venv/Scripts/pytest.exe `
  tests/test_bf657_local_embedding_fallback.py `
  tests/test_knowledge_store.py::TestEpisodicMemorySeed `
  tests/test_semantic_knowledge.py::TestAgentIndexing `
  tests/test_ad584_recall_qa_fix.py `
  -q -n 0

Remove-Item env:PROBOS_EMBEDDINGS
Remove-Item env:PROBOS_DATA_DIR
```
Both the Builder and the validator MUST run with `$env:PROBOS_EMBEDDINGS='local'` set — running without it lets the cached real model satisfy the tests and **hides** the fix. Optionally also run once **without** the toggle to confirm the real path still works locally (no regression).

---

## 7. Tracking

- **`PROGRESS.md`**: add a `**BF-657 shipped (2026-07-07) — LOCAL (Captain decides push) — …**` line at the top mirroring the BF-656 line-3 format. Summarize: collection creation passed `embedding_function=None` → Chroma substituted its downloaded default ONNX EF → CI `FileNotFoundError: onnx.tar.gz`; fixed by a network-free `LocalHashEmbeddingFunction` + `get_collection_embedding_function()` (never `None`) swapped at 5 EF sites, `get_active_embedding_model_name()` for honest offline labeling at 4 sites (Chroma's EF-config conflict remains the primary migration guard), and a `PROBOS_EMBEDDINGS=local` CI toggle + removal of the dead onnx-cache-clear step. Note "closes #1020".
- **`docs/development/roadmap.md`**: **skip** the Bug Tracker row (BF rows stopped at BF-624; BF-652/654/655/656 precedent).
- **`DECISIONS.md`**: **not touched** (BF, not an AD).
- Close `seangalliher/ProbOS#1020` on ship (`gh`, `--repo seangalliher/ProbOS`; commit body `closes #1020`).

---

## 8. Acceptance criteria

1. `get_or_create_collection` is never called with `embedding_function=None` from the 5 Category-A sites: each obtains `ef` via `get_collection_embedding_function()` (never `None`).
2. `LocalHashEmbeddingFunction` is a fully protocol-compliant chromadb 1.5.8 `EmbeddingFunction` (`__call__`/`name`/`get_config`/`build_from_config`/`__init__`), deterministic across process restarts (stable hash, not builtin `hash()`), 384-dim L2-normalized, reuses `_tokenize`, and a real `PersistentClient` collection created with it survives **create → add → query → reopen** with **no network** (tests #7, #8).
3. `get_active_embedding_model_name()` returns `"probos-local-hash-v1"` when `get_embedding_function()` is `None`, else the real model name; wired into the 4 Category-B metadata sources (test #6).
4. `PROBOS_EMBEDDINGS=local` forces the local path and skips the HF/Chroma-S3 download probes; unset/other = today's behavior. `get_embedding_function()`'s `None`-return semantics, `embed_text`, `compute_similarity`, and `get_embedding_model_name()` are otherwise unchanged.
5. `.github/workflows/ci.yml` `python-tests` sets `PROBOS_EMBEDDINGS: local` and no longer runs `Clear stale chroma onnx cache`.
6. The previously-failing suites pass **under forced-local** (`$env:PROBOS_EMBEDDINGS='local'`, isolated `PROBOS_DATA_DIR`, `-n 0`): `test_bf657_local_embedding_fallback.py`, `test_knowledge_store::TestEpisodicMemorySeed`, `test_semantic_knowledge::TestAgentIndexing`, `test_ad584_recall_qa_fix.py`. No existing test is obsoleted.
7. No change to the `except ValueError "Embedding function conflict"` recovery, `__ef_conflict__`, `migrate_embedding_model`'s param write, or `config.py`/`section_registry.py` `embedding_model`.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 9. Verify-first checklist (grep/read evidence @ HEAD `a7968f4b`, 2026-07-07)

```
# BF number free (only a don't-use note in the bf-656 prompt; no tracker entry)
git grep -n "BF-657" -- .
  prompts/bf-656-boot-log-warning-hygiene.md:6/7  (do-NOT-use note only)

# installed versions + EF protocol
.venv/Scripts/python.exe -c "import chromadb; print(chromadb.__version__)"   -> 1.5.8
.venv/Scripts/python.exe -c "import sentence_transformers as s; print(s.__version__)" -> 5.4.1
inspect chromadb.api.types.EmbeddingFunction -> Protocol: __call__ (abstract) + name()/get_config()/build_from_config()/__init__ warn-if-missing

# PROVEN by throwaway probe (deleted): compliant local EF -> PersistentClient create+add+query+REOPEN OK, no network;
#   reopen with a DIFFERENT-config EF -> ValueError "...Embedding function conflict..." (both directions); same-config reopen OK.

# collection sites (5 ef-assignments feeding 9 get_or_create_collection calls)
git grep -n "get_embedding_function(" -- src
  episodic.py:685, episodic.py:1299, procedure_store.py:283, evolution_store.py:68, semantic.py:59
  (+ embeddings.py:149/169 = embed_text/compute_similarity — NOT swapped)
git grep -n "get_or_create_collection" -- src
  episodic:686/1301/1315; procedure_store:286/294/312; evolution_store:69; semantic:64/72/105; _episodic_probe.py:14 (docstring)

# model-name sources (4 metadata sites)
git grep -n "get_embedding_model_name" -- src
  episodic.py:1338, cognitive_services.py:418, procedure_store.py:284, semantic.py:60 (+ embeddings.py:91 def)

# migration-coherence anchors (untouched recovery path)
git grep -n "Embedding function conflict|__ef_conflict__|embedding_model" -- src   (episodic/procedure_store/semantic)

# CI + toggle name
sed -n '10,45p' .github/workflows/ci.yml   -> python-tests: L10, timeout L16, onnx-cache-clear L32-33, run L41; NO env: block
git grep -n "PROBOS_EMBEDDINGS|PROBOS_EMBEDDING_BACKEND|get_collection_embedding_function|get_active_embedding_model_name|LocalHashEmbedding" -- .   (all EMPTY -> free)
conftest precedent: tests/conftest.py:24 os.environ.setdefault("PROBOS_NATS_ENABLED","false"); PROBOS_DATA_DIR isolation :43-51; AD-682 chroma-path sanity :55

# previously-failing tests are STRUCTURAL (pass with lexical local EF)
tests/test_knowledge_store.py:81 TestEpisodicMemorySeed  (recent() time-ordered, no embeddings)
tests/test_semantic_knowledge.py:146 TestAgentIndexing   (count==1 / metadata / len(ids)>=1)
tests/test_ad584_recall_qa_fix.py:227 TestRecallPipelineIntegration (isinstance list; MagicMock collection) / :371 TestEmbeddingModelMigration (explicit model_name)
```

**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**
