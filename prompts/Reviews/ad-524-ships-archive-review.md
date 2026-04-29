# Review: AD-524 — Ship's Archive (Generational Knowledge Persistence)

**Verdict:** ⚠️ Conditional
**Headline:** OracleService doesn't accept `archive_store` — Section 3's SEARCH/REPLACE will fail.

## Required

1. **OracleService missing `archive_store` parameter.** Prompt asserts (Section 3) that `OracleService.__init__` accepts `archive_store`, but [oracle_service.py:51](src/probos/cognitive/oracle_service.py#L51) shows it accepts only `episodic_memory`, `records_store`, `knowledge_store`, `trust_network`, `hebbian_router`, `expertise_directory`. Either:
   - (a) Add `archive_store: Any = None` to OracleService `__init__` as part of this AD's scope, or
   - (b) Defer Oracle integration to a follow-up AD and ship ArchiveStore standalone for MVP.
2. **Caller audit.** No existing code calls `ArchiveStore.append()`. Specify in Tracking: who calls `append()`? Auto-trigger on agent reset, or manual via API? Without a caller, the feature is dark.

## Recommended

1. **Cloud-Ready Storage:** `ArchiveStore` uses `ConnectionFactory` correctly. The `_SCHEMA` SQL has `ESCAPE '\\'` on the `LIKE` clause — document the rationale (defense in depth) inline.
2. **Archive dir resolution.** Config field `db_path: str = ""` with "empty = `{platform_archive_dir}/archive.db`" — but the resolution helper is missing from the prompt. Add a `resolve_archive_db_path()` step to Section 4 or the wiring code won't pick the platform path.

## Nits

- SQL schema header comment says "AD-524" twice (lines 12, 18).
- `ArchiveEntry.metadata` defaults to `{}` — frozen dataclass makes this safe, but use `field(default_factory=dict)` for consistency with other ProbOS dataclasses.

## Verified

- `ConnectionFactory` Protocol at [protocols.py:223](src/probos/protocols.py#L223).
- `RecordsConfig` pattern at [config.py:683](src/probos/config.py#L683) matches.
- `OracleService` at [oracle_service.py:43](src/probos/cognitive/oracle_service.py#L43) — verified its current `__init__` signature does NOT accept `archive_store`.
- Startup wiring location after `qual_store` at [runtime.py:1310](src/probos/runtime.py#L1310) is correct.
