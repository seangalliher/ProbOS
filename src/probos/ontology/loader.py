"""OntologyLoader — YAML I/O and initialization for vessel ontology schemas."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from probos.ontology.models import (
    AlertProcedure,
    Assignment,
    ChannelTypeSchema,
    Department,
    DocumentClass,
    DocumentClassification,
    DocumentField,
    DutyCategory,
    KnowledgeSourceSchema,
    KnowledgeTier,
    MessagePattern,
    ModelTier,
    Post,
    QualificationPath,
    QualificationRequirement,
    RepositoryDirectory,
    RetentionPolicy,
    RoleTemplate,
    SkillRequirement,
    StandingOrderTier,
    ToolCapability,
    ThreadModeSchema,
    VesselIdentity,
    WatchTypeSchema,
)

logger = logging.getLogger(__name__)


class OntologyLoader:
    """Loads vessel ontology YAML schemas into structured data."""

    def __init__(self, config_dir: Path, data_dir: Path | None = None) -> None:
        self.config_dir = config_dir
        self.data_dir = data_dir
        self._started_at: float = time.time()
        # Core organization
        self.departments: dict[str, Department] = {}
        self.posts: dict[str, Post] = {}
        self.assignments: dict[str, Assignment] = {}  # keyed by agent_type
        self.vessel_identity: VesselIdentity | None = None
        self.alert_condition: str = "GREEN"
        self.valid_alert_conditions: list[str] = ["GREEN", "YELLOW", "RED"]
        # Skills domain (AD-429b)
        self.role_templates: dict[str, RoleTemplate] = {}  # keyed by post_id
        self.qualification_paths: dict[str, QualificationPath] = {}  # keyed by "from_to"
        # Operations domain (AD-429c)
        self.standing_order_tiers: list[StandingOrderTier] = []
        self.watch_types: list[WatchTypeSchema] = []
        self.alert_procedures: dict[str, AlertProcedure] = {}
        self.duty_categories: list[DutyCategory] = []
        # Communication domain (AD-429c)
        self.channel_types: list[ChannelTypeSchema] = []
        self.thread_modes: list[ThreadModeSchema] = []
        self.message_patterns: list[MessagePattern] = []
        # Resources domain (AD-429c)
        self.model_tiers: list[ModelTier] = []
        self.tool_capabilities: list[ToolCapability] = []
        self.knowledge_sources: list[KnowledgeSourceSchema] = []
        # Records domain (AD-429d)
        self.knowledge_tiers: list[KnowledgeTier] = []
        self.classifications: list[DocumentClassification] = []
        self.document_classes: list[DocumentClass] = []
        self.retention_policies: list[RetentionPolicy] = []
        self.document_fields_required: list[DocumentField] = []
        self.document_fields_optional: list[DocumentField] = []
        self.repository_directories: list[RepositoryDirectory] = []

    @property
    def started_at(self) -> float:
        return self._started_at

    @staticmethod
    def _read_yaml_sync(path: str) -> dict:
        """Read and parse a YAML file (sync, for use with run_in_executor)."""
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    @staticmethod
    def _load_or_generate_instance_id_sync(id_file: Path, id_dir: Path) -> str:
        """Load or generate instance ID (sync, for run_in_executor)."""
        if id_file.exists():
            return id_file.read_text(encoding="utf-8").strip()
        new_id = str(uuid.uuid4())
        id_dir.mkdir(parents=True, exist_ok=True)
        id_file.write_text(new_id, encoding="utf-8")
        return new_id

    async def initialize(self) -> None:
        """Load YAML schemas and build in-memory graph."""
        await self._load_vessel()
        await self._load_organization()
        await self._load_skills_schema()
        # AD-429c domains
        for name, loader in [
            ("operations.yaml", self._load_operations_schema),
            ("communication.yaml", self._load_communication_schema),
            ("resources.yaml", self._load_resources_schema),
            ("records.yaml", self._load_records_schema),
        ]:
            path = self.config_dir / name
            if path.exists():
                await loader(path)
        logger.info("ontology initialized: %d departments, %d posts, %d assignments, %d role templates, "
                     "%d standing order tiers, %d channel types, %d model tiers",
                     len(self.departments), len(self.posts), len(self.assignments),
                     len(self.role_templates), len(self.standing_order_tiers),
                     len(self.channel_types), len(self.model_tiers))

    async def _load_vessel(self) -> None:
        """Load vessel.yaml -> VesselIdentity."""
        vessel_path = self.config_dir / "vessel.yaml"
        if not vessel_path.exists():
            logger.warning("vessel.yaml not found at %s", vessel_path)
            return

        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(vessel_path))

        vessel = data.get("vessel", {})
        identity = vessel.get("identity", {})

        # Alert conditions
        self.valid_alert_conditions = vessel.get("alert_conditions", ["GREEN", "YELLOW", "RED"])
        self.alert_condition = vessel.get("default_alert_condition", "GREEN")

        # Instance ID: load from persistence or generate
        instance_id = await self._load_or_generate_instance_id()

        self.vessel_identity = VesselIdentity(
            name=identity.get("name", "ProbOS"),
            version=identity.get("version", "0.0.0"),
            description=identity.get("description", ""),
            instance_id=instance_id,
            started_at=self._started_at,
        )

    async def _load_or_generate_instance_id(self) -> str:
        """Generate UUID on first boot, persist, reuse on subsequent boots."""
        if self.data_dir:
            id_dir = self.data_dir / "ontology"
            id_file = id_dir / "instance_id"
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None, self._load_or_generate_instance_id_sync, id_file, id_dir
            )
        return str(uuid.uuid4())

    async def _load_organization(self) -> None:
        """Load organization.yaml -> departments, posts, assignments."""
        org_path = self.config_dir / "organization.yaml"
        if not org_path.exists():
            logger.warning("organization.yaml not found at %s", org_path)
            return

        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(org_path))

        for dept_data in data.get("departments", []):
            dept = Department(
                id=dept_data["id"],
                name=dept_data["name"],
                description=dept_data.get("description", ""),
            )
            self.departments[dept.id] = dept

        for post_data in data.get("posts", []):
            post = Post(
                id=post_data["id"],
                title=post_data["title"],
                department_id=post_data["department"],
                reports_to=post_data.get("reports_to"),
                authority_over=post_data.get("authority_over", []),
                tier=post_data.get("tier", "crew"),
            )
            self.posts[post.id] = post

        for assign_data in data.get("assignments", []):
            assignment = Assignment(
                agent_type=assign_data["agent_type"],
                post_id=assign_data["post_id"],
                callsign=assign_data["callsign"],
                watches=assign_data.get("watches", ["alpha"]),
            )
            self.assignments[assignment.agent_type] = assignment

    async def _load_skills_schema(self) -> None:
        """Load skills.yaml -- role templates and qualification paths (AD-429b)."""
        skills_path = self.config_dir / "skills.yaml"
        if not skills_path.exists():
            return

        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(skills_path))

        for post_id, template_data in data.get("role_templates", {}).items():
            required = [
                SkillRequirement(s["skill_id"], s["min_proficiency"])
                for s in template_data.get("required", [])
            ]
            optional = [
                SkillRequirement(s["skill_id"], s["min_proficiency"])
                for s in template_data.get("optional", [])
            ]
            self.role_templates[post_id] = RoleTemplate(post_id, required, optional)

        for path_key, path_data in data.get("qualification_paths", {}).items():
            parts = path_key.split("_to_")
            if len(parts) != 2:
                continue
            from_rank, to_rank = parts
            reqs = []
            for r in path_data.get("requirements", []):
                reqs.append(QualificationRequirement(
                    type=r["type"],
                    description=r["description"],
                    min_proficiency=r["min_proficiency"],
                    scope=r["scope"],
                    min_count=r.get("min_count"),
                ))
            self.qualification_paths[path_key] = QualificationPath(
                from_rank=from_rank,
                to_rank=to_rank,
                description=path_data.get("description", ""),
                requirements=reqs,
            )

    async def _load_operations_schema(self, path: Path) -> None:
        """Load operations.yaml -- standing order tiers, watch types, alert procedures, duties."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(path))

        for t in data.get("standing_order_tiers", []):
            self.standing_order_tiers.append(StandingOrderTier(
                tier=float(t["tier"]),
                name=t["name"],
                source=t["source"],
                scope=t["scope"],
                mutable=t["mutable"],
                description=t.get("description", ""),
            ))

        for w in data.get("watch_types", []):
            self.watch_types.append(WatchTypeSchema(
                id=w["id"],
                name=w["name"],
                description=w.get("description", ""),
                staffing=w["staffing"],
            ))

        for condition, proc_data in data.get("alert_procedures", {}).items():
            self.alert_procedures[condition] = AlertProcedure(
                condition=condition,
                description=proc_data.get("description", ""),
                watch_default=proc_data.get("watch_default", "alpha"),
                proactive_interval=proc_data.get("proactive_interval", "normal"),
                escalation_threshold=proc_data.get("escalation_threshold", "standard"),
                actions=proc_data.get("actions", []),
            )

        for d in data.get("duty_categories", []):
            self.duty_categories.append(DutyCategory(
                id=d["id"],
                name=d["name"],
                description=d.get("description", ""),
                examples=d.get("examples", []),
            ))

    async def _load_communication_schema(self, path: Path) -> None:
        """Load communication.yaml -- channel types, thread modes, message patterns."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(path))

        for c in data.get("channel_types", []):
            self.channel_types.append(ChannelTypeSchema(
                id=c["id"],
                name=c["name"],
                description=c.get("description", ""),
                default_mode=c.get("default_mode", "discuss"),
            ))

        for t in data.get("thread_modes", []):
            self.thread_modes.append(ThreadModeSchema(
                id=t["id"],
                name=t["name"],
                description=t.get("description", ""),
                reply_expected=t.get("reply_expected", False),
                routing=t.get("routing", "none"),
                use_cases=t.get("use_cases", []),
            ))

        for m in data.get("message_patterns", []):
            self.message_patterns.append(MessagePattern(
                id=m["id"],
                tag=m["tag"],
                description=m.get("description", ""),
                expected_from=m.get("expected_from", "all_crew"),
                min_rank=m.get("min_rank"),
            ))

    async def _load_resources_schema(self, path: Path) -> None:
        """Load resources.yaml -- model tiers, tool capabilities, knowledge sources."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(path))

        for m in data.get("model_tiers", []):
            self.model_tiers.append(ModelTier(
                id=m["id"],
                name=m["name"],
                description=m.get("description", ""),
                default_model=m.get("default_model", ""),
                use_cases=m.get("use_cases", []),
            ))

        for t in data.get("tool_capabilities", []):
            self.tool_capabilities.append(ToolCapability(
                id=t["id"],
                name=t["name"],
                description=t.get("description", ""),
                provider=t.get("provider", ""),
                available_to=t.get("available_to", "all_crew"),
                gated_by=t.get("gated_by"),
            ))

        for k in data.get("knowledge_sources", []):
            self.knowledge_sources.append(KnowledgeSourceSchema(
                id=k["id"],
                name=k["name"],
                description=k.get("description", ""),
                tier=k["tier"],
                tier_name=k.get("tier_name", ""),
                storage=k.get("storage", ""),
                access=k.get("access", ""),
            ))

    async def _load_records_schema(self, path: Path) -> None:
        """Load records.yaml -- knowledge tiers, classifications, document classes, retention."""
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, self._read_yaml_sync, str(path))

        for t in data.get("knowledge_tiers", []):
            self.knowledge_tiers.append(KnowledgeTier(
                tier=t["tier"], name=t["name"], store=t["store"],
                description=t["description"], access=t["access"],
                persistence=t["persistence"],
                promotion_path=t.get("promotion_path"),
            ))

        for c in data.get("classifications", []):
            self.classifications.append(DocumentClassification(
                id=c["id"], name=c["name"],
                description=c["description"], access_scope=c["access_scope"],
            ))

        for dc in data.get("document_classes", []):
            self.document_classes.append(DocumentClass(
                id=dc["id"], name=dc["name"], description=dc["description"],
                classification_default=dc["classification_default"],
                retention=dc["retention"], format=dc["format"],
                special_rules=dc.get("special_rules", []),
            ))

        for rp in data.get("retention_policies", []):
            self.retention_policies.append(RetentionPolicy(
                id=rp["id"], name=rp["name"], description=rp["description"],
                archive_after_days=rp.get("archive_after_days"),
                delete_after_days=rp.get("delete_after_days"),
                applies_to=rp.get("applies_to", []),
            ))

        schema = data.get("document_schema", {})
        for f in schema.get("required_fields", []):
            self.document_fields_required.append(DocumentField(
                name=f["name"], type=f["type"], description=f["description"],
                values=f.get("values"),
            ))
        for f in schema.get("optional_fields", []):
            self.document_fields_optional.append(DocumentField(
                name=f["name"], type=f["type"], description=f["description"],
                values=f.get("values"), default=f.get("default"),
            ))

        repo = data.get("repository_structure", {})
        for d in repo.get("directories", []):
            self.repository_directories.append(RepositoryDirectory(
                path=d["path"], description=d["description"],
            ))
