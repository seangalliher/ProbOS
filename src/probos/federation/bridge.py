"""FederationBridge — connects the local IntentBus to the federation transport layer."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
import uuid
from collections import deque
from collections.abc import Callable, Awaitable, Iterable
from typing import Any, TYPE_CHECKING

from probos.config import FederationConfig
from probos.dm_reply import DM_REPLY_METADATA_KEY
from probos.federation.relay import (
    RELAY_RATE_LIMIT_PER_SECOND,
    FederationRelayTopic,
    build_relay_topic_registry,
    extract_relay_wire_payload,
    finalize_relay_wire_payload,
    is_canonical_relay_topic,
    is_safe_relay_node_id,
    is_valid_relay_timestamp,
)
from probos.federation.router import FederationRouter
from probos.mesh.pre_intent_auth import IntentAuthorizationDenied
from probos.types import FederationMessage, IntentMessage, IntentResult, NodeSelfModel

if TYPE_CHECKING:
    from probos.federation.mock_transport import MockFederationTransport
    from probos.identity import AgentIdentityRegistry
    from probos.mesh.intent import IntentBus
    from probos.mobility import TransferCertificate

logger = logging.getLogger(__name__)

AttachmentResolver = Callable[[dict[str, Any], str], Awaitable[int]]

_FEDERATED_ATTACHMENT_REF_LIMIT = 8
_FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT = 64
_FEDERATED_VISION_SCAN_LIMIT = 64
_FEDERATED_IMAGE_MIME_TYPES = frozenset({
    "image/png",
    "image/jpeg",
    "image/webp",
    "image/gif",
})
_FEDERATED_VISION_MESSAGE_KEYS = frozenset({"content"})
_FEDERATED_VISION_BLOCK_KEYS = frozenset({"type", "source"})
_FEDERATED_VISION_SOURCE_KEYS = frozenset({
    "type",
    "sha256",
    "media_type",
})
_DIRECTED_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_DIRECTED_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_DIRECTED_INTENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_DIRECTED_CORRELATION_ID_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$"
)
_DIRECTED_DM_MODE = "targeted_dm"
_DIRECTED_TEXT_LIMIT = 65_536
_DIRECTED_REQUEST_KEYS = frozenset({
    "delivery_mode",
    "target_node_id",
    "target_agent_id",
    "intent",
    "params",
    "id",
    "ttl_seconds",
})
_DIRECTED_RESPONSE_KEYS = frozenset({"delivery_mode", "results"})
_DIRECTED_RESULT_KEYS = frozenset({
    "intent_id",
    "agent_id",
    "success",
    "result",
    "error",
    "confidence",
})
#: BF-799: the SAME shape plus the AD-1248 disclosure. Two exact shapes rather
#: than relaxing to "ignore unknown keys" -- the exact-key check is a relay
#: control against key smuggling, and one additional documented shape keeps it.
#: A turn with nothing to disclose still serialises as the six-key shape above,
#: byte for byte, so this is additive on the wire.
_DIRECTED_RESULT_KEYS_WITH_DM_REPLY = _DIRECTED_RESULT_KEYS | {DM_REPLY_METADATA_KEY}
_DIRECTED_PARAM_KEYS = frozenset({
    "text",
    "attachment_ref",
    "attachment_refs",
    "vision_messages",
    "has_image_attachment",
    "_transport_stripped",
})
_DIRECTED_TRANSPORT_STRIPPED_ORDER = (
    "attachment_ref",
    "attachment_refs",
    "vision_messages",
    "has_image_attachment",
)
_DIRECTED_RESULT_MAX_DEPTH = 16
_DIRECTED_RESULT_MAX_NODES = 4_096
_DIRECTED_RESULT_MAX_STRING_CHARS = 65_536
_DIRECTED_RESULT_MAX_UTF8_BYTES = 262_144
_DIRECTED_RESPONSE_MAX_JSON_BYTES = 262_144
_DIRECTED_ERROR_MAX_CHARS = 4_096
_SIGNED_INT64_MIN = -(2**63)
_SIGNED_INT64_MAX = 2**63 - 1


def _preflight_exact_dict_fields(
    mapping: Any,
    approved_keys: frozenset[str],
) -> tuple[bool, dict[str, Any]]:
    """Validate exact-string keys and return approved fields only."""
    if type(mapping) is not dict:
        return False, {}

    key_safe_items: list[tuple[str, Any]] = []
    for key, value in dict.items(mapping):
        if type(key) is not str:
            return False, {}
        key_safe_items.append((key, value))

    fields: dict[str, Any] = {}
    for key, value in key_safe_items:
        if key in approved_keys:
            fields[key] = value
    return True, fields


def _sanitize_attachment_params_for_federation(
    params: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Return a reference-only copy of federation attachment params.

    Attachment-candidate traversal is bounded, but the exact top-level key
    pass remains O(n) in the existing open generic-params contract. Unrelated
    values are preserved shallowly and are never traversed here.
    """
    if type(params) is not dict:
        return {}, ["params"]

    top_level_items: list[tuple[str, Any]] = []
    for key, value in dict.items(params):
        if type(key) is not str:
            return {}, ["params"]
        top_level_items.append((key, value))

    attachment_keys = (
        "attachment_ref",
        "attachment_refs",
        "vision_messages",
        "has_image_attachment",
    )
    params_by_key = dict(top_level_items)
    present_attachment_keys = {
        key for key, _value in top_level_items if key in attachment_keys
    }
    if not present_attachment_keys:
        return params_by_key, []

    sanitized = {
        key: value
        for key, value in top_level_items
        if key not in attachment_keys and key != "_transport_stripped"
    }
    processed_keys: list[str] = []
    admitted_shas: set[str] = set()

    def _is_sha(value: Any) -> bool:
        return (
            type(value) is str
            and len(value) == 64
            and all(char in "0123456789abcdef" for char in value)
        )

    def _is_string(value: Any, expected: str) -> bool:
        return type(value) is str and value == expected

    def _admit(value: Any) -> bool:
        if not _is_sha(value):
            return False
        if value in admitted_shas:
            return True
        if len(admitted_shas) >= _FEDERATED_ATTACHMENT_REF_LIMIT:
            return False
        admitted_shas.add(value)
        return True

    if "attachment_ref" in present_attachment_keys:
        processed_keys.append("attachment_ref")
        attachment_ref = params_by_key["attachment_ref"]
        if _admit(attachment_ref):
            sanitized["attachment_ref"] = attachment_ref

    if "attachment_refs" in present_attachment_keys:
        processed_keys.append("attachment_refs")
        attachment_refs = params_by_key["attachment_refs"]
        retained_refs: list[str] = []
        seen_refs: set[str] = set()
        if type(attachment_refs) is list or type(attachment_refs) is tuple:
            for value in attachment_refs[
                :_FEDERATED_ATTACHMENT_CANDIDATE_SCAN_LIMIT
            ]:
                if not _is_sha(value) or value in seen_refs:
                    continue
                seen_refs.add(value)
                if _admit(value):
                    retained_refs.append(value)
        if retained_refs:
            sanitized["attachment_refs"] = retained_refs

    safe_vision_blocks: list[dict[str, Any]] = []
    if "vision_messages" in present_attachment_keys:
        processed_keys.append("vision_messages")
        vision_messages = params_by_key["vision_messages"]
        seen_vision_refs: set[str] = set()
        if type(vision_messages) is list and vision_messages:
            first_message = vision_messages[0]
            message_safe, message_fields = _preflight_exact_dict_fields(
                first_message,
                _FEDERATED_VISION_MESSAGE_KEYS,
            )
            if message_safe:
                content = message_fields.get("content")
                if type(content) is list:
                    for block in content[:_FEDERATED_VISION_SCAN_LIMIT]:
                        block_safe, block_fields = _preflight_exact_dict_fields(
                            block,
                            _FEDERATED_VISION_BLOCK_KEYS,
                        )
                        if not block_safe or not _is_string(
                            block_fields.get("type"), "image"
                        ):
                            continue
                        source = block_fields.get("source")
                        source_safe, source_fields = (
                            _preflight_exact_dict_fields(
                                source,
                                _FEDERATED_VISION_SOURCE_KEYS,
                            )
                        )
                        if not source_safe:
                            continue
                        sha = source_fields.get("sha256")
                        media_type = source_fields.get("media_type")
                        if (
                            not _is_string(
                                source_fields.get("type"), "attachment_ref"
                            )
                            or not _is_sha(sha)
                            or type(media_type) is not str
                            or media_type not in _FEDERATED_IMAGE_MIME_TYPES
                            or sha in seen_vision_refs
                        ):
                            continue
                        seen_vision_refs.add(sha)
                        if not _admit(sha):
                            continue
                        safe_vision_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "attachment_ref",
                                "sha256": sha,
                                "media_type": media_type,
                            },
                        })
        if safe_vision_blocks:
            sanitized["vision_messages"] = [{
                "role": "user",
                "content": safe_vision_blocks,
            }]

    if "has_image_attachment" in present_attachment_keys:
        has_safe_vision = bool(safe_vision_blocks)
        has_image_attachment = params_by_key["has_image_attachment"]
        if has_safe_vision and type(has_image_attachment) is bool and has_image_attachment:
            sanitized["has_image_attachment"] = True
        else:
            processed_keys.append("has_image_attachment")

    return sanitized, processed_keys


def _is_safe_node_id(value: Any) -> bool:
    return type(value) is str and _DIRECTED_NODE_ID_RE.fullmatch(value) is not None


def _is_safe_agent_id(value: Any) -> bool:
    return type(value) is str and _DIRECTED_AGENT_ID_RE.fullmatch(value) is not None


def _is_safe_intent_id(value: Any) -> bool:
    return type(value) is str and _DIRECTED_INTENT_ID_RE.fullmatch(value) is not None


def _is_safe_correlation_id(value: Any) -> bool:
    return (
        type(value) is str
        and _DIRECTED_CORRELATION_ID_RE.fullmatch(value) is not None
    )


def _strict_json_detach(value: Any) -> Any:
    return json.loads(json.dumps(value, allow_nan=False))


def _extract_exact_directed_request_payload(
    payload: Any,
) -> dict[str, Any] | None:
    if type(payload) is not dict or dict.__len__(payload) != 7:
        return None
    seen: set[str] = set()
    for key in dict.keys(payload):
        if type(key) is not str or key not in _DIRECTED_REQUEST_KEYS:
            return None
        seen.add(key)
    if seen != _DIRECTED_REQUEST_KEYS:
        return None
    return payload


def _extract_exact_directed_response_payload(
    payload: Any,
) -> list[Any] | None:
    if type(payload) is not dict or dict.__len__(payload) != 2:
        return None
    seen: set[str] = set()
    for key in dict.keys(payload):
        if type(key) is not str or key not in _DIRECTED_RESPONSE_KEYS:
            return None
        seen.add(key)
    if seen != _DIRECTED_RESPONSE_KEYS:
        return None
    if type(dict.__getitem__(payload, "delivery_mode")) is not str:
        return None
    if dict.__getitem__(payload, "delivery_mode") != _DIRECTED_DM_MODE:
        return None
    results = dict.__getitem__(payload, "results")
    if type(results) is not list or list.__len__(results) != 1:
        return None
    return results


def _validate_transport_stripped_marker(marker: Any) -> bool:
    if type(marker) is not list:
        return False
    marker_length = list.__len__(marker)
    if marker_length < 1 or marker_length > len(
        _DIRECTED_TRANSPORT_STRIPPED_ORDER
    ):
        return False
    prior_index = -1
    for position in range(marker_length):
        item = list.__getitem__(marker, position)
        if type(item) is not str:
            return False
        try:
            item_index = _DIRECTED_TRANSPORT_STRIPPED_ORDER.index(item)
        except ValueError:
            return False
        if item_index <= prior_index:
            return False
        prior_index = item_index
    return True


def _is_canonical_attachment_sha(value: Any) -> bool:
    return (
        type(value) is str
        and str.__len__(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _has_exact_dict_keys(value: Any, expected: frozenset[str]) -> bool:
    if type(value) is not dict or dict.__len__(value) != len(expected):
        return False
    seen: set[str] = set()
    for key in dict.keys(value):
        if type(key) is not str or key not in expected:
            return False
        seen.add(key)
    return seen == expected


def _validate_canonical_directed_attachments(params: dict[str, Any]) -> bool:
    admitted_shas: set[str] = set()

    if dict.__contains__(params, "attachment_ref"):
        attachment_ref = dict.__getitem__(params, "attachment_ref")
        if not _is_canonical_attachment_sha(attachment_ref):
            return False
        admitted_shas.add(attachment_ref)

    if dict.__contains__(params, "attachment_refs"):
        attachment_refs = dict.__getitem__(params, "attachment_refs")
        if type(attachment_refs) is not list:
            return False
        ref_count = list.__len__(attachment_refs)
        if ref_count < 1 or ref_count > _FEDERATED_ATTACHMENT_REF_LIMIT:
            return False
        seen_refs: set[str] = set()
        for index in range(ref_count):
            ref = list.__getitem__(attachment_refs, index)
            if not _is_canonical_attachment_sha(ref) or ref in seen_refs:
                return False
            seen_refs.add(ref)
            admitted_shas.add(ref)

    has_vision = False
    if dict.__contains__(params, "vision_messages"):
        vision_messages = dict.__getitem__(params, "vision_messages")
        if type(vision_messages) is not list or list.__len__(vision_messages) != 1:
            return False
        message = list.__getitem__(vision_messages, 0)
        if not _has_exact_dict_keys(
            message, frozenset({"role", "content"})
        ):
            return False
        if (
            type(dict.__getitem__(message, "role")) is not str
            or dict.__getitem__(message, "role") != "user"
        ):
            return False
        content = dict.__getitem__(message, "content")
        if type(content) is not list:
            return False
        content_count = list.__len__(content)
        if content_count < 1 or content_count > _FEDERATED_ATTACHMENT_REF_LIMIT:
            return False
        seen_vision_refs: set[str] = set()
        for index in range(content_count):
            block = list.__getitem__(content, index)
            if not _has_exact_dict_keys(
                block, _FEDERATED_VISION_BLOCK_KEYS
            ):
                return False
            if (
                type(dict.__getitem__(block, "type")) is not str
                or dict.__getitem__(block, "type") != "image"
            ):
                return False
            source = dict.__getitem__(block, "source")
            if not _has_exact_dict_keys(
                source, _FEDERATED_VISION_SOURCE_KEYS
            ):
                return False
            if (
                type(dict.__getitem__(source, "type")) is not str
                or dict.__getitem__(source, "type") != "attachment_ref"
            ):
                return False
            sha = dict.__getitem__(source, "sha256")
            media_type = dict.__getitem__(source, "media_type")
            if (
                not _is_canonical_attachment_sha(sha)
                or sha in seen_vision_refs
                or type(media_type) is not str
                or media_type not in _FEDERATED_IMAGE_MIME_TYPES
            ):
                return False
            seen_vision_refs.add(sha)
            admitted_shas.add(sha)
        has_vision = True

    if len(admitted_shas) > _FEDERATED_ATTACHMENT_REF_LIMIT:
        return False
    if dict.__contains__(params, "has_image_attachment"):
        has_image_attachment = dict.__getitem__(
            params, "has_image_attachment"
        )
        if type(has_image_attachment) is not bool or not has_image_attachment:
            return False
        if not has_vision:
            return False
    return True


def _is_forbidden_result_data_url(value: str) -> bool:
    length = str.__len__(value)
    offset = 0
    ascii_whitespace = " \t\n\r\v\f"
    while offset < length and str.__getitem__(value, offset) in ascii_whitespace:
        offset += 1
    expected = "data:image/"
    if length - offset < str.__len__(expected):
        return False
    for index in range(str.__len__(expected)):
        candidate = str.__getitem__(value, offset + index)
        codepoint = ord(candidate)
        if 65 <= codepoint <= 90:
            candidate = chr(codepoint + 32)
        if candidate != str.__getitem__(expected, index):
            return False
    return True


def _is_forbidden_result_dict_shape(value: dict[Any, Any]) -> bool:
    value_type = (
        dict.__getitem__(value, "type")
        if dict.__contains__(value, "type")
        else None
    )
    if type(value_type) is str and value_type == "image_url":
        return True
    if dict.__contains__(value, "image_url"):
        return True
    if (
        type(value_type) is str
        and value_type in {"base64", "image"}
        and dict.__contains__(value, "data")
    ):
        return True
    source = (
        dict.__getitem__(value, "source")
        if dict.__contains__(value, "source")
        else None
    )
    if type(source) is dict:
        source_type = (
            dict.__getitem__(source, "type")
            if dict.__contains__(source, "type")
            else None
        )
        if (
            type(source_type) is str and source_type == "base64"
        ) or dict.__contains__(source, "data"):
            return True
    return False


def _detach_directed_result_value(
    value: Any,
    *,
    _string_budget: list[int] | None = None,
    _node_budget: list[int] | None = None,
) -> Any:
    """Return an exact-built-in detached result under fixed work bounds.

    BF-799: ``_node_budget`` is threaded like ``_string_budget`` so that two
    fields detached for the same message SHARE the node allowance. Left local,
    carrying a second field would silently grant 2 x ``_MAX_NODES`` per
    message.
    """
    root: list[Any] = [None]
    active_container_ids: set[int] = set()
    node_budget = [0] if _node_budget is None else _node_budget
    string_budget = [0] if _string_budget is None else _string_budget
    stack: list[tuple[Any, ...]] = [("visit", value, 0, root, 0)]

    def _assign(parent: list[Any] | dict[str, Any], slot: Any, item: Any) -> None:
        if type(parent) is list:
            list.__setitem__(parent, slot, item)
        else:
            dict.__setitem__(parent, slot, item)

    def _account_string(item: str) -> None:
        if str.__len__(item) > _DIRECTED_RESULT_MAX_STRING_CHARS:
            raise ValueError("federation_result_not_serializable")
        string_budget[0] += len(str.encode(item, "utf-8"))
        if string_budget[0] > _DIRECTED_RESULT_MAX_UTF8_BYTES:
            raise ValueError("federation_result_not_serializable")

    while stack:
        frame = stack.pop()
        operation = frame[0]
        if operation == "exit":
            active_container_ids.remove(frame[1])
            continue
        if operation == "dict_exit":
            container_id, detached = frame[1:]
            if _is_forbidden_result_dict_shape(detached):
                raise ValueError("federation_result_not_serializable")
            active_container_ids.remove(container_id)
            continue
        if operation == "list_next":
            source, index, depth, detached = frame[1:]
            if index >= list.__len__(source):
                continue
            list.append(detached, None)
            stack.append(("list_next", source, index + 1, depth, detached))
            stack.append((
                "visit",
                list.__getitem__(source, index),
                depth + 1,
                detached,
                index,
            ))
            continue
        if operation == "dict_next":
            iterator, depth, detached = frame[1:]
            try:
                key, item = next(iterator)
            except StopIteration:
                continue
            node_budget[0] += 1
            if node_budget[0] > _DIRECTED_RESULT_MAX_NODES:
                raise ValueError("federation_result_not_serializable")
            if depth + 1 > _DIRECTED_RESULT_MAX_DEPTH or type(key) is not str:
                raise ValueError("federation_result_not_serializable")
            _account_string(key)
            if _is_forbidden_result_data_url(key):
                raise ValueError("federation_result_not_serializable")
            stack.append(("dict_next", iterator, depth, detached))
            stack.append(("visit", item, depth + 1, detached, key))
            continue

        item, depth, parent, slot = frame[1:]
        node_budget[0] += 1
        if (
            node_budget[0] > _DIRECTED_RESULT_MAX_NODES
            or depth > _DIRECTED_RESULT_MAX_DEPTH
        ):
            raise ValueError("federation_result_not_serializable")
        item_type = type(item)
        if item is None or item_type is bool:
            _assign(parent, slot, item)
        elif item_type is int:
            if item < _SIGNED_INT64_MIN or item > _SIGNED_INT64_MAX:
                raise ValueError("federation_result_not_serializable")
            _assign(parent, slot, item)
        elif item_type is float:
            if not math.isfinite(item):
                raise ValueError("federation_result_not_serializable")
            _assign(parent, slot, item)
        elif item_type is str:
            _account_string(item)
            if _is_forbidden_result_data_url(item):
                raise ValueError("federation_result_not_serializable")
            _assign(parent, slot, item)
        elif item_type is list:
            container_id = id(item)
            if container_id in active_container_ids:
                raise ValueError("federation_result_not_serializable")
            detached_list: list[Any] = []
            _assign(parent, slot, detached_list)
            active_container_ids.add(container_id)
            stack.append(("exit", container_id))
            stack.append(("list_next", item, 0, depth, detached_list))
        elif item_type is dict:
            container_id = id(item)
            if container_id in active_container_ids:
                raise ValueError("federation_result_not_serializable")
            detached_dict: dict[str, Any] = {}
            _assign(parent, slot, detached_dict)
            active_container_ids.add(container_id)
            stack.append(("dict_exit", container_id, detached_dict))
            stack.append((
                "dict_next",
                iter(dict.items(item)),
                depth,
                detached_dict,
            ))
        elif item_type in (bytes, bytearray, memoryview):
            raise ValueError("federation_result_not_serializable")
        else:
            raise ValueError("federation_result_not_serializable")

    return list.__getitem__(root, 0)


def _detach_serialized_directed_result(
    raw_result: Any,
    *,
    malformed_error: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if not (
        _has_exact_dict_keys(raw_result, _DIRECTED_RESULT_KEYS)
        or _has_exact_dict_keys(raw_result, _DIRECTED_RESULT_KEYS_WITH_DM_REPLY)
    ):
        return None, malformed_error
    intent_id = dict.__getitem__(raw_result, "intent_id")
    agent_id = dict.__getitem__(raw_result, "agent_id")
    success = dict.__getitem__(raw_result, "success")
    error = dict.__getitem__(raw_result, "error")
    confidence = dict.__getitem__(raw_result, "confidence")
    if not _is_safe_intent_id(intent_id) or not _is_safe_agent_id(agent_id):
        return None, malformed_error
    if type(success) is not bool:
        return None, malformed_error
    if error is not None and (
        type(error) is not str
        or str.__len__(error) > _DIRECTED_ERROR_MAX_CHARS
    ):
        return None, malformed_error
    if type(confidence) not in (int, float):
        return None, malformed_error
    try:
        normalized_confidence = float(confidence)
    except (OverflowError, TypeError, ValueError):
        return None, malformed_error
    if not math.isfinite(normalized_confidence):
        return None, malformed_error
    string_budget = [0]
    node_budget = [0]
    if error is not None:
        try:
            string_budget[0] = len(str.encode(error, "utf-8"))
        except UnicodeEncodeError:
            return None, "federation_result_not_serializable"
        if (
            string_budget[0] > _DIRECTED_RESULT_MAX_UTF8_BYTES
            or _is_forbidden_result_data_url(error)
        ):
            return None, "federation_result_not_serializable"
    try:
        detached_value = _detach_directed_result_value(
            dict.__getitem__(raw_result, "result"),
            _string_budget=string_budget,
            _node_budget=node_budget,
        )
    except ValueError:
        return None, "federation_result_not_serializable"

    detached = {
        "intent_id": intent_id,
        "agent_id": agent_id,
        "success": success,
        "result": detached_value,
        "error": error,
        "confidence": normalized_confidence,
    }

    # BF-799: the disclosure is detached AFTER the body and can only ever drop
    # ITSELF. Letting it fail the whole record would mean a malformed or
    # oversized disclosure destroys the answer it was attached to -- exactly
    # the BF-802 defect, one layer down. The body is already safely detached
    # above, so the worst case here is a reply that arrives without its
    # disclosure, which is what happens today anyway.
    if dict.__contains__(raw_result, DM_REPLY_METADATA_KEY):
        raw_payload = dict.__getitem__(raw_result, DM_REPLY_METADATA_KEY)
        if type(raw_payload) is not dict:
            logger.warning(
                "BF-799: directed result disclosure is %s, not a dict; "
                "delivering the reply without it",
                type(raw_payload).__name__,
            )
        else:
            try:
                detached[DM_REPLY_METADATA_KEY] = _detach_directed_result_value(
                    raw_payload,
                    _string_budget=string_budget,
                    _node_budget=node_budget,
                )
            except ValueError:
                logger.warning(
                    "BF-799: directed result disclosure exceeded the shared "
                    "detachment budget; delivering the reply without it"
                )

    return detached, None


def _compact_detach_directed_response(
    serialized_result: dict[str, Any],
) -> dict[str, Any] | None:
    """Encode the response envelope, dropping the disclosure before the answer.

    BF-799: a result sized just under the cap plus even a small disclosure tips
    the envelope, and returning ``None`` here discards the Captain's whole
    answer. Measured: a body compacting to exactly 262,144 bytes went to
    262,176 with a tiny disclosure attached. So when the payload does not fit,
    retry once WITHOUT the disclosure -- the answer is what must survive.
    """
    encoded = _encode_directed_response(serialized_result)
    if encoded is None and dict.__contains__(serialized_result, DM_REPLY_METADATA_KEY):
        without = dict(serialized_result)
        dict.__delitem__(without, DM_REPLY_METADATA_KEY)
        encoded = _encode_directed_response(without)
        if encoded is not None:
            logger.warning(
                "BF-799: directed response exceeded %d bytes with its "
                "disclosure attached; delivering the reply without it",
                _DIRECTED_RESPONSE_MAX_JSON_BYTES,
            )
    if encoded is None:
        return None
    detached = json.loads(encoded.decode("utf-8"))
    return detached if type(detached) is dict else None


def _encode_directed_response(serialized_result: dict[str, Any]) -> bytes | None:
    payload = {
        "delivery_mode": _DIRECTED_DM_MODE,
        "results": [serialized_result],
    }
    try:
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (OverflowError, TypeError, ValueError):
        return None
    if len(encoded) > _DIRECTED_RESPONSE_MAX_JSON_BYTES:
        return None
    return encoded


def _finalize_directed_result_for_origin(
    serialized_result: dict[str, Any],
) -> dict[str, Any] | None:
    payload = _compact_detach_directed_response(serialized_result)
    if payload is None:
        return None
    results = dict.__getitem__(payload, "results")
    return list.__getitem__(results, 0)


def _normalize_origin_ttl(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if not math.isfinite(normalized) or normalized <= 0.0:
        return None
    return min(normalized, 60.0)


def _normalize_wire_ttl(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(normalized)
        or normalized <= 0.0
        or normalized > 60.0
    ):
        return None
    return normalized


def _has_directed_attachment(params: dict[str, Any]) -> bool:
    if type(params.get("attachment_ref")) is str:
        return True
    refs = params.get("attachment_refs")
    if type(refs) is list and bool(refs):
        return True
    vision_messages = params.get("vision_messages")
    if type(vision_messages) is list and bool(vision_messages):
        return True
    return False


def _directed_dm_params(
    params: dict[str, Any],
) -> tuple[dict[str, Any] | None, str | None]:
    sanitized, processed_attachment_keys = (
        _sanitize_attachment_params_for_federation(params)
    )
    directed: dict[str, Any] = {}
    text = sanitized.get("text")
    if type(text) is str and len(text) <= _DIRECTED_TEXT_LIMIT:
        directed["text"] = text
    for key in (
        "attachment_ref",
        "attachment_refs",
        "vision_messages",
        "has_image_attachment",
    ):
        if key in sanitized:
            directed[key] = sanitized[key]
    if processed_attachment_keys:
        directed["_transport_stripped"] = processed_attachment_keys
    if not directed.get("text") and not _has_directed_attachment(directed):
        return None, "federation_payload_invalid"
    try:
        detached = _strict_json_detach(directed)
    except (TypeError, ValueError, OverflowError):
        return None, "federation_payload_not_serializable"
    if type(detached) is not dict:
        return None, "federation_payload_invalid"
    return detached, None


def _validate_directed_wire_params(
    params: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    if type(params) is not dict or dict.__len__(params) > len(
        _DIRECTED_PARAM_KEYS
    ):
        return None, "federation_payload_invalid"
    for key in dict.keys(params):
        if type(key) is not str or key not in _DIRECTED_PARAM_KEYS:
            return None, "federation_payload_invalid"
    text = (
        dict.__getitem__(params, "text")
        if dict.__contains__(params, "text")
        else None
    )
    if dict.__contains__(params, "text") and (
        type(text) is not str or len(text) > _DIRECTED_TEXT_LIMIT
    ):
        return None, "federation_payload_invalid"
    if not _validate_canonical_directed_attachments(params):
        return None, "federation_payload_invalid"
    if dict.__contains__(params, "_transport_stripped"):
        marker = dict.__getitem__(params, "_transport_stripped")
        if not _validate_transport_stripped_marker(marker):
            return None, "federation_payload_invalid"
    if not text and not _has_directed_attachment(params):
        return None, "federation_payload_invalid"
    try:
        detached = _strict_json_detach(params)
    except (TypeError, ValueError, OverflowError):
        return None, "federation_payload_not_serializable"
    if type(detached) is not dict:
        return None, "federation_payload_invalid"
    return detached, None


def _serialize_directed_result(result: IntentResult) -> dict[str, Any]:
    """Serialize for the wire, adding the AD-1248 disclosure only if there is one.

    BF-799: directed federation is a transport HOP, not a sink -- the origin
    reconstructs an ``IntentResult`` and a LOCAL sink renders it -- so the
    disclosure has to ride across rather than be rendered remotely. Dropping it
    here is what made a tool failure invisible on the far side.

    The key is omitted entirely when absent, so a turn with nothing to disclose
    produces the identical six-key payload it always has.
    """
    serialized = {
        "intent_id": result.intent_id,
        "agent_id": result.agent_id,
        "success": result.success,
        "result": result.result,
        "error": result.error,
        "confidence": result.confidence,
    }
    metadata = getattr(result, "metadata", None)
    if type(metadata) is dict:
        payload = metadata.get(DM_REPLY_METADATA_KEY)
        if payload is not None:
            serialized[DM_REPLY_METADATA_KEY] = payload
    return serialized


def _detach_local_directed_result(
    result: Any,
) -> dict[str, Any] | None:
    if type(result) is not IntentResult:
        return None
    serialized = _serialize_directed_result(result)
    detached, error = _detach_serialized_directed_result(
        serialized,
        malformed_error="federation_result_not_serializable",
    )
    if error is not None:
        return None
    return detached


class FederationForwardOutcome(list[IntentResult]):
    """Remote results, plus what the peers said about DELIVERY (AD-1297).

    A ``list`` subclass because every existing reader of ``forward_intent`` --
    iterate, index, ``len``, ``== []`` -- must keep working untouched. The
    counters ride alongside for the one caller that has to tell "no peer had a
    handler" from "a peer ran it and returned nothing", a distinction the list
    cannot carry: both are ``[]``.

    ``peers_unknown`` is the load-bearing counter. A peer that omits the
    ``admitted`` key is an OLD peer, not a peer reporting no candidate.
    Collapsing those two is the same defect as BF-870 pointed the other way --
    orders stranded active forever because a pre-AD-1297 peer never claimed
    them -- so omission increments THIS, never ``peers_admitted``'s complement.
    """

    def __init__(
        self,
        results: Iterable[IntentResult] = (),
        *,
        peers_attempted: int = 0,
        peers_answered: int = 0,
        peers_admitted: int = 0,
        peers_unknown: int = 0,
    ) -> None:
        super().__init__(results)
        self.peers_attempted: int = peers_attempted
        self.peers_answered: int = peers_answered
        self.peers_admitted: int = peers_admitted
        self.peers_unknown: int = peers_unknown


class FederationBridge:
    """Connects the local IntentBus to the federation transport layer.

    Outbound: Forwards local intents to peers, collects remote results.
    Inbound: Receives intents from peers, broadcasts locally, returns results.
    Gossip: Periodically sends this node's self-model to all peers.
    """

    def __init__(
        self,
        node_id: str,
        transport: Any,  # FederationTransport or MockFederationTransport
        router: FederationRouter,
        intent_bus: Any,  # IntentBus
        config: FederationConfig,
        self_model_fn: Callable[[], NodeSelfModel],
        validate_fn: Callable[..., Awaitable[bool]] | None = None,
        identity_registry: "AgentIdentityRegistry | None" = None,
        trust_network: Any | None = None,
        hebbian_map: Any | None = None,
        attachment_resolver: AttachmentResolver | None = None,
        relay_topics: tuple[FederationRelayTopic, ...] = (),
    ) -> None:
        self._node_id = node_id
        self._transport = transport
        self._router = router
        self._intent_bus = intent_bus
        self._config = config
        self._self_model_fn = self_model_fn
        self._validate_fn = validate_fn
        # AD-443e: Identity registry handle — required for transfer/chain
        # message handling; None disables the mobility wire types.
        self._identity_registry = identity_registry
        # AD-479b/c: optional trust + Hebbian handles for per-result outcome wiring.
        self._trust_network = trust_network
        self._hebbian_map = hebbian_map
        self._attachment_resolver = attachment_resolver
        self._gossip_task: asyncio.Task[None] | None = None
        self._stopped = False
        self._directed_admission_open = True
        self._relay_topics = build_relay_topic_registry(relay_topics)
        self._relay_admission_open = True
        self._relay_rate: dict[tuple[str, str], deque[float]] = {}
        self._stats = {
            "intents_forwarded": 0,
            "intents_received": 0,
            "results_collected": 0,
            "transfers_sent": 0,
            "transfers_received": 0,
        }

    async def start(self) -> None:
        """Start the bridge: register as transport inbound handler, start gossip loop."""
        self._directed_admission_open = False
        self._relay_admission_open = False
        self._relay_rate.clear()
        self._stopped = False
        self._transport._inbound_handler = self.handle_inbound
        self._gossip_task = asyncio.create_task(
            self._gossip_loop(), name="federation-gossip"
        )
        self._directed_admission_open = True
        self._relay_admission_open = True

    async def stop(self) -> None:
        """Stop gossip loop."""
        self._directed_admission_open = False
        self._relay_admission_open = False
        self._relay_rate.clear()
        self._stopped = True
        if self._gossip_task is not None:
            self._gossip_task.cancel()
            try:
                await self._gossip_task
            except asyncio.CancelledError:
                pass
            self._gossip_task = None

    async def relay_one_way(
        self,
        target_node_id: str,
        topic: str,
        payload: dict[str, Any],
    ) -> bool:
        """Best-effort send one bounded relay datagram to one peer."""
        if not self._relay_admission_open:
            return False
        if not is_safe_relay_node_id(self._node_id):
            return False
        if (
            not is_safe_relay_node_id(target_node_id)
            or target_node_id == self._node_id
        ):
            return False
        if (
            target_node_id not in {peer.node_id for peer in self._config.peers}
            or target_node_id not in self._transport.connected_peers
        ):
            return False
        if not is_canonical_relay_topic(topic):
            return False
        contract = self._relay_topics.get(topic)
        if contract is None:
            return False
        message = FederationMessage(
            type="relay_one_way",
            source_node=self._node_id,
            payload={
                "relay_version": 1,
                "target_node_id": target_node_id,
                "topic": topic,
                "payload": payload,
                "hop_count": 0,
            },
            timestamp=time.monotonic(),
        )
        if not _is_safe_correlation_id(message.message_id):
            return False
        finalized = finalize_relay_wire_payload(
            source_node=message.source_node,
            message_id=message.message_id,
            relay_payload=message.payload,
            timestamp=message.timestamp,
        )
        if finalized is None:
            logger.debug(
                "One-way federation relay rejected target=%s topic=%s "
                "reason=payload_invalid action=drop",
                target_node_id,
                topic,
            )
            return False
        validation_copy = finalize_relay_wire_payload(
            source_node=message.source_node,
            message_id=message.message_id,
            relay_payload=finalized,
            timestamp=message.timestamp,
        )
        if validation_copy is None:
            return False
        try:
            valid = contract.validate_payload(
                dict.__getitem__(validation_copy, "payload")
            )
        except Exception as exc:
            logger.warning(
                "One-way federation relay validator failed target=%s topic=%s "
                "reason=validator_exception action=drop exception_type=%s",
                target_node_id,
                topic,
                type(exc).__name__,
            )
            return False
        if valid is not True:
            return False
        message.payload = finalized
        try:
            await self._transport.send_to_peer(target_node_id, message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "One-way federation relay send failed target=%s topic=%s "
                "reason=transport_exception action=drop exception_type=%s",
                target_node_id,
                topic,
                type(exc).__name__,
            )
            return False
        return True

    async def forward_intent(self, intent: IntentMessage) -> FederationForwardOutcome:
        """Forward an intent to selected peers and collect results.

        This is the function registered as IntentBus._federation_fn.

        AD-1297: returns a ``FederationForwardOutcome`` -- still a list, so no
        existing reader changes -- carrying whether any peer ADMITTED the
        intent. ``[]`` alone could not say whether a peer ran the work and
        returned nothing or no peer had a handler at all, and the watch path
        needs those apart before it consumes a one-shot Captain's order.
        """
        peers = self._router.select_peers(
            intent.intent, self._transport.connected_peers
        )
        if not peers:
            # Nothing was attempted, so nothing is unknown: no peer could have
            # run this. That is a KNOWN zero, and the caller may act on it.
            return FederationForwardOutcome()

        params_for_transport, processed_attachment_keys = (
            _sanitize_attachment_params_for_federation(intent.params)
        )
        if processed_attachment_keys:
            params_for_transport["_transport_stripped"] = processed_attachment_keys

        msg = FederationMessage(
            type="intent_request",
            source_node=self._node_id,
            payload={
                "intent": intent.intent,
                "params": params_for_transport,
                "urgency": intent.urgency,
                "context": intent.context,
                "id": intent.id,
                "ttl_seconds": intent.ttl_seconds,
            },
            timestamp=time.monotonic(),
        )

        # Send to each peer
        for peer_id in peers:
            await self._transport.send_to_peer(peer_id, msg)
        self._stats["intents_forwarded"] += 1

        # Collect responses with timeout
        results: list[IntentResult] = []
        peers_answered = 0
        peers_admitted = 0
        peers_unknown = 0
        for peer_id in peers:
            response = await self._transport.receive_with_timeout(
                peer_id, self._config.forward_timeout_ms
            )
            if response is None:
                # AD-1297: silence is NOT absence. The intent was already sent
                # to this peer above, so it may have run the handler and had
                # its reply lost -- a timeout cannot prove non-execution. Read
                # as a known zero it would let the watch path raise, keep the
                # order active, and re-dispatch work that already ran; that is
                # BF-814 attempt 1 ("a handler that acts still yields []") one
                # layer out, and duplicated remote side effects when measured.
                # The genuine known zero is an EMPTY peer list, which returns
                # earlier without ever entering this loop.
                peers_unknown += 1
                continue
            peers_answered += 1
            # AD-1297: THREE states, not two. Only an explicit ``False`` is a
            # peer telling us it had no candidate. Omission, ``None``, or any
            # shape this version does not recognise is an old or malformed peer
            # -- UNKNOWN -- and must never be read as absence.
            admitted = response.payload.get("admitted")
            if admitted is True:
                peers_admitted += 1
            elif admitted is not False:
                peers_unknown += 1
            # Deserialize results from response payload
            remote_results = response.payload.get("results", [])
            for rr in remote_results:
                ir = IntentResult(
                    intent_id=rr.get("intent_id", intent.id),
                    agent_id=rr.get("agent_id", f"{peer_id}:remote"),
                    success=rr.get("success", False),
                    result=rr.get("result"),
                    error=rr.get("error"),
                    confidence=rr.get("confidence", 0.0),
                )
                # Validate if validation function is set
                if self._validate_fn:
                    try:
                        valid = await self._validate_fn(ir)
                        if not valid:
                            continue
                    except Exception:
                        logger.warning("Federation message validator failed — message passed without validation", exc_info=True)
                results.append(ir)
                self._stats["results_collected"] += 1
                # AD-479b: record per-result trust outcome on the ZeroMQ peer record.
                self._record_zmq_peer_outcome(
                    peer_node_id=peer_id,
                    success=bool(ir.success),
                    intent_type=intent.intent,
                )

        return FederationForwardOutcome(
            results,
            peers_attempted=len(peers),
            peers_answered=peers_answered,
            peers_admitted=peers_admitted,
            peers_unknown=peers_unknown,
        )

    def _directed_error(
        self,
        intent: IntentMessage | None,
        error: str,
        *,
        intent_id: Any = "",
        agent_id: Any = "",
    ) -> IntentResult:
        resolved_intent_id = (
            intent.id
            if intent is not None and _is_safe_intent_id(intent.id)
            else intent_id if _is_safe_intent_id(intent_id) else ""
        )
        resolved_agent_id = (
            intent.target_agent_id
            if intent is not None and _is_safe_agent_id(intent.target_agent_id)
            else agent_id if _is_safe_agent_id(agent_id) else ""
        )
        return IntentResult(
            intent_id=resolved_intent_id,
            agent_id=resolved_agent_id,
            success=False,
            result=None,
            error=error,
            confidence=0.0,
        )

    async def forward_direct_message(
        self,
        target_node_id: str,
        intent: IntentMessage,
    ) -> IntentResult:
        """Forward one direct_message to one configured node and agent."""
        if not self._directed_admission_open:
            return self._directed_error(
                intent, "federation_target_node_unavailable"
            )
        if not _is_safe_node_id(target_node_id) or target_node_id == self._node_id:
            return self._directed_error(
                intent, "federation_target_node_invalid"
            )
        configured_peers = {
            peer.node_id for peer in self._config.peers
        }
        if (
            target_node_id not in configured_peers
            or target_node_id not in self._transport.connected_peers
        ):
            return self._directed_error(
                intent, "federation_target_node_unavailable"
            )
        if intent.intent != "direct_message":
            return self._directed_error(
                intent, "federation_directed_intent_not_allowed"
            )
        if not _is_safe_agent_id(intent.target_agent_id):
            return self._directed_error(
                intent, "federation_target_agent_invalid"
            )
        if not _is_safe_intent_id(intent.id):
            return self._directed_error(
                intent, "federation_payload_invalid"
            )
        if type(intent.params) is not dict:
            return self._directed_error(
                intent, "federation_payload_invalid"
            )
        ttl_seconds = _normalize_origin_ttl(intent.ttl_seconds)
        if ttl_seconds is None:
            return self._directed_error(
                intent, "federation_payload_invalid"
            )
        directed_params, params_error = _directed_dm_params(intent.params)
        if params_error is not None or directed_params is None:
            return self._directed_error(intent, params_error or "federation_payload_invalid")
        try:
            payload = _strict_json_detach({
                "delivery_mode": _DIRECTED_DM_MODE,
                "target_node_id": target_node_id,
                "target_agent_id": intent.target_agent_id,
                "intent": "direct_message",
                "params": directed_params,
                "id": intent.id,
                "ttl_seconds": ttl_seconds,
            })
        except (TypeError, ValueError, OverflowError):
            return self._directed_error(
                intent, "federation_payload_not_serializable"
            )
        message = FederationMessage(
            type="intent_request",
            source_node=self._node_id,
            payload=payload,
            timestamp=time.monotonic(),
        )
        if not _is_safe_correlation_id(message.message_id):
            return self._directed_error(
                intent, "federation_target_delivery_failed"
            )
        timeout_ms = max(1, math.ceil(ttl_seconds * 1000.0))
        try:
            response = await self._transport.request_peer(
                target_node_id,
                message,
                timeout_ms,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_code = (
                "federation_target_node_unavailable"
                if type(exc) is RuntimeError
                and exc.args == ("federation_transport_closed",)
                else "federation_target_delivery_failed"
            )
            logger.warning(
                "Directed federation request failed peer=%s intent_id=%s "
                "action=%s exception_type=%s",
                target_node_id,
                intent.id,
                error_code,
                type(exc).__name__,
            )
            return self._directed_error(intent, error_code)
        if response is None:
            return self._directed_error(intent, "federation_peer_timeout")
        if (
            type(response) is not FederationMessage
            or type(response.type) is not str
            or response.type != "intent_response"
            or type(response.source_node) is not str
            or response.source_node != target_node_id
            or not _is_safe_correlation_id(response.message_id)
            or response.message_id != message.message_id
        ):
            return self._directed_error(
                intent, "federation_response_invalid"
            )
        remote_results = _extract_exact_directed_response_payload(
            response.payload
        )
        if remote_results is None:
            return self._directed_error(
                intent, "federation_response_invalid"
            )
        raw_result = list.__getitem__(remote_results, 0)
        detached_result, result_error = _detach_serialized_directed_result(
            raw_result,
            malformed_error="federation_response_invalid",
        )
        if result_error is not None or detached_result is None:
            return self._directed_error(intent, result_error or "federation_response_invalid")
        finalized_result = _finalize_directed_result_for_origin(
            detached_result
        )
        if finalized_result is None:
            return self._directed_error(
                intent, "federation_result_not_serializable"
            )
        detached_result = finalized_result
        if dict.__getitem__(detached_result, "intent_id") != intent.id:
            return self._directed_error(
                intent, "federation_result_correlation_mismatch"
            )
        if dict.__getitem__(detached_result, "agent_id") != intent.target_agent_id:
            return self._directed_error(
                intent, "federation_result_target_mismatch"
            )
        remote_result = IntentResult(
            intent_id=dict.__getitem__(detached_result, "intent_id"),
            agent_id=dict.__getitem__(detached_result, "agent_id"),
            success=dict.__getitem__(detached_result, "success"),
            result=dict.__getitem__(detached_result, "result"),
            error=dict.__getitem__(detached_result, "error"),
            confidence=dict.__getitem__(detached_result, "confidence"),
        )
        # BF-799: put the carried disclosure back where the LOCAL sink looks for
        # it. The bridge never interprets it -- `ToolFailures.from_wire` at the
        # consumer validates and degrades to empty on anything malformed.
        if dict.__contains__(detached_result, DM_REPLY_METADATA_KEY):
            remote_result.metadata[DM_REPLY_METADATA_KEY] = dict.__getitem__(
                detached_result, DM_REPLY_METADATA_KEY
            )
        if self._validate_fn:
            try:
                valid = await self._validate_fn(remote_result)
                if not valid:
                    return self._directed_error(
                        intent, "federation_result_validation_failed"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Directed federation result validator failed peer=%s "
                    "intent_id=%s target=%s "
                    "action=validator_passed_without_validation "
                    "exception_type=%s",
                    target_node_id,
                    intent.id,
                    intent.target_agent_id,
                    type(exc).__name__,
                )
        self._stats["intents_forwarded"] += 1
        self._stats["results_collected"] += 1
        return remote_result

    async def handle_inbound(self, message: FederationMessage) -> None:
        """Handle a message received from a peer.

        Dispatches by message type:
        - intent_request: broadcast locally (federated=False), send results back
        - intent_response: route to pending request (correlation by message_id)
        - gossip_self_model: update router's peer model
        - ping: respond with pong
        """
        if message.type == "intent_request":
            await self._handle_intent_request(message)
        elif message.type == "relay_one_way":
            await self._handle_relay_one_way(message)
            return
        elif message.type == "intent_response":
            # Route to pending request by delivering to transport's response queue
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "gossip_self_model":
            self._handle_gossip(message)
        elif message.type == "ping":
            pong = FederationMessage(
                type="pong",
                source_node=self._node_id,
                message_id=message.message_id,
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, pong)
        elif message.type == "chain_request":
            await self._handle_chain_request(message)
        elif message.type == "chain_response":
            await self._transport.deliver_response(message.source_node, message)
        elif message.type == "transfer_request":
            await self._handle_transfer_request(message)
        elif message.type == "transfer_response":
            await self._transport.deliver_response(message.source_node, message)

    async def _handle_relay_one_way(
        self,
        message: FederationMessage,
    ) -> None:
        if not self._relay_admission_open:
            return
        if (
            type(message) is not FederationMessage
            or type(message.type) is not str
            or message.type != "relay_one_way"
        ):
            return
        if not is_safe_relay_node_id(self._node_id):
            return
        if (
            not is_safe_relay_node_id(message.source_node)
            or message.source_node == self._node_id
        ):
            return
        if message.source_node not in {
            peer.node_id for peer in self._config.peers
        }:
            return
        if (
            not _is_safe_correlation_id(message.message_id)
            or not is_valid_relay_timestamp(message.timestamp)
        ):
            return
        exact = extract_relay_wire_payload(message.payload)
        if exact is None:
            return
        relay_version = dict.__getitem__(exact, "relay_version")
        hop_count = dict.__getitem__(exact, "hop_count")
        target_node_id = dict.__getitem__(exact, "target_node_id")
        topic = dict.__getitem__(exact, "topic")
        if type(relay_version) is not int or relay_version != 1:
            return
        if type(hop_count) is not int or hop_count != 0:
            return
        if (
            not is_safe_relay_node_id(target_node_id)
            or target_node_id != self._node_id
        ):
            return
        if not is_canonical_relay_topic(topic):
            return
        contract = self._relay_topics.get(topic)
        if contract is None:
            return

        now = time.monotonic()
        rate_key = (message.source_node, topic)
        window = self._relay_rate.get(rate_key)
        if window is not None:
            cutoff = now - 1.0
            while window and window[0] <= cutoff:
                window.popleft()
            if not window:
                self._relay_rate.pop(rate_key, None)
                window = None
            elif len(window) >= RELAY_RATE_LIMIT_PER_SECOND:
                return

        finalized = finalize_relay_wire_payload(
            source_node=message.source_node,
            message_id=message.message_id,
            relay_payload=exact,
            timestamp=message.timestamp,
        )
        if finalized is None:
            return
        validation_copy = finalize_relay_wire_payload(
            source_node=message.source_node,
            message_id=message.message_id,
            relay_payload=finalized,
            timestamp=message.timestamp,
        )
        if validation_copy is None:
            return
        try:
            valid = contract.validate_payload(
                dict.__getitem__(validation_copy, "payload")
            )
        except Exception as exc:
            logger.warning(
                "Inbound one-way federation relay validator failed source=%s "
                "topic=%s reason=validator_exception action=drop "
                "exception_type=%s",
                message.source_node,
                topic,
                type(exc).__name__,
            )
            return
        if valid is not True:
            return

        if window is None:
            window = deque()
            self._relay_rate[rate_key] = window
        window.append(now)
        try:
            await contract.sink(
                message.source_node,
                dict.__getitem__(finalized, "payload"),
            )
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            logger.warning(
                "Inbound one-way federation relay sink failed source=%s "
                "topic=%s reason=plugin_cancelled_error action=drop "
                "exception_type=CancelledError",
                message.source_node,
                topic,
            )
        except Exception as exc:
            logger.warning(
                "Inbound one-way federation relay sink failed source=%s "
                "topic=%s reason=sink_exception action=drop exception_type=%s",
                message.source_node,
                topic,
                type(exc).__name__,
            )

    async def _handle_intent_request(self, message: FederationMessage) -> None:
        """Handle an inbound intent request from a peer."""
        self._stats["intents_received"] += 1

        if type(message.payload) is dict and dict.__contains__(
            message.payload, "delivery_mode"
        ):
            if not _is_safe_correlation_id(message.message_id):
                return
            delivery_mode = dict.__getitem__(
                message.payload, "delivery_mode"
            )
            if type(delivery_mode) is str and delivery_mode == _DIRECTED_DM_MODE:
                await self._handle_direct_message_request(message)
                return
            if self._configured_directed_source(message.source_node):
                await self._send_directed_response(
                    message,
                    self._directed_error(
                        None,
                        "federation_delivery_mode_invalid",
                        intent_id=message.payload.get("id"),
                        agent_id=message.payload.get("target_agent_id"),
                    ),
                )
            return

        payload = message.payload
        intent = IntentMessage(
            intent=payload.get("intent", ""),
            params=payload.get("params", {}),
            urgency=payload.get("urgency", 0.5),
            context=payload.get("context", ""),
            id=payload.get("id", uuid.uuid4().hex),
            ttl_seconds=payload.get("ttl_seconds", 30.0),
        )

        # AD-731a-1c/BF-672: resolve referenced bytes before local agents
        # consume them. Ordinary resolver failures degrade to the existing
        # broadcast path; cancellation remains lifecycle control.
        attachment_resolver = self._attachment_resolver
        if attachment_resolver is not None:
            try:
                await attachment_resolver(intent.params, message.source_node)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "AD-731a-1c: attachment resolution failed; local broadcast "
                    "will proceed without prefetched bytes",
                    exc_info=True,
                )

        # AD-1297: the fact the FORWARDER cannot see -- did this node have a
        # handler at all. Captured before the fan-out, because the roster can
        # change during it, and reported regardless of how the broadcast then
        # goes: a peer that admitted the intent and was refused by policy, or
        # whose handler raised, still ADMITTED it. Admission is about delivery,
        # not outcome, and conflating the two would re-fire remote work.
        #
        # It must not cost the peer its reply. Computing this unconditionally
        # put a new raise ABOVE the AD-1276 envelope -- measured against a bus
        # without the method: the peer got no intent_response at all and timed
        # out, which is the exact failure AD-1276 exists to prevent. A node
        # that cannot answer the admission question is in the same position as
        # a pre-AD-1297 peer, so it says nothing and the key is OMITTED, which
        # the forwarder reads as UNKNOWN.
        admitted: bool | None
        try:
            admitted = bool(self._intent_bus.candidate_agent_ids(intent.intent))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            admitted = None
            logger.warning(
                "AD-1297: cannot determine local admission for inbound "
                "federated intent %s from %s (exception_type=%s); the reply "
                "will omit 'admitted', which the peer reads as UNKNOWN so it "
                "does not mistake this node for one without a handler",
                intent.intent, message.source_node, type(exc).__name__,
            )

        # Broadcast locally with federated=False to prevent loop.
        #
        # AD-1276: opts into the raising shape so a POLICY REFUSAL is
        # distinguishable. The default denial shape is ``[]``, so until now a
        # refusal presented to the peer as "no agent answered" -- honest about
        # the outcome, silent about the cause, and identical to the ordinary
        # empty case. The peer could not tell which it had.
        denied_reason: str | None = None
        denied_entry_point = ""
        failure_error: str | None = None
        try:
            local_results = await self._intent_bus.broadcast(
                intent, federated=False, raise_on_denial=True
            )
        except IntentAuthorizationDenied as denial:
            local_results = []
            denied_reason = denial.reason
            denied_entry_point = denial.entry_point
            logger.info(
                "AD-1276: inbound federated intent %s from %s denied by "
                "pre-auth hook '%s'; replying with a denial rather than an "
                "empty result set",
                intent.intent, message.source_node, denial.reason,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # AD-1276: the peer is owed an answer even when the local fan-out
            # fails. Without this the exception escaped to the transport, no
            # intent_response was ever sent, and the peer waited out its
            # timeout -- a local fault presenting to the peer as a dead node.
            local_results = []
            failure_error = type(exc).__name__
            logger.error(
                "AD-1276: local broadcast of inbound federated intent %s from "
                "%s raised %s; replying with a failure so the peer does not "
                "time out",
                intent.intent, message.source_node, failure_error,
                exc_info=True,
            )

        # Build response
        serialized_results = []
        for r in local_results:
            serialized_results.append({
                "intent_id": r.intent_id,
                "agent_id": r.agent_id,
                "success": r.success,
                "result": r.result,
                "error": r.error,
                "confidence": r.confidence,
            })

        # AD-1276: the same envelope Section 1 puts on the NATS reply -- one
        # shape, two transports. ``results`` is still carried so a peer that
        # predates the `denied`/`error` keys behaves exactly as it did: the
        # reader for this path is ``forward_intent``, which does
        # ``response.payload.get("results", [])``. The DIRECTED path is a
        # different reader with an EXACT key set (``_DIRECTED_RESPONSE_KEYS``),
        # which is one more reason these keys are added here and never there.
        response_payload: dict[str, Any] = {"results": serialized_results}
        if admitted is not None:
            response_payload["admitted"] = admitted
        if denied_reason is not None:
            response_payload["denied"] = True
            response_payload["reason"] = denied_reason
            response_payload["entry_point"] = denied_entry_point
        elif failure_error is not None:
            response_payload["error"] = failure_error

        response = FederationMessage(
            type="intent_response",
            source_node=self._node_id,
            message_id=message.message_id,
            payload=response_payload,
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(message.source_node, response)

    def _configured_directed_source(self, source_node: Any) -> bool:
        if not _is_safe_node_id(source_node) or source_node == self._node_id:
            return False
        return source_node in {peer.node_id for peer in self._config.peers}

    async def _send_directed_response(
        self,
        request: FederationMessage,
        result: IntentResult,
    ) -> None:
        serialized_result = _detach_local_directed_result(result)
        payload = (
            _compact_detach_directed_response(serialized_result)
            if serialized_result is not None
            else None
        )
        if payload is None:
            request_payload = request.payload
            request_intent_id = (
                dict.__getitem__(request_payload, "id")
                if type(request_payload) is dict
                and dict.__contains__(request_payload, "id")
                else ""
            )
            request_agent_id = (
                dict.__getitem__(request_payload, "target_agent_id")
                if type(request_payload) is dict
                and dict.__contains__(request_payload, "target_agent_id")
                else ""
            )
            synthetic = self._directed_error(
                None,
                "federation_result_not_serializable",
                intent_id=request_intent_id,
                agent_id=request_agent_id,
            )
            detached_synthetic = _detach_local_directed_result(synthetic)
            if detached_synthetic is None:
                return
            payload = _compact_detach_directed_response(detached_synthetic)
            if payload is None:
                return
        response = FederationMessage(
            type="intent_response",
            source_node=self._node_id,
            message_id=request.message_id,
            payload=payload,
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(request.source_node, response)

    async def _handle_direct_message_request(
        self,
        message: FederationMessage,
    ) -> None:
        if (
            type(message) is not FederationMessage
            or type(message.type) is not str
            or message.type != "intent_request"
            or not self._configured_directed_source(message.source_node)
            or not _is_safe_correlation_id(message.message_id)
        ):
            return
        payload = _extract_exact_directed_request_payload(message.payload)
        if payload is None:
            raw_payload = message.payload
            raw_intent_id = (
                dict.__getitem__(raw_payload, "id")
                if type(raw_payload) is dict
                and dict.__contains__(raw_payload, "id")
                else ""
            )
            raw_agent_id = (
                dict.__getitem__(raw_payload, "target_agent_id")
                if type(raw_payload) is dict
                and dict.__contains__(raw_payload, "target_agent_id")
                else ""
            )
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_payload_invalid",
                    intent_id=raw_intent_id,
                    agent_id=raw_agent_id,
                ),
            )
            return
        intent_id = dict.__getitem__(payload, "id")
        target_agent_id = dict.__getitem__(payload, "target_agent_id")
        target_node_id = dict.__getitem__(payload, "target_node_id")
        directed_intent = dict.__getitem__(payload, "intent")
        delivery_mode = dict.__getitem__(payload, "delivery_mode")
        if type(delivery_mode) is not str or delivery_mode != _DIRECTED_DM_MODE:
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_payload_invalid",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        if type(target_node_id) is not str or target_node_id != self._node_id:
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_target_node_mismatch",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        if type(directed_intent) is not str or directed_intent != "direct_message":
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_directed_intent_not_allowed",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        if not _is_safe_agent_id(target_agent_id):
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_target_agent_invalid",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        if not _is_safe_intent_id(intent_id):
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_payload_invalid",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        ttl_seconds = _normalize_wire_ttl(
            dict.__getitem__(payload, "ttl_seconds")
        )
        if ttl_seconds is None:
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_payload_invalid",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        raw_params = dict.__getitem__(payload, "params")
        if type(raw_params) is not dict:
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_payload_invalid",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        params, params_error = _validate_directed_wire_params(raw_params)
        if params_error is not None or params is None:
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    params_error or "federation_payload_invalid",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        if not self._intent_bus.has_subscriber(target_agent_id):
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_target_not_found",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        params["from"] = f"federation:{message.source_node}"
        params["federation_source_node"] = message.source_node
        params["federation_message_id"] = message.message_id
        params["session"] = False
        params["session_history"] = []
        try:
            params = _strict_json_detach(params)
        except (TypeError, ValueError, OverflowError):
            await self._send_directed_response(
                message,
                self._directed_error(
                    None,
                    "federation_payload_not_serializable",
                    intent_id=intent_id,
                    agent_id=target_agent_id,
                ),
            )
            return
        intent = IntentMessage(
            intent="direct_message",
            params=params,
            urgency=0.5,
            context=f"federation:{message.source_node}",
            id=intent_id,
            ttl_seconds=ttl_seconds,
            target_agent_id=target_agent_id,
        )
        attachment_resolver = self._attachment_resolver
        if attachment_resolver is not None:
            try:
                await attachment_resolver(intent.params, message.source_node)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Directed federation attachment resolution failed "
                    "source=%s message_id=%s target=%s "
                    "action=deliver_to_exact_target_without_prefetch "
                    "exception_type=%s",
                    message.source_node,
                    message.message_id,
                    target_agent_id,
                    type(exc).__name__,
                )
        try:
            local_result = await self._intent_bus.send(intent)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Directed federation target delivery failed source=%s "
                "message_id=%s intent_id=%s target=%s "
                "action=federation_target_delivery_failed "
                "exception_type=%s",
                message.source_node,
                message.message_id,
                intent_id,
                target_agent_id,
                type(exc).__name__,
            )
            local_result = self._directed_error(
                None,
                "federation_target_delivery_failed",
                intent_id=intent_id,
                agent_id=target_agent_id,
            )
        if local_result is None:
            local_result = self._directed_error(
                None,
                "federation_target_declined",
                intent_id=intent_id,
                agent_id=target_agent_id,
            )
        await self._send_directed_response(message, local_result)

    def _handle_gossip(self, message: FederationMessage) -> None:
        """Handle an inbound gossip self-model message."""
        payload = message.payload
        model = NodeSelfModel(
            node_id=payload.get("node_id", message.source_node),
            capabilities=payload.get("capabilities", []),
            pool_sizes=payload.get("pool_sizes", {}),
            agent_count=payload.get("agent_count", 0),
            health=payload.get("health", 0.0),
            uptime_seconds=payload.get("uptime_seconds", 0.0),
            timestamp=payload.get("timestamp", 0.0),
        )
        self._router.update_peer_model(model)

    # ── AD-443e: Mobility wire-protocol handlers ──────────────────────────

    async def _handle_chain_request(self, message: FederationMessage) -> None:
        """Peer asks for our exported Identity Ledger chain."""
        if self._identity_registry is None:
            response = FederationMessage(
                type="chain_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={"blocks": [], "error": "identity_registry not wired"},
                timestamp=time.monotonic(),
            )
        else:
            blocks = await self._identity_registry.export_chain()
            response = FederationMessage(
                type="chain_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={"blocks": blocks},
                timestamp=time.monotonic(),
            )
        await self._transport.send_to_peer(message.source_node, response)

    async def _handle_transfer_request(self, message: FederationMessage) -> None:
        """Peer wants to transfer an agent to us.

        Pipeline: import_chain (validates) -> import_transfer_certificate
        (validates). Slot reassignment is NOT performed automatically.
        """
        from probos.mobility import TransferCertificate

        if self._identity_registry is None:
            response = FederationMessage(
                type="transfer_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={
                    "accepted": False,
                    "message": "identity_registry not wired",
                    "agent_uuid": None,
                },
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, response)
            return

        cert_dict = message.payload.get("cert_dict") or {}
        chain_blocks = message.payload.get("chain_blocks") or []
        try:
            cert = TransferCertificate.from_dict(cert_dict)
        except (KeyError, TypeError) as exc:
            response = FederationMessage(
                type="transfer_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={
                    "accepted": False,
                    "message": f"malformed cert_dict: {exc!s}",
                    "agent_uuid": None,
                },
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, response)
            return

        chain_ok, chain_msg = await self._identity_registry.import_chain(chain_blocks)
        if not chain_ok:
            response = FederationMessage(
                type="transfer_response",
                source_node=self._node_id,
                message_id=message.message_id,
                payload={
                    "accepted": False,
                    "message": f"chain rejected: {chain_msg}",
                    "agent_uuid": None,
                },
                timestamp=time.monotonic(),
            )
            await self._transport.send_to_peer(message.source_node, response)
            return

        cert_ok, cert_msg = await self._identity_registry.import_transfer_certificate(cert)
        if cert_ok:
            self._stats["transfers_received"] += 1

            # AD-479e: optional designed-agent template reconstruction.
            designed_payload = message.payload.get("designed_agent_payload")
            if designed_payload:
                designed_msg = await self._reconstruct_designed_agent(
                    designed_payload, source_node=message.source_node,
                )
                if designed_msg is not None:
                    cert_msg = f"{cert_msg}; designed_agent_note={designed_msg}"

        response = FederationMessage(
            type="transfer_response",
            source_node=self._node_id,
            message_id=message.message_id,
            payload={
                "accepted": cert_ok,
                "message": cert_msg,
                "agent_uuid": cert.agent_uuid if cert_ok else None,
            },
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(message.source_node, response)

    async def request_chain(self, peer_node_id: str) -> list[dict[str, Any]]:
        """Outbound: ask a specific peer for its exported chain."""
        msg = FederationMessage(
            type="chain_request",
            source_node=self._node_id,
            payload={},
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(peer_node_id, msg)
        response = await self._transport.receive_with_timeout(
            peer_node_id, self._config.forward_timeout_ms
        )
        if response is None:
            logger.warning(
                "Chain request to %s timed out; returning empty chain", peer_node_id,
            )
            return []
        return list(response.payload.get("blocks", []))

    async def request_transfer(
        self,
        peer_node_id: str,
        certificate: "TransferCertificate",
        chain_blocks: list[dict[str, Any]],
        designed_agent_payload: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        """Outbound: ship an agent's transfer cert + supporting chain to a peer.

        AD-479e: optional ``designed_agent_payload`` carries the agent's
        ``instructions`` string + designed-template metadata so the destination
        ship can rehydrate the designed template via CodeValidator + AgentDesigner.
        """
        outbound_payload: dict[str, Any] = {
            "cert_dict": certificate.to_dict(),
            "chain_blocks": chain_blocks,
        }
        if designed_agent_payload is not None:
            outbound_payload["designed_agent_payload"] = designed_agent_payload
        msg = FederationMessage(
            type="transfer_request",
            source_node=self._node_id,
            payload=outbound_payload,
            timestamp=time.monotonic(),
        )
        await self._transport.send_to_peer(peer_node_id, msg)
        self._stats["transfers_sent"] += 1
        response = await self._transport.receive_with_timeout(
            peer_node_id, self._config.forward_timeout_ms
        )
        if response is None:
            logger.warning(
                "Transfer request to %s timed out; agent %s remains on origin ship",
                peer_node_id, certificate.did,
            )
            return False, "timeout"
        accepted = bool(response.payload.get("accepted", False))
        message_text = str(response.payload.get("message", ""))
        return accepted, message_text

    async def _gossip_loop(self) -> None:
        """Periodically broadcast this node's self-model to all peers."""
        while not self._stopped:
            try:
                await asyncio.sleep(self._config.gossip_interval_seconds)
                model = self._self_model_fn()
                msg = FederationMessage(
                    type="gossip_self_model",
                    source_node=self._node_id,
                    payload={
                        "node_id": model.node_id,
                        "capabilities": model.capabilities,
                        "pool_sizes": model.pool_sizes,
                        "agent_count": model.agent_count,
                        "health": model.health,
                        "uptime_seconds": model.uptime_seconds,
                        "timestamp": model.timestamp,
                    },
                    timestamp=time.monotonic(),
                )
                await self._transport.send_to_all_peers(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Gossip loop error: %s", e)

    def _record_zmq_peer_outcome(
        self,
        *,
        peer_node_id: str,
        success: bool,
        intent_type: str,
    ) -> None:
        """AD-479b: update TrustNetwork + AD-479c FederationHebbianMap for a ZMQ peer.

        Idempotent on missing trust_network / hebbian_map. The trust record id
        is namespaced ``federation_peer:{node_id}`` to keep ZMQ peer records
        from colliding with AD-480f MCP/A2A peer records (which use the
        ``mcp-peer:`` / ``a2a-peer:`` namespaces per peer.py + AD-480g).
        """
        trust_network = self._trust_network
        if trust_network is not None:
            record_id = f"federation_peer:{peer_node_id}"
            try:
                trust_network.record_outcome(
                    record_id,
                    success=success,
                    weight=1.0,
                    intent_type=intent_type,
                    source="federation_outcome",
                )
            except Exception as exc:
                logger.debug("AD-479b: trust_network.record_outcome raised: %s", exc)
        hebbian_map = self._hebbian_map
        if hebbian_map is not None:
            try:
                hebbian_map.record_outcome(
                    intent_name=intent_type,
                    peer_node_id=peer_node_id,
                    success=success,
                )
            except Exception as exc:
                logger.debug("AD-479c: hebbian_map.record_outcome raised: %s", exc)

    async def _reconstruct_designed_agent(
        self,
        payload: dict[str, Any],
        *,
        source_node: str,
    ) -> str | None:
        """Keep AD-479e designed-agent reconstruction explicitly dormant.

        BF-672 removes the broad runtime handle because production never wired
        it. Rehydration requires a future narrow, typed, governance-complete
        seam; the production-observable result remains ``no_runtime_handle``.
        """
        return "no_runtime_handle"

    async def add_peer(self, peer_config: Any) -> bool:
        """AD-479h: register a runtime-discovered peer.

        Returns True if newly registered, False if already known. Idempotent
        on the underlying transport.
        """
        add = getattr(self._transport, "add_peer", None)
        if not callable(add):
            logger.debug(
                "AD-479h: transport %s has no add_peer hook",
                type(self._transport).__name__,
            )
            return False
        try:
            result = add(peer_config)
            if asyncio.iscoroutine(result):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.warning("AD-479h: transport.add_peer raised: %s", exc)
            return False

    def federation_status(self) -> dict[str, Any]:
        """Return federation status for shell/panels."""
        peer_models = {}
        for nid, model in self._router.known_peers.items():
            peer_models[nid] = {
                "capabilities": model.capabilities,
                "pool_sizes": model.pool_sizes,
                "agent_count": model.agent_count,
                "health": model.health,
                "uptime_seconds": model.uptime_seconds,
                "timestamp": model.timestamp,
            }

        return {
            "node_id": self._node_id,
            "bind_address": self._config.bind_address,
            "connected_peers": self._transport.connected_peers,
            "peer_models": peer_models,
            "intents_forwarded": self._stats["intents_forwarded"],
            "intents_received": self._stats["intents_received"],
            "results_collected": self._stats["results_collected"],
            "gossip_interval": self._config.gossip_interval_seconds,
        }
