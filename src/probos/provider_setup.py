"""Provider setup behind ``probos setup`` / ``probos model`` (AD-1135, #1054).

Provider presets, the managed ``cognitive`` keys, input validation, classified
provider probes and a fail-closed, line-preserving config editor. It runs in the
operator's own CLI process against a URL the operator typed; within ``probos``
only ``probos.__main__`` imports it.

Setup never prints the API key. Probe messages never include a 401 or 403 body,
any part of a redirect's Location, or a chat reply's text. The key's literal,
percent-encoded (``quote``, ``quote_plus``) and base64 (bare and
``Bearer``-prefixed) forms are what ``carries_key`` detects and ``redact``
replaces with ``<redacted>``. A listed model ID holding one is withheld from
``model_ids``, so setup never shows, suggests or writes it (B8); other provider
excerpts are shown redacted. A provider can still echo another transformation,
such as its own masked form ``sk-abcd****wxyz``. Tests measure each of these
properties.
"""

from __future__ import annotations

import base64
import codecs
import difflib
import ipaddress
import os
import re
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote, quote_plus, urlsplit

import httpx
import yaml
from pydantic import ValidationError

from probos.cognitive.image_gen_dispatch import is_image_gen_tier_configured
from probos.cognitive.llm_client import _LLM_TIERS, _TIER_ORDER
from probos.cognitive.vision_dispatch import is_vision_tier_configured
from probos.config import CognitiveConfig, load_config

# The text-only fallback chain (AD-706c-2 / BF-269, llm_client.py:44-48).
TEXT_TIERS: tuple[str, ...] = _TIER_ORDER
# Every other runtime tier; setup writes none of their keys, nor the shared URL while one with a model uses it (B7).
OPTIONAL_TIERS: tuple[str, ...] = tuple(tier for tier in _LLM_TIERS if tier not in TEXT_TIERS)
# Each optional tier's configured-ness as its runtime consumer reads it (B8); a test pins the keys to OPTIONAL_TIERS.
TIER_CONFIGURED_CHECKS: Mapping[str, Callable[[CognitiveConfig], bool]] = MappingProxyType({
    # routers/chat.py:666, routers/agents.py:3270, tools/browser/actions.py:1251
    "vision": lambda config: is_vision_tier_configured(config, "vision"),
    "vision_fast": lambda config: is_vision_tier_configured(config, "vision_fast"),  # perception/consumer.py:907
    "compute_use": lambda config: is_vision_tier_configured(config, "compute_use"),  # tools/browser/compute_use.py:107
    "image_gen": is_image_gen_tier_configured,  # cognitive/image_gen_dispatch.py:142
})

# Caps each connect/read wait so an endpoint that goes silent fails the check; costs failing a listing slower than 10 s.
MODELS_PROBE_TIMEOUT_S = 10.0
# The ceiling of the runtime's BF-270 boot probe, min(tier timeout, 30 s); costs failing a cold model that needs longer.
CHAT_PROBE_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class ProviderPreset:
    """A named provider endpoint; an empty ``base_url`` means ``--base-url`` is required."""

    name: str
    label: str
    base_url: str
    requires_key: bool
    key_env: str | None = None
    models: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))


PRESETS: Mapping[str, ProviderPreset] = MappingProxyType({
    "openai": ProviderPreset(
        name="openai",
        label="OpenAI (api.openai.com)",
        base_url="https://api.openai.com/v1",
        requires_key=True,
        key_env="OPENAI_API_KEY",
    ),
    "openrouter": ProviderPreset(
        name="openrouter",
        label="OpenRouter (openrouter.ai)",
        base_url="https://openrouter.ai/api/v1",
        requires_key=True,
        key_env="OPENROUTER_API_KEY",
    ),
    "ollama": ProviderPreset(
        name="ollama",
        label="Ollama on this machine, through its OpenAI-compatible /v1 API",
        base_url="http://localhost:11434/v1",
        requires_key=False,
    ),
    "copilot-proxy": ProviderPreset(
        name="copilot-proxy",
        label="The GitHub Copilot proxy on this machine, with the shipped model names",
        base_url="http://127.0.0.1:8080/v1",
        requires_key=False,
        # The shipped config/system.yaml model names; a test pins the two together.
        models=MappingProxyType({"fast": "claude-sonnet-4.6", "standard": "claude-sonnet-4.6", "deep": "claude-opus-4.6"}),
    ),
    "custom": ProviderPreset(
        name="custom",
        label="Any OpenAI-compatible endpoint (--base-url required)",
        base_url="",
        requires_key=False,
    ),
})


@dataclass(frozen=True)
class ProviderChoice:
    """The provider settings setup writes; ``api_key`` is kept out of ``repr``."""

    provider: str
    base_url: str
    models: Mapping[str, str]
    api_key: str = field(default="", repr=False)


class SetupInputError(ValueError):
    """An invalid setup input (CLI exit 2); the message never contains the API key."""


class ConfigEditRefused(Exception):
    """The config cannot be safely edited (CLI exit 4); the message names keys and reasons, never the API key."""


class ConfigReplaceFailed(OSError):
    """The final replace failed after the backup was written (CLI exit 4); ``backup`` keeps the original bytes."""

    def __init__(self, message: str, backup: Path) -> None:
        super().__init__(message)
        self.backup = backup


def normalize_base_url(url: str) -> str:
    """Return ``url`` without trailing slashes, or raise SetupInputError (CLI exit 2).

    The URL must be http(s) with a host and, if one is given, a non-zero port.
    Credentials (``user@``), a query or fragment, and whitespace or control
    characters anywhere are refused.
    """
    if not url or any(ch.isspace() or not ch.isprintable() for ch in url):
        raise SetupInputError("the base URL must be non-empty, without whitespace or control characters")
    if "?" in url or "#" in url:
        raise SetupInputError("the base URL must not have a query or fragment")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise SetupInputError("the base URL is not a valid URL (check the host and port)") from None
    if parts.scheme not in ("http", "https"):
        raise SetupInputError("the base URL must start with http:// or https://")
    if "@" in parts.netloc:
        raise SetupInputError("the base URL must not carry credentials; pass the key with --api-key-env")
    if not parts.hostname or port == 0:
        raise SetupInputError("the base URL must name a host (and a non-zero port, if any)")
    return url.rstrip("/")


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def sends_key_in_clear(base_url: str, api_key: str) -> bool:
    """Whether ``api_key`` would go over plain ``http://`` to a host other than ``localhost`` or a loopback IP."""
    parts = urlsplit(base_url)
    return bool(api_key) and parts.scheme == "http" and not _is_loopback(parts.hostname or "")


def validate_key_transport(base_url: str, api_key: str, *, allow_insecure_http: bool) -> None:
    """Raise SetupInputError (CLI exit 2) unless ``api_key`` can be sent to ``base_url`` as given.

    The key must be printable ASCII, since it travels in an HTTP header, must hold no ``<`` or
    ``>`` and must not be part of ``<redacted>``, which is what lets ``redact`` hide every form
    of it (B9, B10). A key over plain ``http://`` to a non-loopback host (no DNS lookup) needs
    ``allow_insecure_http``. Messages name the problem and never interpolate the key.
    """
    if not (api_key.isascii() and api_key.isprintable()):
        raise SetupInputError("the API key must be printable ASCII (no control, zero-width or non-ASCII characters)")
    if _REDACTED in api_key:
        raise SetupInputError(f"the API key contains setup's redaction marker {_REDACTED!r}")
    if "<" in api_key or ">" in api_key:
        raise SetupInputError("the API key contains < or >; API keys do not contain < or >")
    if api_key and api_key in _REDACTED:
        raise SetupInputError(f"the API key is part of setup's redaction marker {_REDACTED!r}")
    if sends_key_in_clear(base_url, api_key) and not allow_insecure_http:
        raise SetupInputError(
            "refusing to send the API key over plain http:// to a non-loopback host; "
            "use https:// or pass --allow-insecure-http"
        )


def validate_holds_no_key(value: str, api_key: str, *, name: str) -> None:
    """Raise SetupInputError (CLI exit 2) if ``value`` holds a form of ``api_key`` (``carries_key``, B9).

    The message names the input as ``name``, never its value.
    """
    if carries_key(value, api_key):
        raise SetupInputError(f"{name} contains the API key, or an encoding of it")


def validate_choice(choice: ProviderChoice, *, allow_insecure_http: bool) -> None:
    """Raise SetupInputError (CLI exit 2) unless ``choice`` can be written and sent as given.

    The base URL must already be normalised, the key must pass validate_key_transport, and
    every text-tier model must be printable text; neither the base URL nor a model may hold a
    form of the key (B9). Messages name the problem, never the key.
    """
    if normalize_base_url(choice.base_url) != choice.base_url:
        raise SetupInputError("the base URL must not end with a slash")
    validate_key_transport(choice.base_url, choice.api_key, allow_insecure_http=allow_insecure_http)
    validate_holds_no_key(choice.base_url, choice.api_key, name="the base URL")
    for tier in TEXT_TIERS:
        model = choice.models.get(tier, "")
        if not model or not model.isprintable():
            raise SetupInputError(f"the {tier} model name must be non-empty printable text")
        validate_holds_no_key(model, choice.api_key, name=f"the model for the {tier} tier")


def managed_values(choice: ProviderChoice, *, retain_shared_url: bool = False) -> dict[str, str]:
    """Return the managed ``cognitive`` keys for ``choice`` in canonical order.

    All 13, or with ``retain_shared_url`` the 12 per-tier text keys, which leave the shared
    ``llm_base_url`` as it is (B7).
    """
    values: dict[str, str] = {} if retain_shared_url else {"llm_base_url": choice.base_url}
    for tier in TEXT_TIERS:
        values[f"llm_base_url_{tier}"] = choice.base_url
        values[f"llm_api_key_{tier}"] = choice.api_key
        values[f"llm_model_{tier}"] = choice.models[tier]
        values[f"llm_api_format_{tier}"] = "openai"
    return values


class ProbeOutcome(Enum):
    """Classified result of one provider probe."""

    OK = "ok"
    NOT_FOUND = "not_found"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    REDIRECTED = "redirected"
    AUTH_REJECTED = "auth_rejected"
    MODEL_REJECTED = "model_rejected"
    REQUEST_REJECTED = "request_rejected"
    RATE_LIMITED = "rate_limited"
    PROVIDER_ERROR = "provider_error"
    BAD_RESPONSE = "bad_response"
    # A 200 the runtime's boot probe reads as a degraded tier: no text in content or reasoning.
    EMPTY_RESPONSE = "empty_response"


@dataclass(frozen=True)
class ProbeResult:
    """One probe's outcome; ``message`` has the key's forms ``<redacted>``, and no ``model_ids`` entry holds one."""

    outcome: ProbeOutcome
    message: str
    status_code: int | None = None
    model_ids: tuple[str, ...] = ()


# Caps provider text shown to the operator at one readable line; costs the rest of a long error body.
_EXCERPT_MAX_CHARS = 200
_REDACTED = "<redacted>"


def _key_forms(api_key: str) -> list[str]:
    raw = api_key.encode("utf-8")
    forms = {
        api_key,
        quote(api_key, safe=""),
        quote_plus(api_key),
        base64.b64encode(raw).decode("ascii"),
        base64.b64encode(b"Bearer " + raw).decode("ascii"),
    }
    return sorted(forms, key=lambda form: (-len(form), form))


def _key_pattern(api_key: str) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(form) for form in _key_forms(api_key)))


def carries_key(text: str, api_key: str) -> bool:
    """Whether ``text`` holds a form of ``api_key`` that ``redact`` replaces; never for an empty key."""
    return bool(api_key) and _key_pattern(api_key).search(text) is not None


def redact(text: str, api_key: str) -> str:
    """Replace each literal, percent-encoded and base64 form of ``api_key`` in ``text`` with ``<redacted>``.

    One left-to-right pass over the whole text, longest form first; an empty key changes nothing.
    For any other key that validate_key_transport accepts, the output holds no form of the key,
    so ``carries_key`` is False on it and a second pass changes nothing. Proof:

    1. No form holds ``<`` or ``>``: the key holds neither, percent-encoding writes only
       ``A-Za-z0-9_.-~%+``, and base64 only ``A-Za-z0-9+/=``.
    2. No form lies inside ``redacted``: the key is not part of ``<redacted>``, a percent-encoded
       form made only of letters is the key itself, a base64 form is a multiple of 4 characters
       long and no 4- or 8-character window of ``redacted`` base64-decodes to printable ASCII,
       and a ``Bearer`` form has at least 12 characters.
    3. By 1, a form touching a marker, the text's own or one the pass wrote, would lie inside its
       ``redacted``, which 2 rules out; so no marker is matched, split or completed by a form, and
       none is left in the text the pass did not replace, where it would have been matched.
    """
    if not api_key:
        return text
    return _key_pattern(api_key).sub(_REDACTED, text)


def _excerpt(text: str, api_key: str) -> str:
    # Redact before and after folding whitespace, which can rebuild a key that holds a space, and before
    # capping, so the cap cannot cut a key form in half.
    printable = "".join(ch if ch.isprintable() else " " for ch in redact(text, api_key))
    line = redact(" ".join(printable.split()), api_key)
    return line if len(line) <= _EXCERPT_MAX_CHARS else line[: _EXCERPT_MAX_CHARS - 3] + "..."


def _result(
    outcome: ProbeOutcome,
    message: str,
    api_key: str,
    status: int | None = None,
    model_ids: tuple[str, ...] = (),
) -> ProbeResult:
    return ProbeResult(outcome, redact(message, api_key), status, model_ids)


def _probe_client(
    base_url: str, api_key: str, timeout: float, transport: httpx.BaseTransport | None,
) -> httpx.Client:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    return httpx.Client(
        base_url=base_url.rstrip("/") + "/",  # the runtime's normalisation (llm_client.py _build_client)
        headers=headers,
        timeout=timeout,
        follow_redirects=False,  # a redirect must never carry the key to a host the operator did not name
        transport=transport,
    )


def _request(
    base_url: str,
    api_key: str,
    timeout: float,
    transport: httpx.BaseTransport | None,
    path: str,
    payload: Mapping[str, object] | None = None,
) -> httpx.Response | ProbeResult:
    """Send one probe (a POST when ``payload`` is given); a transport failure comes back as a ProbeResult."""
    try:
        with _probe_client(base_url, api_key, timeout, transport) as client:
            return client.get(path) if payload is None else client.post(path, json=payload)
    except httpx.TimeoutException as exc:
        message = f"the provider did not answer within {timeout:g} s ({type(exc).__name__})"
        return _result(ProbeOutcome.TIMEOUT, message, api_key)
    except httpx.TransportError as exc:
        return _result(ProbeOutcome.UNREACHABLE, f"could not reach the provider ({type(exc).__name__})", api_key)
    except httpx.RequestError as exc:
        return _result(ProbeOutcome.BAD_RESPONSE, f"the provider's answer could not be read ({type(exc).__name__})", api_key)


def _status_failure(response: httpx.Response, api_key: str, subject: str) -> ProbeResult:
    """Classify a non-200 answer to ``subject``, such as "the model listing"."""
    status = response.status_code
    if status in (401, 403):
        # The body is never shown: OpenAI's 401 echoes the key partially masked.
        return _result(ProbeOutcome.AUTH_REJECTED, f"the provider rejected the API key (HTTP {status})", api_key, status)
    if 300 <= status < 400:
        # No part of the Location is shown: it can carry the key, or an encoding of it (B6/H1).
        message = (
            f"the provider redirected {subject} elsewhere (HTTP {status}); setup does not forward your "
            "API key to redirects, so check that --base-url is the provider's own API URL"
        )
        return _result(ProbeOutcome.REDIRECTED, message, api_key, status)
    if status == 404:
        return _result(ProbeOutcome.NOT_FOUND, f"{subject} returned HTTP 404 (not found)", api_key, status)
    detail = _excerpt(response.text, api_key)
    suffix = f": {detail}" if detail else ""
    if status == 429:
        return _result(ProbeOutcome.RATE_LIMITED, f"the provider rate-limited {subject} (HTTP 429){suffix}", api_key, status)
    if 400 <= status < 500:
        return _result(ProbeOutcome.REQUEST_REJECTED, f"the provider rejected {subject} (HTTP {status}){suffix}", api_key, status)
    if status >= 500:
        return _result(ProbeOutcome.PROVIDER_ERROR, f"the provider failed {subject} (HTTP {status}){suffix}", api_key, status)
    return _result(ProbeOutcome.BAD_RESPONSE, f"{subject} returned an unexpected HTTP {status}", api_key, status)


def probe_models(
    base_url: str,
    api_key: str,
    *,
    timeout: float = MODELS_PROBE_TIMEOUT_S,
    transport: httpx.BaseTransport | None = None,
) -> ProbeResult:
    """``GET {base}/models``: classify reachability, the key and the path, and return the listed model IDs.

    A 404 or 405 is NOT_FOUND: no listing at this path or for this method (B5). An ID that
    ``carries_key`` is withheld from ``model_ids``, and the message counts it (B8).
    """
    response = _request(base_url, api_key, timeout, transport, "models")
    if isinstance(response, ProbeResult):
        return response
    status = response.status_code
    if status == 405:
        return _result(ProbeOutcome.NOT_FOUND, "the model listing returned HTTP 405 (method not allowed)", api_key, status)
    if status != 200:
        return _status_failure(response, api_key, "the model listing")
    try:
        listed = tuple(entry["id"] for entry in response.json()["data"])
    except (ValueError, KeyError, TypeError):
        listed = None
    if listed is None or not all(isinstance(model_id, str) for model_id in listed):
        message = "the model listing is not an OpenAI-compatible JSON response"
        return _result(ProbeOutcome.BAD_RESPONSE, message, api_key, status)
    model_ids = tuple(model_id for model_id in listed if not carries_key(model_id, api_key))
    message = f"the provider lists {len(listed)} model(s)"
    if len(model_ids) < len(listed):
        message += f"; setup withholds {len(listed) - len(model_ids)} whose ID contains the API key"
    return _result(ProbeOutcome.OK, message, api_key, status, model_ids)


def probe_chat(
    base_url: str,
    api_key: str,
    model: str,
    *,
    model_ids: Sequence[str] = (),
    timeout: float = CHAT_PROBE_TIMEOUT_S,
    transport: httpx.BaseTransport | None = None,
) -> ProbeResult:
    """One-token ``POST {base}/chat/completions`` with the runtime's boot-probe payload.

    A 404 reads as an unknown model when ``model_ids`` (a successful listing) is
    non-empty, and as a missing endpoint otherwise; an ID that ``carries_key`` is
    never offered as a close match. A 200 passes only when the runtime's boot probe
    would accept the same body: non-blank text in ``choices[0].message``
    ``content``, else in ``reasoning``.
    """
    payload = {"model": model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
    subject = f"the chat check for model {model!r}"
    response = _request(base_url, api_key, timeout, transport, "chat/completions", payload)
    if isinstance(response, ProbeResult):
        return response
    status = response.status_code
    if status == 404 and model_ids:
        candidates = [model_id for model_id in model_ids if not carries_key(model_id, api_key)]
        close = difflib.get_close_matches(model, candidates, n=5)
        hint = f"; close matches: {', '.join(repr(m) for m in close)}" if close else ""
        message = f"the provider does not serve model {model!r} (HTTP 404){hint}"
        return _result(ProbeOutcome.MODEL_REJECTED, message, api_key, status)
    if status != 200:
        return _status_failure(response, api_key, subject)
    # Mirrors the OpenAI-format acceptance in llm_client.py _check_endpoint; a chain test pins the two together.
    # The reply's text is only checked, never shown: a provider can echo the key in it (B8).
    try:
        message_body = response.json()["choices"][0]["message"]
        content = message_body.get("content") or message_body.get("reasoning")
    except (AttributeError, IndexError, KeyError, TypeError, ValueError):
        message = f"{subject} did not return an OpenAI-compatible completion"
        return _result(ProbeOutcome.BAD_RESPONSE, message, api_key, status)
    if not (isinstance(content, str) and content.strip()):
        message = (
            f"the provider answered but returned no text for model {model!r}; "
            "ProbOS's boot check would mark that tier degraded"
        )
        return _result(ProbeOutcome.EMPTY_RESPONSE, message, api_key, status)
    return _result(ProbeOutcome.OK, f"model {model!r} answered", api_key, status)


_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+\Z")
_HEADER_RE = re.compile(r"cognitive[ \t]*:(?P<rest>.*)")
_HEADER_REST_RE = re.compile(r"(?:[ \t]+#.*)?[ \t]*")
_QUOTED_HEADER_RE = re.compile(r"""["']cognitive["'][ \t]*:""")
_MARKER_RE = re.compile(r"(?:---|\.\.\.)(?:[ \t].*)?")
_LEADING_START_RE = re.compile(r"---(?:[ \t]+#.*)?[ \t]*")
# Block scalar, anchor, alias, tag and flow-collection indicators: none is a one-line scalar.
_NOT_SINGLE_LINE = ("|", ">", "&", "*", "!", "[", "{")
_DEFAULT_INDENT = "  "
_UNPROVEN = "could not prove the edit changes only the provider keys"
_ABSENT = object()


def _content(line: str) -> str:
    return line.rstrip("\r\n")


def _eol(line: str) -> str:
    return line[len(_content(line)):]


def _indent(content: str) -> str:
    return content[: len(content) - len(content.lstrip(" \t"))]


def _is_entry(line: str) -> bool:
    stripped = _content(line).strip()
    return bool(stripped) and not stripped.startswith("#")


def _starts_top_level(line: str) -> bool:
    content = _content(line)
    return bool(content.strip()) and content[0] not in " \t#"


def parse_config_text(text: str) -> dict:
    """Return the YAML mapping in ``text`` (``{}`` when empty); raise ConfigEditRefused otherwise."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        raise ConfigEditRefused(f"the config is not valid YAML{where}") from None
    if document is None:
        return {}
    if not isinstance(document, dict):
        raise ConfigEditRefused("the config's top level is not a mapping")
    return document


def _render_line(indent: str, key: str, value: str, eol: str, comment: str = "") -> str:
    # safe_dump quotes and escapes the value, so user input never reaches the file unrendered.
    dumped = yaml.safe_dump({"v": value}, default_flow_style=False, allow_unicode=True, width=2**31 - 1)
    rendered = dumped[len("v: "):].removesuffix("\n") if dumped.startswith("v: ") else ""
    if not rendered or "\n" in rendered or "\r" in rendered:
        raise ConfigEditRefused(f"the value for {key} cannot be written on one line")
    return f"{indent}{key}: {rendered}{comment}{eol}"


def _isolated_comment(rest: str, original: object) -> str:
    """Return the trailing comment after a ``key:`` with its leading whitespace, or "" if it cannot be isolated.

    The comment starts at the first `` #`` whose left side re-parses to the line's current value.
    """
    for match in re.finditer(r"[ \t]#", rest):
        left = rest[: match.start()]
        try:
            parsed = yaml.safe_load(f"v: {left}")
        except yaml.YAMLError:
            continue
        if isinstance(parsed, dict) and "v" in parsed and parsed["v"] == original:
            return rest[len(left.rstrip()):]
    return ""


def _replaced_line(
    lines: list[str], at: int, block: range, indent: str, key: str, value: str, rest: str, original: object,
) -> str:
    """Return line ``at`` with ``key`` set to ``value``; refuse unless its current value is one plain or quoted line."""
    if rest.strip().startswith(_NOT_SINGLE_LINE):
        raise ConfigEditRefused(
            f"{key} is not a single-line value (a block scalar, anchor, alias, tag or flow collection)"
        )
    following = next((i for i in block if i > at and _is_entry(lines[i])), None)
    if following is not None and len(_indent(_content(lines[following]))) > len(indent):
        raise ConfigEditRefused(f"{key} is not a single-line value: it continues on a more-indented line")
    return _render_line(indent, key, value, _eol(lines[at]), _isolated_comment(rest, original))


def _edit_section(
    lines: list[str], header: int, values: Mapping[str, str], current: Mapping[str, object], file_eol: str,
) -> list[str]:
    header_match = _HEADER_RE.match(_content(lines[header]))
    if header_match is None or not _HEADER_REST_RE.fullmatch(header_match.group("rest")):
        raise ConfigEditRefused("the cognitive: header carries inline content")
    eol = _eol(lines[header]) or file_eol
    end = header + 1
    while end < len(lines) and not _starts_top_level(lines[end]):
        end += 1
    block = range(header + 1, end)
    indent = next((_indent(_content(lines[i])) for i in block if _is_entry(lines[i])), _DEFAULT_INDENT)
    if "\t" in indent:
        raise ConfigEditRefused("the cognitive section is indented with tabs")
    new_lines = list(lines)
    missing: list[str] = []
    for key, value in values.items():
        quoted_re = re.compile(rf"{re.escape(indent)}[\"']{re.escape(key)}[\"'][ \t]*:")
        if any(quoted_re.match(_content(lines[i])) for i in block):
            raise ConfigEditRefused(f"the cognitive section spells {key} in quotes")
        key_re = re.compile(rf"{re.escape(indent)}{re.escape(key)}[ \t]*:(?=[ \t]|$)")
        hits = [(i, match) for i in block if (match := key_re.match(_content(lines[i])))]
        if len(hits) > 1:
            raise ConfigEditRefused(f"the cognitive section sets {key} more than once")
        original = current.get(key, _ABSENT)
        if not hits:
            missing.append(_render_line(indent, key, value, eol))
        elif original != value:  # an unchanged value keeps its line's bytes, quoting and comment
            at, match = hits[0]
            rest = _content(lines[at])[match.end():]
            new_lines[at] = _replaced_line(lines, at, block, indent, key, value, rest, original)
    if missing:
        anchor = max(
            (i for i in block if _content(lines[i]).strip() and len(_indent(_content(lines[i]))) >= len(indent)),
            default=header,
        )
        if not _eol(new_lines[anchor]):
            new_lines[anchor] += eol
        new_lines[anchor + 1:anchor + 1] = missing
    return new_lines


def _prove_edit(new_text: str, document: dict, values: Mapping[str, str]) -> None:
    try:
        edited = yaml.safe_load(new_text)
    except yaml.YAMLError:
        raise ConfigEditRefused(_UNPROVEN) from None
    expected = dict(document)
    expected["cognitive"] = {**(document.get("cognitive") or {}), **values}
    if edited != expected:
        raise ConfigEditRefused(_UNPROVEN)


def apply_managed_values(text: str, values: Mapping[str, str]) -> str:
    """Return ``text`` with ``values`` set in its ``cognitive`` section, editing only those lines.

    A value already equal keeps its line byte for byte; a changed line keeps an isolated
    trailing comment. Every other line keeps its bytes, except that a final line without
    an EOL gains one when lines are added after it. Raises ConfigEditRefused for a file
    this cannot edit safely, and unless re-parsing the result yields the original
    document with exactly ``values`` changed.
    """
    document = parse_config_text(text)
    section = document.get("cognitive")
    if section is not None and not isinstance(section, dict):
        raise ConfigEditRefused("the cognitive section is not a mapping")
    lines = _LINE_RE.findall(text)
    markers = [i for i, line in enumerate(lines) if _MARKER_RE.fullmatch(_content(line))]
    first_entry = next((i for i, line in enumerate(lines) if _is_entry(line)), None)
    if markers and not (markers == [first_entry] and _LEADING_START_RE.fullmatch(_content(lines[first_entry]))):
        raise ConfigEditRefused("the config uses a YAML document marker other than one leading ---")
    if any(_QUOTED_HEADER_RE.match(_content(line)) for line in lines):
        raise ConfigEditRefused("the config spells the cognitive key in quotes")
    file_eol = next((_eol(line) for line in lines if _eol(line)), "\n")
    headers = [i for i, line in enumerate(lines) if _HEADER_RE.match(_content(line))]
    if len(headers) > 1:
        raise ConfigEditRefused("the config has more than one cognitive: header")
    if headers:
        new_lines = _edit_section(lines, headers[0], values, section or {}, file_eol)
    else:
        new_lines = list(lines)
        if new_lines and not _eol(new_lines[-1]):
            new_lines[-1] += file_eol
        new_lines.append(f"cognitive:{file_eol}")
        new_lines.extend(_render_line(_DEFAULT_INDENT, key, value, file_eol) for key, value in values.items())
    new_text = "".join(new_lines)
    _prove_edit(new_text, document, values)
    return new_text


def rewrite_with_managed_values(text: str, values: Mapping[str, str], *, header: str) -> str:
    """Return ``text`` re-serialised with ``values`` set in ``cognitive``: the ``--force`` path.

    Every setting is kept and every comment lost; ``header`` becomes the leading comment
    and the file's first EOL is kept. Raises ConfigEditRefused if ``text`` is not a YAML
    mapping, its ``cognitive`` is not a mapping, or the re-parse is not the original with
    exactly ``values`` changed.
    """
    document = parse_config_text(text)
    section = document.get("cognitive")
    if section is not None and not isinstance(section, dict):
        raise ConfigEditRefused("the cognitive section is not a mapping")
    expected = {**document, "cognitive": {**(section or {}), **values}}
    try:
        body = yaml.safe_dump(expected, sort_keys=False, allow_unicode=True, default_flow_style=False)
    except yaml.YAMLError:
        raise ConfigEditRefused(_UNPROVEN) from None
    rewritten = "".join(f"# {line}\n" for line in header.splitlines()) + body
    eol = next((_eol(line) for line in _LINE_RE.findall(text) if _eol(line)), "\n")
    if eol != "\n":
        rewritten = rewritten.replace("\n", eol)
    _prove_edit(rewritten, document, values)
    return rewritten


def changed_keys(text: str | None, values: Mapping[str, str]) -> list[str]:
    """Return the keys of ``values`` whose current ``cognitive`` value in ``text`` differs (all of them for None)."""
    section = None if text is None else parse_config_text(text).get("cognitive")
    current = section if isinstance(section, dict) else {}
    return [key for key, value in values.items() if current.get(key) != value]


def read_config_text(path: Path) -> tuple[str, bool]:
    """Return ``(text, had_bom)`` with EOLs intact; raise ConfigEditRefused if unreadable or not UTF-8."""
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ConfigEditRefused(f"the config cannot be read ({type(exc).__name__})") from None
    had_bom = data.startswith(codecs.BOM_UTF8)
    try:
        text = data[len(codecs.BOM_UTF8):].decode("utf-8") if had_bom else data.decode("utf-8")
    except UnicodeDecodeError:
        raise ConfigEditRefused("the config is not valid UTF-8") from None
    return text, had_bom


def _load_errors(exc: ValidationError, prefix: str = "") -> str:
    # Pydantic's loc and msg only: its input could be a value the operator typed.
    return "; ".join(
        f"{prefix}{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()
    )


@dataclass(frozen=True)
class TierEndpoint:
    """An optional tier's ``tier_config`` URL and model, and whether its consumer reads it as configured.

    ``configured`` is the tier's ``TIER_CONFIGURED_CHECKS`` answer (B8). ``inherited`` means
    it has no own URL, so it resolves to the shared ``llm_base_url``.
    """

    base_url: str
    model: str | None
    inherited: bool
    configured: bool


def optional_tier_endpoints(text: str | None) -> dict[str, TierEndpoint]:
    """Return how the runtime resolves each optional tier under ``text`` (``{}`` for None).

    Only the shared ``llm_base_url`` and each optional tier's own URL and model are loaded,
    so an invalid value elsewhere is left for the final check. Raises ConfigEditRefused if
    ``text`` is not a YAML mapping or those settings do not load; the message names fields,
    not values.
    """
    if text is None:
        return {}
    section = parse_config_text(text).get("cognitive")
    fields = ("llm_base_url", *(f"llm_{name}_{tier}" for tier in OPTIONAL_TIERS for name in ("base_url", "model")))
    settings = {key: section[key] for key in fields if key in section} if isinstance(section, dict) else {}
    try:
        config = CognitiveConfig.model_validate(settings)
    except ValidationError as exc:
        raise ConfigEditRefused(
            f"the optional tiers' endpoint settings do not load: {_load_errors(exc, 'cognitive.')}"
        ) from None
    endpoints = {}
    for tier in OPTIONAL_TIERS:
        resolved = config.tier_config(tier)
        # tier_config falls back to the shared URL for an own URL of None and of "" alike.
        inherited = not getattr(config, f"llm_base_url_{tier}")
        configured = TIER_CONFIGURED_CHECKS[tier](config)
        endpoints[tier] = TierEndpoint(resolved["base_url"], resolved["model"], inherited, configured)
    return endpoints


def tiers_using_shared_url(endpoints: Mapping[str, TierEndpoint]) -> dict[str, str]:
    """Return tier to model for each optional tier that has a model and no own URL (B7).

    Each sends its model to the shared ``llm_base_url``, so setup leaves that URL as it is
    while one exists. A tier without a model does not count; it follows the shared URL.
    """
    return {tier: endpoint.model for tier, endpoint in endpoints.items() if endpoint.model and endpoint.inherited}


def verify_config_file(
    path: Path, choice: ProviderChoice, *, kept: Mapping[str, TierEndpoint] = MappingProxyType({}),
) -> None:
    """Raise ConfigEditRefused unless ``path`` loads and each text tier resolves to ``choice``.

    Each ``kept`` tier (from optional_tier_endpoints on the old config) must also keep its URL,
    model and ``TIER_CONFIGURED_CHECKS`` answer. Only when no kept tier uses the shared URL
    (tiers_using_shared_url) does a tier without its own URL follow the result's shared URL.
    A load failure reports pydantic's ``loc`` and ``msg`` but not its ``input``, with the key's
    forms redacted: a ``loc`` can hold a mapping key from the file, and some validators quote
    the value they refuse.
    """
    try:
        config = load_config(path)
    except ValidationError as exc:
        raise ConfigEditRefused(redact(f"the result does not load: {_load_errors(exc)}", choice.api_key)) from None
    for tier in TEXT_TIERS:
        resolved = config.cognitive.tier_config(tier)
        if (resolved["base_url"], resolved["api_key"], resolved["model"], resolved["api_format"]) != (
            choice.base_url, choice.api_key, choice.models[tier], "openai",
        ):
            raise ConfigEditRefused(f"the result does not resolve the {tier} tier to the chosen provider")
    retained = bool(tiers_using_shared_url(kept))
    for tier, before in kept.items():
        resolved = config.cognitive.tier_config(tier)
        url = config.cognitive.llm_base_url if before.inherited and not retained else before.base_url
        if (resolved["base_url"], resolved["model"]) != (url, before.model):
            raise ConfigEditRefused(f"the result moves the {tier} tier to another endpoint")
        if TIER_CONFIGURED_CHECKS[tier](config.cognitive) != before.configured:
            raise ConfigEditRefused(f"the result changes whether the {tier} tier is configured")


def _write_temp(path: Path, body: bytes) -> Path:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(body)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


def _write_backup(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.name}.bak-{stamp}")
    suffix = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}.bak-{stamp}-{suffix}")
        suffix += 1
    # mkstemp + os.replace (never shutil.copy2) so the backup does not keep the old file's looser mode.
    tmp = _write_temp(path, path.read_bytes())
    try:
        os.replace(tmp, backup)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup


def write_config_atomic(
    path: Path,
    text: str,
    *,
    had_bom: bool,
    create: bool,
    verify: Callable[[Path], None],
) -> Path | None:
    """Install ``text`` at ``path`` once ``verify`` accepts the exact bytes; return the backup path, if any.

    A create translates ``\\n`` to ``os.linesep`` like ``probos init``; an update keeps EOLs
    verbatim. An existing file is first copied to ``<name>.bak-<UTC stamp>`` (``-N`` on a
    collision). On POSIX the file and its backup are 0600 (``mkstemp``) and a new parent
    directory 0700. A failure unlinks the temp file and propagates; ``path`` changes only
    at the final ``os.replace``. An OSError from that replace after a backup was written
    is raised as ConfigReplaceFailed, which names the kept backup.
    """
    body = (text.replace("\n", os.linesep) if create else text).encode("utf-8")
    if had_bom:
        body = codecs.BOM_UTF8 + body
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = _write_temp(path, body)
    backup: Path | None = None
    try:
        verify(tmp)
        backup = _write_backup(path) if path.exists() else None
        os.replace(tmp, path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if backup is None:
            raise
        raise ConfigReplaceFailed(str(exc), backup) from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return backup
