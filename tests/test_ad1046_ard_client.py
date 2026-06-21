"""AD-1046: tests for the ARD discovery client + pure catalog parser.

DD-1 SSRF + BF-287 real transport: ``ArdClient`` is exercised with a real
``httpx.AsyncClient`` wrapping an ``httpx.MockTransport`` (deterministic, no
network). The pure ``catalog_from_dict`` / ``entry_from_dict`` honest-degrade
paths are unit-tested directly.

asyncio_mode="auto": async tests carry NO ``@pytest.mark.asyncio`` marker (they
are auto-collected); no ``asyncio.run`` is used.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1046_ard_client.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx

from probos.federation.ard import (
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    ArdClient,
    CatalogEntry,
    catalog_from_dict,
    entry_from_dict,
)
from probos.federation.ard.client import _MAX_CATALOG_BYTES

# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #

_GOOD_CATALOG = {
    "specVersion": "1.0",
    "host": {"displayName": "Publisher"},
    "entries": [
        {
            "identifier": "urn:air:pub.example.com:tools:x",
            "displayName": "X",
            "type": MT_PROBOS_TOOL,
            "data": {"axis": "tool"},
            "tags": ["core"],
        }
    ],
}


def _mock_client(handler: Callable[[httpx.Request], httpx.Response], *, follow_redirects: bool = False) -> httpx.AsyncClient:
    """Build a real AsyncClient over a MockTransport (BF-287 real-transport seam)."""
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
    )


# --------------------------------------------------------------------------- #
# Pure entry_from_dict honest-degrade
# --------------------------------------------------------------------------- #


def test_entry_from_dict_url_only_ok() -> None:
    e = entry_from_dict(
        {"identifier": "urn:air:p:mcp:z", "displayName": "Z", "type": MT_MCP_SERVER, "url": "https://e/z"}
    )
    assert e is not None
    assert e.url == "https://e/z"
    assert e.data is None


def test_entry_from_dict_data_only_ok() -> None:
    e = entry_from_dict(
        {"identifier": "urn:air:p:tools:x", "displayName": "X", "type": MT_PROBOS_TOOL, "data": {"a": 1}}
    )
    assert e is not None
    assert e.data == {"a": 1}
    assert e.url is None


def test_entry_from_dict_both_url_and_data_returns_none() -> None:
    # DD-4 value-or-reference: both set → __post_init__ raises → dropped.
    assert (
        entry_from_dict(
            {
                "identifier": "urn:air:p:tools:x",
                "displayName": "X",
                "type": MT_PROBOS_TOOL,
                "url": "https://e/x",
                "data": {"a": 1},
            }
        )
        is None
    )


def test_entry_from_dict_neither_url_nor_data_returns_none() -> None:
    assert (
        entry_from_dict(
            {"identifier": "urn:air:p:tools:x", "displayName": "X", "type": MT_PROBOS_TOOL}
        )
        is None
    )


def test_entry_from_dict_missing_required_field_returns_none() -> None:
    assert entry_from_dict({"displayName": "X", "type": MT_PROBOS_TOOL, "data": {}}) is None
    assert entry_from_dict({"identifier": "urn:air:p:tools:x", "type": MT_PROBOS_TOOL, "data": {}}) is None
    assert entry_from_dict({"identifier": "urn:air:p:tools:x", "displayName": "X", "data": {}}) is None


def test_entry_from_dict_non_dict_returns_none() -> None:
    assert entry_from_dict("not-a-dict") is None
    assert entry_from_dict(None) is None
    assert entry_from_dict([1, 2]) is None


def test_entry_from_dict_coerces_malformed_list_fields() -> None:
    e = entry_from_dict(
        {
            "identifier": "urn:air:p:tools:x",
            "displayName": "X",
            "type": MT_PROBOS_TOOL,
            "data": {"a": 1},
            "tags": ["ok", 5, None],  # non-strings dropped
            "representativeQueries": "not-a-list",  # wrong type → []
        }
    )
    assert e is not None
    assert e.tags == ["ok"]
    assert e.representative_queries == []


def test_entry_from_dict_parses_trust_manifest_signature_opaque() -> None:
    e = entry_from_dict(
        {
            "identifier": "urn:air:pub.example.com:tools:x",
            "displayName": "X",
            "type": MT_PROBOS_TOOL,
            "data": {"a": 1},
            "trustManifest": {
                "identity": "pub.example.com",
                "attestations": [{"type": "slsa", "uri": "https://a/1"}],
                "signature": "opaque-sig-blob",
            },
        }
    )
    assert e is not None
    assert e.trust_manifest is not None
    assert e.trust_manifest.identity == "pub.example.com"
    assert len(e.trust_manifest.attestations) == 1
    # Signature kept verbatim as an opaque carrier (never dereferenced).
    assert e.trust_manifest.signature == "opaque-sig-blob"


# --------------------------------------------------------------------------- #
# Pure catalog_from_dict honest-degrade
# --------------------------------------------------------------------------- #


def test_catalog_from_dict_drops_malformed_entries() -> None:
    cat = catalog_from_dict(
        {
            "specVersion": "1.0",
            "entries": [
                {"identifier": "urn:air:p:tools:x", "displayName": "X", "type": MT_PROBOS_TOOL, "data": {}},
                {"identifier": "bad", "displayName": "B", "type": MT_PROBOS_TOOL},  # neither url|data → dropped
                "not-a-dict",  # dropped
            ],
        }
    )
    assert len(cat.entries) == 1
    assert cat.entries[0].identifier == "urn:air:p:tools:x"


def test_catalog_from_dict_non_dict_returns_empty() -> None:
    cat = catalog_from_dict("garbage")
    assert cat.spec_version == "1.0"
    assert cat.entries == []


def test_catalog_from_dict_parses_host_and_spec_version() -> None:
    cat = catalog_from_dict(_GOOD_CATALOG)
    assert cat.spec_version == "1.0"
    assert cat.host is not None
    assert cat.host.display_name == "Publisher"
    assert len(cat.entries) == 1


def test_catalog_round_trips_through_to_dict() -> None:
    original = CatalogEntry(
        identifier="urn:air:p:tools:x", display_name="X", type=MT_PROBOS_TOOL, data={"a": 1}, tags=["t"]
    )
    parsed = entry_from_dict(original.to_dict())
    assert parsed is not None
    assert parsed.identifier == original.identifier
    assert parsed.tags == ["t"]
    assert parsed.data == {"a": 1}


# --------------------------------------------------------------------------- #
# ArdClient.discover via MockTransport
# --------------------------------------------------------------------------- #


async def test_discover_happy_parse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_GOOD_CATALOG)

    client = ArdClient(http=_mock_client(handler))
    results = await client.discover(["https://pub.example.com"])

    assert len(results) == 1
    assert results[0].error == ""
    assert results[0].catalog is not None
    assert len(results[0].catalog.entries) == 1
    assert results[0].catalog.entries[0].identifier == "urn:air:pub.example.com:tools:x"


async def test_discover_one_bad_endpoint_isolated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "good.example.com":
            return httpx.Response(200, json=_GOOD_CATALOG)
        return httpx.Response(500, text="boom")  # non-JSON → isolated error

    client = ArdClient(http=_mock_client(handler))
    results = await client.discover(["https://good.example.com", "https://bad.example.com"])

    assert len(results) == 2
    assert results[0].catalog is not None and results[0].error == ""
    assert results[1].catalog is None and results[1].error != ""


async def test_discover_size_cap_truncates_over_limit() -> None:
    # A fully-valid JSON catalog whose serialized size EXCEEDS the cap. Truncation
    # at _MAX_CATALOG_BYTES cuts the JSON mid-string → parse fails → error.
    # A full (uncapped) parse would have succeeded, so the error proves the cap.
    big = {
        "specVersion": "1.0",
        "entries": [
            {
                "identifier": "urn:air:p:tools:x",
                "displayName": "X",
                "type": MT_PROBOS_TOOL,
                "data": {"a": 1},
                "description": "x" * (_MAX_CATALOG_BYTES + 10_000),
            }
        ],
    }
    body = json.dumps(big).encode("utf-8")
    assert len(body) > _MAX_CATALOG_BYTES

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    client = ArdClient(http=_mock_client(handler))
    results = await client.discover(["https://pub.example.com"])

    assert results[0].catalog is None
    assert results[0].error != ""


async def test_discover_does_not_follow_redirects_ssrf() -> None:
    # Inject a client whose OWN default is the UNSAFE follow_redirects=True; the
    # client must STILL pass follow_redirects=False per request, so the metadata
    # SSRF target is never dereferenced.
    requested: list[str] = []
    metadata = "http://169.254.169.254/latest/meta-data/"

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"Location": metadata})

    client = ArdClient(http=_mock_client(handler, follow_redirects=True))
    results = await client.discover(["https://pub.example.com"])

    # Only the well-known endpoint was hit; the 302 Location was NOT followed.
    assert len(requested) == 1
    assert requested[0].endswith("/.well-known/ai-catalog.json")
    assert all("169.254.169.254" not in u for u in requested)
    # Empty 302 body → parse fails → isolated honest-degrade error.
    assert results[0].catalog is None
    assert results[0].error != ""


async def test_discover_never_fetches_entry_url() -> None:
    requested: list[str] = []
    catalog_with_ref = {
        "specVersion": "1.0",
        "entries": [
            {
                "identifier": "urn:air:pub.example.com:mcp:z",
                "displayName": "Z",
                "type": MT_MCP_SERVER,
                "url": "http://evil.internal/secret",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(200, json=catalog_with_ref)

    client = ArdClient(http=_mock_client(handler))
    results = await client.discover(["https://pub.example.com"])

    # The entry's url is an OPAQUE reference — kept in the parsed envelope but
    # NEVER dereferenced by discovery.
    assert len(requested) == 1
    assert all("evil.internal" not in u for u in requested)
    assert results[0].catalog is not None
    assert results[0].catalog.entries[0].url == "http://evil.internal/secret"


async def test_discover_empty_endpoints_returns_empty() -> None:
    client = ArdClient()  # no injected client; no endpoints → zero network calls
    assert await client.discover([]) == []


async def test_search_registry_parses_results() -> None:
    captured: dict[str, str] = {}
    results_payload = {
        "results": [
            {
                "identifier": "urn:air:p:tools:y",
                "displayName": "Y",
                "type": MT_PROBOS_TOOL,
                "data": {"axis": "tool"},
            }
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json=results_payload)

    client = ArdClient(http=_mock_client(handler))
    catalog = await client.search_registry("https://reg.example.com", text="weather", page_size=5)

    assert captured["url"].endswith("/ard/search")
    assert "weather" in captured["body"]
    assert len(catalog.entries) == 1
    assert catalog.entries[0].identifier == "urn:air:p:tools:y"


async def test_search_registry_honest_degrade_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="nope")

    client = ArdClient(http=_mock_client(handler))
    catalog = await client.search_registry("https://reg.example.com", text="x")
    assert catalog.entries == []
