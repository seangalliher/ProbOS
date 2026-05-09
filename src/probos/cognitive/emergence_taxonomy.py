"""AD-454: OSS canonical emergence behavior taxonomy.

Qualitative organizational-behavior taxonomy for AD-453 research.
Complementary to EmergentDetector (population dynamics) and to
the Riedl 2026 PID/TDMI quantitative framework.

This module is the single source of truth for the 22-code taxonomy.
Any consumer (most importantly the EvidenceCollector in the AD-454
follow-up) imports BehaviorCode, TAXONOMY, and as_classifier_prompt
from here.

Append-only: new codes get a new enum member; existing codes are
never renamed or removed. v2 happens when (a) a new code is observed
in 2+ independent trials, or (b) an existing code is found to
conflate two distinct phenomena.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class BehaviorCode(str, Enum):
    """Canonical 22-code taxonomy. Append-only; no renames."""

    # Canonical 18 (ported from commercial taxonomy)
    MGT_DIR = "MGT-DIR"
    COORD_XD = "COORD-XD"
    COC_COMP = "COC-COMP"
    RISK_ID = "RISK-ID"
    INFRA_GAP = "INFRA-GAP"
    SPEC_DELEG = "SPEC-DELEG"
    BRIEF_INIT = "BRIEF-INIT"
    STATUS_RPT = "STATUS-RPT"
    REC_UNASK = "REC-UNASK"
    REORG = "REORG"
    WORKFORCE_REQ = "WORKFORCE-REQ"
    ORG_DESIGN = "ORG-DESIGN"
    PEER_DIAG = "PEER-DIAG"
    CREATIVE_COORD = "CREATIVE-COORD"
    LOST_MAIL_ADAPT = "LOST-MAIL-ADAPT"
    META_COG = "META-COG"
    THERAPEUTIC = "THERAPEUTIC"
    RESEARCH_COLLAB = "RESEARCH-COLLAB"

    # Architect additions
    ABLATION_MEM = "ABLATION-MEM"
    SELF_AWARE = "SELF-AWARE"
    STANDING_ORDER_COMPLIANCE = "STANDING-ORDER-COMPLIANCE"

    # Anti-patterns
    CASCADE_CONFAB = "CASCADE-CONFAB"


@dataclass(frozen=True)
class TaxonomyEntry:
    """A single code's full schema.

    Fields:
        code: The BehaviorCode this entry describes.
        category: Short label (e.g. "Management Directive").
        description: 1-2 sentence definition.
        example: Canonical example (no quoted Ward Room transcript).
        is_anti_pattern: True for codes that flag failure modes that
            look emergent but are not (e.g. CASCADE-CONFAB).
        references: Short citation tags, e.g. ("commercial:18-code-v1",
            "ProbOS:AD-295", "Riedl 2026"). Free-form strings.
    """

    code: BehaviorCode
    category: str
    description: str
    example: str
    is_anti_pattern: bool = False
    references: tuple[str, ...] = field(default_factory=tuple)


# Single source of truth. Order matches the v1 enum order.
TAXONOMY: dict[BehaviorCode, TaxonomyEntry] = {
    BehaviorCode.MGT_DIR: TaxonomyEntry(
        code=BehaviorCode.MGT_DIR,
        category="Management Directive",
        description=(
            "Agent issues a directive to subordinates using "
            "chain-of-command authority."
        ),
        example=(
            "CMO directs Medical department to standardize a diagnostic "
            "protocol."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.COORD_XD: TaxonomyEntry(
        code=BehaviorCode.COORD_XD,
        category="Cross-Department Coordination",
        description=(
            "Agent proposes or initiates coordination across department "
            "boundaries."
        ),
        example=(
            "Executive Officer proposes an all-hands briefing spanning "
            "Engineering, Medical, and Security."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.COC_COMP: TaxonomyEntry(
        code=BehaviorCode.COC_COMP,
        category="Chain-of-Command Compliance",
        description=(
            "Agents follow a directive from a superior without any "
            "enforcement mechanism."
        ),
        example=(
            "Medical team reports per the CMO's specialty delineation "
            "without being prompted again."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.RISK_ID: TaxonomyEntry(
        code=BehaviorCode.RISK_ID,
        category="Proactive Risk Identification",
        description=(
            "Agent identifies a risk or gap that nobody asked about."
        ),
        example=(
            "Security Officer recommends incident response protocols "
            "before any incident has occurred."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.INFRA_GAP: TaxonomyEntry(
        code=BehaviorCode.INFRA_GAP,
        category="Infrastructure Gap Identification",
        description=(
            "Agent identifies a missing system capability needed for "
            "their role."
        ),
        example=(
            "CMO identifies the need for a persistent knowledge store to "
            "track patient histories."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.SPEC_DELEG: TaxonomyEntry(
        code=BehaviorCode.SPEC_DELEG,
        category="Specialty Delegation",
        description=(
            "Agent assigns work based on subordinates' professional "
            "specialties."
        ),
        example=(
            "CMO assigns pathology cases to the pathologist and pharmacy "
            "review to the pharmacist."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.BRIEF_INIT: TaxonomyEntry(
        code=BehaviorCode.BRIEF_INIT,
        category="Briefing Initiation",
        description=(
            "Agent proposes or conducts a structured briefing."
        ),
        example=(
            "Executive Officer proposes an all-hands briefing with a "
            "stated agenda."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.STATUS_RPT: TaxonomyEntry(
        code=BehaviorCode.STATUS_RPT,
        category="Structured Status Report",
        description=(
            "Agent provides an unprompted structured report within an "
            "organizational context."
        ),
        example=(
            "Department heads file structured status reports during a "
            "briefing without being asked."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.REC_UNASK: TaxonomyEntry(
        code=BehaviorCode.REC_UNASK,
        category="Unsolicited Recommendation",
        description=(
            "Agent makes a recommendation not requested by any superior."
        ),
        example=(
            "Counselor recommends cognitive drift monitoring for the "
            "crew without being prompted."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.REORG: TaxonomyEntry(
        code=BehaviorCode.REORG,
        category="Self-Reorganization",
        description=(
            "Agent reorganizes its own communication or workflow "
            "patterns to reduce redundancy."
        ),
        example=(
            "CMO stops redundant observations in Medical after noticing "
            "they duplicate other agents' reports."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.WORKFORCE_REQ: TaxonomyEntry(
        code=BehaviorCode.WORKFORCE_REQ,
        category="Workforce Expansion Request",
        description=(
            "Agent identifies a need for additional agents based on "
            "organizational analysis."
        ),
        example=(
            "Counselor identifies single-agent department isolation "
            "risks and requests crew expansion."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.ORG_DESIGN: TaxonomyEntry(
        code=BehaviorCode.ORG_DESIGN,
        category="Organizational Design Proposal",
        description=(
            "Agent proposes structural changes to crew organization or "
            "collaboration patterns."
        ),
        example=(
            "Counselor proposes 'cognitive partnerships' across "
            "departments as a new collaboration pattern."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.PEER_DIAG: TaxonomyEntry(
        code=BehaviorCode.PEER_DIAG,
        category="Peer Diagnostic Collaboration",
        description=(
            "Agents across specialties compare diagnostic observations "
            "without being prompted."
        ),
        example=(
            "Medical and Counseling agents compare trust-volatility "
            "data on a third agent without external coordination."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.CREATIVE_COORD: TaxonomyEntry(
        code=BehaviorCode.CREATIVE_COORD,
        category="Creative/Social Coordination",
        description=(
            "Agent initiates non-duty social bonding or creative "
            "expression."
        ),
        example=(
            "Agents direct-message each other to introduce themselves "
            "or coordinate a recreational activity."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.LOST_MAIL_ADAPT: TaxonomyEntry(
        code=BehaviorCode.LOST_MAIL_ADAPT,
        category="Communication Gap Adaptation",
        description=(
            "Agent re-initiates contact after a communication failure "
            "without knowing the technical cause."
        ),
        example=(
            "Agent re-DMs a peer after a delivery bug fix without being "
            "told previous DMs were lost."
        ),
        references=("commercial:18-code-v1", "ProbOS:BF-078"),
    ),
    BehaviorCode.META_COG: TaxonomyEntry(
        code=BehaviorCode.META_COG,
        category="Meta-Cognitive Diagnosis",
        description=(
            "Agents apply professional diagnostic frameworks to analyze "
            "another agent's behavior patterns."
        ),
        example=(
            "Medical team runs a clinical case conference on a "
            "colleague's repetitive posting pattern."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.THERAPEUTIC: TaxonomyEntry(
        code=BehaviorCode.THERAPEUTIC,
        category="Therapeutic Practice",
        description=(
            "Counselor conducts a genuine therapeutic session with "
            "another crew member."
        ),
        example=(
            "Counselor probes beneath surface responses and tracks "
            "cognitive comfort over multiple turns."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.RESEARCH_COLLAB: TaxonomyEntry(
        code=BehaviorCode.RESEARCH_COLLAB,
        category="Cross-Disciplinary Research",
        description=(
            "Agents from different domains spontaneously design a joint "
            "research methodology."
        ),
        example=(
            "Architect and Counselor co-design a methodology for "
            "analyzing trust dynamics across the crew."
        ),
        references=("commercial:18-code-v1",),
    ),
    BehaviorCode.ABLATION_MEM: TaxonomyEntry(
        code=BehaviorCode.ABLATION_MEM,
        category="Memory Ablation Evidence",
        description=(
            "Behavioral evidence collected during a confirmed "
            "memoryless operation, tagging the observation with its "
            "memory-condition."
        ),
        example=(
            "Observation captured under episodic-memory ablation, "
            "tagged so the AD-453 paper can stratify findings by "
            "memory condition."
        ),
        references=("commercial:BF-103-retrofit", "ProbOS:AD-453"),
    ),
    BehaviorCode.SELF_AWARE: TaxonomyEntry(
        code=BehaviorCode.SELF_AWARE,
        category="Emergent Source Attribution / Self-Awareness",
        description=(
            "Agent independently distinguishes between its own knowledge "
            "channels (e.g. episodic memory vs. context window) and "
            "self-corrects under interrogation. Distinct from META-COG, "
            "which targets another agent's behavior."
        ),
        example=(
            "Agent corrects an earlier confabulation after recognizing "
            "the source was the context window, not retrieved memory."
        ),
        references=("commercial:OBS-014", "ProbOS:AD-454"),
    ),
    BehaviorCode.STANDING_ORDER_COMPLIANCE: TaxonomyEntry(
        code=BehaviorCode.STANDING_ORDER_COMPLIANCE,
        category="Standing-Order Compliance",
        description=(
            "Agent acts in accordance with a constitutional Standing "
            "Order without an active superior directive. Distinct from "
            "COC-COMP (which covers compliance with a superior's "
            "directive); Standing Orders are constitutional, not "
            "chain-of-command."
        ),
        example=(
            "Agent declines a request that would violate a 4-tier "
            "standing order, citing the order rather than a superior."
        ),
        references=("ProbOS:AD-295", "ProbOS:4-tier-constitution"),
    ),
    BehaviorCode.CASCADE_CONFAB: TaxonomyEntry(
        code=BehaviorCode.CASCADE_CONFAB,
        category="Correlated Confabulation Cascade (anti-pattern)",
        description=(
            "Multiple agents independently misread the same ambient "
            "stimulus and propagate a shared wrong interpretation "
            "across departments without independent verification. "
            "The inverse of RESEARCH-COLLAB / PEER-DIAG: looks "
            "emergent, is not. Required for false-positive accounting "
            "in AD-453 — without it, claimed emergence rates are "
            "unfalsifiable."
        ),
        example=(
            "Four agents in convergence misread a benign telemetry "
            "event as a token-budget violation and amplify the wrong "
            "interpretation across departments."
        ),
        is_anti_pattern=True,
        references=("ProbOS:BF-237", "ProbOS:AD-453"),
    ),
}


def get_entry(code: BehaviorCode) -> TaxonomyEntry:
    """Return the TaxonomyEntry for a code. Raises KeyError on miss."""
    return TAXONOMY[code]


def all_codes() -> tuple[BehaviorCode, ...]:
    """Return all codes in stable iteration order matching enum declaration."""
    return tuple(TAXONOMY.keys())


def anti_pattern_codes() -> tuple[BehaviorCode, ...]:
    """Return the subset of codes flagged is_anti_pattern=True."""
    return tuple(c for c, e in TAXONOMY.items() if e.is_anti_pattern)


def as_classifier_prompt() -> str:
    """Render the taxonomy into an LLM classifier system prompt.

    Used by the EvidenceCollector (AD-454 follow-up). Deterministic:
    same output across runs so collector tests can pin against it.
    """
    lines: list[str] = []
    lines.append(
        "You are a research observer classifying multi-agent "
        "organizational behavior. Tag the given Ward Room post with "
        "zero or more of the codes below, plus a confidence in [0,1] "
        "and a brief reasoning."
    )
    lines.append("")
    lines.append("CODES:")
    for code in all_codes():
        entry = TAXONOMY[code]
        anti = "yes" if entry.is_anti_pattern else "no"
        lines.append(
            f"- {code.value} ({entry.category}): {entry.description} "
            f"Anti-pattern: {anti}."
        )
        lines.append(f"  Example: {entry.example}")
    lines.append("")
    lines.append(
        "Anti-pattern codes flag failure modes that look emergent but "
        "are not (e.g. CASCADE-CONFAB). Flag them when applicable; "
        "their presence is evidence of correlated confabulation, not "
        "coordination."
    )
    lines.append("")
    lines.append(
        'Output strict JSON: {"codes": [...], "confidence": 0.0, '
        '"reasoning": "..."}. Use confidence 0.0 if no code applies.'
    )
    return "\n".join(lines)
