"""ScoutAgent -- Daily GitHub intelligence gathering for ProbOS (AD-394, AD-395)."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import CapabilityDescriptor, IntentDescriptor

logger = logging.getLogger(__name__)

_DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"

_INSTRUCTIONS = (
    "You are the ProbOS Scout, a Science department officer responsible for "
    "intelligence gathering. You analyze GitHub repositories and classify them "
    "for ProbOS relevance.\n\n"
    "For each repository provided, respond with a structured report block.\n\n"
    "CLASSIFICATION CRITERIA:\n"
    "- ABSORB: Contains a pattern, technique, or architectural concept ProbOS "
    "should learn from. Focus on: agent communication, context management, "
    "trust/safety patterns, multi-agent orchestration, developer experience.\n"
    "- VISITING_OFFICER: A tool that could integrate under ProbOS command. "
    "Must pass the Subordination Principle -- ProbOS must control context, "
    "commits, model selection, and trust tracking. If the tool manages its "
    "own orchestration loop, classify as SKIP (competing captain).\n"
    "- SKIP: Not relevant to ProbOS. Most repos will be skips.\n\n"
    "RESPONSE FORMAT (one block per repo):\n"
    "===SCOUT_REPORT===\n"
    "REPO: owner/name\n"
    "STARS: 1234\n"
    "URL: https://github.com/owner/name\n"
    "CLASS: absorb | visiting_officer | skip\n"
    "RELEVANCE: 3\n"
    "CREDIBILITY: 3\n"
    "RELIABILITY: 3\n"
    "SUMMARY: One-line description.\n"
    "INSIGHT: Why this matters to ProbOS.\n"
    "===END===\n\n"
    "QUALITY STANDARDS:\n"
    "- Be concise -- the Captain reads these over coffee\n"
    "- Include the 'so what' -- why should the Captain care?\n"
    "- Relevance scale: 1=tangential, 2=somewhat related, 3=useful pattern, "
    "4=important insight, 5=critical find\n"
    "- Credibility scale: 1-5 (project maturity -- docs quality, CI status, "
    "contributor count, release cadence)\n"
    "- Reliability scale: 1-5 (maintenance health -- last commit recency, "
    "issue response, test coverage indicators)\n"
)


@dataclass
class ScoutFinding:
    """A single scout intelligence finding."""

    repo_full_name: str
    stars: int
    url: str
    classification: str  # "absorb" | "visiting_officer"
    relevance: int  # 1-5
    credibility: int  # 1-5 (AD-395)
    reliability: int  # 1-5 (AD-395)
    summary: str
    insight: str
    language: str = ""
    license: str = ""
    topics: list[str] = field(default_factory=list)

    @property
    def composite_score(self) -> float:
        """Weighted composite: relevance 50%, credibility 25%, reliability 25%."""
        return self.relevance * 0.5 + self.credibility * 0.25 + self.reliability * 0.25


def parse_scout_reports(text: str) -> list[ScoutFinding]:
    """Parse ===SCOUT_REPORT=== blocks from LLM output."""
    findings: list[ScoutFinding] = []
    blocks = text.split("===SCOUT_REPORT===")
    for block in blocks:
        if "===END===" not in block:
            continue
        content = block.split("===END===")[0].strip()
        fields: dict[str, str] = {}
        for line in content.splitlines():
            line = line.strip()
            if ":" in line:
                key, _, val = line.partition(":")
                fields[key.strip().upper()] = val.strip()

        classification = fields.get("CLASS", "skip").lower().strip()
        if classification not in ("absorb", "visiting_officer"):
            continue

        try:
            relevance = int(fields.get("RELEVANCE", "0"))
        except ValueError:
            relevance = 0

        try:
            credibility = int(fields.get("CREDIBILITY", "3"))
        except ValueError:
            credibility = 3

        try:
            reliability = int(fields.get("RELIABILITY", "3"))
        except ValueError:
            reliability = 3

        findings.append(ScoutFinding(
            repo_full_name=fields.get("REPO", ""),
            stars=int(fields.get("STARS", "0")) if fields.get("STARS", "0").isdigit() else 0,
            url=fields.get("URL", ""),
            classification=classification,
            relevance=relevance,
            credibility=credibility,
            reliability=reliability,
            summary=fields.get("SUMMARY", ""),
            insight=fields.get("INSIGHT", ""),
        ))
    return findings


def filter_findings(findings: list[ScoutFinding], min_relevance: int = 3) -> list[ScoutFinding]:
    """Filter findings by minimum composite score and sort descending."""
    return sorted(
        [f for f in findings if f.composite_score >= min_relevance],
        key=lambda f: f.composite_score,
        reverse=True,
    )


def format_digest(findings: list[ScoutFinding], date_str: str) -> str:
    """Format findings as a Discord-ready markdown digest."""
    absorb = [f for f in findings if f.classification == "absorb"]
    visiting = [f for f in findings if f.classification == "visiting_officer"]

    lines = [f"**ProbOS Scout Report -- {date_str}**", ""]

    if absorb:
        lines.append("**ABSORB CANDIDATES:**")
        for f in absorb:
            meta = f"{f.stars} stars"
            if f.language:
                meta += f", {f.language}"
            if f.license:
                meta += f", {f.license}"
            lines.append(f"- **{f.repo_full_name}** ({meta}) [score: {f.composite_score:.1f}]")
            lines.append(f"  {f.summary}")
            lines.append(f"  *Insight:* {f.insight}")
            lines.append(f"  R:{f.relevance} C:{f.credibility} L:{f.reliability} | {f.url}")
        lines.append("")

    if visiting:
        lines.append("**VISITING OFFICER CANDIDATES:**")
        for f in visiting:
            meta = f"{f.stars} stars"
            if f.language:
                meta += f", {f.language}"
            if f.license:
                meta += f", {f.license}"
            lines.append(f"- **{f.repo_full_name}** ({meta}) [score: {f.composite_score:.1f}]")
            lines.append(f"  {f.summary}")
            lines.append(f"  *Integration:* {f.insight}")
            lines.append(f"  R:{f.relevance} C:{f.credibility} L:{f.reliability} | {f.url}")
        lines.append("")

    if not absorb and not visiting:
        lines.append("No significant findings today.")
        lines.append("")

    lines.append(f"{len(findings)} findings | Full report on Bridge")
    return "\n".join(lines)


def _load_seen(seen_file: Path) -> dict[str, str]:
    """Load seen repo IDs with timestamps. Returns {repo_full_name: iso_date}."""
    if seen_file.exists():
        try:
            return json.loads(seen_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_seen(seen: dict[str, str], seen_file: Path) -> None:
    """Save seen repo IDs, pruning entries older than 90 days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
    pruned = {k: v for k, v in seen.items() if v >= cutoff}
    seen_file.parent.mkdir(parents=True, exist_ok=True)
    seen_file.write_text(json.dumps(pruned, indent=2), encoding="utf-8")


class ScoutAgent(CognitiveAgent):
    """GitHub intelligence scout -- finds AI agent projects relevant to ProbOS."""

    agent_type = "scout"
    tier = "domain"
    instructions = _INSTRUCTIONS
    default_capabilities = [
        CapabilityDescriptor(
            can="scout",
            detail="Search GitHub for AI agent projects and classify relevance to ProbOS",
        ),
    ]
    intent_descriptors = [
        IntentDescriptor(
            name="scout_search",
            description="Search GitHub for AI agent projects relevant to ProbOS -- "
                        "absorption candidates and visiting officer candidates",
        ),
        IntentDescriptor(
            name="scout_report",
            description="Show the latest scout intelligence report",
        ),
    ]
    _handled_intents = {"scout_search", "scout_report"}

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("pool", "scout")
        super().__init__(**kwargs)
        self._runtime = kwargs.get("runtime")
        self._last_findings: list[ScoutFinding] = []

    @property
    def _data_dir(self) -> Path:
        """Resolve data directory from runtime, falling back to project default."""
        if self._runtime and hasattr(self._runtime, "_data_dir"):
            return Path(self._runtime._data_dir)
        return _DEFAULT_DATA_DIR

    @property
    def _seen_file(self) -> Path:
        return self._data_dir / "scout_seen.json"

    @property
    def _reports_dir(self) -> Path:
        return self._data_dir / "scout_reports"

    def _resolve_tier(self) -> str:
        return "standard"

    async def _search_github(self, query: str, min_stars: int) -> list[dict[str, Any]]:
        """Search GitHub via gh CLI for authenticated rate limits (AD-395)."""
        encoded_query = f"{query} stars:>={min_stars}"
        logger.info("Scout: searching GitHub — %s", encoded_query[:100])
        try:
            result = await asyncio.to_thread(
                subprocess.run,
                ["gh", "api", "search/repositories",
                 "--method", "GET",
                 "-f", f"q={encoded_query}",
                 "-f", "sort=stars",
                 "-f", "per_page=30"],
                capture_output=True, encoding="utf-8", errors="replace", timeout=30,
            )
            if result.returncode != 0:
                logger.warning("Scout: gh api failed (rc=%d): %s", result.returncode, result.stderr[:200])
                return []
            if not result.stdout:
                logger.warning("Scout: gh api returned empty stdout for: %s", query[:80])
                return []
            data = json.loads(result.stdout)
            items = data.get("items", [])
            logger.info("Scout: found %d items for: %s", len(items), query[:60])
            return items
        except Exception as e:
            logger.warning("Scout: GitHub search error (%s): %s", type(e).__name__, e)
            return []

    async def perceive(self, intent: dict[str, Any]) -> dict[str, Any]:
        """Search GitHub for recent AI agent repositories."""
        result = await super().perceive(intent)
        intent_name = result.get("intent", "")

        if intent_name == "scout_report":
            report_text = self._load_latest_report()
            result["context"] = report_text or "No scout reports found yet. Run /scout to generate one."
            return result

        if intent_name != "scout_search":
            return result

        seven_days_ago = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        # GitHub search doesn't support OR between topic: qualifiers —
        # each topic needs a separate query.
        queries = [
            (f"topic:ai-agents pushed:>{seven_days_ago}", 50),
            (f"topic:llm-agents pushed:>{seven_days_ago}", 50),
            (f"topic:multi-agent pushed:>{seven_days_ago}", 50),
            (f"topic:agent-framework pushed:>{seven_days_ago}", 50),
            (f"topic:ai-coding pushed:>{seven_days_ago}", 100),
            (f"topic:code-generation pushed:>{seven_days_ago}", 100),
        ]

        seen = _load_seen(self._seen_file)
        new_repos: list[dict[str, Any]] = []

        for query, min_stars in queries:
            items = await self._search_github(query, min_stars)
            for item in items:
                full_name = item.get("full_name", "")
                if full_name in seen:
                    continue
                seen[full_name] = datetime.now(timezone.utc).isoformat()
                new_repos.append({
                    "full_name": full_name,
                    "description": item.get("description", "") or "",
                    "stars": item.get("stargazers_count", 0),
                    "created_at": item.get("created_at", ""),
                    "updated_at": item.get("updated_at", ""),
                    "language": item.get("language", "") or "",
                    "license": (item.get("license") or {}).get("spdx_id", ""),
                    "topics": item.get("topics", []),
                    "url": item.get("html_url", ""),
                })

        _save_seen(seen, self._seen_file)

        if not new_repos:
            result["context"] = "No new repositories found since last scan."
            return result

        repo_text = []
        for r in new_repos:
            repo_text.append(
                f"REPO: {r['full_name']}\n"
                f"DESC: {r['description'][:200]}\n"
                f"STARS: {r['stars']}\n"
                f"LANG: {r['language']}\n"
                f"LICENSE: {r['license']}\n"
                f"TOPICS: {', '.join(r['topics'][:10])}\n"
                f"URL: {r['url']}\n"
            )

        result["context"] = (
            f"Classify these {len(new_repos)} repositories:\n\n"
            + "\n---\n".join(repo_text)
        )

        self._repo_metadata = {r["full_name"]: r for r in new_repos}
        return result

    async def act(self, decision: dict[str, Any]) -> dict[str, Any]:
        """Parse LLM classification, store report, deliver notifications."""
        # AD-398: pass through conversational responses for 1:1 and ward room
        if decision.get("intent") in ("direct_message", "ward_room_notification"):
            return {"success": True, "result": decision.get("llm_output", "")}
        llm_output = decision.get("llm_output", "")
        if "No new repositories" in llm_output or not llm_output.strip():
            return {"success": True, "result": "No new findings to report."}

        findings = parse_scout_reports(llm_output)

        # Enrich with metadata from perceive
        metadata = getattr(self, "_repo_metadata", {})
        for f in findings:
            meta = metadata.get(f.repo_full_name, {})
            f.language = meta.get("language", f.language)
            f.license = meta.get("license", f.license)
            f.topics = meta.get("topics", f.topics)

        # Filter by relevance
        filtered = filter_findings(findings, min_relevance=3)
        self._last_findings = filtered

        # Store report
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._reports_dir.mkdir(parents=True, exist_ok=True)
        report_path = self._reports_dir / f"{date_str}.json"
        report_data = {
            "date": date_str,
            "total_classified": len(findings),
            "total_relevant": len(filtered),
            "findings": [asdict(f) for f in filtered],
        }
        report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

        # Bridge notifications for high-scoring findings (AD-395: composite_score)
        if self._runtime and hasattr(self._runtime, "notification_queue"):
            for f in filtered:
                if f.composite_score >= 4:
                    self._runtime.notification_queue.notify(
                        agent_id=self.id,
                        agent_type="scout",
                        department="science",
                        title=f"Scout: {f.repo_full_name}",
                        detail=f"[{f.classification}] {f.summary}",
                        notification_type="info",
                        action_url=f.url,
                    )

        # Discord delivery
        await self._deliver_discord(filtered, date_str)

        digest = format_digest(filtered, date_str)
        return {"success": True, "result": digest}

    async def _deliver_discord(self, findings: list[ScoutFinding], date_str: str) -> None:
        """Deliver digest to Discord if configured."""
        if not self._runtime:
            return

        channel_adapters = getattr(self._runtime, "channel_adapters", {})
        adapter = channel_adapters.get("discord")
        if not adapter or not getattr(adapter, "running", False):
            return

        config = getattr(self._runtime, "config", None)
        if not config:
            return

        scout_channel_id = getattr(config.channels.discord, "scout_channel_id", 0)
        if not scout_channel_id:
            return

        digest = format_digest(findings, date_str)
        try:
            await adapter.send_response(str(scout_channel_id), digest)
        except Exception as exc:
            logger.warning("Scout: Discord delivery failed: %s", exc)

    def _load_latest_report(self) -> str | None:
        """Load the most recent scout report and format it."""
        if not self._reports_dir.exists():
            return None
        reports = sorted(self._reports_dir.glob("*.json"), reverse=True)
        if not reports:
            return None
        try:
            data = json.loads(reports[0].read_text(encoding="utf-8"))
            findings = [ScoutFinding(**f) for f in data.get("findings", [])]
            return format_digest(findings, data.get("date", "unknown"))
        except Exception as exc:
            logger.warning("Scout: failed to load report: %s", exc)
            return None
