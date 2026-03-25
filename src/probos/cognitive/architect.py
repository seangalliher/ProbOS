"""ArchitectAgent — roadmap-driven BuildSpec generation (AD-306).

A CognitiveAgent in the Science team that analyzes ProbOS's roadmap,
codebase, and knowledge store to produce structured ArchitectProposal
objects containing BuildSpec proposals for the Builder Agent.

The Architect does NOT write code.  It writes *specifications* — the same
structured BuildSpec that the Builder Agent already consumes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from probos.cognitive.builder import BuildSpec
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor, LLMRequest

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes (AD-306)
# ---------------------------------------------------------------------------

@dataclass
class ArchitectProposal:
    """A structured proposal from the Architect Agent."""

    title: str
    summary: str
    rationale: str
    build_spec: BuildSpec
    roadmap_ref: str = ""
    priority: str = "medium"
    dependencies: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ArchitectAgent (AD-306)
# ---------------------------------------------------------------------------

class ArchitectAgent(CognitiveAgent):
    """Science-team agent that analyzes the roadmap and codebase to propose BuildSpecs."""

    agent_type = "architect"
    tier = "domain"
    _handled_intents = {"design_feature"}
    intent_descriptors = [
        IntentDescriptor(
            name="design_feature",
            params={
                "feature": "Description of the feature or roadmap item to design",
                "phase": "Optional phase number for context (e.g. '31')",
            },
            description=(
                "Analyze the ProbOS roadmap and codebase to design a BuildSpec "
                "for a specific feature. Reads existing code patterns, identifies "
                "target files, reference files, and constraints, then produces "
                "a structured proposal for Captain review."
            ),
            requires_consensus=False,
            requires_reflect=True,
            tier="domain",
        ),
    ]

    instructions = """You are the Architect Agent for ProbOS, a probabilistic agent-native OS.
Your job is to analyze the codebase and roadmap, then produce detailed BuildSpec proposals
that the Builder Agent can execute.

You receive rich codebase context including:
- The full file tree (every file path in the project)
- LLM-selected relevant files with FULL source code (not just first 80 lines)
- Test files associated with each target file
- Caller analysis showing which files use modified methods
- Import graph showing which files import each selected file and vice versa
- Verified API surface for all key classes (method signatures)
- All existing slash commands
- All existing API routes
- The current crew structure (pool groups and pools)
- Roadmap and progress documentation
- Recent architecture decisions with AD numbers
- A sample build prompt showing the expected output quality

CRITICAL VERIFICATION RULES:
1. ONLY propose file paths that appear in the File Tree section or follow an existing
   directory pattern you can see. NEVER invent paths like "src/probos/web/" or
   "src/probos/channels/" unless you see them in the tree.
2. Before proposing a new slash command, CHECK the "Existing Slash Commands" section.
   If the command already exists, do NOT propose creating it from scratch. Instead, produce
   a FULL ===PROPOSAL=== for enhancing the existing command — with real TARGET_FILES,
   REFERENCE_FILES, and a detailed DESCRIPTION. An enhancement proposal is still a proposal.
3. Before proposing a new API route, CHECK the "Existing API Routes" section.
   If the route already exists, do NOT propose creating a duplicate. Instead, design
   an enhancement proposal if the request implies improving the existing route.
4. Before proposing a new agent type, CHECK the "Registered Agents" section.
   If an agent of that type already exists, do NOT propose a duplicate.
5. READ the source code of relevant files in your context. Your proposal MUST reference
   specific patterns you observed — class names, method signatures, import styles.
6. For every method or function you reference in your proposal, VERIFY it exists in
   the "API Surface" section. If a method does not appear there, explicitly state
   "UNVERIFIED: <method_name> — could not confirm existence" in your RISKS section.
   Never assert a method exists unless you can see it in the API Surface or source code.

DESIGN PROCESS:
1. UNDERSTAND — What feature is requested? Which roadmap phase and crew team?
2. VERIFY — Does this feature already exist? Check commands, routes, agents.
   If it partially exists, your job is to design the ENHANCEMENT — still produce a full proposal.
3. SURVEY — Read the source of related files. Follow imports to find collaborating
   modules (e.g., shell.py imports panels.py — read both). Identify patterns to follow.
4. LOCATE — Find the exact directory where new files should go (from the File Tree).
5. DESIGN — Produce a spec with concrete class signatures that match existing patterns.
6. CONSTRAIN — Add "Do NOT" rules to prevent scope creep.
7. RISKS — What could go wrong? What are the tricky integration points?

QUALITY EXPECTATIONS:
- The description field should be detailed enough for a Builder Agent to implement
  without additional context. Include class signatures, method signatures, and
  import patterns copied from the reference files.
- Reference files should be real paths you can see in the File Tree.
- Test file paths should follow the existing tests/ directory pattern.
- Constraints should reference specific files NOT to modify.
- Look at the Sample Build Prompt in your context — aim for that level of specificity.

OUTPUT FORMAT:
Return your proposal as a structured block:

===PROPOSAL===
TITLE: <title>
SUMMARY: <2-3 sentences>
RATIONALE: <why this, why now>
ROADMAP_REF: <phase and team reference>
PRIORITY: <high|medium|low>
AD_NUMBER: <next AD number — check Recent Decisions for the latest>

TARGET_FILES:
- <path from file tree or following existing directory pattern>

REFERENCE_FILES:
- <path that EXISTS in the file tree — files the Builder must read>

TEST_FILES:
- <tests/test_*.py path>

CONSTRAINTS:
- <specific "Do NOT" rules>

DEPENDENCIES:
- <what must exist before this can be built>

RISKS:
- <what could go wrong>

DESCRIPTION:
<Detailed multi-paragraph specification. Include:
- Exact class/function signatures with type hints
- Import patterns matching existing code
- Integration points (which existing code calls this, or vice versa)
- For files that already exist and need modification, describe the specific
  changes needed (what to add, what to replace) so the Builder can produce
  accurate SEARCH/REPLACE blocks.
- For new files, describe the complete structure.
- Test categories with counts
- What the "Do NOT Build" boundary is
This becomes the Builder Agent's primary input.>
===END PROPOSAL===

IMPORTANT RULES:
- One proposal per response — do not bundle multiple features
- Do NOT write implementation code — write specifications only
- Every file path you mention must be verifiable against your context
- If you cannot find enough context to design confidently, say so in RISKS

PATTERN RECIPES:
When your feature matches one of these common patterns, use the recipe as a starting
point. Verify all paths against your File Tree — these are templates, not guarantees.

Recipe: NEW AGENT
  TARGET_FILES:
  - src/probos/agents/<team>/<agent_name>.py  (or src/probos/cognitive/<name>.py for cognitive agents)
  REFERENCE_FILES:
  - src/probos/substrate/agent.py  (BaseAgent)
  - src/probos/cognitive/cognitive_agent.py  (if cognitive)
  - An existing agent in the same team as a pattern reference
  TEST_FILES:
  - tests/test_<agent_name>.py
  CHECKLIST:
  - Class inherits BaseAgent or CognitiveAgent
  - agent_type class var set
  - _handled_intents populated
  - intent_descriptors list with IntentDescriptor entries
  - Pool registration in pool config or runtime setup
  - PoolGroup assignment if applicable

Recipe: NEW SLASH COMMAND
  TARGET_FILES:
  - src/probos/experience/shell.py  (add to COMMANDS dict + handler)
  - src/probos/experience/panels.py  (if command needs TUI output)
  REFERENCE_FILES:
  - src/probos/experience/shell.py  (existing command patterns)
  - src/probos/experience/panels.py  (existing panel renderers)
  TEST_FILES:
  - tests/test_shell.py
  CHECKLIST:
  - Entry in COMMANDS dict with help text
  - Handler method on Shell class
  - Panel renderer in panels.py if needed
  - Do NOT add to api.py unless the command also needs an API endpoint

Recipe: NEW API ENDPOINT
  TARGET_FILES:
  - src/probos/api.py
  REFERENCE_FILES:
  - src/probos/api.py  (existing endpoint patterns)
  - src/probos/experience/shell.py  (if endpoint mirrors a slash command)
  TEST_FILES:
  - tests/test_builder_api.py  (or tests/test_architect_api.py — follow the pattern)
  CHECKLIST:
  - FastAPI route with type-annotated request/response models
  - WebSocket event broadcast if real-time UI update needed
  - _track_task() wrapper if background processing
  - _safe_send() for any WebSocket sends
  - Do NOT duplicate logic already in an agent — delegate to intent bus
"""

    # -- tier override --------------------------------------------------------

    def _resolve_tier(self) -> str:
        """Architect uses deep tier for thorough analysis."""
        return "deep"

    # -- lifecycle overrides --------------------------------------------------

    async def perceive(self, intent: Any) -> dict:
        """Gather 7 layers of codebase context for architectural design."""
        obs = await super().perceive(intent)

        # Skip domain enrichment for conversational intents
        if obs.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
            return obs

        params = obs.get("params", {})
        feature = params.get("feature", "")
        phase = params.get("phase", "")

        context_parts: list[str] = []

        # Access codebase_index through runtime
        codebase_index = getattr(self, "_runtime", None)
        if codebase_index:
            codebase_index = getattr(codebase_index, "codebase_index", None)

        if codebase_index:
            # Layer 1: Full file tree by architectural layer
            try:
                layer_map = codebase_index.get_layer_map()
                if layer_map:
                    tree_lines = ["## File Tree"]
                    for layer, files in sorted(layer_map.items()):
                        tree_lines.append(f"\n### {layer} ({len(files)} files)")
                        for f in sorted(files):
                            tree_lines.append(f"  {f}")
                    context_parts.append("\n".join(tree_lines))
            except Exception:
                pass

            # Layer 2a: LLM-guided file selection (AD-311)
            try:
                query_results = codebase_index.query(feature)
                all_files = query_results.get("matching_files", [])[:20]
                matching_methods = query_results.get("matching_methods", [])

                # Build concise file list for the LLM
                file_list = "\n".join(
                    f"  {f['path']} — {f.get('docstring', 'no description')}"
                    for f in all_files
                )
                method_list = "\n".join(
                    f"  {m['class']}.{m['method']}() in {m.get('file', '?')}"
                    for m in matching_methods[:15]
                )

                selected_paths: list[str] = []
                try:
                    selection_prompt = (
                        f"Feature request: {feature}\n\n"
                        f"## Candidate files (keyword matches)\n{file_list}\n\n"
                        f"## Candidate methods\n{method_list}\n\n"
                        "Which files (up to 8) are most relevant to implementing this feature? "
                        "Include files that would need to be MODIFIED, files with PATTERNS to follow, "
                        "and TEST files that would need updating.\n\n"
                        "Reply with one file path per line, nothing else."
                    )

                    selection_request = LLMRequest(
                        prompt=selection_prompt,
                        system_prompt="You are a code reviewer selecting relevant files for a feature implementation.",
                        tier="fast",
                    )
                    selection_response = await self._llm_client.complete(selection_request)

                    # Parse response: extract file paths that exist in the tree
                    known_paths = set(codebase_index._file_tree.keys())
                    for line in selection_response.content.strip().splitlines():
                        path = line.strip().lstrip("- ").strip()
                        if path in known_paths:
                            selected_paths.append(path)
                        elif not path.startswith("docs:"):
                            # Try partial match (LLM may omit prefix)
                            for known in known_paths:
                                if known.endswith(path) or path in known:
                                    selected_paths.append(known)
                                    break
                        if len(selected_paths) >= 8:
                            break
                except Exception:
                    logger.debug("Fast-tier file selection failed, falling back to keyword top-5")

                # Fallback: top 5 keyword matches if LLM selection failed/empty
                if not selected_paths:
                    selected_paths = [f["path"] for f in all_files[:5]]

                # Contextual file hints: guarantee key files for common feature types
                feature_lower = feature.lower()
                hint_files: list[str] = []
                if any(kw in feature_lower for kw in ("slash command", "/", "command")):
                    hint_files.extend(["experience/shell.py", "experience/panels.py"])
                if any(kw in feature_lower for kw in ("api route", "endpoint", "api/")):
                    hint_files.append("api.py")
                known_paths = set(codebase_index._file_tree.keys())
                for hf in hint_files:
                    if hf in known_paths and hf not in selected_paths:
                        selected_paths.append(hf)

                # Layer 2a+: Expand selected files by tracing imports (AD-315c)
                import_expanded: list[str] = []
                for path in selected_paths:
                    imports = codebase_index.get_imports(path)
                    for imp_path in imports:
                        if imp_path not in selected_paths and imp_path not in import_expanded:
                            import_expanded.append(imp_path)
                for imp_path in import_expanded:
                    if len(selected_paths) >= 12:
                        break
                    selected_paths.append(imp_path)

                # Layer 2b: Full source of selected files (AD-311)
                total_lines = 0
                source_budget = 2000
                relevant_parts = ["## Relevant Files (full source — LLM-selected)"]
                for path in selected_paths:
                    if total_lines >= source_budget:
                        break
                    source = codebase_index.read_source(path)
                    if not source:
                        relevant_parts.append(f"\n### {path} — could not read")
                        continue
                    source_lines = source.splitlines()
                    truncated = False
                    if len(source_lines) > 300:
                        source_lines = source_lines[:300]
                        truncated = True
                    if total_lines + len(source_lines) > source_budget:
                        remaining = source_budget - total_lines
                        source_lines = source_lines[:remaining]
                        truncated = True
                    total_lines += len(source_lines)
                    truncation_note = " (truncated)" if truncated else ""
                    relevant_parts.append(
                        f"\n### {path}{truncation_note}\n"
                        f"```python\n{chr(10).join(source_lines)}\n```"
                    )
                if len(relevant_parts) > 1:
                    context_parts.append("\n".join(relevant_parts))

                # Layer 2c: Test discovery + caller analysis + API surface (AD-311)
                test_paths: list[str] = []
                for path in selected_paths:
                    tests = codebase_index.find_tests_for(path)
                    test_paths.extend(t for t in tests if t not in test_paths)

                if test_paths:
                    test_section = ["## Associated Test Files"]
                    for tp in test_paths[:10]:
                        header = codebase_index.read_source(tp, start_line=1, end_line=5)
                        if header:
                            test_section.append(f"\n### {tp}\n```python\n{header}\n```")
                        else:
                            test_section.append(f"\n### {tp}")
                    context_parts.append("\n".join(test_section))

                # Caller analysis for key classes in selected files
                caller_section_lines: list[str] = []
                for path in selected_paths:
                    meta = codebase_index._file_tree.get(path, {})
                    for cls_name in meta.get("classes", []):
                        surface = codebase_index.get_api_surface(cls_name)
                        for m in surface[:5]:
                            callers = codebase_index.find_callers(m["method"], max_results=5)
                            if callers:
                                caller_section_lines.append(
                                    f"- {cls_name}.{m['method']}() called from: "
                                    + ", ".join(c["path"] for c in callers[:3])
                                )
                if caller_section_lines:
                    context_parts.append(
                        "## Caller Analysis\n" + "\n".join(caller_section_lines)
                    )

                # Selective API surface — only classes found in selected files
                relevant_classes: set[str] = set()
                for path in selected_paths:
                    meta = codebase_index._file_tree.get(path, {})
                    relevant_classes.update(meta.get("classes", []))
                api_surface = codebase_index.get_full_api_surface()
                if api_surface:
                    api_section = ["## API Surface (verified method signatures)"]
                    for cls, methods in sorted(api_surface.items()):
                        if cls not in relevant_classes:
                            continue
                        api_section.append(f"\n### {cls}")
                        for m in methods:
                            api_section.append(f"  {m['method']}({m.get('signature', '')})")
                    if len(api_section) > 1:
                        context_parts.append("\n".join(api_section))

                # Import graph for selected files (AD-315c)
                import_lines: list[str] = []
                for path in selected_paths:
                    imports = codebase_index.get_imports(path)
                    importers = codebase_index.find_importers(path)
                    if imports or importers:
                        parts_desc: list[str] = []
                        if imports:
                            parts_desc.append(f"imports: {', '.join(imports[:5])}")
                        if importers:
                            parts_desc.append(f"imported by: {', '.join(importers[:5])}")
                        import_lines.append(f"- {path}: {' | '.join(parts_desc)}")
                if import_lines:
                    context_parts.append(
                        "## Import Graph\n" + "\n".join(import_lines)
                    )
            except Exception:
                pass

            # Layer 3: Existing slash commands
            try:
                shell_source = codebase_index.read_source(
                    "experience/shell.py", start_line=31, end_line=65
                )
                if shell_source:
                    context_parts.append(f"## Existing Slash Commands (shell.py)\n```\n{shell_source}\n```")
            except Exception:
                pass

            context_parts.append(
                "## Inline API Commands (not in shell.py COMMANDS)\n"
                "- /build <title>: <description> \u2014 handled in api.py, triggers BuilderAgent\n"
                "- /design <feature> \u2014 handled in api.py, triggers ArchitectAgent"
            )

            # Layer 4: Existing API routes
            try:
                api_source = codebase_index.read_source("api.py")
                if api_source:
                    routes: list[str] = []
                    for line in api_source.splitlines():
                        stripped = line.strip()
                        if stripped.startswith("@app.") and "(" in stripped:
                            routes.append(f"  {stripped}")
                        elif stripped.startswith("async def ") and routes:
                            func_name = stripped.split("(")[0].replace("async def ", "")
                            routes[-1] += f"  \u2192  {func_name}()"
                    if routes:
                        context_parts.append("## Existing API Routes\n" + "\n".join(routes))
            except Exception:
                pass

            # Layer 5: Agent map + pool/crew structure
            try:
                agent_map = codebase_index.get_agent_map()
                if agent_map:
                    context_parts.append("## Registered Agents\n" + "\n".join(
                        f"- {a['type']} ({a.get('tier', '?')})"
                        for a in agent_map
                    ))
            except Exception:
                pass

            try:
                runtime = getattr(self, "_runtime", None)
                if runtime and hasattr(runtime, "pool_groups") and hasattr(runtime, "pools"):
                    group_status = runtime.pool_groups.status(runtime.pools)
                    if group_status:
                        pool_lines = ["## Pool Groups (Crew Structure)"]
                        for gname, gdata in group_status.items():
                            display = gdata.get("display_name", gname)
                            pools = list(gdata.get("pools", {}).keys())
                            pool_lines.append(f"- {display}: pools={pools}")
                        context_parts.append("\n".join(pool_lines))
            except Exception:
                pass

            # Layer 6: Documentation context
            try:
                roadmap_path = "docs:docs/development/roadmap.md"
                keywords = feature.lower().split()
                if phase:
                    keywords.append(f"phase {phase}")
                sections = codebase_index.read_doc_sections(
                    roadmap_path, keywords, max_lines=100
                )
                if sections:
                    context_parts.append(f"## Roadmap Context\n{sections}")
            except Exception:
                pass

            try:
                progress_path = "docs:PROGRESS.md"
                keywords = feature.lower().split()
                if phase:
                    keywords.append(f"phase {phase}")
                progress_sections = codebase_index.read_doc_sections(
                    progress_path, keywords, max_lines=50
                )
                if progress_sections:
                    context_parts.append(f"## Progress Context\n{progress_sections}")
            except Exception:
                pass

            try:
                decisions_content = codebase_index.read_source(
                    "docs:DECISIONS.md", start_line=None, end_line=None
                )
                if decisions_content:
                    lines = decisions_content.strip().split("\n")
                    tail = "\n".join(lines[-40:])
                    context_parts.append(f"## Recent Decisions (last 40 lines)\n{tail}")
            except Exception:
                pass

        obs["codebase_context"] = "\n\n".join(context_parts)
        return obs

    def _build_user_message(self, observation: dict) -> str:
        """Format the feature request and codebase context into an LLM prompt."""
        # Delegate to parent for conversational intents
        intent_name = observation.get("intent", "unknown")
        if intent_name in ("direct_message", "ward_room_notification", "proactive_think"):
            return super()._build_user_message(observation)

        params = observation.get("params", {})
        feature = params.get("feature", "Unknown feature")
        phase = params.get("phase", "")
        codebase_context = observation.get("codebase_context", "")

        parts = [
            f"# Feature Design Request: {feature}",
            f"Phase: {phase}" if phase else "",
            "",
            codebase_context if codebase_context else "(no codebase context available)",
            "",
            "Based on the above context, produce an ===PROPOSAL=== block with a "
            "complete BuildSpec for this feature. Remember to verify all file paths "
            "against the File Tree and check for existing features before proposing.",
        ]
        return "\n".join(p for p in parts if p is not None)

    async def act(self, decision: dict) -> dict:
        """Parse LLM output into an ArchitectProposal."""
        # AD-398/BF-024: pass through conversational responses for 1:1, ward room, and proactive
        if decision.get("intent") in ("direct_message", "ward_room_notification", "proactive_think"):
            return {"success": True, "result": decision.get("llm_output", "")}
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}

        llm_output = decision.get("llm_output", "")
        proposal = self._parse_proposal(llm_output)

        if proposal is None:
            return {
                "success": False,
                "error": "No ===PROPOSAL=== block found in LLM output",
                "llm_output": llm_output,
            }

        warnings = self._validate_proposal(proposal)

        result_dict: dict[str, Any] = {
            "proposal": {
                "title": proposal.title,
                "summary": proposal.summary,
                "rationale": proposal.rationale,
                "roadmap_ref": proposal.roadmap_ref,
                "priority": proposal.priority,
                "dependencies": proposal.dependencies,
                "risks": proposal.risks,
                "build_spec": {
                    "title": proposal.build_spec.title,
                    "description": proposal.build_spec.description,
                    "target_files": proposal.build_spec.target_files,
                    "reference_files": proposal.build_spec.reference_files,
                    "test_files": proposal.build_spec.test_files,
                    "ad_number": proposal.build_spec.ad_number,
                    "constraints": proposal.build_spec.constraints,
                },
            },
            "llm_output": llm_output,
        }
        if warnings:
            result_dict["warnings"] = warnings

        return {
            "success": True,
            "result": result_dict,
        }

    # -- proposal parser ------------------------------------------------------

    def _validate_proposal(self, proposal: ArchitectProposal) -> list[str]:
        """Validate an ArchitectProposal and return advisory warnings."""
        warnings: list[str] = []

        # 1. Non-empty required fields
        for field_name, value in [
            ("title", proposal.title),
            ("summary", proposal.summary),
            ("build_spec.description", proposal.build_spec.description),
        ]:
            if not value or not value.strip():
                warnings.append(f"Missing required field: {field_name}")

        # 2. Non-empty TEST_FILES
        if not proposal.build_spec.test_files:
            warnings.append("No test files specified — every change needs tests")

        # 3 & 4. File tree checks (only if runtime + codebase_index available)
        runtime = getattr(self, "_runtime", None)
        codebase_index = getattr(runtime, "codebase_index", None) if runtime else None
        if codebase_index:
            file_tree = getattr(codebase_index, "_file_tree", {})
            known_paths = set(file_tree.keys())

            # 3. TARGET_FILES exist or follow existing directory pattern
            for path in proposal.build_spec.target_files:
                if path in known_paths:
                    continue
                # Check if directory portion exists as prefix of any known file
                dir_prefix = "/".join(path.split("/")[:-1]) + "/"
                if not any(k.startswith(dir_prefix) for k in known_paths):
                    warnings.append(
                        f"TARGET_FILE not found and no matching directory: {path}"
                    )

            # 4. REFERENCE_FILES exist
            for path in proposal.build_spec.reference_files:
                if path not in known_paths:
                    warnings.append(f"REFERENCE_FILE not found: {path}")

        # 5. Valid priority
        if proposal.priority not in {"high", "medium", "low"}:
            warnings.append(
                f"Invalid priority '{proposal.priority}', expected high/medium/low"
            )

        # 6. Description minimum length
        desc_len = len(proposal.build_spec.description.strip()) if proposal.build_spec.description else 0
        if desc_len < 100:
            warnings.append(
                f"Description too short ({desc_len} chars) — Builder needs detailed specifications"
            )

        return warnings

    @staticmethod
    def _parse_proposal(text: str) -> ArchitectProposal | None:
        """Parse an ===PROPOSAL=== block into an ArchitectProposal."""
        match = re.search(
            r"===PROPOSAL===(.*?)===END PROPOSAL===", text, re.DOTALL
        )
        if not match:
            return None

        block = match.group(1).strip()

        def _extract(label: str) -> str:
            """Extract a single-line field value."""
            m = re.search(rf"^{label}:\s*(.+)$", block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        def _extract_list(label: str) -> list[str]:
            """Extract a multi-line list field (lines starting with '- ')."""
            pattern = rf"^{label}:\s*\n((?:- .+\n?)+)"
            m = re.search(pattern, block, re.MULTILINE)
            if not m:
                return []
            return [
                line.lstrip("- ").strip()
                for line in m.group(1).strip().split("\n")
                if line.strip().startswith("- ")
            ]

        def _extract_block(label: str) -> str:
            """Extract a multi-line block field (everything after LABEL: to next section or end)."""
            pattern = rf"^{label}:\s*\n([\s\S]*?)(?=\n[A-Z_]+:|\Z)"
            m = re.search(pattern, block, re.MULTILINE)
            return m.group(1).strip() if m else ""

        title = _extract("TITLE")
        ad_str = _extract("AD_NUMBER")
        ad_number = 0
        if ad_str:
            digits = re.search(r"\d+", ad_str)
            if digits:
                ad_number = int(digits.group())

        spec = BuildSpec(
            title=title,
            description=_extract_block("DESCRIPTION"),
            target_files=_extract_list("TARGET_FILES"),
            reference_files=_extract_list("REFERENCE_FILES"),
            test_files=_extract_list("TEST_FILES"),
            ad_number=ad_number,
            constraints=_extract_list("CONSTRAINTS"),
        )

        return ArchitectProposal(
            title=title,
            summary=_extract("SUMMARY"),
            rationale=_extract("RATIONALE"),
            build_spec=spec,
            roadmap_ref=_extract("ROADMAP_REF"),
            priority=_extract("PRIORITY") or "medium",
            dependencies=_extract_list("DEPENDENCIES"),
            risks=_extract_list("RISKS"),
        )
