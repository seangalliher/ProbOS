"""AD-1137 (#1056): does each LLM tier the runtime calls actually answer?

Supersedes AD-801's reachability roll-up, which read any HTTP status below 500
from ``check_connectivity()`` as reachable, so a rejected key (401/403) or a
wrong base URL or model (404) passed. The check now asks what ``probos setup``
asks, with setup's own classified probes (``provider_setup``): the model listing
once per base URL and key, then the runtime's one-token boot-probe payload once
per distinct model, read as ``__main__._setup_validate`` reads the pair. It adds
no status classifier of its own.

Checked: the three text tiers, and each optional tier its runtime consumer reads
as configured (``provider_setup.TIER_CONFIGURED_CHECKS``). Reported but not
verified (WARN): ``api_format: ollama`` tiers, whose API the probes do not speak,
image_gen, whose runtime call creates an image, a tier whose probe would not fit
in what is left of ``LLM_CHECK_BUDGET_S``, and one whose probe is still running
when that runs out. Every message has each configured key's forms redacted, and a
URL is shown as ``provider_setup.shown_base_url`` shows it.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from probos import provider_setup as ps
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

if TYPE_CHECKING:
    import httpx

logger = logging.getLogger(__name__)

_Probe = ps.ProbeOutcome

# The fix for each failed probe outcome; a test pins that every outcome but OK has one.
REMEDIATION: dict[ps.ProbeOutcome, str] = {
    _Probe.NOT_FOUND: "Check the base URL: OpenAI-compatible APIs usually end in /v1 (OpenRouter: /api/v1).",
    _Probe.UNREACHABLE: "Start the provider, or correct the base URL.",
    _Probe.TIMEOUT: "Check that the provider is running and not overloaded, then rerun `probos doctor`.",
    _Probe.REDIRECTED: "Set the base URL to the provider's own API URL; ProbOS never follows a redirect with the key.",
    _Probe.AUTH_REJECTED: (
        "Check the API key: rerun `probos setup`, or correct llm_api_key_<tier> (or the shared llm_api_key) "
        "in the config."
    ),
    _Probe.MODEL_REJECTED: "Choose a model the provider serves: rerun `probos setup` to pick one.",
    _Probe.REQUEST_REJECTED: "Check the model name and the provider account named in the provider's reply.",
    _Probe.RATE_LIMITED: "The provider is rate-limiting this key; wait, then rerun `probos doctor`.",
    _Probe.PROVIDER_ERROR: "The provider failed the request; check its status, then rerun `probos doctor`.",
    _Probe.BAD_RESPONSE: "Something other than an OpenAI-compatible API answered: check the base URL (usually ending in /v1).",
    _Probe.EMPTY_RESPONSE: "The model answered without text, which the runtime counts as down; choose another model.",
}
# A limit on this key right now, not a fault in the configuration.
_WARN_PROBES = frozenset({_Probe.RATE_LIMITED})
# image_gen's runtime call is POST {base}/images/generations (image_gen_dispatch.py), not a chat completion.
_NOT_PROBED = {"image_gen": "not checked: an image-generation probe would create an image, which providers bill"}
# Doctor stops waiting for providers after this; bounds its wait, costs leaving a slow or later tier unverified.
LLM_CHECK_BUDGET_S = 60.0
# How often the waits wake: the probe's to reread _clock() and the stop signal, the loop's to run a Ctrl+C handler.
_POLL_S = 0.05


@dataclass(frozen=True)
class TierFinding:
    """One tier's verdict. ``detail`` is one line; ``remediation`` is empty for OK."""

    tier: str
    outcome: CheckOutcome
    detail: str
    remediation: str = ""


def _clock() -> float:
    """The monotonic clock the time budget reads; tests replace it to stand in for a slow provider."""
    return time.monotonic()


def _tiers(cognitive: Any) -> list[str]:
    """The tiers the runtime calls: the text tiers, then each optional tier read as configured."""
    optional = [tier for tier in ps.OPTIONAL_TIERS if ps.TIER_CONFIGURED_CHECKS[tier](cognitive)]
    return [*ps.TEXT_TIERS, *optional]


def _failure(tier: str, where: str, result: ps.ProbeResult) -> TierFinding:
    outcome = CheckOutcome.WARN if result.outcome in _WARN_PROBES else CheckOutcome.FAIL
    return TierFinding(tier, outcome, f"{where}: {result.message}", REMEDIATION[result.outcome])


def _unchecked(tier: str, where: str, subject: str, wait: float) -> TierFinding:
    return TierFinding(
        tier, CheckOutcome.WARN,
        f"{where}: not checked: less than {subject}'s {wait:g} s timeout is left of doctor's "
        f"{LLM_CHECK_BUDGET_S:g} s for provider checks",
        "Fix the slow or failing tiers listed here, then rerun `probos doctor`.",
    )


def _abandoned(tier: str, where: str, subject: str) -> TierFinding:
    detail = (
        f"{where}: not verified: {subject} was still waiting for the provider when doctor's "
        f"{LLM_CHECK_BUDGET_S:g} s for provider checks ran out"
    )
    return TierFinding(tier, CheckOutcome.WARN, detail, REMEDIATION[_Probe.TIMEOUT])


class _Abort:
    """A probe's ``on_client``: lets the checking thread close the probe's client, ending an established request (A-4).

    The handoff is a probe's start: a client handed over once ``stop`` is set is closed before its request is
    sent (A-5).
    """

    def __init__(self, stop: threading.Event | None = None) -> None:
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._closed = False
        self._stop = stop if stop is not None else threading.Event()

    def __call__(self, client: httpx.Client) -> None:
        with self._lock:
            self._client = client
            self._closed = self._closed or self._stop.is_set()
            closed = self._closed
        if closed:  # the wait ended, or the check was stopped, before the probe had its client: nothing is sent
            client.close()

    def close(self) -> None:
        with self._lock:
            self._closed, client = True, self._client
        if client is not None:
            client.close()


def _bounded(
    probe: Callable[[_Abort], ps.ProbeResult], deadline: float, stop: threading.Event,
) -> ps.ProbeResult | None:
    """Run ``probe`` in a daemon thread and wait for it until ``_clock()`` reaches ``deadline`` or ``stop`` is set.

    None if it is still running then: it is abandoned and its client closed, which ends an established request
    (AD-1137 A-4, measured on Windows); a connection still being opened is not interrupted, and its request is
    sent when it opens. A daemon thread, not an executor: a pool's workers are joined at interpreter exit, so a
    probe that never ends would keep ``probos doctor`` from exiting (A-3, measured). An exception from ``probe``
    is raised here, in the checking thread.
    A stopped check starts no probe and uses no probe's result (A-5).
    """
    abort = _Abort(stop)
    if stop.is_set():  # AD-1137 A-5: stopped after admission; no thread and no request
        return None
    done: list[ps.ProbeResult | Exception] = []

    def run() -> None:
        try:
            done.append(probe(abort))
        except Exception as exc:  # raised below, in the checking thread, which reports only its type
            done.append(exc)

    worker = threading.Thread(target=run, name="probos-doctor-probe", daemon=True)
    worker.start()
    while worker.is_alive() and not stop.is_set() and (left := deadline - _clock()) > 0:
        worker.join(min(left, _POLL_S))
    if stop.is_set() or not done:  # AD-1137 A-5: once stopped, no probe's result is used
        abort.close()
        return None
    if isinstance(done[0], Exception):
        raise done[0]
    return done[0]


def _probe_tier(
    tier: str,
    tc: dict,
    listings: dict[tuple[str, str], ps.ProbeResult],
    chats: dict[tuple[str, str, str, float], ps.ProbeResult],
    transport: httpx.BaseTransport | None,
    admits: Callable[[float], bool],
    within_budget: Callable[[Callable[[_Abort], ps.ProbeResult]], ps.ProbeResult | None],
) -> TierFinding:
    base_url, api_key, model = tc["base_url"], tc["api_key"] or "", tc["model"]
    where = ps.shown_base_url(base_url)
    listing = listings.get((base_url, api_key))
    if listing is None:
        if not admits(ps.MODELS_PROBE_TIMEOUT_S):
            return _unchecked(tier, where, "the model listing", ps.MODELS_PROBE_TIMEOUT_S)
        listing = within_budget(
            lambda abort: ps.probe_models(base_url, api_key, transport=transport, on_client=abort),
        )
        if listing is None:
            return _abandoned(tier, where, "the model listing")
        listings[(base_url, api_key)] = listing
    if listing.outcome not in (_Probe.OK, _Probe.NOT_FOUND):
        return _failure(tier, where, listing)
    # The runtime's boot probe waits min(tier timeout, 30 s) (llm_client.py _check_endpoint, BF-270).
    timeout = min(float(tc["timeout"] or 5.0), ps.CHAT_PROBE_TIMEOUT_S)
    key = (base_url, api_key, model, timeout)
    chat = chats.get(key)
    if chat is None:
        if not admits(timeout):
            return _unchecked(tier, where, "the chat check", timeout)
        chat = within_budget(lambda abort: ps.probe_chat(
            base_url, api_key, model, model_ids=listing.model_ids, timeout=timeout, transport=transport,
            on_client=abort,
        ))
        if chat is None:
            return _abandoned(tier, where, "the chat check")
        chats[key] = chat
    if chat.outcome is _Probe.OK:
        return TierFinding(tier, CheckOutcome.OK, f"model {model!r} at {where}")
    if listing.outcome is _Probe.NOT_FOUND and chat.outcome is _Probe.NOT_FOUND:
        # Setup's reading of the same pair (__main__._setup_validate).
        return TierFinding(
            tier, CheckOutcome.FAIL, f"{where}: no OpenAI-compatible API at this base URL", REMEDIATION[_Probe.NOT_FOUND],
        )
    return _failure(tier, where, chat)


def check_tiers(
    cognitive: Any, transport: httpx.BaseTransport | None = None, stop: threading.Event | None = None,
) -> list[TierFinding]:
    """Probe every tier the runtime calls, in tier order; blocking, so the check runs it in a thread.

    Probes run one after another, and doctor stops waiting at ``LLM_CHECK_BUDGET_S`` (A-3), or as soon as
    ``stop`` is set, when the check is cancelled (A-4). httpx's timeouts bound each read, not a whole request, so
    a provider that sends its answer a byte at a time can outlast them; each probe therefore runs in a daemon
    thread (``_bounded``). A probe still running when the wait ends is abandoned, its tier reported as not
    verified, and its client closed (``_bounded``); a probe handed its client after the wait ends or the check
    is stopped sends no request (A-5). A probe starts only if its whole timeout fits in what is left, and
    doctor's own limit is never reported as the provider's TIMEOUT.
    A tier that shares a probe already made needs no time, so it is always resolved. The findings of a stopped
    check read as if its budget had run out; the cancelled check that stopped it returns none of them.
    """
    deadline = _clock() + LLM_CHECK_BUDGET_S
    stopped = stop if stop is not None else threading.Event()

    def admits(wait: float) -> bool:
        return not stopped.is_set() and _clock() + wait <= deadline

    def within_budget(probe: Callable[[_Abort], ps.ProbeResult]) -> ps.ProbeResult | None:
        return _bounded(probe, deadline, stopped)

    listings: dict[tuple[str, str], ps.ProbeResult] = {}
    chats: dict[tuple[str, str, str, float], ps.ProbeResult] = {}
    findings: list[TierFinding] = []
    for tier in _tiers(cognitive):
        tc = cognitive.tier_config(tier)
        where = ps.shown_base_url(tc["base_url"])
        if tier in _NOT_PROBED:
            findings.append(TierFinding(tier, CheckOutcome.WARN, f"{where}: {_NOT_PROBED[tier]}"))
        elif tc["api_format"] == "ollama":
            findings.append(TierFinding(
                tier, CheckOutcome.WARN, f"{where}: not checked: doctor checks the OpenAI-compatible API, "
                "and this tier uses api_format ollama",
                "`probos setup --provider ollama` configures Ollama's OpenAI-compatible /v1 API, which doctor checks.",
            ))
        elif not tc["model"]:
            findings.append(TierFinding(
                tier, CheckOutcome.FAIL, f"{where}: no model is configured",
                f"Rerun `probos setup`, or set llm_model_{tier} in the config.",
            ))
        else:
            try:
                findings.append(_probe_tier(tier, tc, listings, chats, transport, admits, within_budget))
            except Exception as exc:  # e.g. a malformed URL; its text can hold the URL, so only its type is used
                logger.debug(
                    "AD-1137: doctor could not probe the %s tier (%s); reporting it as failed",
                    tier, type(exc).__name__,
                )
                findings.append(TierFinding(
                    tier, CheckOutcome.FAIL, f"{where}: the check could not run ({type(exc).__name__})",
                    "Check this tier's base URL in the config.",
                ))
    return findings


def _grouped(findings: list[TierFinding]) -> list[tuple[str, TierFinding]]:
    """Findings with the same verdict, detail and fix, as ("fast, standard", first finding), in order."""
    groups: dict[tuple[CheckOutcome, str, str], list[TierFinding]] = {}
    for finding in findings:
        groups.setdefault((finding.outcome, finding.detail, finding.remediation), []).append(finding)
    return [(", ".join(f.tier for f in members), members[0]) for members in groups.values()]


def summarize(findings: list[TierFinding], secrets: list[str]) -> CheckResult:
    """One result for all tiers: FAIL if any fails, else WARN if any is unverified, else OK."""
    failed = [f for f in findings if f.outcome is CheckOutcome.FAIL]
    warned = [f for f in findings if f.outcome is CheckOutcome.WARN]
    answered = ", ".join(f.tier for f in findings if f.outcome is CheckOutcome.OK)
    if failed:
        outcome = CheckOutcome.FAIL
        message = f"LLM tier check failed for {', '.join(f.tier for f in failed)}"
        if answered:
            message += f" ({answered} answer)"
    elif warned:
        outcome = CheckOutcome.WARN
        message = f"LLM tiers answer: {answered or 'none'}; not verified: {', '.join(f.tier for f in warned)}"
    else:
        outcome = CheckOutcome.OK
        message = "LLM tiers answer: " + "; ".join(f"{tiers}: {f.detail}" for tiers, f in _grouped(findings))
    lines: list[str] = []
    for tiers, finding in _grouped(failed + warned):
        lines.append(f"{tiers}: {finding.detail}")
        if finding.remediation:
            lines.append(f"  {finding.remediation}")
    remediation = "\n".join(lines)
    for secret in secrets:
        message = ps.redact(message, secret)
        remediation = ps.redact(remediation, secret)
    return CheckResult(outcome=outcome, message=message, remediation=remediation)


@dataclass(frozen=True)
class _LLMCheck:
    name: str = "llm_tiers"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="LLM tiers: skipped (config unavailable)",
            )
        cognitive = ctx.config.cognitive
        stop = threading.Event()
        checking = asyncio.get_running_loop().run_in_executor(
            None, check_tiers, cognitive, ctx.provider_transport, stop,
        )
        try:
            while not checking.done():
                # A selector loop (the CLI's, on Windows) runs Ctrl+C's handler only when it wakes (A-4, measured).
                await asyncio.wait({checking}, timeout=_POLL_S)
        finally:
            stop.set()  # cancelled: check_tiers stops waiting, so asyncio.run's join of its thread is prompt
        return summarize(checking.result(), ps.configured_api_keys(cognitive))


register_check(_LLMCheck())
