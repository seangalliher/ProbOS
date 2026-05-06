# AD-594d v1: Consultation Delivery Pipeline (Format + Adapters + Approval)

**Status:** ready for build
**Wave:** 79
**Closes:** GH issue #163
**Depends on:** AD-594a (shipped — Wave 44, `consultation/` package + `WorkspaceRegistry`)
**HEAD at draft:** `acf70a8`
**Baseline pytest:** 11498 → expected **+25 to +30** (target 11523-11528)

## Problem

`AD-594a` shipped the consultation workspace substrate with a placeholder `delivery.yaml` and an `outputs/` subdirectory that no code populates. Workspaces can transition `EXECUTING → COMPLETED → ARCHIVED`, but there is no pipeline that turns staged artifacts in `outputs/` into a real deliverable (markdown→HTML, JSON→report) or routes them anywhere outside the records repo. Three sibling AD-594 issues cite this as a dependency: AD-594b/c need the audit-trail surface, and the roadmap (`docs/development/roadmap.md:4842`) lists AD-594d as `*(planned, OSS)*`.

The issue body asks for: format transformation engine, `DeliveryAdapter` interface with `LocalFileAdapter` + `GitHubAdapter` built-in, captain approval gate, audit trail, partial-vs-atomic delivery, and revision cycle (`COMPLETED → CONSULTING/EXECUTING`).

## Solution (one v1)

Per Captain rule "don't defer unless no choice", ship the entire surface in one v1. PDF rendering is the only sub-feature deferred — kept behind the same Protocol seam pattern AD-594a used for `InputProcessor`/`PassthroughTextProcessor` (PDF/image input was deferred behind that seam too). Concrete transformers ship for the formats already covered by stdlib + project deps; PDF lands when a consumer actually needs it.

### New module: `src/probos/consultation/delivery.py`

**Public surface:**

```python
class FormatTransformer(typing.Protocol):
    def transform(self, content: str, *, source_path: str) -> tuple[str, str]: ...
    # Returns (transformed_content, new_filename). source_path is the workspace-relative
    # path (e.g. "outputs/report.md") used to derive an output filename and content-type.

class PassthroughTransformer:                # passthrough; identity
class MarkdownToHTMLTransformer:             # md → minimal HTML (stdlib-only renderer)
class JSONToMarkdownTransformer:             # JSON dict/list → markdown report

def build_format_transformer(name: str) -> FormatTransformer: ...
# Factory: "passthrough" | "markdown_to_html" | "json_to_markdown" | "" → passthrough.
# Unknown name → log WARNING + return passthrough (tier-2 log-and-degrade).

class DeliveryAdapter(typing.Protocol):
    name: str
    async def deliver(self, request: "DeliveryArtifact") -> "AdapterResult": ...

@dataclass(frozen=True)
class DeliveryArtifact:
    workspace_id: str
    source_path: str          # repo-relative, e.g. "consultations/<id>/outputs/x.md"
    target_filename: str      # adapter-side filename
    content: str              # post-transform content
    content_type: str         # "text/markdown" | "text/html" | "application/json"
    target_hint: str | None   # adapter-specific (LocalFileAdapter: dest dir; GitHubAdapter: "owner/repo:branch:path")

@dataclass(frozen=True)
class AdapterResult:
    success: bool
    delivered_uri: str        # "file:///abs/path" | "https://github.com/.../blob/sha/path" | ""
    error: str = ""

class LocalFileAdapter:
    """Writes to a filesystem destination OUTSIDE the records repo. Default ctor
    binds to ``allowed_roots: list[Path]`` — destinations must be under one of
    these roots (path-traversal prevention). Constructor-injection only."""
    name = "local_file"

class GitHubAdapter:
    """PUT https://api.github.com/repos/{owner}/{repo}/contents/{path}.
    Auth via env-resolved token (default ``GITHUB_TOKEN``; configurable via ctor).
    Constructor accepts an injected ``http_post`` callable for testability —
    default impl uses ``httpx.AsyncClient``."""
    name = "github"

@dataclass(frozen=True)
class DeliveryRequest:
    workspace_id: str
    source_paths: list[str]   # workspace-relative outputs ("outputs/x.md")
    adapter: str              # adapter name registered with the pipeline
    transformer: str = "passthrough"
    target_hint: str | None = None
    atomic: bool = True       # True → all-or-nothing; False → best-effort partial
    requires_approval: bool = False

@dataclass(frozen=True)
class DeliveryReceipt:
    delivery_id: str          # uuid4 hex[:12]
    workspace_id: str
    state: str                # "pending_approval" | "approved" | "delivered" | "failed" | "rolled_back"
    requested_at: float
    delivered_at: float | None
    adapter: str
    transformer: str
    items: list[dict[str, str]]  # [{source_path, target_filename, delivered_uri, error}]
    summary: str

class DeliveryPipeline:
    """Owns adapter registry + executes DeliveryRequests against a WorkspaceRegistry.

    Side effects on success / failure:
      - appends a journal entry on the workspace
      - writes the receipt as YAML to the workspace's ``delivery.yaml`` (overwrite per delivery_id;
        history maintained as a top-level ``deliveries: [...]`` list)
      - emits no events in v1 (kept narrow)

    Approval gate: ``requires_approval=True`` produces a ``pending_approval`` receipt and does NOT
    invoke the adapter. ``approve(workspace_id, delivery_id, *, agent_id)`` flips to "approved"
    and dispatches; ``reject(...)`` flips to "rolled_back" with a journal entry.
    """
    def __init__(
        self,
        registry: "WorkspaceRegistry",
        *,
        adapters: dict[str, DeliveryAdapter] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None: ...

    def register_adapter(self, adapter: DeliveryAdapter) -> None: ...      # replaces + WARNs on dup
    def list_adapters(self) -> list[str]: ...                              # sorted
    async def deliver(self, request: DeliveryRequest, *, agent_id: str = "captain") -> DeliveryReceipt: ...
    async def approve(self, workspace_id: str, delivery_id: str, *, agent_id: str = "captain") -> DeliveryReceipt | None: ...
    async def reject(self, workspace_id: str, delivery_id: str, *, agent_id: str = "captain", reason: str = "") -> DeliveryReceipt | None: ...
    async def list_deliveries(self, workspace_id: str) -> list[DeliveryReceipt]: ...
    async def revise(
        self,
        workspace_id: str,
        *,
        target: WorkspaceLifecycleState,    # CONSULTING | EXECUTING
        agent_id: str = "captain",
        reason: str = "",
    ) -> bool: ...
    # Calls workspace.transition_to(target). Allowed by AD-594d state-machine extension.
```

**Behavior rules (locked in tests):**

1. **Adapter dispatch.** `deliver()` reads each `source_path` via `RecordsStore.read_workspace_file`, pipes through the named transformer (one transformer per request — same transformer for every artifact in the batch), then calls `adapter.deliver()` for each transformed artifact. Missing source files → per-item error in the receipt; never raises.
2. **Atomic vs partial.** `atomic=True` (default): on the first per-item failure, abort remaining items, write the failed receipt with `state="failed"`, and leave items 1..i-1 marked `success=True` in the receipt but **rolled back** if the adapter exposes `rollback(delivered_uri)` — `LocalFileAdapter` rolls back by deleting the written file; `GitHubAdapter` does not roll back (records a journal note). `atomic=False`: deliver all items independently; receipt has per-item success flags; `state="delivered"` if any item succeeded, else `"failed"`.
3. **Approval gate.** `requires_approval=True`: receipt is `pending_approval`, no adapter call made. `approve()` re-runs the dispatch path and updates the same receipt id (state → `"delivered"` or `"failed"`). `reject()` sets state → `"rolled_back"`, no adapter call.
4. **Audit trail.** `delivery.yaml` is overwritten per call with the full deliveries list (chronological, newest last). Each `deliver()`/`approve()`/`reject()` also calls `workspace.append_journal()` with a one-line summary. Tier-2 log-and-degrade: journal failures are logged but never propagate.
5. **Revision cycle.** `pipeline.revise(workspace_id, target=CONSULTING)` and `target=EXECUTING` route through `workspace.transition_to(target)`. AD-594a's `_ALLOWED_TRANSITIONS` is extended (see Section 4) so `COMPLETED → CONSULTING` and `COMPLETED → EXECUTING` are allowed. Any other target via `revise()` returns False (delegated to the workspace state machine).
6. **Engineering principles.**
   - SOLID-S: `DeliveryPipeline` does only orchestration; adapters do only delivery; transformers do only conversion. No god class.
   - SOLID-D: pipeline accepts adapters via ctor injection; adapters accept their HTTP/file primitives via ctor injection.
   - Async hygiene: zero `asyncio.create_task()`; every awaited call has a returned future. `httpx.AsyncClient` lifecycle stays inside `GitHubAdapter` (one client per ctor; closed on `aclose()`).
   - Logging: every error path uses the codified format `"AD-594d: <what failed> on workspace=<id> adapter=<name>"`.
   - Type annotations: all public method signatures fully typed (Python 3.10 syntax).
   - Three-tier exceptions: tier-2 log-and-degrade for journal failures and for adapter-side errors during delivery; tier-3 propagate for `_safe_path` traversal violations on adapter writes.

### Section 0: New module — `src/probos/consultation/delivery.py`

Create the file with the public surface above. Implementation rules:

- **Imports:** stdlib only at module level except `yaml` (already a project dep, used by AD-594a). `httpx` import is **deferred to inside `GitHubAdapter.__init__` / `_default_http_post`** so the module does not pay the import cost when only `LocalFileAdapter` is used.
- **`MarkdownToHTMLTransformer`:** stdlib-only minimal renderer. Handle: ATX headings (`#`..`######`), bold (`**x**` → `<strong>`), italic (`*x*` → `<em>`), inline code (`` `x` `` → `<code>`), fenced code blocks (` ```...``` `), unordered lists (`- `), ordered lists (`1. `), paragraphs separated by blank lines, `\n\n` → `</p><p>`. Escape `<`, `>`, `&` in text segments. Wrap in `<!doctype html><html><body>...</body></html>`. Output filename: `*.md` → `*.html`; other extensions → `<basename>.html`. This is a docs-grade renderer — not GFM-complete; explicitly documented in the docstring.
- **`JSONToMarkdownTransformer`:** parse via `json.loads`. Render top-level dict as `# <key>\n\n<value>` sections (string values inline; nested dicts/lists rendered as fenced YAML for readability). Top-level list → enumerated bullets. Output filename: `*.json` → `*.md`. Parse errors → log warning, return `(content, source_path)` (pass-through fallback) — tier-2 log-and-degrade.
- **`LocalFileAdapter`:** ctor takes `allowed_roots: list[pathlib.Path]` (each `.resolve()`-ed at ctor). `deliver()` rejects any `target_hint` whose resolved abs-path does not have one of the roots as a prefix → `AdapterResult(success=False, error="path outside allowed_roots")`. `target_hint` semantic: directory; final path = `target_hint / target_filename`. `delivered_uri` = `file:///<abs path>` (forward slashes on Windows for URI shape stability). Implements `async def rollback(self, uri: str) -> bool` that deletes the file if it exists under an allowed root; missing file → True (idempotent); error → False + warning.
- **`GitHubAdapter`:** ctor takes `token_env: str = "GITHUB_TOKEN"`, `http_post: Callable | None = None`, `clock: Callable[[], float] = time.time`. Resolves token at delivery time via `os.environ.get(token_env, "")`. Empty token → `AdapterResult(success=False, error="no token in env <name>")` (tier-2 log-and-degrade; never raises). `target_hint` shape: `"owner/repo:branch:path/in/repo"` (3 colon-separated parts; `branch` may be empty for default). Body: `{"message": "AD-594d delivery", "branch": <branch or omitted>, "content": base64.b64encode(content.encode("utf-8")).decode()}`. URL: `https://api.github.com/repos/{owner}/{repo}/contents/{path}/{target_filename}`. Headers: `Authorization: Bearer <token>`, `Accept: application/vnd.github+json`, `X-GitHub-Api-Version: 2022-11-28`. `delivered_uri` from response JSON `content.html_url` on success; `error` from response body on non-2xx. No `rollback()` (Section 5 of AD-594d v1; documented).
- **`DeliveryPipeline.deliver`:** generates `delivery_id = uuid4().hex[:12]`. Reads + transforms + dispatches. On `requires_approval=True`, persists the `pending_approval` receipt and returns it without calling the adapter. Always calls `_persist_receipt(...)` and `workspace.append_journal(...)` at exit (success or failure). The same code path is reused by `approve()` (which loads the pending receipt, calls `_dispatch_one_or_batch(...)`, updates the receipt). `reject()` flips state and journals.
- **`_persist_receipt`:** reads existing `consultations/<id>/delivery.yaml`, parses YAML (placeholder text from AD-594a → empty deliveries list), upserts the receipt (match on `delivery_id`), and writes back via `RecordsStore.write_workspace_file`. Top-level shape: `{schema_version: 1, deliveries: [<receipt-dict>, ...]}`.

### Section 1: State-machine extension in `src/probos/consultation/workspace.py`

Extend `_ALLOWED_TRANSITIONS` so completed workspaces can re-enter CONSULTING (revision) or EXECUTING (mid-execution rework) on captain feedback:

```
SEARCH:
    WorkspaceLifecycleState.COMPLETED: frozenset({WorkspaceLifecycleState.ARCHIVED}),
REPLACE:
    # AD-594d v1: revision cycle — COMPLETED can return to CONSULTING (re-deliberation)
    # or EXECUTING (re-work plan items) on captain feedback before final ARCHIVE.
    WorkspaceLifecycleState.COMPLETED: frozenset({
        WorkspaceLifecycleState.ARCHIVED,
        WorkspaceLifecycleState.CONSULTING,
        WorkspaceLifecycleState.EXECUTING,
    }),
```

No other workspace.py changes. Existing AD-594a tests for the COMPLETED→ARCHIVED transition remain valid (the new transitions are additions; the existing one is preserved as a member of the frozenset).

### Section 2: Re-export from `src/probos/consultation/__init__.py`

Insert a `from probos.consultation.delivery import (...)` block after the existing `workspace` import, and extend `__all__` with the new symbols. Keep alphabetical ordering inside `__all__`. Update the module docstring's "NOT in v1 scope" sentence to remove `AD-594d` from the deferred list.

### Section 3: Pydantic config in `src/probos/config.py`

Add `ConsultationDeliveryConfig` adjacent to `ConsultationWorkspaceConfig` (after line 2082, before the `class CommunicationsConfig` definition):

```python
class ConsultationDeliveryConfig(BaseModel):
    """AD-594d v1: Consultation delivery pipeline.

    Default-True is intentional — pipeline construction is read-only on boot
    (registers built-in adapters into an in-memory dict; no IO). Workspaces
    consume the pipeline only when an agent calls ``runtime.consultation_delivery
    .deliver(...)``. Same precedent as ``ConsultationWorkspaceConfig``.
    """
    enabled: bool = True
    # Adapter enablement — operators can disable individual adapters without
    # disabling the pipeline. Disabled adapters are not registered.
    local_file_enabled: bool = True
    github_enabled: bool = True
    # LocalFileAdapter: list of allowed destination root paths (absolute or
    # tilde-expandable). Empty = LocalFileAdapter registered with no roots
    # (rejects every delivery with "no allowed_roots configured").
    local_file_allowed_roots: list[str] = Field(default_factory=list)
    # GitHubAdapter: env var name from which the token is read at delivery time.
    github_token_env: str = "GITHUB_TOKEN"
    # Default approval requirement — used when a request does not specify
    # requires_approval explicitly via the dataclass default of False.
    default_requires_approval: bool = False
```

Wire onto `SystemConfig` adjacent to `consultation_workspaces` (line 2442):

```
SEARCH:
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    process_chain_registry: ProcessChainRegistryConfig = Field(
REPLACE:
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
    consultation_delivery: ConsultationDeliveryConfig = Field(
        default_factory=ConsultationDeliveryConfig
    )  # AD-594d
    process_chain_registry: ProcessChainRegistryConfig = Field(
```

### Section 4: Finalize wirer in `src/probos/startup/finalize.py`

Add `_wire_consultation_delivery` adjacent to `_wire_consultation_workspaces` (insert immediately after the existing function, before `_wire_workspace_ontology`):

```python
def _wire_consultation_delivery(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594d v1: Wire DeliveryPipeline + built-in adapters.

    Requires ``runtime.consultation_workspaces`` (the registry from AD-594a).
    Tier-2 log-and-degrade: missing registry → no-op + INFO log. Adapter
    construction failures (e.g. LocalFileAdapter with bogus allowed_roots)
    are caught per-adapter so a single bad adapter does not disable the
    pipeline.
    """
    cfg = getattr(config, "consultation_delivery", None)
    if not cfg or not cfg.enabled:
        return False
    registry = getattr(runtime, "consultation_workspaces", None)
    if registry is None:
        logger.info(
            "AD-594d: consultation_workspaces unavailable; consultation_delivery skipped"
        )
        return False

    from pathlib import Path
    from probos.consultation.delivery import (
        DeliveryPipeline, GitHubAdapter, LocalFileAdapter,
    )

    pipeline = DeliveryPipeline(registry)

    if cfg.local_file_enabled:
        try:
            roots = [Path(r).expanduser().resolve() for r in cfg.local_file_allowed_roots]
            pipeline.register_adapter(LocalFileAdapter(allowed_roots=roots))
        except Exception:
            logger.warning(
                "AD-594d: LocalFileAdapter ctor failed; adapter not registered",
                exc_info=True,
            )
    if cfg.github_enabled:
        try:
            pipeline.register_adapter(GitHubAdapter(token_env=cfg.github_token_env))
        except Exception:
            logger.warning(
                "AD-594d: GitHubAdapter ctor failed; adapter not registered",
                exc_info=True,
            )

    runtime.consultation_delivery = pipeline  # public attribute (Wave 5 conv #1)
    logger.info(
        "AD-594d: DeliveryPipeline v1 initialized (adapters=%s, default_requires_approval=%s)",
        pipeline.list_adapters(), cfg.default_requires_approval,
    )
    return True
```

Invoke from `finalize_startup` immediately after `_wire_consultation_workspaces` (insert at line 980, between the `consultation_workspaces` and `workspace_ontology` blocks):

```python
    if _wire_consultation_delivery(runtime=runtime, config=config):
        logger.info("AD-594d: DeliveryPipeline v1 wired during finalization")
```

### Section 5: Tests — `tests/test_ad594d_delivery_pipeline.py`

**Test count target:** ≥25 (over the +25 floor). Distribute as below.

Use `pytest.fixture` + `pytest.mark.asyncio`. Build a `_FakeRecordsStore` stub with `repo_path`, `write_workspace_file`, `read_workspace_file`, `append_workspace_file` matching AD-594a shapes (mirror existing `tests/test_ad594a_consultation_workspace.py`'s helper if present; otherwise build a minimal one in this test file — do not modify the AD-594a test file). Build a real `WorkspaceRegistry` against the fake store; use `tmp_path` fixture for any filesystem destinations.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_format_factory_known_names_returns_concrete` | `build_format_transformer("passthrough")`, `"markdown_to_html"`, `"json_to_markdown"`, `""` each return concrete transformer; class names match. |
| 2 | `test_format_factory_unknown_name_warns_and_returns_passthrough` | `build_format_transformer("xyz")` → passthrough + caplog WARNING. |
| 3 | `test_passthrough_transformer_identity` | `("hello", "outputs/x.md")` → `("hello", "x.md")`. |
| 4 | `test_markdown_to_html_basic` | Input with `# H1`, `**bold**`, `*em*`, `` `code` ``, list, paragraph → output contains `<h1>H1</h1>`, `<strong>bold</strong>`, `<em>em</em>`, `<code>code</code>`, `<ul>`, `<p>`. Output filename `x.md` → `x.html`. |
| 5 | `test_markdown_to_html_escapes_html_in_text` | Input `"<script>alert(1)</script>"` → output contains `&lt;script&gt;` (no raw `<script>`). |
| 6 | `test_json_to_markdown_dict` | `{"title": "Foo", "summary": "Bar"}` → `"# title\n\nFoo\n\n# summary\n\nBar"` (or equivalent). Filename `data.json` → `data.md`. |
| 7 | `test_json_to_markdown_invalid_passthrough` | `"{not json"` → returns input unchanged + WARNING. |
| 8 | `test_local_file_adapter_writes_under_allowed_root` | `LocalFileAdapter([tmp_path])`, deliver `target_hint=str(tmp_path/"sub")`, `target_filename="r.md"`, content `"hi"` → file exists at `tmp_path/"sub"/"r.md"`, `delivered_uri.startswith("file:///")`, `success=True`. |
| 9 | `test_local_file_adapter_rejects_outside_root` | `target_hint=str(tmp_path / "..")` → `success=False`, error contains `"outside allowed_roots"`, no file written. |
| 10 | `test_local_file_adapter_rollback_idempotent` | Deliver then `rollback(uri)` → file gone. Second `rollback` → still True (idempotent). Rollback of URI outside roots → False + warning. |
| 11 | `test_github_adapter_no_token_returns_failure` | `GITHUB_TOKEN` unset (monkeypatch.delenv) → `AdapterResult(success=False, error="no token in env GITHUB_TOKEN")`. No HTTP call. |
| 12 | `test_github_adapter_happy_path_via_injected_post` | Inject stub `http_post` that returns `(201, {"content": {"html_url": "https://github.com/o/r/blob/abc/p/x.md"}})`. monkeypatch GITHUB_TOKEN. → `success=True`, `delivered_uri == "https://github.com/o/r/blob/abc/p/x.md"`. URL = `https://api.github.com/repos/o/r/contents/p/x.md`, `Authorization: Bearer <tok>` header sent. Body has base64 `content`. |
| 13 | `test_github_adapter_4xx_returns_error` | Stub returns `(422, {"message": "branch not found"})` → `success=False`, error contains `"branch not found"`. No exception. |
| 14 | `test_github_adapter_target_hint_parse_three_segments` | `target_hint="owner/repo:main:docs"` → URL contains `/repos/owner/repo/contents/docs/...`, body contains `"branch": "main"`. |
| 15 | `test_pipeline_register_and_list_adapters` | Register two adapters with same name → second replaces first + WARNING. `list_adapters()` returns sorted names. |
| 16 | `test_pipeline_deliver_writes_receipt_and_journal` | Stage an output via `workspace.add_output(...)`, call `pipeline.deliver(DeliveryRequest(...))` with a stub adapter returning success → receipt has `state="delivered"`, `delivery.yaml` parses to `{schema_version: 1, deliveries: [<receipt>]}`, `journal.md` contains a delivery entry. |
| 17 | `test_pipeline_deliver_missing_source_yields_per_item_error` | Request includes a non-existent `outputs/missing.md` → receipt's items array has the failed entry; receipt `state=="failed"` (atomic), no adapter call for the missing item. |
| 18 | `test_pipeline_deliver_atomic_rolls_back_first_success_on_second_failure` | Stub adapter fails on second item; first item was a `LocalFileAdapter` write that exists. After deliver, file is gone (rollback called). Receipt has `state="failed"`, item 1 marked rolled-back, item 2 marked failed. |
| 19 | `test_pipeline_deliver_partial_continues_on_failure` | `atomic=False`. Stub fails on item 2. Item 1 file remains. Receipt `state="delivered"` (partial). |
| 20 | `test_pipeline_approval_gate_pending` | `requires_approval=True` → receipt `state="pending_approval"`, adapter NOT called, `delivery.yaml` contains the pending receipt, journal entry written. |
| 21 | `test_pipeline_approve_dispatches` | Pending receipt → `approve(workspace_id, delivery_id)` → adapter called, receipt updated to `state="delivered"`, same `delivery_id`. |
| 22 | `test_pipeline_reject_marks_rolled_back` | Pending → `reject(...)` → state `"rolled_back"`, adapter NOT called, journal entry "rejected: <reason>". |
| 23 | `test_pipeline_approve_unknown_returns_none` | `approve(unknown_workspace, "xxxxxxxxxxxx")` → None, no exception. |
| 24 | `test_pipeline_revise_to_consulting_after_completed` | Workspace transitioned through INITIATED→…→COMPLETED. `pipeline.revise(workspace_id, target=CONSULTING)` → True; `workspace.lifecycle_state == CONSULTING`. |
| 25 | `test_pipeline_revise_to_executing_after_completed` | Same as #24 but target=EXECUTING. |
| 26 | `test_pipeline_revise_invalid_target_returns_false` | `revise(target=INITIATED)` from COMPLETED → False (state machine rejects). Workspace stays COMPLETED. |
| 27 | `test_workspace_completed_to_archived_still_allowed` | AD-594a regression: COMPLETED → ARCHIVED still works after the `_ALLOWED_TRANSITIONS` extension. |
| 28 | `test_finalize_wirer_constructs_pipeline_with_both_adapters` | Build a real `SystemConfig()` (defaults), monkey-patch `LocalFileAdapter` ctor to accept the empty `allowed_roots=[]`, call `_wire_consultation_delivery` against a SimpleNamespace runtime with `consultation_workspaces=WorkspaceRegistry(...)`. Assert `runtime.consultation_delivery.list_adapters() == ["github", "local_file"]`. |
| 29 | `test_finalize_wirer_no_registry_skips` | Runtime without `consultation_workspaces` attribute → wirer returns False, INFO log. |
| 30 | `test_finalize_wirer_disabled_config_skips` | `ConsultationDeliveryConfig(enabled=False)` → wirer returns False. |

Use `monkeypatch` for env vars. Use `unittest.mock.AsyncMock` for the injected `http_post`. No real network.

### Section 6: PROGRESS.md entry

Insert a new entry at the top of the "Recent Builder Closures" block (immediately above the Wave 78 entry from `acf70a8`). Keep the same paragraph style. One paragraph summarizing: AD-594d v1 ships full-scope (no deferral); module shape; state-machine extension; config + wirer; test count; PDF deferral note (behind FormatTransformer Protocol seam, mirroring AD-594a's InputProcessor pattern); engineering principles compliance.

### Section 7: docs/development/roadmap.md status flip

Line 4842:

```
SEARCH:
> - **AD-594d: Delivery Pipeline** *(planned, OSS)* —
REPLACE:
> - **AD-594d: Delivery Pipeline** *(complete — Wave 79, OSS; PDF rendering deferred behind FormatTransformer Protocol seam pending consumer)* —
```

(Preserve all descriptive prose after the tag.)

### Section 8: DECISIONS.md AD-594d v1 entry

Append a new entry at the top of the file (above the AD-594a entry at line 148), mirroring the AD-594a entry shape. Keep the entry concise (Problem / Decision / Consequences). Reference: HEAD `acf70a8`, baseline 11498, +25..+30 delta, closes #163.

## What this AD does NOT change

- **No PDF rendering.** The `FormatTransformer` Protocol seam ships in v1 — a `MarkdownToPDFTransformer` lands when a consumer requires it (and brings its own optional dep, e.g. `weasyprint`, in a separate AD). Same pattern AD-594a used for `InputProcessor` (PDF/image input deferred behind the Protocol). This is a Protocol-seam deferral, not a feature deferral.
- **No event emission.** `EventType.DELIVERY_*` events are out of scope — the receipt + journal pair is the v1 audit trail. Adding events is a separate AD when an event consumer surfaces.
- **No HXI surface.** No new `/api/consultation-delivery/*` REST endpoints, no HXI panel. AD-594d v1 is a service surface for AD-594b/c and future agentic workflows; consumer routing is the consumer's AD.
- **No commercial adapters.** Loop, OneDrive/SharePoint, Teams, Email-via-Graph, Slack adapters are explicitly commercial-tier (per issue #163 body). The OSS surface is Protocol + LocalFileAdapter + GitHubAdapter only. The wave-plan + dispatch + DECISIONS entry contain ZERO commercial language.
- **No ChannelAdapter consolidation.** The existing `ChannelAdapter` ABC at `src/probos/channels/base.py:34` is a different surface (real-time conversational channels). `DeliveryAdapter` is a Protocol for one-shot artifact delivery; deduplication is not v1 scope.
- **No `WorkItemStore` integration.** AD-594c will plumb work items into delivery; AD-594d v1 only delivers files staged in `outputs/`. Work-item-driven delivery is AD-594c's surface.
- **No `requires_consensus` IntentDescriptor.** AD-594d is invoked as a service (`runtime.consultation_delivery.deliver(...)`) not via IntentBus. The captain approval gate (`requires_approval=True` + `pipeline.approve(...)`) is the v1 in-pipeline equivalent. If a future Intent wraps this surface, it must set `requires_consensus=True` per the standing rule.
- **No new EventType.** Events stay narrow per the no-event-emission rule above.
- **No deletion of AD-594a placeholder behavior.** `WorkspaceRegistry.create()` still writes the empty `delivery.yaml` placeholder at AD-594a workspace creation; AD-594d's `_persist_receipt` overwrites it on the first delivery. Workspaces that never invoke delivery keep the placeholder forever — same shape as today.
- **No GitHub rate-limit handling.** GitHubAdapter does not implement adaptive backoff (HttpFetchAgent's `_domain_state` is HttpFetchAgent-internal class state and not reusable here without architectural surgery). Rate-limit failures surface as 4xx errors via the standard `error` field. AD-594d-followup if it becomes operationally relevant.

## Architect calls (DLogs)

1. **`FormatTransformer` ships, PDF backend deferred.** Captain rule "don't defer unless no choice" satisfied: the *interface* ships and is open for extension; only the PDF *backend* is deferred behind a stable Protocol seam, mirroring AD-594a's `InputProcessor` precedent. PDF rendering needs a heavyweight optional dep (`weasyprint` ~50MB, system-level libs) and there is no present-day consumer; landing it speculatively would either bloat OSS or ship a fragile shim. Forcing function: first AD-594b/c/captain workflow that requires `application/pdf` Content-Type for an external recipient.
2. **Approval gate is in-pipeline, not Intent-level.** `requires_consensus=True` is for IntentMessage handlers; the pipeline is invoked as a service. Sync flag + `approve()`/`reject()` is the equivalent. If/when a `consultation_deliver` Intent wraps this for designed-agent invocation, that Intent will set `requires_consensus=True` per the standing rule — out of scope here.
3. **GitHubAdapter via REST API, not subprocess.** `subprocess(["gh", "api", ...])` would be simpler but introduces a binary dep + sandbox-escape surface for designed agents. Pure HTTP via httpx + env-resolved token is the reviewable path. `http_post` ctor injection makes tests deterministic without `httpx.MockTransport` boilerplate.
4. **`LocalFileAdapter` enforces `allowed_roots`.** A delivery surface that writes outside the records repo is a privilege-escalation vector. Constructor-injected allowed_roots + path-traversal check at delivery time mirrors the same pattern AD-594a used in `RecordsStore._safe_path`. Defaults to empty (rejects every delivery) when operators don't configure roots — fail-safe.
5. **Atomic rollback is best-effort.** `LocalFileAdapter` rolls back via `os.unlink`; `GitHubAdapter` does NOT roll back (would require a second commit deleting the file, which is a different audit shape). The receipt records this asymmetry per item; the journal entry surfaces "rolled-back-where-supported" semantics. Adding deletion-rollback to GitHubAdapter is AD-594d-followup if operationally needed.
6. **Audit lives in `delivery.yaml` + `journal.md`, not a new collection.** AD-594a already provisioned `delivery.yaml` and the journal; reusing both keeps audit data in the workspace's git-backed history without introducing a new persistence layer. The receipt is the durable record; the journal is the human-readable log. Same "two-projection" pattern AD-594a ships for manifest + journal.
7. **`revise()` delegates to `workspace.transition_to()`.** The state-machine extension (Section 1) is the single source of truth for "what's a valid transition"; the pipeline does not duplicate the rules. `revise(target=INITIATED)` returns False because the state machine rejects it — pipeline doesn't pre-check.
8. **No `EventType.DELIVERY_*`.** Adding events without a consumer would be speculative scope. AD-594b/c will land event consumers if the audit surface needs to be observable from outside the workspace; that AD adds the events. v1 stays narrow.

## Tracking

Update on close:

- `PROGRESS.md` — Wave 79 entry (Section 6 of this prompt).
- `docs/development/roadmap.md` — line 4842 status flip (Section 7).
- `DECISIONS.md` — AD-594d v1 entry (Section 8).
- `prompts/wave-plan.yaml` — id `"79"` entry (Captain workflow, see WAVE-79-DISPATCH.md).
- GH issue #163 — close with verify-first evidence + commit hash.

## Acceptance criteria

1. New module `src/probos/consultation/delivery.py` exists with the public surface above.
2. `_ALLOWED_TRANSITIONS` extended in `workspace.py`.
3. `consultation/__init__.py` re-exports + `__all__` updated; module docstring's "NOT in v1 scope" no longer lists AD-594d.
4. `ConsultationDeliveryConfig` Pydantic model + `SystemConfig.consultation_delivery` field present.
5. `_wire_consultation_delivery` finalize wirer present, invoked from `finalize_startup`.
6. `tests/test_ad594d_delivery_pipeline.py` has ≥25 tests, all passing.
7. **Pytest full gate** `pytest tests/ -q -n 4 --dist=loadfile` — collection ≥ 11523 (delta ≥ +25 from baseline 11498), all green. Existing AD-594a tests pass unchanged.
8. **Phantom-API pre-check** on this prompt body returns 0 NEW phantoms (intra-prompt-introduction FPs for `DeliveryAdapter`, `DeliveryPipeline`, `LocalFileAdapter`, `GitHubAdapter`, `FormatTransformer`, `ConsultationDeliveryConfig`, `_wire_consultation_delivery` are all expected — they ARE the migration).
9. PROGRESS.md entry, roadmap.md status flip, DECISIONS.md entry, wave-plan.yaml id "79" entry all present.
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.** Specifically: SOLID-S/D, Liskov (adapters honor `DeliveryAdapter` Protocol; transformers honor `FormatTransformer`), three-tier exception handling (tier-2 log-and-degrade for journal/receipt/adapter errors; tier-3 propagate for `_safe_path` violations), full type annotations on public surface, async hygiene (no fire-and-forget tasks; httpx client lifecycle owned by adapter), structured logging with `"AD-594d: <what> on workspace=<id>"` format, no commercial leak, no emoji, no `requires_consensus` bypass on the in-pipeline equivalent.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  acf70a87b1cf08e63c01e7d39a1bf2cae26a4c98

# AD-594a substrate (the dependency):
src/probos/consultation/__init__.py:1-9
  Module docstring lists AD-594b/c/d as "NOT in v1 scope".
src/probos/consultation/workspace.py:43-58
  WorkspaceLifecycleState IntEnum (7 values) + _ALLOWED_TRANSITIONS dict.
src/probos/consultation/workspace.py:55
  WorkspaceLifecycleState.COMPLETED: frozenset({WorkspaceLifecycleState.ARCHIVED}),
src/probos/consultation/workspace.py:185-191
  add_output(filename, content, *, agent_id="captain") writes to outputs/<filename>.
src/probos/consultation/workspace.py:300-310
  WorkspaceRegistry.create() writes empty delivery.yaml placeholder at workspace creation.
src/probos/knowledge/records_store.py:890-940
  RecordsStore.write_workspace_file / read_workspace_file / append_workspace_file (raw, no
  frontmatter); _safe_path traversal protection.
src/probos/knowledge/records_store.py:64-65
  RecordsStore.repo_path property returns Path.

# Config + wirer integration anchors:
src/probos/config.py:2072-2082
  ConsultationWorkspaceConfig (default-True precedent, docstring template).
src/probos/config.py:2442-2444
  SystemConfig.consultation_workspaces field (insertion anchor for new field).
src/probos/startup/finalize.py:631-660
  _wire_consultation_workspaces (signature + structure template).
src/probos/startup/finalize.py:978-980
  consultation_workspaces wirer invocation point (insertion anchor for new wirer call).

# Project deps:
pyproject.toml:29
  "httpx>=0.27"  → already a hard dep; safe to import in GitHubAdapter.
src/probos/agents/http_fetch.py:34-300
  HttpFetchAgent uses httpx.AsyncClient — pattern reference for async http.

# Roadmap line for status flip:
docs/development/roadmap.md:4842
  > - **AD-594d: Delivery Pipeline** *(planned, OSS)* — Format transformation engine ...

# Test pattern reference:
tests/test_ad594a_consultation_workspace.py
  Existing AD-594a test file (do not modify; new file is sibling).

# Sibling adapter precedents (NOT extended in v1; reference only):
src/probos/channels/base.py:34
  class ChannelAdapter(ABC) — different surface (real-time channels).
src/probos/tools/adapters.py:20
  class InfraServiceAdapter — different surface (tool execution).

# GH issue body:
gh issue view 163
  Title: AD-594d: Delivery Pipeline — Format Transformation & Output Routing
  Scope: format transform, DeliveryAdapter + LocalFile + GitHub, captain approval,
         confirmation + audit, partial vs atomic, revision cycle.
  Commercial extension: Loop / OneDrive / Teams / Email / Slack — explicitly commercial.
  OSS scope: Protocol + LocalFileAdapter + GitHubAdapter.

# AD numbering:
Highest AD in trackers (PROGRESS.md + DECISIONS.md + decisions-era-*.md):
  Stem max = AD-696 (W72 closed); AD-594d is sub-stem of AD-594, no collision.
```

Every concrete claim in this prompt maps to a grep hit above. Phantom-API pre-check on this prompt body: expected ALL FPs from intra-prompt-introduction (DeliveryAdapter / DeliveryPipeline / LocalFileAdapter / GitHubAdapter / FormatTransformer / ConsultationDeliveryConfig / _wire_consultation_delivery / DeliveryArtifact / DeliveryRequest / DeliveryReceipt / AdapterResult / PassthroughTransformer / MarkdownToHTMLTransformer / JSONToMarkdownTransformer / build_format_transformer); 0 NEW phantoms.
