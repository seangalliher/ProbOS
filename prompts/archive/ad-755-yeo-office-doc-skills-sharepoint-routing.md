# AD-755 - Office Document Skills + SharePoint Routing + Templates

Status: drafted (planning slate only)
Issue: #701
Parent: #486
Depends on: AD-749 (#695)
Related: #480

## Objective
Define office-document capability completeness for Yeo and all crew agents.

## Captain Invariant
Capability is usable by all crew agents; Yeo is the front-door orchestrator and delegates to specialists.

## In Scope
- Skill contracts for office document summarize/create/revise workflows.
- SharePoint-aware routing and source provenance tagging.
- Reusable template registry for recurring office tasks.

## Out of Scope
- Vendor-specific premium document processing services.
- Re-implementing generic channel adapter backlog in #480.

## OSS vs Commercial Split

**OSS (Personal Desktop):**
- Office document skills (docx/pptx/xlsx summarize/create/revise) via `python-docx`, `python-pptx`, `openpyxl`.
- SharePoint routing for personal OneDrive/personal-site documents.
- Local template registry for recurring personal tasks.

**Commercial Extension Point:**
- Org template library and library versioning/governance.
- SharePoint site collection and team-drive routing policies.
- Sensitivity-label and permission-level enforcement.
- Document life cycle and retention policy integration.

## File Targets
- `src/probos/skill_framework.py`
- `src/probos/agents/`
- `src/probos/integrations/`
- `src/probos/routers/`
- `src/probos/ward_room/`

## Pre-Flight Anchors
- Verify existing skill agent interfaces in `src/probos/skill_framework.py`.
- Verify integration seams in `src/probos/integrations/` and channel adapters.
- Verify delivery/reporting paths in ward-room services.

## Implementation Spec

### Section 1: Document Skill Contracts

**File:** `src/probos/skill_framework.py` (extend existing)

Create `DocxAgent`, `PptxAgent`, `XlsxAgent` (SkillBasedAgent subclasses):
```python
class DocxAgent(SkillBasedAgent):
    """DOCX summarization, creation, revision via python-docx."""
    
    async def summarize_docx(self, file_path: str) -> str:
        """Extract full text from .docx, return LLM-generated summary."""
    
    async def create_docx(self, title: str, content: list[str], template: str | None = None) -> str:
        """Create new .docx from template or blank. Returns file_path."""
    
    async def revise_docx(self, file_path: str, instructions: str) -> str:
        """Apply revision instructions to existing .docx."""

class PptxAgent(SkillBasedAgent):
    """PPTX creation, slide additions via python-pptx."""
    
    async def summarize_pptx(self, file_path: str) -> str:
        """Extract slide titles + speaker notes, summarize."""
    
    async def create_pptx(self, title: str, slides: list[dict], template: str | None = None) -> str:
        """Create presentation with slides. Returns file_path."""

class XlsxAgent(SkillBasedAgent):
    """XLSX operations: read ranges, update values, pivot summaries."""
    
    async def read_xlsx_range(self, file_path: str, sheet: str, range: str) -> list[list]:
        """Read range from sheet (e.g., 'A1:D10')."""
    
    async def update_xlsx(self, file_path: str, sheet: str, updates: dict[str, Any]) -> str:
        """Update cells/formulas in sheet."""
```

**Tests:** `tests/test_office_agents.py` (6 tests)
- Summarize DOCX: extract text + LLM summary
- Create DOCX from template: file created + readable
- Summarize PPTX: slide extraction works
- Create PPTX: slide content preserved
- Read/update XLSX: round-trip integrity

### Section 2: SharePoint Routing & Source Provenance

**File:** `src/probos/integrations/sharepoint_routing.py` (new)

Create `SharePointRouter` + `DocumentProvenance`:
```python
@dataclass
class DocumentProvenance:
    source: str  # "personal_onedrive" | "sharepoint_site" | "teams_channel" | "local"
    origin_url: str | None
    permission_level: str  # "read" | "edit" | "owner"
    last_modified_by: str | None
    sensitivity_label: str | None  # Commercial only, always None in OSS

class SharePointRouter:
    async def route_for_read(self, doc_path: str) -> SharePointLocation:
        """Determine if doc is on OneDrive/SharePoint, return API route."""
    
    async def upload_to_personal(self, local_path: str, remote_name: str) -> str:
        """Upload to ~/Documents or personal site. Returns remote URL."""
    
    async def tag_provenance(self, doc_path: str) -> DocumentProvenance:
        """Infer provenance from path + metadata."""
```

**Tests:** `tests/test_sharepoint_routing.py` (2 tests)
- Personal OneDrive detected + routed correctly
- Provenance tagging works for local files

### Section 3: Template Registry

**File:** `src/probos/integrations/template_registry.py` (new)

Create `TemplateRegistry` class:
```python
@dataclass
class Template:
    id: str  # UUID
    name: str  # "Meeting Notes", "Weekly Report"
    file_type: str  # "docx" | "pptx" | "xlsx"
    content: bytes  # Stored in AttachmentStore (AD-731 refs)
    created_at: datetime
    used_count: int = 0

class TemplateRegistry:
    def __init__(self, registry_dir: str):
        """Load templates from `~/.probos/templates/` (Git-tracked)."""
    
    async def list_templates(self) -> list[Template]:
        """All available templates."""
    
    async def create_from_template(self, template_id: str, **kwargs) -> str:
        """Instantiate template with substitutions. Returns file path."""
```

**Storage:** Local Git-backed store in `~/.probos/templates/` (operator can commit custom templates).

**Tests:** `tests/test_template_registry.py` (2 tests)
- Template load + list
- Template instantiation with substitutions

### Section 4: Office Skills Runtime Wiring

**File:** `src/probos/runtime.py` (extend `_create_pools`)

Register office agents:
```python
if self.config.office_skills.enabled:
    self._pool_by_intent.register(DocxAgent(runtime=self))
    self._pool_by_intent.register(PptxAgent(runtime=self))
    self._pool_by_intent.register(XlsxAgent(runtime=self))
    self._template_registry = TemplateRegistry(config.office_skills.template_dir)
    logger.info("Office document skills registered")
```

**Config (system.yaml):**
```yaml
office_skills:
  enabled: true
  template_dir: ~/.probos/templates
```

### Section 5: Acceptance Criteria & Gate

**Test Expectations:**
- `test_office_agents.py`: 6 tests
- `test_sharepoint_routing.py`: 2 tests
- `test_template_registry.py`: 2 tests
- **Total: 10 new tests**

**OSS Scope Verification:**
- No sensitivity-label enforcement (commercial extension only)
- Template registry is local Git-backed, no org library sync
- SharePoint routing works only for personal OneDrive/personal sites

**Dependencies:** Requires AD-749 (M365 auth foundation) for SharePoint API access.

**Completion Signal:**
- All 10 tests passing
- Office agents appear in intent registry
- Document skills handle DOCX/PPTX/XLSX without errors
- Template instantiation produces valid documents
- For free leverage documented: office document/template persistence rides existing local attachment/template primitives.

## Acceptance Criteria
- Document skills are typed, bounded, and source-aware.
- SharePoint routing honors auth and permission constraints.
- Template behaviors are deterministic and testable.
- Captain invariant appears in acceptance checks.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
