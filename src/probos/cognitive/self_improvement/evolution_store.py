"""AD-482d v1: Evolution Store -- append-only lessons learned with time-decay.

ChromaDB-backed semantic store mirroring `EpisodicMemory` construction shape,
but on a separate collection (``self_improvement_lessons``) and with a
time-decay weighting layered over cosine similarity.

Tier-2 log-and-degrade: when ``chroma_client`` is None the store keeps lessons
in an in-memory list and serves recall via plain substring matching. The
public API contract is identical in both modes.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_COPY_PAGE_SIZE = 200
_TEMP_NAME_ATTEMPTS = 32
_TXN_METADATA_KEYS = frozenset(
    {
        "bf662_canonical_name",
        "bf662_owner",
        "bf662_txn",
        "bf662_role",
        "bf662_state",
        "bf662_source_count",
    }
)
_TXN_IDENTITY_KEYS = _TXN_METADATA_KEYS - {"bf662_state"}
_VALID_ROLE_STATES = frozenset(
    {
        ("backup", "backup"),
        ("shadow", "copying"),
        ("shadow", "ready"),
        ("failed", "failed"),
    }
)
_VALID_CANONICAL_ROLE_STATES = frozenset(
    {
        ("backup", "backup"),
        ("shadow", "ready"),
    }
)


@dataclass(frozen=True)
class _TransactionMetadata:
    txn: str
    role: str
    state: str
    source_count: int


@dataclass(frozen=True)
class _OwnedTemporary:
    name: str
    role: str
    txn: str
    state: str
    source_count: int
    collection: Any
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Lesson:
    """One append-only lesson record."""

    id: str
    category: str  # "approved", "rejected", "pivot", custom
    summary: str
    source_proposal_id: str
    outcome: str
    timestamp: float
    payload: dict[str, Any] = field(default_factory=dict)


class EvolutionStore:
    """Append-only lessons store with time-decay recall."""

    def __init__(
        self,
        *,
        chroma_client: Any = None,
        chroma_path: str | Path | None = None,
        collection_name: str = "self_improvement_lessons",
        clock: Callable[[], float] = time.time,
        half_life_seconds: float = 2592000.0,  # 30 days
        event_emit_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._injected_client = chroma_client
        self._client = chroma_client
        self._chroma_path = Path(chroma_path) if chroma_path is not None else None
        self._owns_client = False
        self._collection_name = collection_name
        self._clock = clock
        self._half_life = max(1.0, half_life_seconds)
        self._emit = event_emit_fn
        self._collection: Any = None
        self._fallback: list[Lesson] = []  # used when chroma is None

    def start(self) -> None:
        """Open the chroma collection. Tier-2 log-and-degrade on failure.

        Safe to call multiple times -- idempotent.
        """
        if self._collection is not None:
            return
        if self._client is None:
            if self._injected_client is not None:
                self._client = self._injected_client
            elif self._chroma_path is not None:
                import chromadb

                self._client = chromadb.PersistentClient(path=str(self._chroma_path))
                self._owns_client = True
            else:
                return
        try:
            from probos.knowledge.embeddings import (
                get_active_embedding_backend_id,
                get_active_embedding_model_name,
                get_collection_embedding_function,
            )

            embedding_function = get_collection_embedding_function()
            model_name = get_active_embedding_model_name()
            backend_id = get_active_embedding_backend_id()
            self._recover_interrupted_state(
                embedding_function=embedding_function,
                model_name=model_name,
                backend_id=backend_id,
            )
            names = self._collection_names()
            if self._collection_name not in names:
                self._collection = self._client.create_collection(
                    name=self._collection_name,
                    embedding_function=embedding_function,
                    metadata={
                        "hnsw:space": "cosine",
                        "embedding_model": model_name,
                        "embedding_backend_id": backend_id,
                        "bf662_state": "stable",
                    },
                )
                return

            transition_required = False
            try:
                active = self._client.get_collection(
                    name=self._collection_name,
                    embedding_function=embedding_function,
                )
            except ValueError as exc:
                if "Embedding function conflict" not in str(exc):
                    raise
                transition_required = True
                active = None

            if active is not None:
                metadata = active.metadata or {}
                transition_required = transition_required or (
                    metadata.get("embedding_model", "") != model_name
                    or metadata.get("embedding_backend_id", "") != backend_id
                    or metadata.get("bf662_state", "") != "stable"
                )
                if not transition_required:
                    self._collection = active
                    return

            source = self._raw_collection(self._collection_name)
            self._transition_collection(
                source=source,
                embedding_function=embedding_function,
                model_name=model_name,
                backend_id=backend_id,
            )
        except Exception:
            logger.warning(
                "BF-662: failed to open or recover evolution collection %r; "
                "on-disk state is preserved and this run will use in-memory fallback",
                self._collection_name,
                exc_info=True,
            )
            self._collection = None
            if self._owns_client and self._client is not None:
                try:
                    self._client.close()
                except Exception:
                    logger.warning(
                        "BF-662: failed to close owned EvolutionStore client after "
                        "degraded start; OS cleanup is the fallback",
                        exc_info=True,
                    )
                self._client = None
                self._owns_client = False

    def stop(self) -> None:
        """Release owned Chroma resources and permit a later restart."""
        self._collection = None
        if self._owns_client and self._client is not None:
            try:
                self._client.close()
            except Exception:
                logger.warning(
                    "BF-662: failed to close owned EvolutionStore Chroma client; "
                    "references are being cleared and shutdown will continue",
                    exc_info=True,
                )
        self._client = None
        self._owns_client = False

    @property
    def _owner(self) -> str:
        return hashlib.sha256(self._collection_name.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
        return {
            key: value
            for key, value in (metadata or {}).items()
            if not key.startswith("hnsw:")
        }

    def _collection_names(self) -> set[str]:
        return {collection.name for collection in self._client.list_collections()}

    def _raw_collection(self, name: str) -> Any:
        return self._client.get_collection(name=name, embedding_function=None)

    def _temporary_name(self, role: str, txn: str) -> str:
        prefix = "s" if role in {"shadow", "failed"} else "b"
        return f"bf662e-{prefix}-{self._owner}-{txn}"

    def _allocate_transaction_names(self) -> tuple[str, str, str]:
        names = self._collection_names()
        for _ in range(_TEMP_NAME_ATTEMPTS):
            txn = uuid.uuid4().hex[:16]
            shadow_name = self._temporary_name("shadow", txn)
            backup_name = self._temporary_name("backup", txn)
            if shadow_name not in names and backup_name not in names:
                return txn, shadow_name, backup_name
        raise RuntimeError(
            "BF-662 could not allocate collision-free evolution transaction names"
        )

    def _parse_transaction_metadata(
        self,
        *,
        name: str,
        metadata: dict[str, Any],
    ) -> _TransactionMetadata | None:
        """Parse one exact BF-662 transaction marker without coercion."""
        if not _TXN_METADATA_KEYS.issubset(metadata):
            return None
        canonical_name = metadata.get("bf662_canonical_name")
        owner = metadata.get("bf662_owner")
        txn = metadata.get("bf662_txn")
        role = metadata.get("bf662_role")
        state = metadata.get("bf662_state")
        source_count = metadata.get("bf662_source_count")
        if (
            type(canonical_name) is not str
            or canonical_name != self._collection_name
            or type(owner) is not str
            or owner != self._owner
            or type(txn) is not str
            or len(txn) != 16
            or any(character not in "0123456789abcdef" for character in txn)
            or type(role) is not str
            or type(state) is not str
            or (role, state) not in _VALID_ROLE_STATES
            or type(source_count) is not int
            or source_count < 0
        ):
            return None
        if name == self._collection_name:
            if (role, state) not in _VALID_CANONICAL_ROLE_STATES:
                return None
        elif name != self._temporary_name(role, txn):
            return None
        return _TransactionMetadata(
            txn=txn,
            role=role,
            state=state,
            source_count=source_count,
        )

    def _canonical_transaction_metadata(
        self,
        canonical: Any,
    ) -> _TransactionMetadata | None:
        metadata = dict(canonical.metadata or {})
        has_transaction_marker = bool(
            _TXN_IDENTITY_KEYS.intersection(metadata)
            or metadata.get("bf662_state")
            in {"backup", "copying", "ready", "failed"}
        )
        if not has_transaction_marker:
            return None
        parsed = self._parse_transaction_metadata(
            name=self._collection_name,
            metadata=metadata,
        )
        if parsed is None:
            raise RuntimeError(
                "BF-662 canonical transaction metadata is incomplete or invalid; "
                "temporary collections are preserved"
            )
        return parsed

    def _owned_temporary(self, name: str) -> _OwnedTemporary | None:
        shadow_prefix = f"bf662e-s-{self._owner}-"
        backup_prefix = f"bf662e-b-{self._owner}-"
        if not (name.startswith(shadow_prefix) or name.startswith(backup_prefix)):
            return None
        collection = self._raw_collection(name)
        metadata = dict(collection.metadata or {})
        parsed = self._parse_transaction_metadata(name=name, metadata=metadata)
        if parsed is None:
            return None
        return _OwnedTemporary(
            name=name,
            role=parsed.role,
            txn=parsed.txn,
            state=parsed.state,
            source_count=parsed.source_count,
            collection=collection,
            metadata=metadata,
        )

    def _matching_temporary_names(self, names: set[str]) -> set[str]:
        shadow_prefix = f"bf662e-s-{self._owner}-"
        backup_prefix = f"bf662e-b-{self._owner}-"
        return {
            name
            for name in names
            if name.startswith(shadow_prefix) or name.startswith(backup_prefix)
        }

    def _discover_owned_temporaries(
        self,
        names: set[str] | None = None,
    ) -> list[_OwnedTemporary]:
        owned: list[_OwnedTemporary] = []
        for name in sorted(names if names is not None else self._collection_names()):
            temporary = self._owned_temporary(name)
            if temporary is not None:
                owned.append(temporary)
        return owned

    @staticmethod
    def _read_rows_page(
        collection: Any,
        *,
        offset: int,
        limit: int = _COPY_PAGE_SIZE,
    ) -> list[tuple[str, str, dict[str, Any]]]:
        result = collection.get(
            limit=limit,
            offset=offset,
            include=["documents", "metadatas"],
        )
        ids = (result or {}).get("ids") or []
        documents = (result or {}).get("documents") or []
        metadatas = (result or {}).get("metadatas") or []
        if len(documents) != len(ids) or len(metadatas) != len(ids):
            raise RuntimeError("evolution row page has incomplete persisted fields")
        rows: list[tuple[str, str, dict[str, Any]]] = []
        for row_id, document, metadata in zip(
            ids, documents, metadatas, strict=True
        ):
            if not isinstance(row_id, str) or not row_id:
                raise RuntimeError("evolution row lacks an ID required for migration")
            if not isinstance(document, str):
                raise RuntimeError(
                    f"evolution row {row_id!r} lacks a document required for re-embedding"
                )
            if not isinstance(metadata, dict):
                raise RuntimeError(
                    f"evolution row {row_id!r} lacks its persisted metadata dictionary"
                )
            rows.append((row_id, document, dict(metadata)))
        return rows

    @staticmethod
    def _rows_by_id(
        rows: list[tuple[str, str, dict[str, Any]]],
    ) -> dict[str, tuple[str, dict[str, Any]]]:
        return {row_id: (document, metadata) for row_id, document, metadata in rows}

    def _read_rows_by_ids(
        self,
        collection: Any,
        ids: list[str],
    ) -> dict[str, tuple[str, dict[str, Any]]]:
        result = collection.get(ids=ids, include=["documents", "metadatas"])
        result_ids = (result or {}).get("ids") or []
        documents = (result or {}).get("documents") or []
        metadatas = (result or {}).get("metadatas") or []
        if len(documents) != len(result_ids) or len(metadatas) != len(result_ids):
            raise RuntimeError("evolution readback omitted persisted fields")
        rows = [
            (row_id, document, dict(metadata))
            for row_id, document, metadata in zip(
                result_ids, documents, metadatas, strict=True
            )
            if isinstance(row_id, str)
            and isinstance(document, str)
            and isinstance(metadata, dict)
        ]
        if len(rows) != len(result_ids):
            raise RuntimeError("evolution readback returned malformed rows")
        return self._rows_by_id(rows)

    def _prove_raw_readable(self, collection: Any) -> tuple[int, str]:
        expected_count = collection.count()
        seen = 0
        first_document = ""
        offset = 0
        while True:
            rows = self._read_rows_page(collection, offset=offset)
            if not rows:
                break
            if not first_document:
                first_document = rows[0][1]
            seen += len(rows)
            if len(rows) < _COPY_PAGE_SIZE:
                break
            offset += _COPY_PAGE_SIZE
        if seen != expected_count:
            raise RuntimeError(
                f"evolution raw-read proof expected {expected_count} rows, read {seen}"
            )
        return expected_count, first_document

    def _prove_recorded_count(
        self,
        collection: Any,
        *,
        expected_count: int,
        label: str,
    ) -> tuple[int, str]:
        actual_count, first_document = self._prove_raw_readable(collection)
        if actual_count != expected_count:
            raise RuntimeError(
                f"{label} recorded {expected_count} rows but contains {actual_count}"
            )
        return actual_count, first_document

    def _verify_exact_rows(
        self,
        authority: Any,
        candidate: Any,
        *,
        expected_count: int,
    ) -> None:
        if authority.count() != expected_count or candidate.count() != expected_count:
            raise RuntimeError("evolution copy count changed during exact proof")
        offset = 0
        verified = 0
        while True:
            rows = self._read_rows_page(authority, offset=offset)
            if not rows:
                break
            ids = [row[0] for row in rows]
            if self._read_rows_by_ids(candidate, ids) != self._rows_by_id(rows):
                raise RuntimeError("evolution candidate differs from authoritative rows")
            verified += len(rows)
            if len(rows) < _COPY_PAGE_SIZE:
                break
            offset += _COPY_PAGE_SIZE
        if verified != expected_count:
            raise RuntimeError(
                f"evolution exact proof expected {expected_count} rows, verified {verified}"
            )

    def _prove_active_candidate(
        self,
        *,
        authority: Any,
        candidate: Any,
        expected_count: int,
        model_name: str,
        backend_id: str,
    ) -> None:
        metadata = candidate.metadata or {}
        if (
            metadata.get("embedding_model") != model_name
            or metadata.get("embedding_backend_id") != backend_id
            or metadata.get("bf662_state") != "ready"
        ):
            raise RuntimeError("evolution candidate active identity proof failed")
        self._verify_exact_rows(
            authority,
            candidate,
            expected_count=expected_count,
        )
        if expected_count:
            first_rows = self._read_rows_page(authority, offset=0, limit=1)
            result = candidate.query(
                query_texts=[first_rows[0][1]],
                n_results=1,
            )
            if not (result.get("ids") and result["ids"][0]):
                raise RuntimeError("evolution candidate text-query proof returned no rows")

    def _finalize_stable(
        self,
        collection: Any,
        *,
        model_name: str,
        backend_id: str,
    ) -> None:
        metadata = {
            key: value
            for key, value in self._safe_metadata(collection.metadata).items()
            if key not in _TXN_METADATA_KEYS
        }
        collection.modify(
            metadata={
                **metadata,
                "embedding_model": model_name,
                "embedding_backend_id": backend_id,
                "bf662_state": "stable",
            }
        )

    def _clear_transaction_markers(self, collection: Any) -> None:
        metadata = {
            key: value
            for key, value in self._safe_metadata(collection.metadata).items()
            if key not in _TXN_METADATA_KEYS
        }
        if not metadata:
            metadata = {"bf662_recovery": "source-restored"}
        collection.modify(metadata=metadata)

    def _assert_owned_temporary(
        self,
        name: str,
        *,
        role: str,
        txn: str,
    ) -> _OwnedTemporary:
        current = self._owned_temporary(name)
        if current is None or current.role != role or current.txn != txn:
            raise RuntimeError(
                f"evolution temporary ownership changed before touching {name!r}"
            )
        return current

    def _prove_owned_authority(
        self,
        temporary: _OwnedTemporary,
    ) -> _OwnedTemporary:
        current = self._assert_owned_temporary(
            temporary.name,
            role=temporary.role,
            txn=temporary.txn,
        )
        self._prove_recorded_count(
            current.collection,
            expected_count=current.source_count,
            label=f"evolution {current.role} authority {current.name!r}",
        )
        return current

    def _require_unique_backup_coherence(
        self,
        expected_backup: _OwnedTemporary,
    ) -> tuple[_OwnedTemporary, list[_OwnedTemporary]]:
        """Re-prove one backup and every owned temporary before mutation."""
        names = self._collection_names()
        matching_names = self._matching_temporary_names(names)
        temporaries = self._discover_owned_temporaries(names)
        unowned_names = matching_names - {
            temporary.name for temporary in temporaries
        }
        if unowned_names:
            raise RuntimeError(
                "BF-662 recovery found partially owned temporary collections; "
                "disk state is untouched"
            )
        backups = [temporary for temporary in temporaries if temporary.role == "backup"]
        if len(backups) != 1:
            raise RuntimeError(
                "BF-662 recovery no longer has one unique backup authority; "
                "disk state is untouched"
            )
        backup = backups[0]
        if (
            backup.name != expected_backup.name
            or backup.txn != expected_backup.txn
            or backup.source_count != expected_backup.source_count
        ):
            raise RuntimeError(
                "BF-662 backup authority changed during recovery; disk state is untouched"
            )
        backup = self._prove_owned_authority(backup)
        for temporary in temporaries:
            current = self._assert_owned_temporary(
                temporary.name,
                role=temporary.role,
                txn=temporary.txn,
            )
            if (
                current.txn != backup.txn
                or current.source_count != backup.source_count
            ):
                raise RuntimeError(
                    "BF-662 temporary transaction/count disagreement with the "
                    "unique backup authority; disk state is untouched"
                )
        return backup, temporaries

    def _delete_owned_temporary(self, temporary: _OwnedTemporary) -> None:
        current = self._assert_owned_temporary(
            temporary.name,
            role=temporary.role,
            txn=temporary.txn,
        )
        self._client.delete_collection(current.name)

    def _delete_auxiliary_temporaries_before_backup(
        self,
        backup: _OwnedTemporary,
    ) -> _OwnedTemporary:
        """Delete coherent non-authorities while retaining the backup last."""
        while True:
            current_backup, temporaries = self._require_unique_backup_coherence(
                backup
            )
            auxiliaries = [
                temporary
                for temporary in temporaries
                if temporary.name != current_backup.name
            ]
            if not auxiliaries:
                return current_backup
            self._delete_owned_temporary(auxiliaries[0])

    @staticmethod
    def _rename_collection(collection: Any, new_name: str) -> None:
        collection.modify(name=new_name)

    def _transition_collection(
        self,
        *,
        source: Any,
        embedding_function: Any,
        model_name: str,
        backend_id: str,
    ) -> None:
        source_count, _ = self._prove_raw_readable(source)
        txn, shadow_name, backup_name = self._allocate_transaction_names()
        shadow = self._client.create_collection(
            name=shadow_name,
            embedding_function=embedding_function,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": model_name,
                "embedding_backend_id": backend_id,
                "bf662_canonical_name": self._collection_name,
                "bf662_owner": self._owner,
                "bf662_txn": txn,
                "bf662_role": "shadow",
                "bf662_state": "copying",
                "bf662_source_count": source_count,
            },
        )

        offset = 0
        copied = 0
        while True:
            rows = self._read_rows_page(source, offset=offset)
            if not rows:
                break
            ids = [row[0] for row in rows]
            documents = [row[1] for row in rows]
            metadatas = [row[2] for row in rows]
            shadow.add(ids=ids, documents=documents, metadatas=metadatas)
            if self._read_rows_by_ids(shadow, ids) != self._rows_by_id(rows):
                raise RuntimeError("evolution shadow page readback proof failed")
            copied += len(rows)
            if len(rows) < _COPY_PAGE_SIZE:
                break
            offset += _COPY_PAGE_SIZE

        if source.count() != source_count or shadow.count() != source_count:
            raise RuntimeError("evolution source changed during shadow copy")
        if copied != source_count:
            raise RuntimeError(
                f"evolution copy expected {source_count} rows, copied {copied}"
            )
        self._verify_exact_rows(source, shadow, expected_count=source_count)
        shadow_meta = self._safe_metadata(shadow.metadata)
        shadow.modify(metadata={**shadow_meta, "bf662_state": "ready"})

        source_meta = self._safe_metadata(source.metadata)
        source.modify(
            metadata={
                **source_meta,
                "bf662_canonical_name": self._collection_name,
                "bf662_owner": self._owner,
                "bf662_txn": txn,
                "bf662_role": "backup",
                "bf662_state": "backup",
                "bf662_source_count": source_count,
            }
        )
        self._rename_collection(source, backup_name)
        self._rename_collection(shadow, self._collection_name)

        backup = self._raw_collection(backup_name)
        candidate = self._client.get_collection(
            name=self._collection_name,
            embedding_function=embedding_function,
        )
        self._prove_active_candidate(
            authority=backup,
            candidate=candidate,
            expected_count=source_count,
            model_name=model_name,
            backend_id=backend_id,
        )
        owned_backup = self._assert_owned_temporary(
            backup_name,
            role="backup",
            txn=txn,
        )
        if not self._canonical_marker_matches_backup(candidate, owned_backup):
            raise RuntimeError(
                "BF-662 new evolution candidate no longer pairs with its backup"
            )
        owned_backup = self._delete_auxiliary_temporaries_before_backup(
            owned_backup
        )
        owned_backup, _ = self._require_unique_backup_coherence(owned_backup)
        if not self._canonical_marker_matches_backup(candidate, owned_backup):
            raise RuntimeError(
                "BF-662 new evolution candidate changed before backup deletion"
            )
        self._delete_owned_temporary(owned_backup)
        self._finalize_stable(
            candidate,
            model_name=model_name,
            backend_id=backend_id,
        )
        self._collection = candidate

    def _canonical_marker_matches_backup(
        self,
        canonical: Any,
        backup: _OwnedTemporary,
    ) -> bool:
        parsed = self._parse_transaction_metadata(
            name=self._collection_name,
            metadata=dict(canonical.metadata or {}),
        )
        return bool(
            parsed is not None
            and parsed.role == "shadow"
            and parsed.state == "ready"
            and parsed.txn == backup.txn
            and parsed.source_count == backup.source_count
        )

    def _prove_canonical_before_temp_cleanup(
        self,
        canonical: Any,
        shadows: list[_OwnedTemporary],
    ) -> tuple[int, str]:
        marker = self._canonical_transaction_metadata(canonical)
        if marker is not None:
            actual_count, first_document = self._prove_recorded_count(
                canonical,
                expected_count=marker.source_count,
                label="evolution canonical transaction",
            )
        else:
            actual_count, first_document = self._prove_raw_readable(canonical)

        for shadow in shadows:
            current = self._assert_owned_temporary(
                shadow.name,
                role=shadow.role,
                txn=shadow.txn,
            )
            if marker is not None and current.txn != marker.txn:
                raise RuntimeError(
                    "BF-662 canonical/shadow transaction disagreement; "
                    "temporary collections are preserved"
                )
            if actual_count != current.source_count:
                raise RuntimeError(
                    "BF-662 canonical count does not match temporary source count; "
                    "temporary collections are preserved"
                )
            if current.role == "shadow" and current.state == "ready":
                self._verify_exact_rows(
                    canonical,
                    current.collection,
                    expected_count=current.source_count,
                )
        return actual_count, first_document

    def _rollback_candidate_to_backup(
        self,
        *,
        candidate: Any,
        backup: _OwnedTemporary,
    ) -> None:
        candidate_marker = self._parse_transaction_metadata(
            name=self._collection_name,
            metadata=dict(candidate.metadata or {}),
        )
        if (
            candidate_marker is None
            or candidate_marker.role != "shadow"
            or candidate_marker.state != "ready"
            or candidate_marker.txn != backup.txn
            or candidate_marker.source_count != backup.source_count
        ):
            raise RuntimeError(
                "BF-662 rollback candidate no longer pairs with backup authority"
            )
        current_backup, _ = self._require_unique_backup_coherence(backup)
        failed_name = self._temporary_name("failed", backup.txn)
        if failed_name in self._collection_names():
            raise RuntimeError(
                "BF-662 rollback shadow target already exists; disk state is untouched"
            )

        # Preserve the original owner/transaction metadata until the candidate
        # has safely left the canonical name. If this rename fails, recovery can
        # retry the unchanged candidate+backup pair on the next start.
        self._rename_collection(candidate, failed_name)
        failed_raw = self._raw_collection(failed_name)
        failed_metadata = self._safe_metadata(failed_raw.metadata)
        failed_raw.modify(
            metadata={
                **failed_metadata,
                "bf662_role": "failed",
                "bf662_state": "failed",
            }
        )
        current_backup, _ = self._require_unique_backup_coherence(current_backup)
        self._rename_collection(current_backup.collection, self._collection_name)
        restored = self._raw_collection(self._collection_name)
        self._prove_recorded_count(
            restored,
            expected_count=backup.source_count,
            label="restored evolution backup",
        )
        failed = self._assert_owned_temporary(
            failed_name,
            role="failed",
            txn=backup.txn,
        )
        self._prove_canonical_before_temp_cleanup(restored, [failed])
        self._delete_owned_temporary(failed)
        self._clear_transaction_markers(restored)

    def _recover_interrupted_state(
        self,
        *,
        embedding_function: Any,
        model_name: str,
        backend_id: str,
    ) -> None:
        names = self._collection_names()
        canonical_exists = self._collection_name in names
        matching_temporary_names = self._matching_temporary_names(names)
        temporaries = self._discover_owned_temporaries(names)
        unowned_temporary_names = matching_temporary_names - {
            temporary.name for temporary in temporaries
        }
        backups = [item for item in temporaries if item.role == "backup"]
        shadows = [item for item in temporaries if item.role in {"shadow", "failed"}]

        if (not canonical_exists or backups) and unowned_temporary_names:
            raise RuntimeError(
                "BF-662 recovery found temporary-looking evolution collections "
                "without valid ownership metadata; disk state is untouched"
            )

        if canonical_exists:
            canonical_raw = self._raw_collection(self._collection_name)
            if len(backups) > 1:
                raise RuntimeError(
                    "BF-662 recovery found multiple proven evolution backups; "
                    "disk state is untouched because authority is ambiguous"
                )
            if backups:
                backup = backups[0]
                if not self._canonical_marker_matches_backup(canonical_raw, backup):
                    raise RuntimeError(
                        "BF-662 recovery found canonical/backup marker disagreement; "
                        "disk state is untouched"
                    )
                backup, _ = self._require_unique_backup_coherence(backup)
                try:
                    candidate = self._client.get_collection(
                        name=self._collection_name,
                        embedding_function=embedding_function,
                    )
                    self._prove_active_candidate(
                        authority=backup.collection,
                        candidate=candidate,
                        expected_count=backup.source_count,
                        model_name=model_name,
                        backend_id=backend_id,
                    )
                except Exception:
                    logger.warning(
                        "BF-662: candidate canonical failed proof; rolling back "
                        "to the proven backup authority",
                        exc_info=True,
                    )
                    self._rollback_candidate_to_backup(
                        candidate=canonical_raw,
                        backup=backup,
                    )
                    return
                backup = self._delete_auxiliary_temporaries_before_backup(backup)
                backup, _ = self._require_unique_backup_coherence(backup)
                if not self._canonical_marker_matches_backup(candidate, backup):
                    raise RuntimeError(
                        "BF-662 candidate changed before backup cleanup"
                    )
                self._delete_owned_temporary(backup)
                self._finalize_stable(
                    candidate,
                    model_name=model_name,
                    backend_id=backend_id,
                )
                return

            canonical_marker = self._canonical_transaction_metadata(canonical_raw)
            canonical_is_ready_candidate = bool(
                canonical_marker is not None
                and canonical_marker.role == "shadow"
                and canonical_marker.state == "ready"
            )
            if canonical_is_ready_candidate:
                canonical_count, first_document = (
                    self._prove_canonical_before_temp_cleanup(
                        canonical_raw,
                        shadows,
                    )
                )
                candidate = self._client.get_collection(
                    name=self._collection_name,
                    embedding_function=embedding_function,
                )
                metadata = candidate.metadata or {}
                if (
                    metadata.get("embedding_model") != model_name
                    or metadata.get("embedding_backend_id") != backend_id
                ):
                    raise RuntimeError(
                        "BF-662 candidate canonical has no backup and failed active "
                        "identity proof; disk state is untouched"
                    )
                if canonical_count:
                    result = candidate.query(
                        query_texts=[first_document], n_results=1
                    )
                    if not (result.get("ids") and result["ids"][0]):
                        raise RuntimeError(
                            "BF-662 candidate canonical query proof failed"
                        )
                for shadow in shadows:
                    current_shadows = [
                        temporary
                        for temporary in self._discover_owned_temporaries()
                        if temporary.role in {"shadow", "failed"}
                    ]
                    self._prove_canonical_before_temp_cleanup(
                        canonical_raw,
                        current_shadows,
                    )
                    current = next(
                        temporary
                        for temporary in current_shadows
                        if temporary.name == shadow.name
                    )
                    self._delete_owned_temporary(current)
                self._finalize_stable(
                    candidate,
                    model_name=model_name,
                    backend_id=backend_id,
                )
                return

            self._prove_canonical_before_temp_cleanup(canonical_raw, shadows)
            for shadow in shadows:
                current_shadows = [
                    temporary
                    for temporary in self._discover_owned_temporaries()
                    if temporary.role in {"shadow", "failed"}
                ]
                self._prove_canonical_before_temp_cleanup(
                    canonical_raw,
                    current_shadows,
                )
                current = next(
                    temporary
                    for temporary in current_shadows
                    if temporary.name == shadow.name
                )
                self._delete_owned_temporary(current)
            if canonical_marker is not None:
                self._clear_transaction_markers(canonical_raw)
            return

        if len(backups) != 1:
            if backups or shadows:
                raise RuntimeError(
                    "BF-662 recovery has no canonical and no unique proven backup "
                    "authority; disk state is untouched"
                )
            return

        backup = backups[0]
        backup, coherent_temporaries = self._require_unique_backup_coherence(backup)
        shadows = [
            temporary
            for temporary in coherent_temporaries
            if temporary.role in {"shadow", "failed"}
        ]
        matching_ready = [
            shadow
            for shadow in shadows
            if shadow.role == "shadow"
            and shadow.txn == backup.txn
            and shadow.state == "ready"
            and shadow.source_count == backup.source_count
        ]
        if len(matching_ready) > 1:
            raise RuntimeError(
                "BF-662 recovery found multiple ready shadows for one backup; "
                "disk state is untouched"
            )
        if matching_ready:
            shadow = matching_ready[0]
            try:
                active_shadow = self._client.get_collection(
                    name=shadow.name,
                    embedding_function=embedding_function,
                )
                self._prove_active_candidate(
                    authority=backup.collection,
                    candidate=active_shadow,
                    expected_count=backup.source_count,
                    model_name=model_name,
                    backend_id=backend_id,
                )
            except Exception:
                logger.warning(
                    "BF-662: ready shadow failed proof; restoring the proven "
                    "backup authority instead",
                    exc_info=True,
                )
                failed_shadow = self._raw_collection(shadow.name)
                failed_metadata = self._safe_metadata(failed_shadow.metadata)
                failed_shadow.modify(
                    metadata={
                        **failed_metadata,
                        "bf662_role": "failed",
                        "bf662_state": "failed",
                    }
                )
            else:
                backup, _ = self._require_unique_backup_coherence(backup)
                active_shadow = self._client.get_collection(
                    name=shadow.name,
                    embedding_function=embedding_function,
                )
                self._rename_collection(active_shadow, self._collection_name)
                candidate = self._client.get_collection(
                    name=self._collection_name,
                    embedding_function=embedding_function,
                )
                try:
                    self._prove_active_candidate(
                        authority=backup.collection,
                        candidate=candidate,
                        expected_count=backup.source_count,
                        model_name=model_name,
                        backend_id=backend_id,
                    )
                except Exception:
                    self._rollback_candidate_to_backup(
                        candidate=candidate,
                        backup=backup,
                    )
                    return
                if not self._canonical_marker_matches_backup(candidate, backup):
                    raise RuntimeError(
                        "BF-662 promoted candidate no longer pairs with backup authority"
                    )
                backup = self._delete_auxiliary_temporaries_before_backup(backup)
                backup, _ = self._require_unique_backup_coherence(backup)
                if not self._canonical_marker_matches_backup(candidate, backup):
                    raise RuntimeError(
                        "BF-662 promoted candidate changed before backup cleanup"
                    )
                self._delete_owned_temporary(backup)
                self._finalize_stable(
                    candidate,
                    model_name=model_name,
                    backend_id=backend_id,
                )
                return

        current_backup, _ = self._require_unique_backup_coherence(backup)
        self._rename_collection(current_backup.collection, self._collection_name)
        restored = self._raw_collection(self._collection_name)
        self._prove_recorded_count(
            restored,
            expected_count=backup.source_count,
            label="BF-662 restored backup",
        )
        while True:
            remaining = [
                temporary
                for temporary in self._discover_owned_temporaries()
                if temporary.role in {"shadow", "failed"}
            ]
            if not remaining:
                break
            self._prove_canonical_before_temp_cleanup(restored, remaining)
            self._delete_owned_temporary(remaining[0])
        self._clear_transaction_markers(restored)

    def record_lesson(
        self,
        category: str,
        summary: str,
        source_proposal_id: str,
        outcome: str,
        payload: dict[str, Any],
    ) -> str:
        """Append a lesson. Returns the lesson id."""
        lesson = Lesson(
            id=uuid.uuid4().hex[:12],
            category=category,
            summary=summary,
            source_proposal_id=source_proposal_id,
            outcome=outcome,
            timestamp=self._clock(),
            payload=dict(payload),
        )
        if self._collection is not None:
            try:
                self._collection.add(
                    ids=[lesson.id],
                    documents=[lesson.summary],
                    metadatas=[
                        {
                            "category": lesson.category,
                            "source_proposal_id": lesson.source_proposal_id,
                            "outcome": lesson.outcome,
                            "timestamp": lesson.timestamp,
                        }
                    ],
                )
            except Exception:
                logger.warning(
                    "AD-482d: chroma add failed for lesson %s; falling back",
                    lesson.id,
                    exc_info=True,
                )
                self._fallback.append(lesson)
        else:
            self._fallback.append(lesson)
        self._emit_event(
            "EVOLUTION_LESSON_RECORDED",
            lesson_id=lesson.id,
            category=lesson.category,
            outcome=lesson.outcome,
        )
        return lesson.id

    def recall(
        self,
        query: str,
        *,
        top_k: int = 5,
        now: float | None = None,
    ) -> list[Lesson]:
        """Return top-k lessons ranked by ``similarity * time_decay``.

        Time decay: ``0.5 ** ((now - timestamp) / half_life)``.
        Older lessons fade; recent lessons retained.
        """
        when = self._clock() if now is None else now
        if self._collection is not None:
            try:
                hits = self._collection.query(query_texts=[query], n_results=max(top_k * 2, top_k))
                ids_batch = hits.get("ids") or [[]]
                docs_batch = hits.get("documents") or [[]]
                metas_batch = hits.get("metadatas") or [[]]
                dists_batch = hits.get("distances") or [[]]
                ids = ids_batch[0] if ids_batch else []
                docs = docs_batch[0] if docs_batch else []
                metas = metas_batch[0] if metas_batch else []
                dists = dists_batch[0] if dists_batch else [0.0] * len(ids)
                scored: list[tuple[float, Lesson]] = []
                for lid, doc, meta, dist in zip(ids, docs, metas, dists, strict=False):
                    similarity = max(0.0, 1.0 - float(dist))
                    ts = float(meta.get("timestamp", when))
                    age = max(0.0, when - ts)
                    decay = 0.5 ** (age / self._half_life)
                    score = similarity * decay
                    lesson = Lesson(
                        id=lid,
                        category=str(meta.get("category", "")),
                        summary=str(doc),
                        source_proposal_id=str(meta.get("source_proposal_id", "")),
                        outcome=str(meta.get("outcome", "")),
                        timestamp=ts,
                        payload={},
                    )
                    scored.append((score, lesson))
                scored.sort(key=lambda x: x[0], reverse=True)
                return [lesson for _, lesson in scored[:top_k]]
            except Exception:
                logger.warning(
                    "AD-482d: chroma query failed; using in-memory fallback",
                    exc_info=True,
                )
        # Fallback: substring match + time-decay
        scored_fb: list[tuple[float, Lesson]] = []
        q_lower = query.lower()
        for lesson in self._fallback:
            similarity = 1.0 if q_lower in lesson.summary.lower() else 0.1
            age = max(0.0, when - lesson.timestamp)
            decay = 0.5 ** (age / self._half_life)
            scored_fb.append((similarity * decay, lesson))
        scored_fb.sort(key=lambda x: x[0], reverse=True)
        return [lesson for _, lesson in scored_fb[:top_k]]

    def _emit_event(self, name: str, **payload: Any) -> None:
        if self._emit is None:
            return
        try:
            self._emit(name, payload)
        except Exception:
            logger.warning("AD-482d: event_emit %s failed", name, exc_info=True)
