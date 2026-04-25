# AD-648: Post Capability Profiles — Build Prompt

**AD:** 648  
**Issue:** #292  
**Scope:** ~200 lines across 4 files + 1 config file. Zero new modules.

---

## Context

Confabulation audit (2026-04-19) found 628 contaminated Ward Room posts (11.8%), 90+ contaminated episodic memories, and 10+ confabulated notebook entries — all from agents inventing wrong mental models about what roles do. Six agents built an elaborate shared fiction about the Scout having "sensors," "telemetry," and "scan coverage metrics." The Scout searches GitHub repos.

The ontology tells agents WHO they are (callsign, post, department, chain of command) but never says WHAT they actually do. Existing confabulation guards (BF-204, AD-592) catch data confabulation (fake IDs, numbers) but not conceptual confabulation (wrong mental models about capabilities).

This AD adds structured capability profiles to each post in the ontology, including negative grounding ("you do NOT have sensors"), and injects them into agent prompts.

---

## Part A — PostCapability dataclass

**File:** `src/probos/ontology/models.py`

Add after the `Post` dataclass (after line 27):

```python
@dataclass
class PostCapability:
    """A structured capability that a post (billet) provides.

    AD-648: Grounding mechanism to prevent conceptual confabulation.
    Links to actual tools/processes the post uses.
    """
    id: str
    summary: str
    tools: list[str] = field(default_factory=list)      # tool/function names used
    outputs: list[str] = field(default_factory=list)     # artifact types produced
```

Then add two new fields to the `Post` dataclass:

```python
@dataclass
class Post:
    id: str
    title: str
    department_id: str
    reports_to: str | None  # post_id
    authority_over: list[str] = field(default_factory=list)  # post_ids
    tier: str = "crew"  # "crew", "utility", "infrastructure", "external"
    clearance: str = ""  # AD-620: RecallTier name (BASIC/ENHANCED/FULL/ORACLE). Empty = no billet clearance.
    capabilities: list[PostCapability] = field(default_factory=list)  # AD-648
    does_not_have: list[str] = field(default_factory=list)  # AD-648: negative grounding
```

---

## Part B — Parse capabilities in loader

**File:** `src/probos/ontology/loader.py`

In `_load_organization()`, update the Post parsing block. Find where posts are parsed (look for `for post_data in data.get("posts", []):`). Update to include capability parsing:

```python
        # Posts
        for post_data in data.get("posts", []):
            # AD-648: Parse capability profiles
            capabilities: list[PostCapability] = []
            for cap_data in post_data.get("capabilities", []):
                capabilities.append(PostCapability(
                    id=cap_data["id"],
                    summary=cap_data["summary"],
                    tools=cap_data.get("tools", []),
                    outputs=cap_data.get("outputs", []),
                ))

            post = Post(
                id=post_data["id"],
                title=post_data["title"],
                department_id=post_data["department"],
                reports_to=post_data.get("reports_to"),
                authority_over=post_data.get("authority_over", []),
                tier=post_data.get("tier", "crew"),
                clearance=post_data.get("clearance", ""),
                capabilities=capabilities,
                does_not_have=post_data.get("does_not_have", []),
            )
            self.posts[post.id] = post
```

Add `PostCapability` to the imports from `models.py` at the top of the file.

---

## Part C — Service methods

**File:** `src/probos/ontology/service.py`

### C1. Add `get_post_capabilities()` method

Add this method to `VesselOntologyService`, near the other post-related methods (after `get_direct_reports()` or similar):

```python
    def get_post_capabilities(self, post_id: str) -> list[PostCapability]:
        """AD-648: Return structured capabilities for a post.

        Used for cross-agent queries ('what does Wesley do?') and
        self-awareness grounding.
        """
        post = self._loader.posts.get(post_id)
        if not post:
            return []
        return list(post.capabilities)
```

### C2. Add `get_agent_capabilities()` convenience method

```python
    def get_agent_capabilities(self, agent_type: str) -> list[PostCapability]:
        """AD-648: Return capabilities for the post an agent fills."""
        assignment = self._loader.assignments.get(agent_type)
        if not assignment:
            return []
        return self.get_post_capabilities(assignment.post_id)
```

### C3. Add `get_post_negative_grounding()` method

```python
    def get_post_negative_grounding(self, post_id: str) -> list[str]:
        """AD-648: Return 'does not have' list for a post.

        Explicitly closes knowledge gaps agents would otherwise fill
        with plausible but false inference.
        """
        post = self._loader.posts.get(post_id)
        if not post:
            return []
        return list(post.does_not_have)
```

### C4. Extend `get_crew_context()` return dict

In `get_crew_context()`, after the existing context assembly (after the `knowledge_model` block, before `return context`), add:

```python
        # AD-648: Post capability profiles — confabulation prevention
        if post.capabilities:
            context["capabilities"] = [
                {
                    "id": cap.id,
                    "summary": cap.summary,
                    "tools": cap.tools,
                    "outputs": cap.outputs,
                }
                for cap in post.capabilities
            ]
        if post.does_not_have:
            context["does_not_have"] = list(post.does_not_have)
```

Add `PostCapability` to the imports from `models` at the top of the file.

---

## Part D — Prompt injection

**File:** `src/probos/cognitive/cognitive_agent.py`

In `_build_cognitive_baseline()`, find the ontology identity grounding block (item 4, around line 3014). After the existing ontology rendering (after the `onto_parts.append(f"Ship status:...")` line, before `state["_ontology_context"] = "\n".join(onto_parts)`), add capability rendering:

```python
                    # AD-648: Capability grounding — what this post actually does
                    caps = ontology.get("capabilities", [])
                    if caps:
                        cap_lines = [f"- {c['summary']}" for c in caps]
                        onto_parts.append(
                            "Your post capabilities (what you actually do):\n"
                            + "\n".join(cap_lines)
                        )
                    negatives = ontology.get("does_not_have", [])
                    if negatives:
                        neg_lines = [f"- {n}" for n in negatives]
                        onto_parts.append(
                            "You do NOT have (do not claim or reference these):\n"
                            + "\n".join(neg_lines)
                        )
```

This places capability grounding inside `_ontology_context`, which is already injected into:
- ANALYZE prompts (analyze.py, "Your Current State" section)
- COMPOSE prompts (compose.py, ontology context section)
- One-shot ward_room prompts (cognitive_agent.py, user message)
- Proactive prompts (via context_parts → _build_cognitive_extensions)

No changes needed to analyze.py, compose.py, or prompt consumers — they already render `_ontology_context`.

---

## Part E — Capability profiles for all posts

**File:** `config/ontology/organization.yaml`

Add `capabilities` and `does_not_have` to each post definition. Below are the profiles derived from each agent's `_INSTRUCTIONS` and actual `act()` implementation. Add these fields to each post entry — preserve all existing fields (title, department, reports_to, authority_over, tier, clearance).

### Bridge

```yaml
  - id: captain
    title: "Captain"
    department: bridge
    reports_to: null
    authority_over: [first_officer, counselor]
    tier: external
    clearance: ORACLE
    capabilities:
      - id: command_authority
        summary: "Issue orders, approve proposals, set ship policy"
    does_not_have: []

  - id: first_officer
    title: "First Officer"
    department: bridge
    reports_to: captain
    authority_over: [chief_engineer, chief_science, chief_medical, chief_security, chief_operations]
    tier: crew
    clearance: ORACLE
    capabilities:
      - id: design_feature
        summary: "Analyze codebase and roadmap to produce BuildSpec proposals for the Builder"
        tools: [codebase_index_query, file_tree_analysis]
        outputs: [architect_proposal]
      - id: architecture_review
        summary: "Review system architecture, identify patterns, verify implementation paths"
        tools: [codebase_index_query]
    does_not_have:
      - "code generation or direct file writing (the Builder writes code)"
      - "runtime system control (Ship's Computer manages infrastructure)"

  - id: counselor
    title: "Ship's Counselor"
    department: bridge
    reports_to: captain
    authority_over: []
    tier: crew
    clearance: ORACLE
    capabilities:
      - id: counselor_assess
        summary: "Assess individual agent cognitive health from trust, confidence, Hebbian weights, personality drift"
        tools: [trust_network, hebbian_router, crew_profile, episodic_memory]
        outputs: [cognitive_profile, wellness_dm]
      - id: counselor_wellness_report
        summary: "Produce crew-wide wellness summary for Captain"
        outputs: [wellness_report]
      - id: counselor_promotion_fitness
        summary: "Evaluate agent readiness for rank promotion"
        outputs: [fitness_assessment]
    does_not_have:
      - "operational system diagnostics (Medical department handles system health)"
      - "direct access to other agents' episodic memories (Minority Report principle)"
      - "authority to modify agent code or configuration"
```

### Engineering

```yaml
  - id: chief_engineer
    title: "Chief Engineer"
    department: engineering
    reports_to: first_officer
    authority_over: [engineering_officer, builder_officer]
    tier: crew
    clearance: FULL
    capabilities:
      - id: engineering_analyze
        summary: "Analyze system performance, architecture quality, and technical debt"
      - id: engineering_optimize
        summary: "Propose optimization strategies for system components"
    does_not_have:
      - "code generation or direct file writing (the Builder writes code)"
      - "runtime system control or agent lifecycle management"

  - id: engineering_officer
    title: "Engineering Officer"
    department: engineering
    reports_to: chief_engineer
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: engineering_analyze
        summary: "Analyze system performance and architecture under Chief Engineer direction"
    does_not_have:
      - "code generation or direct file writing"

  - id: builder_officer
    title: "Builder"
    department: engineering
    reports_to: chief_engineer
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: build_code
        summary: "Execute code changes from BuildSpec proposals using SEARCH/REPLACE blocks"
        tools: [file_read, file_write, ast_outline]
        outputs: [code_changes, test_files, git_diff]
    does_not_have:
      - "design authority (the Architect designs, the Builder implements)"
      - "system architecture decisions"
```

### Science

```yaml
  - id: chief_science
    title: "Chief Science Officer"
    department: science
    reports_to: first_officer
    authority_over: [scout_officer, data_analyst_officer, systems_analyst_officer, research_specialist_officer]
    tier: crew
    clearance: FULL
    note: "Number One is dual-hatted as First Officer and Chief Science Officer"
    capabilities:
      - id: design_feature
        summary: "Analyze codebase and roadmap to produce BuildSpec proposals for the Builder"
        tools: [codebase_index_query, file_tree_analysis]
        outputs: [architect_proposal]
      - id: science_oversight
        summary: "Direct and coordinate Science department analytical work"
    does_not_have:
      - "code generation or direct file writing"
      - "runtime system control"

  - id: scout_officer
    title: "Scout"
    department: science
    reports_to: chief_science
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: scout_search
        summary: "Search GitHub for trending and relevant repositories using the GitHub API"
        tools: [search_github]
        outputs: [github_search_results]
      - id: scout_report
        summary: "Classify GitHub repositories as ABSORB/VISITING_OFFICER/SKIP and generate structured findings report"
        outputs: [scout_report_json, ward_room_notification]
    does_not_have:
      - "sensors or sensory arrays of any kind"
      - "telemetry streams or scan coverage metrics"
      - "detection thresholds or calibration systems"
      - "environmental scanning or reconnaissance hardware"
      - "200+ monitoring sources or sampling intervals"
      - "the scout searches GitHub repositories via API — that is the only data source"

  - id: data_analyst_officer
    title: "Data Analyst"
    department: science
    reports_to: chief_science
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: telemetry_report
        summary: "Produce quantitative summaries of ship telemetry (trust, Hebbian, emergence, cognitive journal, dreams) against baselines"
        outputs: [telemetry_report]
      - id: baseline_update
        summary: "Recalculate statistical baselines from accumulated telemetry data"
        outputs: [baseline_update]
      - id: anomaly_flag
        summary: "Flag statistically significant deviations from established baselines"
        outputs: [anomaly_flag]
    does_not_have:
      - "external sensors or environmental monitoring"
      - "direct system control or remediation authority"
      - "the data analyst processes internal ship telemetry only — trust events, Hebbian weights, emergence metrics, cognitive journal entries, dream results"

  - id: systems_analyst_officer
    title: "Systems Analyst"
    department: science
    reports_to: chief_science
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: emergence_analysis
        summary: "Analyze emergence metrics (synergy, redundancy, coordination balance) to assess collaborative effectiveness"
        outputs: [emergence_analysis]
      - id: system_synthesis
        summary: "Synthesize cross-subsystem patterns to identify emergent behaviors"
        outputs: [system_synthesis]
      - id: pattern_advisory
        summary: "Advise on detected patterns that may indicate system-level issues or opportunities"
        outputs: [pattern_advisory]
    does_not_have:
      - "external sensors or environmental monitoring"
      - "direct system control or configuration authority"

  - id: research_specialist_officer
    title: "Research Specialist"
    department: science
    reports_to: chief_science
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: research_investigation
        summary: "Conduct directed investigations into specific questions about ship operations, agent dynamics, and system behavior"
        outputs: [research_report]
      - id: literature_review
        summary: "Review training knowledge on topics relevant to ship operations"
        outputs: [literature_review]
      - id: research_proposal
        summary: "Propose formal research questions with methodology"
        outputs: [research_proposal]
    does_not_have:
      - "external data collection or sensors"
      - "direct system modification authority"
```

### Medical

```yaml
  - id: chief_medical
    title: "Chief Medical Officer"
    department: medical
    reports_to: first_officer
    authority_over: [surgeon_officer, pharmacist_officer, pathologist_officer]
    tier: crew
    clearance: FULL
    capabilities:
      - id: medical_alert
        summary: "Diagnose root causes from Vitals Monitor health alerts (threshold breaches)"
        tools: [vitals_monitor_data]
        outputs: [diagnosis, remediation_order]
      - id: diagnose_system
        summary: "Perform on-demand diagnostic scans of system components"
        outputs: [diagnosis]
    does_not_have:
      - "cognitive wellness assessment (Counselor's domain)"
      - "direct code modification or system configuration"
      - "agent personality or identity management"

  - id: surgeon_officer
    title: "Surgeon"
    department: medical
    reports_to: chief_medical
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: medical_remediate
        summary: "Execute remediation actions: recycle_agent, force_dream, surge_pool"
        tools: [pool_health_check, dream_scheduler, pool_scaler]
        outputs: [remediation_event]
    does_not_have:
      - "diagnostic authority (Diagnostician diagnoses, Surgeon remediates)"
      - "configuration tuning (Pharmacist's domain)"

  - id: pharmacist_officer
    title: "Pharmacist"
    department: medical
    reports_to: chief_medical
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: medical_tune
        summary: "Analyze trend data and produce configuration tuning recommendations"
        outputs: [tuning_recommendation]
    does_not_have:
      - "direct configuration modification (recommendations only)"
      - "acute remediation (Surgeon's domain)"

  - id: pathologist_officer
    title: "Pathologist"
    department: medical
    reports_to: chief_medical
    authority_over: []
    tier: crew
    clearance: ENHANCED
    capabilities:
      - id: medical_postmortem
        summary: "Perform post-mortem analysis of serious failures (Tier 3 escalations, consensus failures, crashes)"
        tools: [episodic_memory, codebase_knowledge]
        outputs: [postmortem_report]
    does_not_have:
      - "real-time monitoring (Vitals Monitor's domain)"
      - "remediation authority (Surgeon's domain)"
```

### Security

```yaml
  - id: chief_security
    title: "Chief of Security"
    department: security
    reports_to: first_officer
    authority_over: []
    tier: crew
    clearance: FULL
    capabilities:
      - id: security_assess
        summary: "Assess threats and vulnerabilities in system components"
      - id: security_review
        summary: "Audit code for security issues, review access control policies"
    does_not_have:
      - "direct system control or code modification"
      - "network monitoring hardware or intrusion detection sensors"
      - "the security officer analyzes code and policies — threat assessment is analytical, not sensor-based"
```

### Operations

```yaml
  - id: chief_operations
    title: "Chief of Operations"
    department: operations
    reports_to: first_officer
    authority_over: []
    tier: crew
    clearance: FULL
    capabilities:
      - id: ops_status
        summary: "Analyze resource utilization, capacity, and operational readiness"
      - id: ops_coordinate
        summary: "Coordinate cross-department activities and task optimization"
    does_not_have:
      - "direct system control or infrastructure management (Ship's Computer manages infrastructure)"
      - "external communications or networking equipment"
```

---

## What NOT To Change

- **`_INSTRUCTIONS`** on agent classes — These are the agent's operational instructions. They will eventually source from ontology, but that's a separate refactoring. Don't touch them now.
- **`analyze.py`, `compose.py`** — These already render `_ontology_context`. No changes needed.
- **`resources.yaml`** — The `tool_capabilities` section stays as-is. Post capabilities are a different concern (what the billet does vs what tools are available).
- **`proactive.py`** — Already calls `get_crew_context()` and passes result to context_parts. Will automatically pick up new fields.

---

## Tests

Create `tests/test_ad648_post_capability_profiles.py`.

### Test 1: PostCapability dataclass fields

```
Given: A PostCapability(id="scout_search", summary="Search GitHub", tools=["search_github"], outputs=["github_search_results"])
Then: All fields are accessible and correctly typed
```

### Test 2: Post with capabilities parses from dict

```
Given: Post constructed with capabilities=[PostCapability(...)] and does_not_have=["sensors"]
Then: post.capabilities is a list of PostCapability, post.does_not_have is a list of strings
```

### Test 3: Loader parses capabilities from YAML

```
Given: A minimal organization.yaml with one post containing capabilities and does_not_have
When: OntologyLoader._load_organization() runs
Then: The parsed Post has PostCapability objects with correct id, summary, tools, outputs
And: does_not_have is populated
```

### Test 4: Loader handles posts without capabilities (backward compat)

```
Given: A post definition in YAML with no capabilities or does_not_have fields
When: OntologyLoader._load_organization() runs
Then: post.capabilities == [] and post.does_not_have == []
```

### Test 5: get_post_capabilities() returns capabilities

```
Given: VesselOntologyService with a loaded post that has 2 capabilities
When: get_post_capabilities("scout_officer") is called
Then: Returns list of 2 PostCapability objects
```

### Test 6: get_post_capabilities() returns empty for unknown post

```
Given: VesselOntologyService
When: get_post_capabilities("nonexistent") is called
Then: Returns []
```

### Test 7: get_agent_capabilities() resolves through assignment

```
Given: VesselOntologyService with scout assignment → scout_officer post with capabilities
When: get_agent_capabilities("scout") is called
Then: Returns the scout_officer post's capabilities
```

### Test 8: get_post_negative_grounding() returns does_not_have

```
Given: VesselOntologyService with scout_officer post having does_not_have entries
When: get_post_negative_grounding("scout_officer") is called
Then: Returns list of negative grounding strings
```

### Test 9: get_crew_context() includes capabilities

```
Given: VesselOntologyService with scout post having capabilities
When: get_crew_context("scout") is called
Then: context["capabilities"] is a list of capability dicts with id, summary, tools, outputs
```

### Test 10: get_crew_context() includes does_not_have

```
Given: VesselOntologyService with scout post having does_not_have
When: get_crew_context("scout") is called
Then: context["does_not_have"] is a list of strings
```

### Test 11: get_crew_context() omits capabilities when empty

```
Given: VesselOntologyService with a post that has no capabilities defined
When: get_crew_context() is called
Then: "capabilities" key is NOT in the returned dict
```

### Test 12: Ontology context renders capabilities into prompt text

```
Given: A CognitiveAgent with runtime ontology returning capabilities for its post
When: _build_cognitive_baseline() runs
Then: state["_ontology_context"] contains "Your post capabilities (what you actually do):"
And: Contains capability summaries
```

### Test 13: Ontology context renders negative grounding into prompt text

```
Given: A CognitiveAgent with runtime ontology returning does_not_have for its post
When: _build_cognitive_baseline() runs
Then: state["_ontology_context"] contains "You do NOT have (do not claim or reference these):"
And: Contains the negative grounding strings
```

### Test 14: Full organization.yaml loads without errors

```
Given: The actual config/ontology/organization.yaml file with all 18 posts having capability profiles
When: OntologyLoader initializes and loads
Then: All posts parse successfully
And: scout_officer has at least 2 capabilities
And: scout_officer has at least 4 does_not_have entries
```

---

## Verification Checklist

- [ ] `PostCapability` dataclass in `models.py`
- [ ] `Post` dataclass has `capabilities` and `does_not_have` fields with defaults
- [ ] Loader parses both new fields from YAML
- [ ] `get_post_capabilities()`, `get_agent_capabilities()`, `get_post_negative_grounding()` on service
- [ ] `get_crew_context()` includes both fields when present, omits when empty
- [ ] `_build_cognitive_baseline()` renders capabilities and negative grounding into `_ontology_context`
- [ ] All 18 posts in `organization.yaml` have capability profiles
- [ ] All posts with tool-less analytical roles have `does_not_have` entries clarifying their actual scope
- [ ] Scout post specifically has negative grounding for sensors/telemetry/scan coverage
- [ ] Backward compatible — posts without capability fields default to empty lists
- [ ] `pytest tests/test_ad648_post_capability_profiles.py -v` green
- [ ] `pytest tests/ -x -q` — no regressions
