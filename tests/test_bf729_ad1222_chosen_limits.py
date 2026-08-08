"""BF-729 (#1184) / AD-1222 (#1185): two constraints that nobody chose.

Both were flagged under Design Principle 13(a) — *a capability ceiling must be
a decision, never an inheritance; every constraint states what it defends and
what it costs*.

**BF-729.** ``HttpFetchAgent.MAX_BODY_BYTES`` cuts a response at 1 MB and the
result reports ``body_length`` of the TRUNCATED body, with no flag and no
original size. An agent holding a 1,048,576-char prefix cannot tell it from a
complete document. On 2026-08-07 that produced a confident wrong explanation —
*"this sandbox has no network access, so these versions come from my training
knowledge"* — for boto3 data that had in fact arrived (#1182). The cap itself
is load-bearing (the body crosses the intent bus inline, the AD-731 / #636
shape) and is deliberately NOT raised here; it is made legible instead.

**AD-1222.** ``DependencyConfig`` borrowed ``self_mod.allowed_imports`` as its
auto-approve tier. Those answer different questions: which imports may appear
in generated code is a code-safety allowlist; which packages install without
asking the Captain is an authority grant. Measured on the live vessel, the
borrowed list carried 16 third-party entries, 5 of them absent — so enabling
dynamic install silently granted no-prompt installation of feedparser,
chardet, toml, markdown and psutil. Benign packages, unchosen authority.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from probos.agents.http_fetch import HttpFetchAgent
from probos.capability_request import CapabilityRequestStore
from probos.cognitive.dependency_resolver import DependencyResult
from probos.config import DependencyConfig, SystemConfig
from probos.runtime import ProbOSRuntime


# ── BF-729: truncation must announce itself ────────────────────────────────
class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self.url = "https://example.test/big.json"


class _Client:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        return _Response(self._content)


async def _fetch(monkeypatch, content: bytes) -> dict:
    agent = HttpFetchAgent(agent_id="http-1")
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: _Client(content)
    )
    monkeypatch.setattr(agent, "_validate_url", lambda url: None)
    result = await agent._fetch_url("https://example.test/big.json", "GET")
    assert result["success"], result
    return result["data"]


class TestTruncationIsVisible:
    @pytest.mark.asyncio
    async def test_a_body_under_the_cap_reports_untruncated(
        self, monkeypatch
    ) -> None:
        data = await _fetch(monkeypatch, b'{"version": "1.43.67"}')
        assert data["truncated"] is False
        assert data["total_bytes"] == data["body_length"]

    @pytest.mark.asyncio
    async def test_an_oversized_body_says_so_and_gives_the_real_size(
        self, monkeypatch
    ) -> None:
        """The headline. Before this fix the agent had to infer truncation
        from body_length landing exactly on the cap."""
        oversized = b"x" * (HttpFetchAgent.MAX_BODY_BYTES + 5_000)
        data = await _fetch(monkeypatch, oversized)

        assert data["truncated"] is True
        assert data["total_bytes"] == len(oversized)
        assert data["body_length"] == HttpFetchAgent.MAX_BODY_BYTES
        assert data["total_bytes"] > data["body_length"], (
            "the agent must be able to see that more existed than it received"
        )

    @pytest.mark.asyncio
    async def test_a_body_exactly_at_the_cap_is_not_called_truncated(
        self, monkeypatch
    ) -> None:
        """Boundary. `>` not `>=` — a body that exactly fills the cap is whole,
        and calling it truncated would make the flag cry wolf."""
        exact = b"y" * HttpFetchAgent.MAX_BODY_BYTES
        data = await _fetch(monkeypatch, exact)
        assert data["truncated"] is False
        assert data["total_bytes"] == HttpFetchAgent.MAX_BODY_BYTES

    @pytest.mark.asyncio
    async def test_the_existing_result_keys_are_all_still_there(
        self, monkeypatch
    ) -> None:
        """Additive only — consumers of the old shape must not break."""
        data = await _fetch(monkeypatch, b"{}")
        for key in (
            "url", "status_code", "headers", "body", "body_length",
            "rate_limit_delay",
        ):
            assert key in data

    def test_the_cap_itself_is_unchanged(self) -> None:
        """Deliberately not raised. The body crosses the intent bus inline, so
        widening it reintroduces the #636 OOM shape (AD-731). The path for
        large bodies is AD-1221, not a bigger constant."""
        assert HttpFetchAgent.MAX_BODY_BYTES == 1024 * 1024


# ── AD-1222: the install tier is its own decision ──────────────────────────
class _Resolver:
    def __init__(self, missing: list[str]) -> None:
        self._missing = missing
        self._approval_fn = None

    def detect_missing(self, source: str) -> list[str]:
        return list(self._missing)

    async def resolve(self, source: str, *, pre_approved: bool = False):
        return DependencyResult(success=True, installed=list(self._missing))


def _runtime(store, resolver, *, auto_approve: list[str]):
    return SimpleNamespace(
        config=SimpleNamespace(
            dependency=SimpleNamespace(
                dynamic_install_enabled=True,
                auto_approve_imports=auto_approve,
            ),
            # Deliberately WIDE, to prove the dependency path no longer reads it.
            self_mod=SimpleNamespace(
                allowed_imports=["json", "feedparser", "psutil", "requests"]
            ),
        ),
        dependency_resolver=resolver,
        capability_request_store=store,
        event_log=None,
    )


class TestTheInstallTierIsNotBorrowed:
    @pytest.mark.asyncio
    async def test_a_third_party_package_now_asks_even_if_self_mod_allows_it(
        self, tmp_path
    ) -> None:
        """The headline. `feedparser` sits on self_mod.allowed_imports, so it
        used to install with no prompt. It is not on the dependency tier, so it
        must now reach the Captain."""
        store = CapabilityRequestStore(db_path=str(tmp_path / "r.db"))
        await store.start()
        rt = _runtime(store, _Resolver(["feedparser"]), auto_approve=["json"])

        result = await ProbOSRuntime.ensure_dependency(
            rt, "feedparser", requested_by="counselor_0"
        )

        assert not result.success
        pending = await store.list_pending()
        assert [r.target for r in pending] == ["feedparser"]

    @pytest.mark.asyncio
    async def test_an_import_on_the_dependency_tier_still_auto_approves(
        self, tmp_path
    ) -> None:
        store = CapabilityRequestStore(db_path=str(tmp_path / "r.db"))
        await store.start()
        rt = _runtime(store, _Resolver(["json"]), auto_approve=["json"])

        await ProbOSRuntime.ensure_dependency(rt, "json", requested_by="c_0")

        assert await store.list_pending() == []

    @pytest.mark.asyncio
    async def test_the_self_mod_allowlist_is_not_consulted_at_all(
        self, tmp_path
    ) -> None:
        """Asserted directly, so the coupling cannot quietly return: a config
        with NO self_mod attribute must still work on the dependency path."""
        store = CapabilityRequestStore(db_path=str(tmp_path / "r.db"))
        await store.start()
        rt = SimpleNamespace(
            config=SimpleNamespace(
                dependency=SimpleNamespace(
                    dynamic_install_enabled=True,
                    auto_approve_imports=["json"],
                ),
            ),
            dependency_resolver=_Resolver(["feedparser"]),
            capability_request_store=store,
            event_log=None,
        )

        result = await ProbOSRuntime.ensure_dependency(
            rt, "feedparser", requested_by="counselor_0"
        )

        assert not result.success
        assert len(await store.list_pending()) == 1


class TestTheShippedTier:
    def test_the_default_tier_is_stdlib_only(self) -> None:
        """An install is an authority grant. The shipped set grants it only for
        the standard library; a third-party package asks."""
        import sys

        tier = DependencyConfig().auto_approve_imports
        assert tier, "an empty tier would make even stdlib imports ask"
        third_party = [
            name for name in tier
            if name.split(".")[0] not in sys.stdlib_module_names
        ]
        assert third_party == [], (
            f"these install with NO Captain prompt: {third_party}"
        )

    def test_none_of_the_silently_granted_packages_survive(self) -> None:
        """The measured list. These 16 third-party names rode the borrowed
        self-mod allowlist on the live vessel, and five of them were not even
        installed - so enabling dynamic install would have fetched them with no
        prompt. None may appear on the deliberate tier.
        """
        was_granted = {
            "httpx", "feedparser", "bs4", "lxml", "chardet", "yaml", "toml",
            "pandas", "numpy", "openpyxl", "markdown", "jinja2", "dateutil",
            "tabulate", "psutil", "pydantic",
        }
        tier = set(DependencyConfig().auto_approve_imports)
        assert tier & was_granted == set(), (
            f"still auto-installs without asking: {sorted(tier & was_granted)}"
        )

    def test_config_parses_when_the_field_is_absent(self) -> None:
        """Byte-identical for an operator who never sets it."""
        cfg = SystemConfig(**{"dependency": {"dynamic_install_enabled": True}})
        assert cfg.dependency.auto_approve_imports
        assert cfg.dependency.dynamic_install_enabled is True
