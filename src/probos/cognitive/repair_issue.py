"""AD-1206: Captain-approved issue filing, not autonomous repair execution."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Protocol

import httpx

from probos.capability_request import CapabilityRequest, repair_action
from probos.cognitive.repair_brief import build_repair_brief
from probos.cognitive.trace_analysis import analyse_trace, load_trace, quote_for_prose
from probos.diagnostic_safety import SanitisedTraceReader, sanitise_diagnostic_value
from probos.diagnostic_safety import TraceReader as TraceReader
from probos.fault_issue_filings import (
    FaultIssueFilings, FilingClaim, FilingDisposition, FilingUnavailable, IssueReceipt,
    valid_github_repository, valid_issue_receipt, valid_occurrence_count, valid_repository_url,
)
from probos.fault_report import FaultReport

logger = logging.getLogger(__name__)

_FILING_LIFECYCLE_NOTICE = (
    "Filing this issue is not a fix and does not alter the fault's lifecycle status."
)

class Credentials(Protocol):
    def get(self, name: str, *, requester: str = "unknown") -> str | None: ...


class ApprovedRequests(Protocol):
    async def get(
        self, request_id: str, *, durable: bool = False,
    ) -> CapabilityRequest | None: ...

    async def mark_fulfilled(self, request_id: str) -> CapabilityRequest | None: ...


@dataclass(frozen=True)
class IssueReport:
    title: str
    body: str


@dataclass(frozen=True)
class IssueAttempt:
    disposition: FilingDisposition
    receipt: IssueReceipt | None = None
    failure_code: str = ""


class IssueClient(Protocol):
    async def create(self, repository: str, fault: FaultReport) -> IssueAttempt: ...

    async def reconcile(self, repository: str, signature: str) -> IssueAttempt: ...


class IssueDispatchCancelled(asyncio.CancelledError):
    def __init__(self, dispatched: bool) -> None:
        super().__init__("issue_dispatch_cancelled")
        self.dispatched = dispatched


def issue_marker(signature: str) -> str:
    if re.fullmatch(r"[0-9a-f]{64}", signature) is None:
        raise ValueError("invalid_fault_signature")
    return f"<!-- probos-fault:{signature} -->"


def _warn_trace_unavailable() -> None:
    logger.warning(
        "AD-1206: fault trace could not be read safely; the issue report "
        "will explicitly identify unavailable trace evidence"
    )


async def build_issue_report(
    fault: FaultReport, *, attachment_store: TraceReader | None = None,
    secrets: tuple[str, ...] = (),
) -> IssueReport:
    """Sanitize copies before any summarizer, renderer or length limit runs."""
    fields = sanitise_diagnostic_value(fault.to_dict(), secrets)
    safe = replace(fault, **{
        name: fields[name] for name in (
            "tool_id", "error_text", "attempted", "agent_id", "thread_id",
            "tool_trace_ref", "work_item_id", "observed_as",
        )
    })
    entries = await load_trace(
        SanitisedTraceReader(attachment_store, secrets, warn_unavailable=_warn_trace_unavailable),
        fault.tool_trace_ref or "",
    )
    trace = (
        analyse_trace(entries).render()[:4000] if entries
        else "Trace unavailable: no readable recorded tool calls."
    )
    brief = build_repair_brief(safe, trace_summary=trace)
    provenance = {
        key: fields[key] for key in (
            "agent_id", "thread_id", "work_item_id", "tool_trace_ref", "observed_as",
        )
    }
    body = "\n\n".join((
        "# Approved ProbOS fault report",
        issue_marker(fault.signature),
        f"Fault ID: {fault.id}\nSignature: {fault.signature}\n"
        f"Tool: {quote_for_prose(safe.tool_id)}\nOccurrences: {fault.occurrences}",
        _FILING_LIFECYCLE_NOTICE,
        "## Error evidence\n" + quote_for_prose(brief.error_text)[:2000],
        "## Attempted operation\n" + quote_for_prose(brief.attempted)[:1200],
        "## Trace\n" + trace,
        "## Provenance\n" + json.dumps(provenance, ensure_ascii=False)[:2000],
        "## Repair acceptance\n" + "\n".join(f"- {item}" for item in brief.acceptance),
    ))
    return IssueReport(brief.title[:120], body[:12000])


def _receipt(data: object, repository: str) -> IssueReceipt | None:
    if not isinstance(data, dict) or "pull_request" in data:
        return None
    receipt = IssueReceipt(data.get("number"), data.get("html_url"))
    return receipt if valid_issue_receipt(repository, receipt) else None


class GitHubIssueClient:
    """One injected HTTP boundary: create an issue or reconcile an uncertain one."""

    def __init__(
        self, *, credential_store: Credentials | None,
        http_client_factory: Callable[[], httpx.AsyncClient],
        attachment_store: TraceReader | None = None,
    ) -> None:
        self._credentials = credential_store
        self._http = http_client_factory
        self._attachments = attachment_store

    def _token(self) -> str | None:
        return (
            self._credentials.get("github", requester="repair_issue")
            if self._credentials is not None else None
        )

    async def create(self, repository: str, fault: FaultReport) -> IssueAttempt:
        dispatched = False
        try:
            if not valid_github_repository(repository):
                return IssueAttempt("retryable_failure", failure_code="missing_repository")
            token = self._token()
            if not token:
                return IssueAttempt("retryable_failure", failure_code="missing_credential")
            report = await build_issue_report(
                fault, attachment_store=self._attachments, secrets=(token,),
            )
            async with self._http() as client:
                dispatched = True
                try:
                    response = await client.post(
                        f"https://api.github.com/repos/{repository}/issues",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Accept": "application/vnd.github+json",
                            "X-GitHub-Api-Version": "2022-11-28",
                        },
                        json={"title": report.title, "body": report.body},
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                    return IssueAttempt("retryable_failure", failure_code="pre_send_failure")
                if response.status_code in {400, 401, 403, 404, 410, 422, 429}:
                    return IssueAttempt("retryable_failure", failure_code="rejected")
                if response.status_code != 201:
                    return IssueAttempt("outcome_unknown", failure_code="remote_uncertain")
                try:
                    receipt = _receipt(response.json(), repository)
                except (ValueError, TypeError):
                    receipt = None
                return (
                    IssueAttempt("filed", receipt) if receipt else
                    IssueAttempt("outcome_unknown", failure_code="malformed_receipt")
                )
        except asyncio.CancelledError:
            raise IssueDispatchCancelled(dispatched) from None
        except Exception:
            return IssueAttempt(
                "outcome_unknown" if dispatched else "retryable_failure",
                failure_code="remote_uncertain" if dispatched else "pre_send_failure",
            )

    async def reconcile(self, repository: str, signature: str) -> IssueAttempt:
        unknown = IssueAttempt("outcome_unknown", failure_code="reconciliation_unconfirmed")
        try:
            if not valid_github_repository(repository):
                return unknown
            marker = issue_marker(signature)
            token = self._token()
            if not token:
                return IssueAttempt("outcome_unknown", failure_code="missing_credential")
            async with self._http() as client:
                response = await client.get(
                    "https://api.github.com/search/issues",
                    params={
                        "q": f'repo:{repository} is:issue in:body "{marker}"',
                        "per_page": 100, "page": 1,
                    },
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                )
                if response.status_code != 200:
                    return unknown
                data = response.json()
                if not isinstance(data, dict):
                    return unknown
                items, total = data.get("items"), data.get("total_count")
                if (
                    data.get("incomplete_results") is not False
                    or type(total) is not int or not 0 <= total <= 100
                    or not isinstance(items, list) or len(items) != total
                    or "next" in response.links
                ):
                    return unknown
                matches = []
                for item in items:
                    receipt = _receipt(item, repository)
                    if (
                        receipt is not None
                        and valid_repository_url(repository, item.get("repository_url"))
                        and item.get("state") in {"open", "closed"}
                        and type(item.get("body")) is str
                        and marker in item["body"].splitlines()
                    ):
                        matches.append(receipt)
                return IssueAttempt("filed", matches[0]) if len(matches) == 1 else unknown
        except asyncio.CancelledError:
            raise
        except Exception:
            return unknown


class RepairIssueFulfiller:
    """Inline consumer of durable Captain authority and the fault-owned journal."""

    def __init__(
        self, *, requests: ApprovedRequests, filings: FaultIssueFilings,
        client: IssueClient, repository: str, enabled: bool,
        notify: Callable[..., None], minimum_occurrences: int = 2,
    ) -> None:
        if not valid_occurrence_count(minimum_occurrences):
            raise ValueError("invalid_minimum_occurrences")
        self._requests, self._filings, self._client = requests, filings, client
        self._repository, self._enabled, self._notify = repository, enabled, notify
        self._minimum_occurrences = minimum_occurrences

    def _notice(
        self, request_id: str, category: str, *, uncertain: bool = False,
        issue_url: str = "",
    ) -> None:
        guidance = (
            "Retry only reconciles open and closed issues; it never sends another create."
            if uncertain else "Correct the prerequisite, then explicitly Retry this approval."
        )
        if category == "durable_qualification_unavailable":
            guidance = (
                "Durable qualifying evidence is unavailable. Retry only after "
                "durable evidence or configuration permits filing."
            )
        elif category == "decline_metadata_unavailable":
            guidance = (
                "Denial remains effective. This denial filed no issue; "
                "recording decline audit metadata failed."
            )
        if issue_url:
            guidance = "The issue is linked. " + _FILING_LIFECYCLE_NOTICE
        try:
            self._notify(
                "system", "Fault issue filed" if issue_url else "Fault issue filing needs attention",
                detail=f"Request {request_id}: {category}. {guidance}",
                notification_type="info" if issue_url else "action_required",
                action_url=issue_url,
            )
        except Exception:
            logger.warning(
                "AD-1206: Captain notification delivery failed; filing status "
                "remains durable and the approval queue remains authoritative"
            )

    async def fulfil(self, request_id: str) -> CapabilityRequest | None:
        claim: FilingClaim | None = None
        try:
            req = await self._requests.get(request_id, durable=True)
            identity = repair_action(req) if req is not None else None
            if (
                req is None or identity is None or req.status != "approved"
                or req.decided_by != "captain" or req.decided_at is None
            ):
                self._notice(request_id, "durable_approval_required")
                return None
            if not self._enabled:
                self._notice(request_id, "repair_disabled")
                return None
            claim = await self._filings.claim(
                fault_id=identity.fault_id, signature=identity.signature, tool_id=identity.tool_id,
                request_id=req.id, repository=self._repository, agent_id=req.agent_id,
                thread_id=identity.thread_id, work_item_id=req.work_item_id,
                minimum_occurrences=self._minimum_occurrences,
            )
            filing = claim.filing
            if filing.disposition == "filed":
                receipt = IssueReceipt(filing.issue_number, filing.issue_url)
                if not valid_issue_receipt(filing.repository, receipt):
                    self._notice(request_id, "invalid_receipt", uncertain=True)
                    return None
            else:
                result = (
                    await self._client.create(filing.repository, claim.fault) if claim.acquired
                    else await self._client.reconcile(filing.repository, filing.signature)
                )
                filing = await self._filings.complete(
                    filing.signature, filing.attempt_id, disposition=result.disposition,
                    receipt=result.receipt, failure_code=result.failure_code,
                )
                if filing is None or filing.disposition != "filed":
                    self._notice(
                        request_id, result.failure_code or "receipt_not_committed",
                        uncertain=result.disposition == "outcome_unknown",
                    )
                    return None
            updated = await self._requests.mark_fulfilled(req.id)
            if updated is not None:
                self._notice(request_id, "filed", issue_url=filing.issue_url)
            else:
                self._notice(request_id, "fulfilment_not_recorded", uncertain=True)
            return updated
        except asyncio.CancelledError as exc:
            uncertain = not isinstance(exc, IssueDispatchCancelled) or exc.dispatched
            if claim is not None:
                try:
                    await self._filings.complete(
                        claim.filing.signature, claim.filing.attempt_id,
                        disposition="outcome_unknown" if uncertain else "retryable_failure",
                        failure_code="cancelled",
                    )
                except Exception:
                    uncertain = True
                    logger.error(
                        "AD-1206: cancellation status could not be committed; the "
                        "durable claim remains non-replayable and Retry only reconciles"
                    )
            self._notice(request_id, "cancelled", uncertain=uncertain)
            raise
        except Exception as exc:
            logger.warning(
                "AD-1206: approved fault filing could not complete durably; the "
                "approval remains outstanding and no success is reported"
            )
            category = (
                "durable_qualification_unavailable"
                if isinstance(exc, FilingUnavailable)
                and exc.args == ("durable_qualification_unavailable",)
                else "filing_not_completed"
            )
            self._notice(request_id, category, uncertain=claim is not None)
            return None

    async def decline(self, request_id: str) -> None:
        try:
            req = await self._requests.get(request_id, durable=True)
            identity = repair_action(req) if req is not None else None
            if req is None or identity is None or req.status != "denied" or req.decided_by != "captain":
                return
            await self._filings.decline(
                fault_id=identity.fault_id, signature=identity.signature, tool_id=identity.tool_id,
                request_id=req.id, agent_id=req.agent_id, thread_id=identity.thread_id,
                work_item_id=req.work_item_id,
            )
        except Exception:
            logger.warning(
                "AD-1206: decline metadata could not be committed; the Captain's "
                "denial remains authoritative and no external filing is attempted"
            )
            self._notice(request_id, "decline_metadata_unavailable")
