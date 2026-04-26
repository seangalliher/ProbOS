# AD-618c: Built-in Bills

**Issue:** #204 (AD-618 umbrella)
**Status:** Ready for builder
**Priority:** Medium
**Depends:** AD-618a (Bill Schema + Parser — must be built first)
**Files:** `src/probos/sop/builtin/` (NEW directory), `src/probos/sop/builtin/__init__.py` (NEW), `src/probos/sop/builtin/general_quarters.yaml` (NEW), `src/probos/sop/builtin/research_consultation.yaml` (NEW), `src/probos/sop/builtin/incident_response.yaml` (NEW), `src/probos/sop/builtin/daily_operations_brief.yaml` (NEW), `src/probos/sop/loader.py` (NEW), `src/probos/sop/__init__.py` (EDIT), `tests/test_ad618c_builtin_bills.py` (NEW)

## Problem

AD-618a delivers the schema and parser. AD-618b delivers the runtime. But there are no actual Bills — the `ship_records/bills/` directory starts empty. ProbOS needs a set of default Bills that define how the crew responds to common situations: battle stations, research requests, incidents, daily briefings.

AD-618c delivers built-in Bill YAML files bundled with the codebase (not in Ship's Records — these are code-shipped defaults) and a loader that discovers and parses them at startup.

**Navy model:** Every ship commissioning includes a standard set of Bills (General Quarters, Man Overboard, Abandon Ship, etc.) before the crew ever boards. Custom Bills are added by the Captain over time.

## Design

AD-618c delivers three things:

1. **Built-in YAML Bill files** — shipped in `src/probos/sop/builtin/`. Parsed at startup, available immediately. NOT stored in Ship's Records (they're code artifacts, not user-created documents).
2. **BillLoader** — discovers YAML files in the `builtin/` directory, parses each with `parse_bill()`, returns a dict of `BillDefinition` objects.
3. **Four initial Bills:**
   - **General Quarters** — All-hands battle stations. Every department chief reports readiness. Captain confirms. Ship-wide alert.
   - **Research Consultation** — Science dept. conducts a structured research investigation: data analyst gathers data, systems analyst identifies patterns, research specialist synthesizes, then reports to requesting officer.
   - **Incident Response** — Security/Engineering triage: identify, contain, remediate, post-mortem.
   - **Daily Operations Brief** — Morning brief: each department chief reports status, Captain issues standing orders for the day.

**What this does NOT include:**
- Runtime activation of these bills (that's AD-618b)
- Additional bills (Code Review, Onboarding, Self-Modification Review, Federation Handshake — future ADs)
- Custom bill authoring UI (AD-618d)

---

## Section 1: Create `src/probos/sop/builtin/` package

**File:** `src/probos/sop/builtin/__init__.py` (NEW)

```python
"""Built-in Bill definitions shipped with ProbOS (AD-618c).

These YAML files define default SOPs available from first boot.
They are code artifacts, not user-created documents.
"""
```

---

## Section 2: General Quarters Bill

**File:** `src/probos/sop/builtin/general_quarters.yaml` (NEW)

```yaml
bill: general_quarters
version: 1
title: "General Quarters"
description: >
  All-hands battle stations. Activates during ship-wide emergencies.
  Every department chief reports readiness status. Captain confirms
  ship is at condition one. Remains active until Captain secures.
author: "Ship's Standing Orders"

activation:
  trigger: "alert:red"
  authority: "captain"

roles:
  commanding_officer:
    department: "bridge"
    min_rank: "commander"
  first_officer:
    department: "bridge"
  engineering_chief:
    department: "engineering"
  security_chief:
    department: "security"
  science_chief:
    department: "science"
  medical_chief:
    department: "medical"
  operations_chief:
    department: "operations"

steps:
  - id: sound_general_quarters
    name: "Sound General Quarters"
    role: commanding_officer
    action: post_to_channel
    channel: "general"
    outputs:
      - name: alert_message
        type: text

  - id: engineering_report
    name: "Engineering Readiness Report"
    role: engineering_chief
    action: cognitive_skill
    outputs:
      - name: engineering_status
        type: enum
        values: ["ready", "degraded", "offline"]

  - id: security_report
    name: "Security Readiness Report"
    role: security_chief
    action: cognitive_skill
    outputs:
      - name: security_status
        type: enum
        values: ["ready", "degraded", "offline"]

  - id: science_report
    name: "Science Readiness Report"
    role: science_chief
    action: cognitive_skill
    outputs:
      - name: science_status
        type: enum
        values: ["ready", "degraded", "offline"]

  - id: medical_report
    name: "Medical Readiness Report"
    role: medical_chief
    action: cognitive_skill
    outputs:
      - name: medical_status
        type: enum
        values: ["ready", "degraded", "offline"]

  - id: operations_report
    name: "Operations Readiness Report"
    role: operations_chief
    action: cognitive_skill
    outputs:
      - name: operations_status
        type: enum
        values: ["ready", "degraded", "offline"]

  - id: readiness_assessment
    name: "Readiness Assessment"
    role: first_officer
    action: cognitive_skill
    type: sequential
    inputs:
      - name: eng_status
        source: "step:engineering_report.engineering_status"
      - name: sec_status
        source: "step:security_report.security_status"
      - name: sci_status
        source: "step:science_report.science_status"
      - name: med_status
        source: "step:medical_report.medical_status"
      - name: ops_status
        source: "step:operations_report.operations_status"
    outputs:
      - name: ship_readiness
        type: enum
        values: ["condition_one", "condition_two", "not_ready"]

  - id: captain_confirm
    name: "Captain Confirms Condition"
    role: commanding_officer
    action: captain_approval
    gate: captain_approval
    inputs:
      - name: readiness
        source: "step:readiness_assessment.ship_readiness"

expected_results:
  - "All departments report readiness status"
  - "First Officer assesses overall ship condition"
  - "Captain confirms battle stations condition"

standing_order_constraints:
  - "All agents must report within 60 seconds"
  - "Department chiefs may delegate to senior crew if unavailable"
```

---

## Section 3: Research Consultation Bill

**File:** `src/probos/sop/builtin/research_consultation.yaml` (NEW)

```yaml
bill: research_consultation
version: 1
title: "Research Consultation"
description: >
  Structured research investigation using the Science Department's
  analytical pyramid. Data flows up through the pyramid, synthesis
  is reported to the requesting officer.
author: "Ship's Standing Orders"

activation:
  trigger: "manual"
  authority: "department_chief"

roles:
  requester:
    department: "any"
  data_analyst:
    department: "science"
    qualifications: ["data_analysis"]
  systems_analyst:
    department: "science"
    qualifications: ["systems_analysis"]
  research_specialist:
    department: "science"
    qualifications: ["research_methodology"]

steps:
  - id: receive_request
    name: "Receive Research Request"
    role: requester
    action: receive_message
    inputs:
      - name: research_question
        source: "activation_data"
    outputs:
      - name: research_scope
        type: text

  - id: data_gathering
    name: "Gather Relevant Data"
    role: data_analyst
    action: cognitive_skill
    inputs:
      - name: scope
        source: "step:receive_request.research_scope"
    outputs:
      - name: raw_findings
        type: document

  - id: pattern_analysis
    name: "Identify Patterns and Correlations"
    role: systems_analyst
    action: cognitive_skill
    inputs:
      - name: findings
        source: "step:data_gathering.raw_findings"
    outputs:
      - name: patterns
        type: document

  - id: synthesis
    name: "Synthesize Research Report"
    role: research_specialist
    action: cognitive_skill
    inputs:
      - name: raw_data
        source: "step:data_gathering.raw_findings"
      - name: patterns
        source: "step:pattern_analysis.patterns"
    outputs:
      - name: report
        type: document

  - id: deliver_report
    name: "Deliver Report to Requester"
    role: research_specialist
    action: send_dm
    # DM recipient is the agent filling the 'requester' role
    inputs:
      - name: report
        source: "step:synthesis.report"

expected_results:
  - "Research question scoped by data analyst"
  - "Data gathered and analyzed through analytical pyramid"
  - "Synthesized report delivered to requester"
  # Note: report archival is the responsibility of the delivering agent's
  # cognitive_skill. A dedicated ARCHIVE action may be added in a future AD.

standing_order_constraints:
  - "Each analyst adds independent perspective — no parroting upstream"
  - "Research specialist must cite specific data points, not just summarize"
```

---

## Section 4: Incident Response Bill

**File:** `src/probos/sop/builtin/incident_response.yaml` (NEW)

```yaml
bill: incident_response
version: 1
title: "Incident Response"
description: >
  Structured triage and remediation for ship-wide incidents.
  Security leads identification, Engineering leads remediation,
  post-mortem written to Ship's Records.
author: "Ship's Standing Orders"

activation:
  trigger: "alert:amber"
  authority: "department_chief"

roles:
  incident_commander:
    department: "security"
  engineering_lead:
    department: "engineering"
  science_support:
    department: "science"
  counselor:
    department: "bridge"

steps:
  - id: identify
    name: "Identify and Classify Incident"
    role: incident_commander
    action: cognitive_skill
    inputs:
      - name: incident_data
        source: "activation_data"
    outputs:
      - name: classification
        type: enum
        values: ["critical", "major", "minor"]
      - name: affected_systems
        type: text

  - id: triage_decision
    name: "Triage Decision Point"
    role: incident_commander
    type: xor_gateway
    condition: "step:identify.classification"
    branches:
      critical: contain_critical
      major: contain_standard
      minor: contain_standard

  - id: contain_critical
    name: "Critical Containment — Isolate Systems"
    role: engineering_lead
    action: cognitive_skill
    inputs:
      - name: systems
        source: "step:identify.affected_systems"
    outputs:
      - name: containment_status
        type: text

  - id: contain_standard
    name: "Standard Containment"
    role: engineering_lead
    action: cognitive_skill
    inputs:
      - name: systems
        source: "step:identify.affected_systems"
    outputs:
      - name: containment_status
        type: text

  # FIX 1 (architect review): Both XOR branches emit the same output
  # name (containment_status). root_cause lists both as input sources
  # so the data graph is valid regardless of which branch executes.
  # At runtime (AD-618e), the step resolver checks which source
  # actually produced output and uses that one.
  - id: root_cause
    name: "Root Cause Analysis"
    role: science_support
    action: cognitive_skill
    inputs:
      - name: containment
        source: "step:contain_critical.containment_status"
      - name: containment_alt
        source: "step:contain_standard.containment_status"
    outputs:
      - name: root_cause
        type: document

  - id: remediate
    name: "Remediate and Verify"
    role: engineering_lead
    action: cognitive_skill
    inputs:
      - name: cause
        source: "step:root_cause.root_cause"
    outputs:
      - name: remediation_status
        type: enum
        values: ["resolved", "mitigated", "ongoing"]

  - id: post_mortem
    name: "Write Post-Mortem Report"
    role: incident_commander
    action: cognitive_skill
    inputs:
      - name: classification
        source: "step:identify.classification"
      - name: root_cause
        source: "step:root_cause.root_cause"
      - name: remediation
        source: "step:remediate.remediation_status"
    outputs:
      - name: report
        type: document

  - id: crew_wellness
    name: "Crew Wellness Check"
    role: counselor
    action: cognitive_skill

expected_results:
  - "Incident classified and contained"
  - "Root cause identified"
  - "Remediation completed or mitigated"
  - "Post-mortem documented in Ship's Records"
  # Note: archival is the responsibility of the cognitive_skill action
  # holder — the agent performing post_mortem is expected to call
  # records storage internally. A dedicated WRITE_TO_RECORDS action
  # may be added in a future AD-618 iteration.
  - "Crew wellness assessed"

standing_order_constraints:
  - "Critical incidents require Captain notification within 5 minutes"
  - "Post-mortem must be filed within 24 hours of resolution"
```

---

## Section 5: Daily Operations Brief Bill

**File:** `src/probos/sop/builtin/daily_operations_brief.yaml` (NEW)

```yaml
bill: daily_operations_brief
version: 1
title: "Daily Operations Brief"
description: >
  Morning brief where each department chief reports status and
  the Captain issues standing orders for the day.
author: "Ship's Standing Orders"

activation:
  trigger: "schedule:0 8 * * *"
  authority: "first_officer"

roles:
  first_officer:
    department: "bridge"
  engineering_chief:
    department: "engineering"
  security_chief:
    department: "security"
  science_chief:
    department: "science"
  operations_chief:
    department: "operations"
  medical_chief:
    department: "medical"

steps:
  - id: call_to_brief
    name: "Call Department Chiefs to Brief"
    role: first_officer
    action: post_to_channel
    channel: "bridge"

  - id: engineering_brief
    name: "Engineering Status"
    role: engineering_chief
    action: cognitive_skill
    outputs:
      - name: status
        type: text

  - id: security_brief
    name: "Security Status"
    role: security_chief
    action: cognitive_skill
    outputs:
      - name: status
        type: text

  - id: science_brief
    name: "Science Status"
    role: science_chief
    action: cognitive_skill
    outputs:
      - name: status
        type: text

  - id: operations_brief
    name: "Operations Status"
    role: operations_chief
    action: cognitive_skill
    outputs:
      - name: status
        type: text

  - id: medical_brief
    name: "Medical Status"
    role: medical_chief
    action: cognitive_skill
    outputs:
      - name: status
        type: text

  - id: summary
    name: "Compile Brief Summary"
    role: first_officer
    action: cognitive_skill
    inputs:
      - name: engineering
        source: "step:engineering_brief.status"
      - name: security
        source: "step:security_brief.status"
      - name: science
        source: "step:science_brief.status"
      - name: operations
        source: "step:operations_brief.status"
      - name: medical
        source: "step:medical_brief.status"
    outputs:
      - name: brief_report
        type: document

expected_results:
  - "All departments report current status"
  - "First Officer compiles summary"

standing_order_constraints:
  - "Brief should complete within 15 minutes"
  - "Absent department chiefs delegate to senior crew"
```

---

## Section 6: Bill loader functions

**File:** `src/probos/sop/loader.py` (NEW)

```python
"""AD-618c: BillLoader — discovers and loads built-in Bill YAML files.

Scans the builtin/ directory at startup, parses each YAML file with
parse_bill_file(), returns a dict of BillDefinition objects keyed by
bill slug.

Also loads custom bills from Ship's Records bills/ directory if available.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from probos.sop.parser import BillValidationError, parse_bill_file
from probos.sop.schema import BillDefinition

logger = logging.getLogger(__name__)

# Path to built-in bills shipped with ProbOS.
# Uses __file__ resolution — sufficient while ProbOS runs from source.
# If ProbOS ever ships as a wheel, switch to importlib.resources.files().
_BUILTIN_DIR = Path(__file__).parent / "builtin"


def load_builtin_bills() -> dict[str, BillDefinition]:
    """Load all built-in Bill YAML files from the builtin/ directory.

    Returns a dict of {bill_slug: BillDefinition}. Logs warnings for
    any files that fail to parse (does not raise — best-effort loading).
    """
    bills: dict[str, BillDefinition] = {}

    if not _BUILTIN_DIR.is_dir():
        logger.warning("AD-618c: Built-in bills directory not found: %s", _BUILTIN_DIR)
        return bills

    for yaml_path in sorted(_BUILTIN_DIR.glob("*.yaml")):
        try:
            bill = parse_bill_file(yaml_path)
            bills[bill.bill] = bill
            logger.debug("AD-618c: Loaded built-in bill: %s", bill.bill)
        except (BillValidationError, FileNotFoundError, yaml.YAMLError) as exc:
            logger.warning(
                "AD-618c: Failed to load built-in bill '%s': %s — skipping",
                yaml_path.name, exc,
            )

    logger.info("AD-618c: Loaded %d built-in bill(s)", len(bills))
    return bills


def load_custom_bills(records_bills_dir: Path | str) -> dict[str, BillDefinition]:
    """Load custom Bill YAML files from Ship's Records bills/ directory.

    Same parsing logic as built-in, but from user-created files.
    Returns empty dict if directory doesn't exist or is empty.

    Note: Custom bills may shadow built-in bills of the same slug.
    Callers are responsible for merging with appropriate precedence
    (typically custom overrides builtin). Within this directory,
    duplicate slugs are logged and skipped (first-wins).
    """
    bills_dir = Path(records_bills_dir)
    bills: dict[str, BillDefinition] = {}

    if not bills_dir.is_dir():
        return bills

    for yaml_path in sorted(bills_dir.glob("*.yaml")):
        try:
            bill = parse_bill_file(yaml_path)
            if bill.bill in bills:
                logger.warning(
                    "AD-618c: Duplicate custom bill slug '%s' in %s — skipping",
                    bill.bill, yaml_path.name,
                )
                continue
            bills[bill.bill] = bill
        except (BillValidationError, FileNotFoundError, yaml.YAMLError) as exc:
            logger.warning(
                "AD-618c: Failed to load custom bill '%s': %s — skipping",
                yaml_path.name, exc,
            )

    if bills:
        logger.info("AD-618c: Loaded %d custom bill(s)", len(bills))
    return bills
```

---

## Section 7: Update `src/probos/sop/__init__.py`

**File:** `src/probos/sop/__init__.py` (EDIT)

Add the loader exports. `BillValidationError` is already exported from AD-618a — verify it remains in `__all__`.

```python
from probos.sop.loader import load_builtin_bills, load_custom_bills
```

Add to `__all__`:
```python
    "load_builtin_bills",
    "load_custom_bills",
```

---

## Section 8: Tests

**File:** `tests/test_ad618c_builtin_bills.py` (NEW)

### Built-in YAML Tests
1. **general_quarters.yaml parses without errors** — `parse_bill_file()` returns BillDefinition
2. **research_consultation.yaml parses without errors**
3. **incident_response.yaml parses without errors**
4. **daily_operations_brief.yaml parses without errors**
5. **general_quarters has correct roles** — commanding_officer, first_officer, 5 dept chiefs
6. **general_quarters has correct step count** — 8 steps
6b. **incident_response has correct step count** — 8 steps (identify, triage_decision, contain_critical, contain_standard, root_cause, remediate, post_mortem, crew_wellness)
7. **research_consultation has qualification requirements** — data_analyst role has qualifications
8. **incident_response has XOR gateway** — triage_decision step's `gateway_type` field equals `GatewayType.XOR_GATEWAY` (YAML field `type` maps to dataclass attribute `gateway_type` per schema.py:73)
9. **daily_operations_brief has schedule trigger** — activation.trigger starts with "schedule:"
10. **All built-in bills have unique slugs** — no collisions

### Loader Tests
11. **load_builtin_bills() returns all 4 bills** — keyed by slug
12. **load_builtin_bills() handles missing directory** — returns empty dict, logs warning
13. **load_builtin_bills() skips invalid YAML** — create a temp invalid file, verify it's skipped and logged
14. **load_custom_bills() loads from a temp directory** — create temp YAML, verify parsed
15. **load_custom_bills() skips duplicate slugs** — two files with same slug, only first loaded
16. **load_custom_bills() returns empty for missing directory**

### Schema Validation Tests (via parser)
17. **All built-in bills pass role reference validation** (regression pin) — every step.role exists in bill.roles. Implicit in Tests 1–4 since the parser raises BillValidationError on bad role refs, but kept as a regression pin: will fail if anyone removes a role definition without removing its step references.
18. **All built-in bills pass branch target validation** — incident_response branches reference valid step IDs
19. **All built-in bills have non-empty expected_results**
20. **All built-in bills have valid action types** (regression pin) — every step.action is in StepAction enum. Parser already validates this; kept as regression guard.
21. **incident_response root_cause accepts inputs from both XOR branches** — root_cause step has inputs referencing both contain_critical.containment_status and contain_standard.containment_status, so data flow is valid regardless of which branch executes.
22. **research_consultation requester role is wired** — receive_request step uses role: requester, not data_analyst.
23. **Custom bill shadowing builtin logs warning** — load custom bill with slug "general_quarters", merge with builtins, verify custom overrides builtin (or document the merge contract in test assertion).

---

## Engineering Principles Compliance

- **SOLID/S** — Loader functions handle discovery/parse only. YAML files are declarative data, not logic. Schema validation is in the parser (AD-618a), not duplicated here.
- **Fail Fast** — `parse_bill_file` raises `BillValidationError` for invalid YAML. Loader catches and logs-and-skips (log-and-degrade tier) so one bad file doesn't block startup.
- **DRY** — Both `load_builtin_bills` and `load_custom_bills` use the same `parse_bill_file` from AD-618a. No duplicate parsing logic.
- **Defense in Depth** — Parser validates role references, branch targets, and action types. Tests re-verify as regression pins (Tests 17, 20).
- **Law of Demeter** — Loader returns `dict[str, BillDefinition]` — callers don't reach into loader internals.

---

## Tracking Updates

### PROGRESS.md
```
AD-618c COMPLETE. Built-in Bills — 4 default YAML bills (General Quarters, Research Consultation, Incident Response, Daily Operations Brief) + loader functions (builtin discovery/parse, custom loading). XOR gateway with dual-input convergence in incident_response. 23 tests. Issue #204.
```

### DECISIONS.md
```
### AD-618c — Built-in Bills (2026-04-25)
**Context:** AD-618a delivered schema/parser but no actual Bill files exist. Ships need default SOPs available from first boot.
**Decision:** Four initial Bills cover the most common scenarios: emergency response (General Quarters), knowledge work (Research Consultation), incident management (Incident Response), routine operations (Daily Ops Brief). Bills are shipped as code artifacts in src/probos/sop/builtin/, not as Ship's Records documents. Loader functions discover and parse them at startup. Custom bills from Ship's Records are loaded separately and may shadow built-ins of the same slug. Invalid files are logged-and-skipped, not fatal. Incident Response demonstrates XOR gateway with dual-input convergence pattern (downstream step lists both branch outputs as inputs). Schedule triggers (daily_operations_brief cron) are parsed but inert until a future scheduler AD.
**Consequences:** ProbOS ships with usable SOPs out of the box. Report archival is the cognitive skill holder's responsibility (no dedicated WRITE_TO_RECORDS action yet — future AD). Additional bills (Code Review, Onboarding, Self-Mod Review, Federation Handshake) are future ADs. Captain can create custom bills in Ship's Records.
```

### docs/development/roadmap.md
Update AD-618c entry to COMPLETE.
