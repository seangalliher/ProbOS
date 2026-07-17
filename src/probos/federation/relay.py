"""Bounded contracts for federation one-way relay messages (AD-1123).

Configured-peer admission is a deployment/transport ACL boundary, not cryptographic source authentication.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

RelayPayloadValidator = Callable[[dict[str, Any]], bool]
RelaySink = Callable[[str, dict[str, Any]], Awaitable[None]]

MAX_RELAY_DEPTH = 8
MAX_RELAY_NODES = 512
MAX_RELAY_STRING_CHARS = 4_096
MAX_RELAY_STRING_UTF8_BYTES = 32_768
MAX_RELAY_ENVELOPE_BYTES = 32_768
MAX_RELAY_TOPICS = 16
MAX_RELAY_TOPIC_CHARS = 64
RELAY_RATE_LIMIT_PER_SECOND = 64

_SIGNED_INT64_MIN = -(2**63)
_SIGNED_INT64_MAX = 2**63 - 1
_RELAY_NODE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_RELAY_TOPIC_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_RELAY_PAYLOAD_KEYS = frozenset({
    "relay_version",
    "target_node_id",
    "topic",
    "payload",
    "hop_count",
})
_FORBIDDEN_SECRET_KEYS = frozenset({
    "password",
    "passwd",
    "secret",
    "token",
    "access_token",
    "refresh_token",
    "api_key",
    "authorization",
    "cookie",
    "set-cookie",
    "private_key",
    "client_secret",
})
_FORBIDDEN_STRING_PREFIXES = (
    "data:",
    "bearer ",
    "basic ",
    "-----begin private key-----",
    "-----begin rsa private key-----",
    "-----begin openssh private key-----",
)
_ASCII_WHITESPACE = " \t\n\r\v\f"


@dataclass(frozen=True)
class FederationRelayTopic:
    name: str
    validate_payload: RelayPayloadValidator
    sink: RelaySink


def is_canonical_relay_topic(value: Any) -> bool:
    """Return whether *value* is an exact canonical relay topic."""
    return type(value) is str and _RELAY_TOPIC_RE.fullmatch(value) is not None


def is_safe_relay_node_id(value: Any) -> bool:
    """Return whether *value* is an exact safe relay node identifier."""
    return type(value) is str and _RELAY_NODE_ID_RE.fullmatch(value) is not None


def is_valid_relay_timestamp(value: Any) -> bool:
    """Return whether sender-local envelope metadata is bounded and finite."""
    if type(value) is int:
        return _SIGNED_INT64_MIN <= value <= _SIGNED_INT64_MAX
    return type(value) is float and math.isfinite(value)


def _has_exact_callable_contract(
    value: Any,
    *,
    positional_count: int,
    require_async: bool,
) -> bool:
    try:
        if not callable(value):
            return False
        is_async = inspect.iscoroutinefunction(value)
        parameters = tuple(inspect.signature(value).parameters.values())
        if len(parameters) != positional_count:
            return False
        positional_only = all(
            parameter.kind
            in (
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            )
            for parameter in parameters
        )
    except Exception:
        return False
    return positional_only and is_async is require_async


def build_relay_topic_registry(
    relay_topics: tuple[FederationRelayTopic, ...],
) -> Mapping[str, FederationRelayTopic]:
    """Validate and freeze bridge-construction relay topic policy."""
    if type(relay_topics) is not tuple:
        raise ValueError("relay_topics_invalid")
    topic_count = tuple.__len__(relay_topics)
    if topic_count > MAX_RELAY_TOPICS:
        raise ValueError("relay_topics_invalid")

    registry: dict[str, FederationRelayTopic] = {}
    for index in range(topic_count):
        contract = tuple.__getitem__(relay_topics, index)
        if type(contract) is not FederationRelayTopic:
            raise ValueError("relay_topics_invalid")
        if not is_canonical_relay_topic(contract.name):
            raise ValueError("relay_topics_invalid")
        if contract.name in registry:
            raise ValueError("relay_topics_invalid")
        validator = contract.validate_payload
        sink = contract.sink
        validator_valid = _has_exact_callable_contract(
            validator,
            positional_count=1,
            require_async=False,
        )
        sink_valid = _has_exact_callable_contract(
            sink,
            positional_count=2,
            require_async=True,
        )
        if not validator_valid or not sink_valid:
            raise ValueError("relay_topics_invalid")
        registry[contract.name] = contract
    return MappingProxyType(registry)


def extract_relay_wire_payload(payload: Any) -> dict[str, Any] | None:
    """Return an exact five-key relay payload without traversing its body."""
    if type(payload) is not dict or dict.__len__(payload) != len(
        _RELAY_PAYLOAD_KEYS
    ):
        return None
    seen: set[str] = set()
    for key in dict.keys(payload):
        if type(key) is not str or key not in _RELAY_PAYLOAD_KEYS:
            return None
        seen.add(key)
    return payload if seen == _RELAY_PAYLOAD_KEYS else None


def _ascii_lower(value: str) -> str:
    lowered: list[str] = []
    length = str.__len__(value)
    for index in range(length):
        character = str.__getitem__(value, index)
        codepoint = ord(character)
        if 65 <= codepoint <= 90:
            character = chr(codepoint + 32)
        lowered.append(character)
    return "".join(lowered)


def _is_forbidden_secret_key(value: str) -> bool:
    return _ascii_lower(value) in _FORBIDDEN_SECRET_KEYS


def _starts_with_forbidden_prefix(value: str) -> bool:
    length = str.__len__(value)
    offset = 0
    while (
        offset < length
        and str.__getitem__(value, offset) in _ASCII_WHITESPACE
    ):
        offset += 1
    for prefix in _FORBIDDEN_STRING_PREFIXES:
        prefix_length = str.__len__(prefix)
        if length - offset < prefix_length:
            continue
        matches = True
        for index in range(prefix_length):
            character = str.__getitem__(value, offset + index)
            codepoint = ord(character)
            if 65 <= codepoint <= 90:
                character = chr(codepoint + 32)
            if character != str.__getitem__(prefix, index):
                matches = False
                break
        if matches:
            return True
    return False


def detach_relay_payload(value: Any) -> dict[str, Any]:
    """Return an exact-built-in detached JSON object under fixed work bounds."""
    if type(value) is not dict:
        raise ValueError("relay_payload_invalid")

    root: list[Any] = [None]
    active_container_ids: set[int] = set()
    node_count = 0
    string_bytes = 0
    stack: list[tuple[Any, ...]] = [("visit", value, 0, root, 0)]

    def _reject() -> None:
        raise ValueError("relay_payload_invalid")

    def _assign(
        parent: list[Any] | dict[str, Any],
        slot: int | str,
        item: Any,
    ) -> None:
        if type(parent) is list:
            list.__setitem__(parent, slot, item)
        else:
            dict.__setitem__(parent, slot, item)

    def _account_string(item: str, *, secret_key: bool = False) -> None:
        nonlocal string_bytes
        if str.__len__(item) > MAX_RELAY_STRING_CHARS:
            _reject()
        try:
            encoded = str.encode(item, "utf-8")
        except UnicodeEncodeError:
            _reject()
            return
        string_bytes += bytes.__len__(encoded)
        if string_bytes > MAX_RELAY_STRING_UTF8_BYTES:
            _reject()
        if secret_key and _is_forbidden_secret_key(item):
            _reject()
        if _starts_with_forbidden_prefix(item):
            _reject()

    while stack:
        frame = stack.pop()
        operation = frame[0]
        if operation == "exit":
            active_container_ids.remove(frame[1])
            continue
        if operation == "list_next":
            source, index, length, depth, detached = frame[1:]
            if index >= length:
                continue
            list.append(detached, None)
            stack.append((
                "list_next",
                source,
                index + 1,
                length,
                depth,
                detached,
            ))
            stack.append((
                "visit",
                list.__getitem__(source, index),
                depth + 1,
                detached,
                index,
            ))
            continue
        if operation == "dict_next":
            source, iterator, index, length, depth, detached = frame[1:]
            if index >= length:
                continue
            try:
                key, item = next(iterator)
            except StopIteration:
                _reject()
                continue
            if type(key) is not str or depth + 1 > MAX_RELAY_DEPTH:
                _reject()
            node_count += 1
            if node_count > MAX_RELAY_NODES:
                _reject()
            _account_string(key, secret_key=True)
            stack.append((
                "dict_next",
                source,
                iterator,
                index + 1,
                length,
                depth,
                detached,
            ))
            stack.append(("visit", item, depth + 1, detached, key))
            continue

        item, depth, parent, slot = frame[1:]
        node_count += 1
        if node_count > MAX_RELAY_NODES or depth > MAX_RELAY_DEPTH:
            _reject()
        item_type = type(item)
        if item is None or item_type is bool:
            _assign(parent, slot, item)
        elif item_type is int:
            if item < _SIGNED_INT64_MIN or item > _SIGNED_INT64_MAX:
                _reject()
            _assign(parent, slot, item)
        elif item_type is float:
            if not math.isfinite(item):
                _reject()
            _assign(parent, slot, item)
        elif item_type is str:
            _account_string(item)
            _assign(parent, slot, item)
        elif item_type is list:
            length = list.__len__(item)
            if node_count + length > MAX_RELAY_NODES:
                _reject()
            container_id = id(item)
            if container_id in active_container_ids:
                _reject()
            detached_list: list[Any] = []
            _assign(parent, slot, detached_list)
            active_container_ids.add(container_id)
            stack.append(("exit", container_id))
            stack.append(("list_next", item, 0, length, depth, detached_list))
        elif item_type is dict:
            length = dict.__len__(item)
            if node_count + 2 * length > MAX_RELAY_NODES:
                _reject()
            container_id = id(item)
            if container_id in active_container_ids:
                _reject()
            detached_dict: dict[str, Any] = {}
            _assign(parent, slot, detached_dict)
            active_container_ids.add(container_id)
            stack.append(("exit", container_id))
            stack.append((
                "dict_next",
                item,
                iter(dict.items(item)),
                0,
                length,
                depth,
                detached_dict,
            ))
        else:
            _reject()

    detached = list.__getitem__(root, 0)
    if type(detached) is not dict:
        raise ValueError("relay_payload_invalid")
    return detached


def finalize_relay_wire_payload(
    *,
    source_node: str,
    message_id: str,
    relay_payload: dict[str, Any],
    timestamp: int | float,
) -> dict[str, Any] | None:
    """Detach and cap the complete normalized five-field transport object."""
    if (
        not is_safe_relay_node_id(source_node)
        or type(message_id) is not str
        or not is_valid_relay_timestamp(timestamp)
    ):
        return None
    exact = extract_relay_wire_payload(relay_payload)
    if exact is None:
        return None
    relay_version = dict.__getitem__(exact, "relay_version")
    target_node_id = dict.__getitem__(exact, "target_node_id")
    topic = dict.__getitem__(exact, "topic")
    hop_count = dict.__getitem__(exact, "hop_count")
    if (
        type(relay_version) is not int
        or relay_version != 1
        or not is_safe_relay_node_id(target_node_id)
        or not is_canonical_relay_topic(topic)
        or type(hop_count) is not int
        or hop_count != 0
    ):
        return None
    nested_payload = dict.__getitem__(exact, "payload")
    try:
        detached_payload = detach_relay_payload(nested_payload)
    except ValueError:
        return None
    normalized_payload = {
        "relay_version": relay_version,
        "target_node_id": target_node_id,
        "topic": topic,
        "payload": detached_payload,
        "hop_count": hop_count,
    }
    normalized_wire = {
        "type": "relay_one_way",
        "source_node": source_node,
        "message_id": message_id,
        "payload": normalized_payload,
        "timestamp": timestamp,
    }
    try:
        encoded = json.dumps(
            normalized_wire,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (OverflowError, TypeError, UnicodeEncodeError, ValueError):
        return None
    if bytes.__len__(encoded) > MAX_RELAY_ENVELOPE_BYTES:
        return None
    try:
        detached_wire = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(detached_wire) is not dict:
        return None
    detached_relay = dict.__getitem__(detached_wire, "payload")
    return detached_relay if type(detached_relay) is dict else None
